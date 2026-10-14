"""Ports: the interfaces services depend on (typing.Protocol)."""

from datetime import datetime
from typing import Protocol, Self
from uuid import UUID

from booking.domain.booking import Booking
from booking.domain.idempotency import IdempotencyKey
from booking.domain.room import Room


class Clock(Protocol):
    def now(self) -> datetime: ...


class BookingRepository(Protocol):
    def add(self, booking: Booking) -> None: ...

    def get(self, booking_id: UUID) -> Booking | None: ...

    def list_for_user(self, user_id: UUID) -> list[Booking]:
        """Every booking of the user, of any status, sorted by start and then by id."""
        ...

    def cancel(self, booking_id: UUID) -> bool:
        """Marks a confirmed booking as cancelled. False if no confirmed booking matched."""
        ...

    def find_overlapping(self, room_id: UUID, start: datetime, end: datetime) -> list[Booking]:
        """Confirmed bookings in the room whose range overlaps [start, end)."""
        ...

    def count_future(self, user_id: UUID, now: datetime) -> int:
        """Confirmed bookings of the user that start strictly after now."""
        ...

    def find_due_for_reminder(self, now: datetime) -> list[Booking]:
        """Confirmed, not yet reminded bookings with now < start <= now + the lead time.

        Locks them with FOR UPDATE SKIP LOCKED until the end of the transaction.
        """
        ...

    def mark_reminder_sent(self, booking_id: UUID, sent_at: datetime) -> None: ...


class Notifier(Protocol):
    def send_reminder(self, booking: Booking) -> None: ...


class RoomRepository(Protocol):
    def exists(self, room_id: UUID) -> bool: ...

    def list_all(self) -> list[Room]:
        """Every room, sorted by name."""
        ...


class UserRepository(Protocol):
    def exists(self, user_id: UUID) -> bool: ...

    def lock(self, user_id: UUID) -> None:
        """Locks the user until the end of the transaction."""
        ...


class IdempotencyKeyRepository(Protocol):
    def get(self, user_id: UUID, key: UUID) -> IdempotencyKey | None: ...

    def add(self, idempotency_key: IdempotencyKey) -> None: ...


class UnitOfWork(Protocol):
    @property
    def bookings(self) -> BookingRepository: ...

    @property
    def rooms(self) -> RoomRepository: ...

    @property
    def users(self) -> UserRepository: ...

    @property
    def idempotency_keys(self) -> IdempotencyKeyRepository: ...

    def __enter__(self) -> Self: ...

    def __exit__(self, *args: object) -> None: ...

    def commit(self) -> None: ...
