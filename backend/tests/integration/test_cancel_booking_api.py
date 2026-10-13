from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from booking.domain.booking import Booking, BookingStatus

Book = Callable[[UUID, UUID, datetime, datetime], Response]
GivenBooking = Callable[..., Booking]
ConfirmedBookings = Callable[[UUID], list[Booking]]
Cancel = Callable[[UUID, UUID | str], Response]


def utc(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


# Bookings of user A in room 1 as (start, end, status). The clock is at 2026-10-20T10:00Z.
BOOKINGS = {
    "confirmed": (utc(22, 8), utc(22, 9), BookingStatus.CONFIRMED),
    "cancelled": (utc(22, 8), utc(22, 9), BookingStatus.CANCELLED),
    "past deadline": (utc(21, 10), utc(21, 11), BookingStatus.CONFIRMED),
}


@pytest.fixture
def cancel(client: TestClient) -> Cancel:
    """Returns a function that sends POST /bookings/{id}/cancel as the given user."""

    def post(user_id: UUID, booking_id: UUID | str) -> Response:
        return client.post(f"/bookings/{booking_id}/cancel", headers={"X-User-Id": str(user_id)})

    return post


def test_user_cancels_own_booking(
    cancel: Cancel, given_booking: GivenBooking, user_a: UUID, room_1: UUID
) -> None:
    booking = given_booking(room_1, user_a, utc(22, 8), utc(22, 9))

    response = cancel(user_a, booking.id)

    assert response.status_code == 200
    assert response.json() == {
        "id": str(booking.id),
        "room_id": str(room_1),
        "user_id": str(user_a),
        "start": "2026-10-22T08:00:00Z",
        "end": "2026-10-22T09:00:00Z",
        "status": "cancelled",
    }


def test_cancelled_booking_is_still_readable(
    client: TestClient, cancel: Cancel, given_booking: GivenBooking, user_a: UUID, room_1: UUID
) -> None:
    booking = given_booking(room_1, user_a, utc(22, 8), utc(22, 9))
    assert cancel(user_a, booking.id).status_code == 200

    response = client.get(f"/bookings/{booking.id}", headers={"X-User-Id": str(user_a)})

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_cancelled_booking_frees_its_slot(
    book: Book,
    cancel: Cancel,
    given_booking: GivenBooking,
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
) -> None:
    booking = given_booking(room_1, user_a, utc(22, 8), utc(22, 9))
    assert cancel(user_a, booking.id).status_code == 200

    response = book(user_b, room_1, utc(22, 8), utc(22, 9))

    assert response.status_code == 201


def test_cancelling_just_before_deadline_is_allowed(
    cancel: Cancel, given_booking: GivenBooking, user_a: UUID, room_1: UUID
) -> None:
    # The clock is at 2026-10-20T10:00Z: 24 hours and 1 minute before the start.
    booking = given_booking(room_1, user_a, utc(21, 10, 1), utc(21, 11))

    response = cancel(user_a, booking.id)

    assert response.status_code == 200


def test_cancelling_exactly_at_deadline_is_rejected(
    cancel: Cancel,
    given_booking: GivenBooking,
    confirmed_bookings: ConfirmedBookings,
    user_a: UUID,
    room_1: UUID,
) -> None:
    # The clock is at 2026-10-20T10:00Z: exactly 24 hours before the start.
    booking = given_booking(room_1, user_a, utc(21, 10), utc(21, 11))

    response = cancel(user_a, booking.id)

    assert response.status_code == 422
    assert confirmed_bookings(room_1) == [booking]


def test_booking_already_started_cannot_be_cancelled(
    cancel: Cancel,
    given_booking: GivenBooking,
    confirmed_bookings: ConfirmedBookings,
    user_a: UUID,
    room_1: UUID,
) -> None:
    booking = given_booking(room_1, user_a, utc(20, 9), utc(20, 11))

    response = cancel(user_a, booking.id)

    assert response.status_code == 422
    assert confirmed_bookings(room_1) == [booking]


def test_cancelling_twice_is_a_conflict(
    cancel: Cancel, given_booking: GivenBooking, user_a: UUID, room_1: UUID
) -> None:
    booking = given_booking(room_1, user_a, utc(22, 8), utc(22, 9))
    assert cancel(user_a, booking.id).status_code == 200

    response = cancel(user_a, booking.id)

    assert response.status_code == 409


def test_already_cancelled_takes_precedence_over_deadline(
    cancel: Cancel, given_booking: GivenBooking, user_a: UUID, room_1: UUID
) -> None:
    booking = given_booking(
        room_1, user_a, utc(20, 12), utc(20, 13), status=BookingStatus.CANCELLED
    )

    response = cancel(user_a, booking.id)

    assert response.status_code == 409


# Visibility is checked before status and deadline, so nothing about the booking leaks.
@pytest.mark.parametrize("kind", list(BOOKINGS))
def test_other_users_booking_cannot_be_cancelled(
    client: TestClient,
    cancel: Cancel,
    given_booking: GivenBooking,
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
    kind: str,
) -> None:
    start, end, status = BOOKINGS[kind]
    booking = given_booking(room_1, user_a, start, end, status=status)

    other_users = cancel(user_b, booking.id)
    missing = cancel(user_b, uuid4())

    assert other_users.status_code == 404
    assert missing.status_code == 404
    assert other_users.json() == missing.json()
    assert other_users.json()["type"] == "/problems/booking-not-found"
    stored = client.get(f"/bookings/{booking.id}", headers={"X-User-Id": str(user_a)})
    assert stored.json()["status"] == status.value


def test_booking_that_does_not_exist_returns_404(cancel: Cancel, user_a: UUID) -> None:
    response = cancel(user_a, uuid4())

    assert response.status_code == 404
    # Distinguishes the domain 404 from a route that does not exist.
    assert response.json()["type"] == "/problems/booking-not-found"


def test_malformed_input_is_rejected(cancel: Cancel, user_a: UUID) -> None:
    response = cancel(user_a, "not-a-uuid")

    assert response.status_code == 422


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-User-Id": "not-a-uuid"}, {"X-User-Id": str(uuid4())}],
    ids=["missing", "not a UUID", "unknown user"],
)
def test_missing_or_unknown_user_returns_401(
    client: TestClient,
    given_booking: GivenBooking,
    confirmed_bookings: ConfirmedBookings,
    user_a: UUID,
    room_1: UUID,
    headers: dict[str, str],
) -> None:
    booking = given_booking(room_1, user_a, utc(22, 8), utc(22, 9))

    response = client.post(f"/bookings/{booking.id}/cancel", headers=headers)

    assert response.status_code == 401
    assert confirmed_bookings(room_1) == [booking]


