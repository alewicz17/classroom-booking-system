"""In-memory fakes of the ports, for tests."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Self
from uuid import UUID

from booking.domain.booking import REMINDER_LEAD_TIME, Booking, BookingStatus
from booking.domain.errors import SlotUnavailable
from booking.domain.idempotency import IdempotencyKey
from booking.domain.room import Room


@dataclass(frozen=True)
class FixedClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


class InMemoryBookingRepository:
    def __init__(self, room_ids: set[UUID], user_ids: set[UUID]) -> None:
        self.room_ids = room_ids
        self.user_ids = user_ids
        self.bookings: dict[UUID, Booking] = {}
        self.reminder_sent_at: dict[UUID, datetime] = {}

    def add(self, booking: Booking) -> None:
        # Stands in for the foreign keys. Services check first, so this only fires on a bug.
        if booking.room_id not in self.room_ids or booking.user_id not in self.user_ids:
            raise ValueError("unknown room or user")
        # Stands in for the exclusion constraint, so the fake rejects what Postgres rejects.
        if booking.status == BookingStatus.CONFIRMED and self.find_overlapping(
            booking.room_id, booking.start, booking.end
        ):
            raise SlotUnavailable
        self.bookings[booking.id] = booking

    def get(self, booking_id: UUID) -> Booking | None:
        return self.bookings.get(booking_id)

    def list_for_user(self, user_id: UUID) -> list[Booking]:
        own = [booking for booking in self.bookings.values() if booking.user_id == user_id]
        return sorted(own, key=lambda booking: (booking.start, booking.id))

    def cancel(self, booking_id: UUID) -> bool:
        booking = self.bookings.get(booking_id)
        if booking is None or booking.status != BookingStatus.CONFIRMED:
            return False
        self.bookings[booking_id] = replace(booking, status=BookingStatus.CANCELLED)
        return True

    def find_overlapping(self, room_id: UUID, start: datetime, end: datetime) -> list[Booking]:
        overlapping = [
            booking
            for booking in self.bookings.values()
            if booking.room_id == room_id
            and booking.status == BookingStatus.CONFIRMED
            and booking.start < end
            and start < booking.end
        ]
        return sorted(overlapping, key=lambda booking: booking.start)

    def count_future(self, user_id: UUID, now: datetime) -> int:
        return sum(
            1
            for booking in self.bookings.values()
            if booking.user_id == user_id
            and booking.status == BookingStatus.CONFIRMED
            and booking.start > now
        )

    def find_due_for_reminder(self, now: datetime) -> list[Booking]:
        due = [
            booking
            for booking in self.bookings.values()
            if booking.status == BookingStatus.CONFIRMED
            and booking.id not in self.reminder_sent_at
            and now < booking.start <= now + REMINDER_LEAD_TIME
        ]
        return sorted(due, key=lambda booking: booking.start)

    def mark_reminder_sent(self, booking_id: UUID, sent_at: datetime) -> None:
        self.reminder_sent_at[booking_id] = sent_at


class RecordingNotifier:
    def __init__(self) -> None:
        self.received: list[Booking] = []

    def send_reminder(self, booking: Booking) -> None:
        self.received.append(booking)


class InMemoryRoomRepository:
    def __init__(self, rooms: dict[UUID, str]) -> None:
        self.rooms = rooms

    def exists(self, room_id: UUID) -> bool:
        return room_id in self.rooms

    def list_all(self) -> list[Room]:
        rooms = [Room(id=id_, name=name) for id_, name in self.rooms.items()]
        return sorted(rooms, key=lambda room: (room.name, room.id))


class InMemoryUserRepository:
    def __init__(self, user_ids: set[UUID]) -> None:
        self.user_ids = user_ids

    def exists(self, user_id: UUID) -> bool:
        return user_id in self.user_ids

    def lock(self, user_id: UUID) -> None:
        # Nothing to lock: the fake is used from one thread only. Concurrency is tested
        # against Postgres.
        pass


class InMemoryIdempotencyKeyRepository:
    def __init__(self, user_ids: set[UUID]) -> None:
        self.user_ids = user_ids
        self.keys: dict[tuple[UUID, UUID], IdempotencyKey] = {}

    def get(self, user_id: UUID, key: UUID) -> IdempotencyKey | None:
        return self.keys.get((user_id, key))

    def add(self, idempotency_key: IdempotencyKey) -> None:
        # Stands in for the primary key and the foreign key on the user.
        id_ = (idempotency_key.user_id, idempotency_key.key)
        if id_ in self.keys or idempotency_key.user_id not in self.user_ids:
            raise ValueError("duplicate key or unknown user")
        self.keys[id_] = idempotency_key


class InMemoryUnitOfWork:
    """Keeps its data across uses, like a database. Uncommitted changes are discarded on exit."""

    def __init__(self, rooms: dict[UUID, str], user_ids: set[UUID]) -> None:
        self.bookings = InMemoryBookingRepository(set(rooms), user_ids)
        self.rooms = InMemoryRoomRepository(rooms)
        self.users = InMemoryUserRepository(user_ids)
        self.idempotency_keys = InMemoryIdempotencyKeyRepository(user_ids)
        self.committed_bookings: dict[UUID, Booking] = {}
        self.committed_keys: dict[tuple[UUID, UUID], IdempotencyKey] = {}
        self.committed_reminders: dict[UUID, datetime] = {}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        # Restoring the last committed state is the in-memory version of a rollback.
        self.bookings.bookings = dict(self.committed_bookings)
        self.idempotency_keys.keys = dict(self.committed_keys)
        self.bookings.reminder_sent_at = dict(self.committed_reminders)

    def commit(self) -> None:
        # Values are frozen dataclasses, so shallow copies are enough.
        self.committed_bookings = dict(self.bookings.bookings)
        self.committed_keys = dict(self.idempotency_keys.keys)
        self.committed_reminders = dict(self.bookings.reminder_sent_at)
