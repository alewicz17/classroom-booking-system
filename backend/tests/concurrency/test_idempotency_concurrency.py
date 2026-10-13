import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import UUID

from booking import services
from booking.adapters.memory import FixedClock
from booking.adapters.postgres import PostgresUnitOfWork
from booking.domain.booking import Booking
from booking.domain.errors import IdempotencyKeyMismatch
from booking.domain.idempotency import IdempotencyKey

THREADS = 50
KEY_K = UUID("7e4b2c19-3a5d-4f6e-8b1c-9d0a2e3f4b5c")

# (user_id, room_id, start, end, idempotency_key)
Request = tuple[UUID, UUID, datetime, datetime, UUID]


def book_concurrently(
    database_url: str, clock: FixedClock, requests: list[Request]
) -> list[Booking | Exception]:
    """Sends every request at once, one thread and one connection per request."""
    barrier = threading.Barrier(len(requests))

    def attempt(
        user_id: UUID, room_id: UUID, start: datetime, end: datetime, key: UUID
    ) -> Booking | Exception:
        uow = PostgresUnitOfWork(database_url)
        barrier.wait()
        try:
            return services.create_booking(uow, clock, user_id, room_id, start, end, key)
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=len(requests)) as executor:
        futures = [executor.submit(attempt, *request) for request in requests]
        return [future.result() for future in futures]


def test_concurrent_retries_with_same_key_create_one_booking(
    database_url: str,
    clock: FixedClock,
    confirmed_bookings: Callable[[UUID], list[Booking]],
    stored_key: Callable[[UUID, UUID], IdempotencyKey | None],
    at: Callable[..., datetime],
    user_a: UUID,
    room_1: UUID,
) -> None:
    requests = [(user_a, room_1, at(8), at(9), KEY_K)] * THREADS

    results = book_concurrently(database_url, clock, requests)

    assert all(isinstance(result, Booking) for result in results)
    assert all(result == results[0] for result in results)
    assert confirmed_bookings(room_1) == [results[0]]
    stored = stored_key(user_a, KEY_K)
    assert stored is not None
    assert stored.response == results[0]


def test_concurrent_requests_with_same_key_and_different_payloads_exactly_one_wins(
    database_url: str,
    clock: FixedClock,
    confirmed_bookings: Callable[[UUID], list[Booking]],
    at: Callable[..., datetime],
    user_a: UUID,
    room_1: UUID,
) -> None:
    slot = timedelta(minutes=15)
    requests = [
        (user_a, room_1, at(6) + i * slot, at(6) + (i + 1) * slot, KEY_K) for i in range(THREADS)
    ]

    results = book_concurrently(database_url, clock, requests)

    assert sum(isinstance(result, Booking) for result in results) == 1
    assert sum(isinstance(result, IdempotencyKeyMismatch) for result in results) == THREADS - 1
    assert len(confirmed_bookings(room_1)) == 1
