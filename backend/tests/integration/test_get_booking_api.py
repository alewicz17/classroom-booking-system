from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from booking.domain.booking import Booking

GivenBooking = Callable[..., Booking]
At = Callable[..., datetime]


def test_user_reads_own_booking(
    client: TestClient, given_booking: GivenBooking, at: At, user_a: UUID, room_1: UUID
) -> None:
    booking = given_booking(room_1, user_a, at(10), at(11))

    response = client.get(f"/bookings/{booking.id}", headers={"X-User-Id": str(user_a)})

    assert response.status_code == 200
    assert response.json() == {
        "id": str(booking.id),
        "room_id": str(room_1),
        "user_id": str(user_a),
        "start": "2026-10-21T10:00:00Z",
        "end": "2026-10-21T11:00:00Z",
        "status": "confirmed",
    }


def test_other_users_booking_is_not_visible(
    client: TestClient,
    given_booking: GivenBooking,
    at: At,
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
) -> None:
    booking = given_booking(room_1, user_a, at(10), at(11))
    as_user_b = {"X-User-Id": str(user_b)}

    other_users = client.get(f"/bookings/{booking.id}", headers=as_user_b)
    missing = client.get(f"/bookings/{uuid4()}", headers=as_user_b)

    assert other_users.status_code == 404
    assert missing.status_code == 404
    for field in ("type", "title", "status"):
        assert other_users.json()[field] == missing.json()[field]
