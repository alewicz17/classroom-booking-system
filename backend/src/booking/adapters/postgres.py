from datetime import datetime
from typing import Self
from uuid import UUID

from booking.domain.booking import Booking


class PostgresBookingRepository:
    def add(self, booking: Booking) -> None:
        raise NotImplementedError

    def find_overlapping(self, room_id: UUID, start: datetime, end: datetime) -> list[Booking]:
        raise NotImplementedError


class PostgresUnitOfWork:
    bookings: PostgresBookingRepository

    def __init__(self, conninfo: str) -> None:
        self.conninfo = conninfo

    def __enter__(self) -> Self:
        raise NotImplementedError

    def __exit__(self, *args: object) -> None:
        raise NotImplementedError

    def commit(self) -> None:
        raise NotImplementedError
