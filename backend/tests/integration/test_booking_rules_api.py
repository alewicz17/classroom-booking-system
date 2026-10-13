from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import Response

from booking.domain.booking import Booking, BookingStatus

Book = Callable[[UUID, UUID, datetime, datetime], Response]
GivenBooking = Callable[..., Booking]
ConfirmedBookings = Callable[[UUID], list[Booking]]
At = Callable[..., datetime]


def given_future_bookings(
    given_booking: GivenBooking, at: At, user_id: UUID, room_id: UUID, count: int
) -> None:
    """Gives the user `count` future confirmed bookings in the room, from 14:00Z onwards."""
    for i in range(count):
        given_booking(room_id, user_id, at(14 + i), at(15 + i))


def test_booking_of_exactly_maximum_duration_is_allowed(
    book: Book, at: At, user_a: UUID, room_1: UUID
) -> None:
    response = book(user_a, room_1, at(8), at(14))

    assert response.status_code == 201


def test_booking_longer_than_maximum_is_rejected(
    book: Book, confirmed_bookings: ConfirmedBookings, at: At, user_a: UUID, room_1: UUID
) -> None:
    response = book(user_a, room_1, at(8), at(14, 1))

    assert response.status_code == 422
    assert confirmed_bookings(room_1) == []


def test_user_below_limit_can_book(
    book: Book, given_booking: GivenBooking, at: At, user_a: UUID, room_1: UUID, room_2: UUID
) -> None:
    given_future_bookings(given_booking, at, user_a, room_2, 2)

    response = book(user_a, room_1, at(8), at(9))

    assert response.status_code == 201


def test_user_at_limit_is_rejected(
    book: Book,
    given_booking: GivenBooking,
    confirmed_bookings: ConfirmedBookings,
    at: At,
    user_a: UUID,
    room_1: UUID,
    room_2: UUID,
) -> None:
    given_future_bookings(given_booking, at, user_a, room_2, 3)

    response = book(user_a, room_1, at(8), at(9))

    assert response.status_code == 422
    assert confirmed_bookings(room_1) == []


def test_cancelled_bookings_do_not_count(
    book: Book, given_booking: GivenBooking, at: At, user_a: UUID, room_1: UUID, room_2: UUID
) -> None:
    given_future_bookings(given_booking, at, user_a, room_2, 2)
    given_booking(room_2, user_a, at(18), at(19), BookingStatus.CANCELLED)

    response = book(user_a, room_1, at(8), at(9))

    assert response.status_code == 201


def test_booking_in_progress_does_not_count(
    book: Book, given_booking: GivenBooking, at: At, user_a: UUID, room_1: UUID, room_2: UUID
) -> None:
    given_future_bookings(given_booking, at, user_a, room_2, 2)
    given_booking(
        room_2,
        user_a,
        datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
        datetime(2026, 10, 20, 11, 0, tzinfo=UTC),
    )

    response = book(user_a, room_1, at(8), at(9))

    assert response.status_code == 201


def test_booking_starting_exactly_now_does_not_count(
    book: Book, given_booking: GivenBooking, at: At, user_a: UUID, room_1: UUID, room_2: UUID
) -> None:
    given_future_bookings(given_booking, at, user_a, room_2, 2)
    given_booking(
        room_2,
        user_a,
        datetime(2026, 10, 20, 10, 0, tzinfo=UTC),
        datetime(2026, 10, 20, 11, 0, tzinfo=UTC),
    )

    response = book(user_a, room_1, at(8), at(9))

    assert response.status_code == 201


def test_limit_applies_across_rooms(
    book: Book, given_booking: GivenBooking, at: At, user_a: UUID, room_1: UUID, room_2: UUID
) -> None:
    given_future_bookings(given_booking, at, user_a, room_1, 2)
    given_booking(room_2, user_a, at(18), at(19))

    response = book(user_a, room_2, at(8), at(9))

    assert response.status_code == 422


def test_limit_is_per_user(
    book: Book,
    given_booking: GivenBooking,
    at: At,
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
    room_2: UUID,
) -> None:
    given_future_bookings(given_booking, at, user_a, room_2, 3)

    response = book(user_b, room_1, at(8), at(9))

    assert response.status_code == 201


def test_limit_is_checked_before_overlap(
    book: Book,
    given_booking: GivenBooking,
    at: At,
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
    room_2: UUID,
) -> None:
    given_future_bookings(given_booking, at, user_a, room_2, 3)
    given_booking(room_1, user_b, at(8), at(9))

    response = book(user_a, room_1, at(8), at(9))

    assert response.status_code == 422


@pytest.mark.parametrize("case", ["booking too long", "booking limit reached"])
def test_rule_errors_use_problem_details(
    book: Book,
    given_booking: GivenBooking,
    at: At,
    user_a: UUID,
    room_1: UUID,
    room_2: UUID,
    case: str,
) -> None:
    if case == "booking too long":
        response = book(user_a, room_1, at(8), at(14, 1))
    else:
        given_future_bookings(given_booking, at, user_a, room_2, 3)
        response = book(user_a, room_1, at(8), at(9))

    assert response.status_code == 422
    assert response.headers["Content-Type"].startswith("application/problem+json")
    body = response.json()
    assert isinstance(body["type"], str)
    assert isinstance(body["title"], str)
    assert body["status"] == 422
