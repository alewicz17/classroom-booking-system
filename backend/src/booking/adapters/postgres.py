from datetime import UTC, datetime
from typing import Any, Self
from uuid import UUID

import psycopg
from psycopg import errors
from psycopg.types.json import Jsonb

from booking.domain.booking import Booking, BookingStatus
from booking.domain.errors import SlotUnavailable
from booking.domain.idempotency import IdempotencyKey

BOOKING_COLUMNS = "id, room_id, user_id, lower(period), upper(period), status"


def _to_booking(row: tuple[Any, ...]) -> Booking:
    id_, room_id, user_id, start, end, status = row
    return Booking(
        id=id_,
        room_id=room_id,
        user_id=user_id,
        start=start.astimezone(UTC),
        end=end.astimezone(UTC),
        status=BookingStatus(status),
    )


# The stored snapshot of a booking in idempotency_keys.response (ADR 0007). Kept apart from
# the API rendering, so the storage format does not change when the API does.
def _booking_to_snapshot(booking: Booking) -> dict[str, str]:
    return {
        "id": str(booking.id),
        "room_id": str(booking.room_id),
        "user_id": str(booking.user_id),
        "start": booking.start.astimezone(UTC).isoformat(),
        "end": booking.end.astimezone(UTC).isoformat(),
        "status": booking.status.value,
    }


def _snapshot_to_booking(snapshot: dict[str, str]) -> Booking:
    return Booking(
        id=UUID(snapshot["id"]),
        room_id=UUID(snapshot["room_id"]),
        user_id=UUID(snapshot["user_id"]),
        start=datetime.fromisoformat(snapshot["start"]),
        end=datetime.fromisoformat(snapshot["end"]),
        status=BookingStatus(snapshot["status"]),
    )


class PostgresBookingRepository:
    def __init__(self, connection: psycopg.Connection[Any]) -> None:
        self.connection = connection

    def add(self, booking: Booking) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO bookings (id, room_id, user_id, period, status)
                VALUES (%s, %s, %s, tstzrange(%s, %s, '[)'), %s)
                """,
                (
                    booking.id,
                    booking.room_id,
                    booking.user_id,
                    booking.start,
                    booking.end,
                    booking.status.value,
                ),
            )
        except errors.ExclusionViolation as error:
            raise SlotUnavailable from error
        except errors.DeadlockDetected as error:
            # The only lock taken before this insert is the user lock, and a transaction
            # waiting on it has inserted nothing, so a deadlock here can only come from a
            # concurrent overlapping insert on the exclusion constraint (ADR 0005, 0006).
            raise SlotUnavailable from error

    def get(self, booking_id: UUID) -> Booking | None:
        row = self.connection.execute(
            f"SELECT {BOOKING_COLUMNS} FROM bookings WHERE id = %s", (booking_id,)
        ).fetchone()
        return None if row is None else _to_booking(row)

    def cancel(self, booking_id: UUID) -> bool:
        # A single conditional update: a concurrent cancel waits on the row lock, then
        # re-checks the WHERE against the committed row and matches nothing.
        cursor = self.connection.execute(
            "UPDATE bookings SET status = 'cancelled' WHERE id = %s AND status = 'confirmed'",
            (booking_id,),
        )
        return cursor.rowcount == 1

    def find_overlapping(self, room_id: UUID, start: datetime, end: datetime) -> list[Booking]:
        rows = self.connection.execute(
            f"""
            SELECT {BOOKING_COLUMNS} FROM bookings
            WHERE room_id = %s
              AND status = 'confirmed'
              AND period && tstzrange(%s, %s, '[)')
            ORDER BY lower(period)
            """,
            (room_id, start, end),
        ).fetchall()
        return [_to_booking(row) for row in rows]

    def count_future(self, user_id: UUID, now: datetime) -> int:
        row = self.connection.execute(
            """
            SELECT count(*) FROM bookings
            WHERE user_id = %s AND status = 'confirmed' AND lower(period) > %s
            """,
            (user_id, now),
        ).fetchone()
        assert row is not None
        count: int = row[0]
        return count


class PostgresRoomRepository:
    def __init__(self, connection: psycopg.Connection[Any]) -> None:
        self.connection = connection

    def exists(self, room_id: UUID) -> bool:
        row = self.connection.execute("SELECT 1 FROM rooms WHERE id = %s", (room_id,)).fetchone()
        return row is not None


class PostgresUserRepository:
    def __init__(self, connection: psycopg.Connection[Any]) -> None:
        self.connection = connection

    def exists(self, user_id: UUID) -> bool:
        row = self.connection.execute("SELECT 1 FROM users WHERE id = %s", (user_id,)).fetchone()
        return row is not None

    def lock(self, user_id: UUID) -> None:
        self.connection.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user_id,))


class PostgresIdempotencyKeyRepository:
    def __init__(self, connection: psycopg.Connection[Any]) -> None:
        self.connection = connection

    def get(self, user_id: UUID, key: UUID) -> IdempotencyKey | None:
        row = self.connection.execute(
            "SELECT request_hash, response FROM idempotency_keys WHERE user_id = %s AND key = %s",
            (user_id, key),
        ).fetchone()
        if row is None:
            return None
        request_hash, response = row
        return IdempotencyKey(user_id, key, request_hash, _snapshot_to_booking(response))

    def add(self, idempotency_key: IdempotencyKey) -> None:
        self.connection.execute(
            """
            INSERT INTO idempotency_keys (user_id, key, request_hash, response)
            VALUES (%s, %s, %s, %s)
            """,
            (
                idempotency_key.user_id,
                idempotency_key.key,
                idempotency_key.request_hash,
                Jsonb(_booking_to_snapshot(idempotency_key.response)),
            ),
        )


class PostgresUnitOfWork:
    bookings: PostgresBookingRepository
    rooms: PostgresRoomRepository
    users: PostgresUserRepository
    idempotency_keys: PostgresIdempotencyKeyRepository

    def __init__(self, conninfo: str) -> None:
        self.conninfo = conninfo

    def __enter__(self) -> Self:
        self.connection = psycopg.connect(self.conninfo)
        self.bookings = PostgresBookingRepository(self.connection)
        self.rooms = PostgresRoomRepository(self.connection)
        self.users = PostgresUserRepository(self.connection)
        self.idempotency_keys = PostgresIdempotencyKeyRepository(self.connection)
        return self

    def __exit__(self, *args: object) -> None:
        # Anything not committed explicitly is discarded.
        self.connection.rollback()
        self.connection.close()

    def commit(self) -> None:
        self.connection.commit()
