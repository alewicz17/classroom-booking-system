from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from booking.adapters.memory import FixedClock
from booking.domain.booking import (
    Booking,
    BookingStatus,
    cancel,
    check_booking_limit,
    new_booking,
)
from booking.domain.errors import (
    BookingAlreadyCancelled,
    BookingInPast,
    BookingLimitReached,
    BookingTooLong,
    CancellationTooLate,
    InvalidTimeRange,
)

At = Callable[..., datetime]
Book = Callable[[datetime, datetime], Booking]


@pytest.fixture
def book(room_1: UUID, user_a: UUID, clock: FixedClock) -> Book:
    def create(start: datetime, end: datetime) -> Booking:
        return new_booking(room_1, user_a, start, end, clock.now())

    return create


def test_start_equal_to_end_is_invalid_range(book: Book, at: At) -> None:
    with pytest.raises(InvalidTimeRange):
        book(at(10), at(10))


def test_start_after_end_is_invalid_range(book: Book, at: At) -> None:
    with pytest.raises(InvalidTimeRange):
        book(at(11), at(10))


def test_start_equal_to_now_is_in_past(book: Book, clock: FixedClock) -> None:
    with pytest.raises(BookingInPast):
        book(clock.now(), clock.now() + timedelta(hours=1))


def test_start_just_after_now_is_accepted(book: Book, clock: FixedClock) -> None:
    start = clock.now() + timedelta(microseconds=1)

    booking = book(start, start + timedelta(hours=1))

    assert booking.start == start


def test_duration_of_exactly_six_hours_is_accepted(book: Book, at: At) -> None:
    booking = book(at(8), at(14))

    assert booking.end - booking.start == timedelta(hours=6)


def test_duration_over_six_hours_is_too_long(book: Book, at: At) -> None:
    with pytest.raises(BookingTooLong):
        book(at(8), at(14, 1))


def test_non_utc_times_are_stored_in_utc(book: Book, at: At) -> None:
    rome = timezone(timedelta(hours=2))

    booking = book(at(10).astimezone(rome), at(11).astimezone(rome))

    assert booking.start.utcoffset() == timedelta(0)
    assert booking.end.utcoffset() == timedelta(0)
    assert (booking.start, booking.end) == (at(10), at(11))


def test_new_booking_is_confirmed(book: Book, at: At) -> None:
    assert book(at(10), at(11)).status == BookingStatus.CONFIRMED


def test_two_future_bookings_allow_another() -> None:
    check_booking_limit(2)


def test_three_future_bookings_reach_the_limit() -> None:
    with pytest.raises(BookingLimitReached):
        check_booking_limit(3)


def test_cancel_exactly_24_hours_before_start_is_too_late(book: Book, at: At) -> None:
    booking = book(at(10), at(11))

    with pytest.raises(CancellationTooLate):
        cancel(booking, booking.start - timedelta(hours=24))


def test_cancel_just_before_deadline_is_accepted(book: Book, at: At) -> None:
    booking = book(at(10), at(11))

    cancelled = cancel(booking, booking.start - timedelta(hours=24, microseconds=1))

    assert cancelled.status == BookingStatus.CANCELLED
    assert cancelled.id == booking.id


def test_cancel_already_cancelled_and_late_gives_already_cancelled(
    room_1: UUID, user_a: UUID, at: At
) -> None:
    booking = Booking(uuid4(), room_1, user_a, at(10), at(11), BookingStatus.CANCELLED)

    with pytest.raises(BookingAlreadyCancelled):
        cancel(booking, at(9))
