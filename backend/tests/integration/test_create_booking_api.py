from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from booking.adapters.memory import FixedClock
from booking.domain.booking import Booking, BookingStatus

Book = Callable[[UUID, UUID, datetime, datetime], Response]
GivenBooking = Callable[..., Booking]
ConfirmedBookings = Callable[[UUID], list[Booking]]
At = Callable[..., datetime]


def test_free_slot_is_booked(client: TestClient, user_a: UUID, room_1: UUID) -> None:
    response = client.post(
        "/bookings",
        headers={"X-User-Id": str(user_a)},
        json={
            "room_id": str(room_1),
            "start": "2026-10-21T10:00:00+02:00",
            "end": "2026-10-21T11:00:00+02:00",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert response.headers["Location"] == f"/bookings/{body['id']}"
    assert UUID(body["id"])
    assert body["room_id"] == str(room_1)
    assert body["user_id"] == str(user_a)
    assert body["start"] == "2026-10-21T08:00:00Z"
    assert body["end"] == "2026-10-21T09:00:00Z"
    assert body["status"] == "confirmed"


def test_overlapping_booking_is_rejected(
    book: Book,
    given_booking: GivenBooking,
    confirmed_bookings: ConfirmedBookings,
    at: At,
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
) -> None:
    existing = given_booking(room_1, user_a, at(10), at(11))

    response = book(user_b, room_1, at(10, 30), at(11, 30))

    assert response.status_code == 409
    assert confirmed_bookings(room_1) == [existing]


def test_booking_contained_in_existing_one_is_rejected(
    book: Book, given_booking: GivenBooking, at: At, user_a: UUID, user_b: UUID, room_1: UUID
) -> None:
    given_booking(room_1, user_a, at(10), at(12))

    response = book(user_b, room_1, at(10, 30), at(11))

    assert response.status_code == 409


def test_back_to_back_bookings_do_not_overlap(
    book: Book, given_booking: GivenBooking, at: At, user_a: UUID, user_b: UUID, room_1: UUID
) -> None:
    given_booking(room_1, user_a, at(10), at(11))

    response = book(user_b, room_1, at(11), at(12))

    assert response.status_code == 201


def test_same_slot_in_different_room_is_allowed(
    book: Book,
    given_booking: GivenBooking,
    at: At,
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
    room_2: UUID,
) -> None:
    given_booking(room_1, user_a, at(10), at(11))

    response = book(user_b, room_2, at(10), at(11))

    assert response.status_code == 201


def test_cancelled_booking_does_not_block_slot(
    book: Book, given_booking: GivenBooking, at: At, user_a: UUID, user_b: UUID, room_1: UUID
) -> None:
    given_booking(room_1, user_a, at(10), at(11), BookingStatus.CANCELLED)

    response = book(user_b, room_1, at(10), at(11))

    assert response.status_code == 201


def test_different_offsets_for_same_instant_overlap(
    client: TestClient, given_booking: GivenBooking, at: At, user_a: UUID, room_1: UUID
) -> None:
    given_booking(room_1, user_a, at(8), at(9))

    response = client.post(
        "/bookings",
        headers={"X-User-Id": str(user_a)},
        json={
            "room_id": str(room_1),
            "start": "2026-10-21T10:00:00+02:00",
            "end": "2026-10-21T11:00:00+02:00",
        },
    )

    assert response.status_code == 409


@pytest.mark.parametrize(("start_hour", "end_hour"), [(10, 10), (11, 10)])
def test_end_must_be_after_start(
    book: Book,
    confirmed_bookings: ConfirmedBookings,
    at: At,
    user_a: UUID,
    room_1: UUID,
    start_hour: int,
    end_hour: int,
) -> None:
    response = book(user_a, room_1, at(start_hour), at(end_hour))

    assert response.status_code == 422
    assert confirmed_bookings(room_1) == []


@pytest.mark.parametrize("minutes_before_now", [0, 1])
def test_booking_cannot_start_in_past(
    book: Book,
    confirmed_bookings: ConfirmedBookings,
    clock: FixedClock,
    user_a: UUID,
    room_1: UUID,
    minutes_before_now: int,
) -> None:
    start = clock.now() - timedelta(minutes=minutes_before_now)

    response = book(user_a, room_1, start, start + timedelta(hours=1))

    assert response.status_code == 422
    assert confirmed_bookings(room_1) == []


MALFORMED_REQUESTS: dict[str, tuple[str, str, dict[str, Any] | None]] = {
    "start without offset": (
        "POST",
        "/bookings",
        {"start": "2026-10-21T10:00:00", "end": "2026-10-21T11:00:00Z"},
    ),
    "end without offset": (
        "POST",
        "/bookings",
        {"start": "2026-10-21T10:00:00Z", "end": "2026-10-21T11:00:00"},
    ),
    "room_id not a UUID": ("POST", "/bookings", {"room_id": "room-1"}),
    "booking id not a UUID": ("GET", "/bookings/not-a-uuid", None),
}


@pytest.mark.parametrize("case", MALFORMED_REQUESTS, ids=list(MALFORMED_REQUESTS))
def test_malformed_input_is_rejected(
    client: TestClient,
    confirmed_bookings: ConfirmedBookings,
    user_a: UUID,
    room_1: UUID,
    room_2: UUID,
    case: str,
) -> None:
    method, path, overrides = MALFORMED_REQUESTS[case]
    body = None
    if overrides is not None:
        body = {
            "room_id": str(room_1),
            "start": "2026-10-21T10:00:00Z",
            "end": "2026-10-21T11:00:00Z",
            **overrides,
        }

    response = client.request(method, path, headers={"X-User-Id": str(user_a)}, json=body)

    assert response.status_code == 422
    assert confirmed_bookings(room_1) == []
    assert confirmed_bookings(room_2) == []


def test_unknown_room_returns_404(book: Book, at: At, user_a: UUID) -> None:
    response = book(user_a, uuid4(), at(10), at(11))

    assert response.status_code == 404


@pytest.mark.parametrize("method", ["POST", "GET"])
@pytest.mark.parametrize(
    "headers",
    [{}, {"X-User-Id": "not-a-uuid"}, {"X-User-Id": str(uuid4())}],
    ids=["missing", "not a UUID", "unknown user"],
)
def test_missing_or_unknown_user_returns_401(
    client: TestClient, room_1: UUID, method: str, headers: dict[str, str]
) -> None:
    if method == "POST":
        response = client.post(
            "/bookings",
            headers=headers,
            json={
                "room_id": str(room_1),
                "start": "2026-10-21T10:00:00Z",
                "end": "2026-10-21T11:00:00Z",
            },
        )
    else:
        response = client.get(f"/bookings/{uuid4()}", headers=headers)

    assert response.status_code == 401


ERROR_CASES = [
    "overlap",
    "invalid range",
    "in the past",
    "start without offset",
    "room_id not a UUID",
    "booking id not a UUID",
    "unknown room",
    "unknown booking",
    "missing user",
]


@pytest.mark.parametrize("case", ERROR_CASES)
def test_errors_use_problem_details(
    client: TestClient,
    book: Book,
    given_booking: GivenBooking,
    clock: FixedClock,
    at: At,
    user_a: UUID,
    room_1: UUID,
    case: str,
) -> None:
    as_user_a = {"X-User-Id": str(user_a)}
    if case == "overlap":
        given_booking(room_1, user_a, at(10), at(11))
        response = book(user_a, room_1, at(10), at(11))
    elif case == "invalid range":
        response = book(user_a, room_1, at(11), at(10))
    elif case == "in the past":
        response = book(user_a, room_1, clock.now(), clock.now() + timedelta(hours=1))
    elif case == "start without offset":
        response = client.post(
            "/bookings",
            headers=as_user_a,
            json={
                "room_id": str(room_1),
                "start": "2026-10-21T10:00:00",
                "end": "2026-10-21T11:00:00Z",
            },
        )
    elif case == "room_id not a UUID":
        response = client.post(
            "/bookings",
            headers=as_user_a,
            json={
                "room_id": "room-1",
                "start": "2026-10-21T10:00:00Z",
                "end": "2026-10-21T11:00:00Z",
            },
        )
    elif case == "booking id not a UUID":
        response = client.get("/bookings/not-a-uuid", headers=as_user_a)
    elif case == "unknown room":
        response = book(user_a, uuid4(), at(10), at(11))
    elif case == "unknown booking":
        response = client.get(f"/bookings/{uuid4()}", headers=as_user_a)
    else:
        response = client.get(f"/bookings/{uuid4()}")

    assert response.status_code >= 400
    assert response.headers["Content-Type"].startswith("application/problem+json")
    body = response.json()
    assert isinstance(body["type"], str)
    assert isinstance(body["title"], str)
    assert body["status"] == response.status_code
