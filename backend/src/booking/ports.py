"""Ports: the interfaces services depend on (typing.Protocol)."""

from datetime import datetime
from typing import Protocol, Self
from uuid import UUID

from booking.domain.booking import Booking
from booking.domain.idempotency import IdempotencyKey


class Clock(Protocol):
    def now(self) -> datetime: ...


class BookingRepository(Protocol):
    def add(self, booking: Booking) -> None: ...

    def get(self, booking_id: UUID) -> Booking | None: ...

    def cancel(self, booking_id: UUID) -> bool:
        """Marks a confirmed booking as cancelled. False if no confirmed booking matched."""
        ...

    def find_overlapping(self, room_id: UUID, start: datetime, end: datetime) -> list[Booking]:
        """Confirmed bookings in the room whose range overlaps [start, end)."""
        ...

    def count_future(self, user_id: UUID, now: datetime) -> int:
        """Confirmed bookings of the user that start strictly after now."""
        ...


class RoomRepository(Protocol):
    def exists(self, room_id: UUID) -> bool: ...


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