# (requester, target, expected status). The target is a key of BOOKINGS, "unknown" for a
# valid UUID that matches no booking, or "not a UUID".
ERROR_CASES = [
    pytest.param(None, "confirmed", 401, id="missing user"),
    pytest.param("a", "not a UUID", 422, id="booking id not a UUID"),
    pytest.param("a", "unknown", 404, id="unknown booking"),
    pytest.param("b", "confirmed", 404, id="other user's booking"),
    pytest.param("a", "cancelled", 409, id="already cancelled"),
    pytest.param("a", "past deadline", 422, id="too late"),
]


@pytest.mark.parametrize(("requester", "target", "expected_status"), ERROR_CASES)
def test_errors_use_problem_details(
    client: TestClient,
    given_booking: GivenBooking,
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
    requester: str | None,
    target: str,
    expected_status: int,
) -> None:
    booking_id: UUID | str
    if target in BOOKINGS:
        start, end, status = BOOKINGS[target]
        booking_id = given_booking(room_1, user_a, start, end, status=status).id
    elif target == "unknown":
        booking_id = uuid4()
    else:
        booking_id = "not-a-uuid"
    users = {"a": user_a, "b": user_b}
    headers = {} if requester is None else {"X-User-Id": str(users[requester])}

    response = client.post(f"/bookings/{booking_id}/cancel", headers=headers)

    assert response.status_code == expected_status
    assert response.headers["Content-Type"].startswith("application/problem+json")
    body = response.json()
    assert isinstance(body["type"], str)
    assert isinstance(body["title"], str)
    assert body["status"] == response.status_code
