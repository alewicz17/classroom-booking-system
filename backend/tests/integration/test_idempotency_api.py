from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from booking.adapters.api import create_app
from booking.adapters.memory import FixedClock
from booking.adapters.postgres import PostgresUnitOfWork
from booking.domain.booking import Booking
from booking.domain.idempotency import IdempotencyKey

Book = Callable[[UUID, UUID, datetime, datetime], Response]
BookWithKey = Callable[[UUID, UUID, datetime, datetime, str], Response]
GivenBooking = Callable[..., Booking]
ConfirmedBookings = Callable[[UUID], list[Booking]]
StoredKey = Callable[[UUID, UUID], IdempotencyKey | None]
At = Callable[..., datetime]

KEY_K = UUID("7e4b2c19-3a5d-4f6e-8b1c-9d0a2e3f4b5c")
MISMATCH_TYPE = "/problems/idempotency-key-mismatch"


def send(
    client: TestClient, user_id: UUID, room_id: UUID, start: datetime, end: datetime, key: str
) -> Response:
    return client.post(
        "/bookings",
        headers={"X-User-Id": str(user_id), "Idempotency-Key": key},
        json={"room_id": str(room_id), "start": start.isoformat(), "end": end.isoformat()},
    )


@pytest.fixture
def book_with_key(client: TestClient) -> BookWithKey:
    """Returns a function that sends POST /bookings as the given user with an Idempotency-Key."""

    def post(user_id: UUID, room_id: UUID, start: datetime, end: datetime, key: str) -> Response:
        return send(client, user_id, room_id, start, end, key)

    return post


@pytest.fixture
def cancel(client: TestClient) -> Callable[[UUID, str], Response]:
    """Returns a function that cancels a booking as the given user."""

    def post(user_id: UUID, booking_id: str) -> Response:
        return client.post(f"/bookings/{booking_id}/cancel", headers={"X-User-Id": str(user_id)})

    return post


def day_after(value: datetime) -> datetime:
    """Same time on the next day: far enough from NOW to be cancelled (spec 002)."""
    return value + timedelta(days=1)


# First use and replay


def test_request_with_new_key_creates_booking(
    book_with_key: BookWithKey, stored_key: StoredKey, at: At, user_a: UUID, room_1: UUID
) -> None:
    response = book_with_key(user_a, room_1, at(8), at(9), str(KEY_K))

    assert response.status_code == 201
    assert response.headers["Location"] == f"/bookings/{response.json()['id']}"
    assert response.json()["status"] == "confirmed"
    assert stored_key(user_a, KEY_K) is not None


def test_retry_with_same_key_and_payload_replays_response(
    book_with_key: BookWithKey,
    confirmed_bookings: ConfirmedBookings,
    at: At,
    user_a: UUID,
    room_1: UUID,
) -> None:
    first = book_with_key(user_a, room_1, at(8), at(9), str(KEY_K))

    retry = book_with_key(user_a, room_1, at(8), at(9), str(KEY_K))

    assert retry.status_code == 201
    assert retry.headers["Location"] == first.headers["Location"]
    assert retry.json() == first.json()
    assert len(confirmed_bookings(room_1)) == 1


def test_payload_is_compared_after_normalization_to_utc(
    book_with_key: BookWithKey,
    confirmed_bookings: ConfirmedBookings,
    at: At,
    user_a: UUID,
    room_1: UUID,
) -> None:
    first = book_with_key(user_a, room_1, at(8), at(9), str(KEY_K))
    plus_two = timezone(timedelta(hours=2))

    retry = book_with_key(
        user_a, room_1, at(8).astimezone(plus_two), at(9).astimezone(plus_two), str(KEY_K)
    )

    assert retry.status_code == 201
    assert retry.json() == first.json()
    assert len(confirmed_bookings(room_1)) == 1


def test_retry_with_same_key_and_different_payload_is_rejected(
    book_with_key: BookWithKey,
    confirmed_bookings: ConfirmedBookings,
    at: At,
    user_a: UUID,
    room_1: UUID,
) -> None:
    first = book_with_key(user_a, room_1, at(8), at(9), str(KEY_K))

    response = book_with_key(user_a, room_1, at(12), at(13), str(KEY_K))

    assert response.status_code == 422
    assert response.json()["type"] == MISMATCH_TYPE
    assert [booking.id for booking in confirmed_bookings(room_1)] == [UUID(first.json()["id"])]


def test_replay_ignores_rules_that_no_longer_pass(
    book_with_key: BookWithKey, database_url: str, at: At, user_a: UUID, room_1: UUID
) -> None:
    first = book_with_key(user_a, room_1, at(8), at(9), str(KEY_K))
    later = create_app(
        uow_factory=lambda: PostgresUnitOfWork(database_url),
        clock=FixedClock(datetime(2026, 10, 21, 8, 30, tzinfo=UTC)),
    )

    retry = send(TestClient(later), user_a, room_1, at(8), at(9), str(KEY_K))

    assert retry.status_code == 201
    assert retry.json() == first.json()


