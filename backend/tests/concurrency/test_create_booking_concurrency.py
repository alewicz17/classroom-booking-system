import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import UUID

from booking import services
from booking.adapters.memory import FixedClock
from booking.adapters.postgres import PostgresUnitOfWork
from booking.domain.booking import Booking
from booking.domain.errors import SlotUnavailable

THREADS = 50


def book_concurrently(
    database_url: str,
    clock: FixedClock,
    user_id: UUID,
    room_id: UUID,
    ranges: list[tuple[datetime, datetime]],
) -> list[Booking | Exception]:
    """Books every range at once, one thread and one connection per range."""
    barrier = threading.Barrier(len(ranges))

    def attempt(start: datetime, end: datetime) -> Booking | Exception:
        uow = PostgresUnitOfWork(database_url)
        barrier.wait()
        try:
            return services.create_booking(uow, clock, user_id, room_id, start, end)
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=len(ranges)) as executor:
        futures = [executor.submit(attempt, start, end) for start, end in ranges]
        return [future.result() for future in futures]


def test_concurrent_requests_for_same_slot_exactly_one_wins(
    database_url: str,
    clock: FixedClock,
    confirmed_bookings: Callable[[UUID], list[Booking]],
    at: Callable[..., datetime],
    user_a: UUID,
    room_1: UUID,
) -> None:
    ranges = [(at(10), at(11))] * THREADS

    results = book_concurrently(database_url, clock, user_a, room_1, ranges)

    assert sum(isinstance(result, Booking) for result in results) == 1
    assert sum(isinstance(result, SlotUnavailable) for result in results) == THREADS - 1
    assert len(confirmed_bookings(room_1)) == 1


def test_concurrent_overlapping_requests_exactly_one_wins(
    database_url: str,
    clock: FixedClock,
    confirmed_bookings: Callable[[UUID], list[Booking]],
    at: Callable[..., datetime],
    user_a: UUID,
    room_1: UUID,
) -> None:
    # Range i is shifted by i minutes, so every range contains 10:49-11:00.
    ranges = [
        (at(10) + timedelta(minutes=i), at(11) + timedelta(minutes=i)) for i in range(THREADS)
    ]

    results = book_concurrently(database_url, clock, user_a, room_1, ranges)

    assert sum(isinstance(result, Booking) for result in results) == 1
    assert len(confirmed_bookings(room_1)) == 1
