from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from booking.domain.errors import BookingInPast, InvalidTimeRange


class BookingStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Booking:
    id: UUID
    room_id: UUID
    user_id: UUID
    start: datetime
    end: datetime
    status: BookingStatus


def new_booking(
    room_id: UUID, user_id: UUID, start: datetime, end: datetime, now: datetime
) -> Booking:
    """Validates the requested range and returns a confirmed booking in UTC."""
    if start >= end:
        raise InvalidTimeRange
    if start <= now:
        raise BookingInPast
    return Booking(
        id=uuid4(),
        room_id=room_id,
        user_id=user_id,
        start=start.astimezone(UTC),
        end=end.astimezone(UTC),
        status=BookingStatus.CONFIRMED,
    )
