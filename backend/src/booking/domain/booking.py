from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from booking.domain.errors import (
    BookingAlreadyCancelled,
    BookingInPast,
    BookingLimitReached,
    BookingTooLong,
    CancellationTooLate,
    InvalidTimeRange,
)

CANCELLATION_DEADLINE = timedelta(hours=24)
MAX_DURATION = timedelta(hours=6)
MAX_FUTURE_BOOKINGS = 3
REMINDER_LEAD_TIME = timedelta(hours=1)


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
    if end - start > MAX_DURATION:
        raise BookingTooLong
    return Booking(
        id=uuid4(),
        room_id=room_id,
        user_id=user_id,
        start=start.astimezone(UTC),
        end=end.astimezone(UTC),
        status=BookingStatus.CONFIRMED,
    )


def check_booking_limit(future_bookings: int) -> None:
    """Rejects a new booking if the user already holds the maximum of future bookings."""
    if future_bookings >= MAX_FUTURE_BOOKINGS:
        raise BookingLimitReached


def cancel(booking: Booking, now: datetime) -> Booking:
    """Returns the booking as cancelled, if it is confirmed and not past the deadline."""
    # Checked before the deadline, so a cancelled booking always gives the same error.
    if booking.status == BookingStatus.CANCELLED:
        raise BookingAlreadyCancelled
    if now >= booking.start - CANCELLATION_DEADLINE:
        raise CancellationTooLate
    return replace(booking, status=BookingStatus.CANCELLED)
