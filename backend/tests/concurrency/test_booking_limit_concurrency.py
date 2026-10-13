import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import UUID

from booking import services
from booking.adapters.memory import FixedClock
from booking.adapters.postgres import PostgresUnitOfWork
from booking.domain.booking import Booking
from booking.domain.errors import BookingLimitReached, SlotUnavailable

THREADS = 50

# (user_id, room_id, start, end)
Request = tuple[UUID, UUID, datetime, datetime]


def book_concurrently(
    database_url: str, clock: FixedClock, requests: list[Request]
) -> list[Booking | Exception]:
    """Sends every request at once, one thread and one connection per request."""
    barrier = threading.Barrier(len(requests))

    def attempt(
        user_id: UUID, room_id: UUID, start: datetime, end: datetime
    ) -> Booking | Exception:
        uow = PostgresUnitOfWork(database_url)
        barrier.wait()
        try:
            return services.create_booking(uow, clock, user_id, room_id, start, end)
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=len(requests)) as executor:
        futures = [executor.submit(attempt, *request) for request in requests]
        return [future.result() for future in futures]


def distinct_slots(at: Callable[..., datetime], count: int) -> list[tuple[datetime, datetime]]:
    """Back-to-back, non-overlapping 15-minute slots from 06:00Z."""
    slot = timedelta(minutes=15)
    return [(at(6) + i * slot, at(6) + (i + 1) * slot) for i in range(count)]


def test_concurrent_requests_from_same_user_exactly_limit_wins(
    database_url: str,
    clock: FixedClock,
    confirmed_bookings: Callable[[UUID], list[Booking]],
    at: Callable[..., datetime],
    user_a: UUID,
    room_1: UUID,
) -> None:
    requests = [(user_a, room_1, start, end) for start, end in distinct_slots(at, THREADS)]

    results = book_concurrently(database_url, clock, requests)

    assert sum(isinstance(result, Booking) for result in results) == 3
    assert sum(isinstance(result, BookingLimitReached) for result in results) == THREADS - 3
    assert len(confirmed_bookings(room_1)) == 3


def test_concurrent_requests_near_limit_exactly_one_wins(
    database_url: str,
    clock: FixedClock,
    given_booking: Callable[..., Booking],
    confirmed_bookings: Callable[[UUID], list[Booking]],
    at: Callable[..., datetime],
    user_a: UUID,
    room_1: UUID,
    room_2: UUID,
) -> None:
    given_booking(room_2, user_a, at(8), at(9))
    given_booking(room_2, user_a, at(9), at(10))
    requests = [(user_a, room_1, start, end) for start, end in distinct_slots(at, THREADS)]

    results = book_concurrently(database_url, clock, requests)

    assert sum(isinstance(result, Booking) for result in results) == 1
    assert sum(isinstance(result, BookingLimitReached) for result in results) == THREADS - 1
    assert len(confirmed_bookings(room_1)) + len(confirmed_bookings(room_2)) == 3


def test_different_users_on_same_slot_overlap_rule_still_decides(
    database_url: str,
    clock: FixedClock,
    confirmed_bookings: Callable[[UUID], list[Booking]],
    at: Callable[..., datetime],
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
) -> None:
    requests = [((user_a, user_b)[i % 2], room_1, at(8), at(9)) for i in range(THREADS)]

    results = book_concurrently(database_url, clock, requests)

    assert sum(isinstance(result, Booking) for result in results) == 1
    assert sum(isinstance(result, SlotUnavailable) for result in results) == THREADS - 1
    assert len(confirmed_bookings(room_1)) == 1