def test_replay_is_not_blocked_by_per_user_limit(
    book_with_key: BookWithKey,
    given_booking: GivenBooking,
    at: At,
    user_a: UUID,
    room_1: UUID,
    room_2: UUID,
) -> None:
    given_booking(room_2, user_a, at(14), at(15))
    given_booking(room_2, user_a, at(15), at(16))
    first = book_with_key(user_a, room_1, at(8), at(9), str(KEY_K))

    retry = book_with_key(user_a, room_1, at(8), at(9), str(KEY_K))

    assert retry.status_code == 201
    assert retry.json() == first.json()


def test_replay_returns_stored_response_after_cancellation(
    book_with_key: BookWithKey,
    cancel: Callable[[UUID, str], Response],
    confirmed_bookings: ConfirmedBookings,
    at: At,
    user_a: UUID,
    room_1: UUID,
) -> None:
    start, end = day_after(at(8)), day_after(at(9))
    first = book_with_key(user_a, room_1, start, end, str(KEY_K))
    assert cancel(user_a, first.json()["id"]).status_code == 200

    retry = book_with_key(user_a, room_1, start, end, str(KEY_K))

    assert retry.status_code == 201
    assert retry.json() == first.json()
    assert retry.json()["status"] == "confirmed"
    assert confirmed_bookings(room_1) == []


# What is stored


def test_failed_request_does_not_store_key(
    book_with_key: BookWithKey,
    given_booking: GivenBooking,
    cancel: Callable[[UUID, str], Response],
    confirmed_bookings: ConfirmedBookings,
    at: At,
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
) -> None:
    start, end = day_after(at(8)), day_after(at(9))
    taken = given_booking(room_1, user_b, start, end)
    assert book_with_key(user_a, room_1, start, end, str(KEY_K)).status_code == 409
    assert cancel(user_b, str(taken.id)).status_code == 200

    retry = book_with_key(user_a, room_1, start, end, str(KEY_K))

    assert retry.status_code == 201
    assert [booking.user_id for booking in confirmed_bookings(room_1)] == [user_a]


def test_key_is_scoped_to_its_user(
    book_with_key: BookWithKey,
    confirmed_bookings: ConfirmedBookings,
    at: At,
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
    room_2: UUID,
) -> None:
    book_with_key(user_a, room_1, at(8), at(9), str(KEY_K))

    response = book_with_key(user_b, room_2, at(8), at(9), str(KEY_K))

    assert response.status_code == 201
    assert [booking.user_id for booking in confirmed_bookings(room_2)] == [user_b]


def test_without_header_nothing_changes(book: Book, at: At, user_a: UUID, room_1: UUID) -> None:
    book(user_a, room_1, at(8), at(9))

    response = book(user_a, room_1, at(8), at(9))

    assert response.status_code == 409


# Validation


@pytest.mark.parametrize("key", ["", "not-a-uuid"])
def test_malformed_key_is_rejected(
    book_with_key: BookWithKey,
    confirmed_bookings: ConfirmedBookings,
    at: At,
    user_a: UUID,
    room_1: UUID,
    key: str,
) -> None:
    response = book_with_key(user_a, room_1, at(8), at(9), key)

    assert response.status_code == 422
    assert confirmed_bookings(room_1) == []


def test_key_mismatch_is_checked_before_rules(
    book_with_key: BookWithKey, at: At, user_a: UUID, room_1: UUID
) -> None:
    book_with_key(user_a, room_1, at(8), at(9), str(KEY_K))

    response = book_with_key(user_a, room_1, at(9), at(8), str(KEY_K))

    assert response.status_code == 422
    assert response.json()["type"] == MISMATCH_TYPE


@pytest.mark.parametrize("case", ["key mismatch", "malformed key"])
def test_idempotency_errors_use_problem_details(
    book_with_key: BookWithKey, at: At, user_a: UUID, room_1: UUID, case: str
) -> None:
    if case == "key mismatch":
        book_with_key(user_a, room_1, at(8), at(9), str(KEY_K))
        response = book_with_key(user_a, room_1, at(12), at(13), str(KEY_K))
    else:
        response = book_with_key(user_a, room_1, at(8), at(9), "not-a-uuid")

    assert response.status_code == 422
    assert response.headers["Content-Type"].startswith("application/problem+json")
    body = response.json()
    assert isinstance(body["type"], str)
    assert isinstance(body["title"], str)
    assert body["status"] == 422
