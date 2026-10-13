import threading
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import UUID

from psycopg.conninfo import make_conninfo

from booking import services
from booking.adapters.memory import FixedClock, RecordingNotifier
from booking.adapters.postgres import PostgresUnitOfWork
from booking.domain.booking import Booking

THREADS = 10
BOOKINGS_PER_ROOM = 10


def test_concurrent_passes_send_each_reminder_exactly_once(
    database_url: str,
    clock: FixedClock,
    given_booking: Callable[..., Booking],
    stored_reminder_sent_at: Callable[[UUID], datetime | None],
    room_1: UUID,
    room_2: UUID,
    user_a: UUID,
    today_at: Callable[..., datetime],
) -> None:
    # 20 back-to-back 3-minute bookings over two rooms, all starting within the hour.
    length = timedelta(minutes=3)
    bookings = [
        given_booking(room_id, user_a, start, start + length)
        for room_id in (room_1, room_2)
        for start in (today_at(10, 3) + i * length for i in range(BOOKINGS_PER_ROOM))
    ]
    notifier = RecordingNotifier()
    barrier = threading.Barrier(THREADS)

    def run_pass() -> int:
        uow = PostgresUnitOfWork(database_url)
        barrier.wait()
        return services.send_reminders(uow, clock, notifier)

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = [executor.submit(run_pass) for _ in range(THREADS)]
        results = [future.result() for future in futures]

    assert Counter(booking.id for booking in notifier.received) == {
        booking.id: 1 for booking in bookings
    }
    assert sum(results) == len(bookings)
    assert all(stored_reminder_sent_at(booking.id) is not None for booking in bookings)


def test_pass_does_not_wait_for_the_locks_of_another_pass(
    database_url: str,
    clock: FixedClock,
    given_booking: Callable[..., Booking],
    room_1: UUID,
    user_a: UUID,
    today_at: Callable[..., datetime],
) -> None:
    booking = given_booking(room_1, user_a, today_at(10, 30), today_at(11, 30))
    notifier = RecordingNotifier()
    # A pass that waited for the lock would fail with LockNotAvailable after 1 second.
    impatient = PostgresUnitOfWork(make_conninfo(database_url, options="-c lock_timeout=1s"))

    with PostgresUnitOfWork(database_url) as holder:
        assert holder.bookings.find_due_for_reminder(clock.now()) == [booking]

        sent = services.send_reminders(impatient, clock, notifier)

    assert sent == 0
    assert notifier.received == []
