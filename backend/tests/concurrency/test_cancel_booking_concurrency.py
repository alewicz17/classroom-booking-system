import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID

from booking import services
from booking.adapters.memory import FixedClock
from booking.adapters.postgres import PostgresUnitOfWork
from booking.domain.booking import Booking, BookingStatus
from booking.domain.errors import BookingAlreadyCancelled

THREADS = 50


def test_concurrent_cancellations_of_same_booking_exactly_one_wins(
    database_url: str,
    clock: FixedClock,
    given_booking: Callable[..., Booking],
    user_a: UUID,
    room_1: UUID,
) -> None:
    booking = given_booking(
        room_1,
        user_a,
        datetime(2026, 10, 22, 8, 0, tzinfo=UTC),
        datetime(2026, 10, 22, 9, 0, tzinfo=UTC),
    )
    barrier = threading.Barrier(THREADS)

    def attempt() -> Booking | Exception:
        uow = PostgresUnitOfWork(database_url)
        barrier.wait()
        try:
            return services.cancel_booking(uow, clock, user_a, booking.id)
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = [executor.submit(attempt) for _ in range(THREADS)]
        results = [future.result() for future in futures]

    assert sum(isinstance(result, Booking) for result in results) == 1
    assert sum(isinstance(result, BookingAlreadyCancelled) for result in results) == THREADS - 1
    with PostgresUnitOfWork(database_url) as uow:
        stored = uow.bookings.get(booking.id)
    assert stored is not None
    assert stored.status == BookingStatus.CANCELLED
