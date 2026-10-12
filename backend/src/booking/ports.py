"""Ports: the interfaces services depend on (typing.Protocol)."""

from datetime import datetime
from typing import Protocol, Self
from uuid import UUID

from booking.domain.booking import Booking


class Clock(Protocol):
    def now(self) -> datetime: ...


class BookingRepository(Protocol):
    def add(self, booking: Booking) -> None: ...

    def find_overlapping(self, room_id: UUID, start: datetime, end: datetime) -> list[Booking]:
        """Confirmed bookings in the room whose range overlaps [start, end)."""
        ...


class UnitOfWork(Protocol):
    @property
    def bookings(self) -> BookingRepository: ...

    def __enter__(self) -> Self: ...

    def __exit__(self, *args: object) -> None: ...

    def commit(self) -> None: ...
