from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from booking.domain.booking import Booking, BookingStatus

GivenBooking = Callable[..., Booking]


def oct_(day: int, hour: int) -> datetime:
    return datetime(2026, 10, day, hour, tzinfo=UTC)


def test_rooms_are_listed_sorted_by_name(
    client: TestClient, user_a: UUID, room_1: UUID, room_2: UUID
) -> None:
    response = client.get("/rooms", headers={"X-User-Id": str(user_a)})

    assert response.status_code == 200
    assert response.json() == [
        {"id": str(room_1), "name": "Room 1"},
        {"id": str(room_2), "name": "Room 2"},
    ]


def test_user_lists_only_own_bookings_sorted_by_start(
    client: TestClient,
    given_booking: GivenBooking,
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
    room_2: UUID,
) -> None:
    confirmed = given_booking(room_1, user_a, oct_(23, 8), oct_(23, 9))
    cancelled = given_booking(
        room_2, user_a, oct_(22, 8), oct_(22, 9), status=BookingStatus.CANCELLED
    )
    given_booking(room_1, user_b, oct_(22, 8), oct_(22, 9))

    response = client.get("/bookings", headers={"X-User-Id": str(user_a)})

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(cancelled.id),
            "room_id": str(room_2),
            "user_id": str(user_a),
            "start": "2026-10-22T08:00:00Z",
            "end": "2026-10-22T09:00:00Z",
            "status": "cancelled",
        },
        {
            "id": str(confirmed.id),
            "room_id": str(room_1),
            "user_id": str(user_a),
            "start": "2026-10-23T08:00:00Z",
            "end": "2026-10-23T09:00:00Z",
            "status": "confirmed",
        },
    ]


def test_user_with_no_bookings_gets_empty_list(client: TestClient, user_b: UUID) -> None:
    response = client.get("/bookings", headers={"X-User-Id": str(user_b)})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("path", ["/rooms", "/bookings"])
@pytest.mark.parametrize(
    "headers",
    [{}, {"X-User-Id": "not-a-uuid"}, {"X-User-Id": str(uuid4())}],
    ids=["missing", "not a UUID", "unknown user"],
)
def test_read_endpoints_require_known_user(
    client: TestClient, path: str, headers: dict[str, str]
) -> None:
    response = client.get(path, headers=headers)

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["status"] == 401
    assert response.json()["title"] == "Unauthorized"
