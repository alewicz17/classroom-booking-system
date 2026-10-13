from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from booking.domain.errors import (
    BookingAlreadyCancelled,
    BookingInPast,
    CancellationTooLate,
    InvalidTimeRange,
)

CANCELLATION_DEADLINE = timedelta(hours=24)


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


def cancel(booking: Booking, now: datetime) -> Booking:
    """Returns the booking as cancelled, if it is confirmed and not past the deadline."""
    # Checked before the deadline, so a cancelled booking always gives the same error.
    if booking.status == BookingStatus.CANCELLED:
        raise BookingAlreadyCancelled
    if now >= booking.start - CANCELLATION_DEADLINE:
        raise CancellationTooLate
    return replace(booking, status=BookingStatus.CANCELLED)
