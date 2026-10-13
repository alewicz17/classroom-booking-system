from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from booking import services
from booking.adapters.memory import FixedClock, InMemoryUnitOfWork, RecordingNotifier
from booking.domain.booking import Booking, BookingStatus

At = Callable[..., datetime]
Store = Callable[..., Booking]


class NotifierDown(Exception):
    pass


class FailingNotifier(RecordingNotifier):
    """Records like the fake, but fails on one chosen booking."""

    def __init__(self, fail_on: UUID) -> None:
        super().__init__()
        self.fail_on = fail_on

    def send_reminder(self, booking: Booking) -> None:
        if booking.id == self.fail_on:
            raise NotifierDown
        super().send_reminder(booking)


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture
def store(memory_uow: InMemoryUnitOfWork) -> Store:
    """Returns a function that stores a booking, bypassing the services."""

    def add(
        room_id: UUID,
        user_id: UUID,
        start: datetime,
        end: datetime,
        status: BookingStatus = BookingStatus.CONFIRMED,
    ) -> Booking:
        booking = Booking(uuid4(), room_id, user_id, start, end, status)
        memory_uow.bookings.add(booking)
        memory_uow.commit()
        return booking

    return add


def by_start(bookings: list[Booking]) -> list[Booking]:
    return sorted(bookings, key=lambda booking: booking.start)


def test_booking_that_starts_within_the_hour_is_reminded(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    notifier: RecordingNotifier,
    store: Store,
    room_1: UUID,
    user_a: UUID,
    today_at: At,
) -> None:
    booking = store(room_1, user_a, today_at(10, 30), today_at(11, 30))

    sent = services.send_reminders(memory_uow, clock, notifier)

    assert notifier.received == [booking]
    assert memory_uow.bookings.reminder_sent_at.get(booking.id) == clock.now()
    assert sent == 1


def test_booking_that_starts_exactly_one_hour_from_now_is_reminded(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    notifier: RecordingNotifier,
    store: Store,
    room_1: UUID,
    user_a: UUID,
    today_at: At,
) -> None:
    booking = store(room_1, user_a, today_at(11), today_at(12))

    sent = services.send_reminders(memory_uow, clock, notifier)

    assert notifier.received == [booking]
    assert sent == 1


def test_booking_that_starts_after_the_window_is_not_reminded(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    notifier: RecordingNotifier,
    store: Store,
    room_1: UUID,
    user_a: UUID,
    today_at: At,
) -> None:
    booking = store(room_1, user_a, today_at(11, 30), today_at(12, 30))

    sent = services.send_reminders(memory_uow, clock, notifier)

    assert notifier.received == []
    assert sent == 0
    assert memory_uow.bookings.reminder_sent_at.get(booking.id) is None


def test_booking_that_starts_now_or_has_started_is_not_reminded(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    notifier: RecordingNotifier,
    store: Store,
    room_1: UUID,
    room_2: UUID,
    user_a: UUID,
    today_at: At,
) -> None:
    store(room_1, user_a, today_at(10), today_at(11))
    store(room_2, user_a, today_at(9, 30), today_at(10, 30))

    sent = services.send_reminders(memory_uow, clock, notifier)

    assert notifier.received == []
    assert sent == 0


def test_cancelled_booking_is_not_reminded(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    notifier: RecordingNotifier,
    store: Store,
    room_1: UUID,
    user_a: UUID,
    today_at: At,
) -> None:
    store(room_1, user_a, today_at(10, 30), today_at(11, 30), BookingStatus.CANCELLED)

    sent = services.send_reminders(memory_uow, clock, notifier)

    assert notifier.received == []
    assert sent == 0


def test_all_due_bookings_are_reminded_in_one_pass(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    notifier: RecordingNotifier,
    store: Store,
    room_1: UUID,
    room_2: UUID,
    user_a: UUID,
    user_b: UUID,
    today_at: At,
) -> None:
    first = store(room_1, user_a, today_at(10, 30), today_at(11, 30))
    second = store(room_2, user_b, today_at(10, 45), today_at(11, 45))
    store(room_1, user_b, today_at(12), today_at(13))

    sent = services.send_reminders(memory_uow, clock, notifier)

    assert by_start(notifier.received) == [first, second]
    assert sent == 2


def test_with_nothing_due_the_notifier_is_not_called(
    memory_uow: InMemoryUnitOfWork, clock: FixedClock, notifier: RecordingNotifier
) -> None:
    sent = services.send_reminders(memory_uow, clock, notifier)

    assert notifier.received == []
    assert sent == 0


def test_second_pass_does_not_send_the_reminder_again(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    notifier: RecordingNotifier,
    store: Store,
    room_1: UUID,
    user_a: UUID,
    today_at: At,
) -> None:
    booking = store(room_1, user_a, today_at(10, 30), today_at(11, 30))
    services.send_reminders(memory_uow, clock, notifier)

    same_time = services.send_reminders(memory_uow, clock, notifier)
    later = services.send_reminders(memory_uow, FixedClock(today_at(10, 20)), notifier)

    assert notifier.received == [booking]
    assert same_time == 0
    assert later == 0


def test_notifier_failure_rolls_back_the_whole_pass(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    store: Store,
    room_1: UUID,
    room_2: UUID,
    user_a: UUID,
    today_at: At,
) -> None:
    first = store(room_1, user_a, today_at(10, 15), today_at(10, 30))
    second = store(room_2, user_a, today_at(10, 30), today_at(11, 30))
    third = store(room_1, user_a, today_at(10, 45), today_at(11, 45))

    with pytest.raises(NotifierDown):
        services.send_reminders(memory_uow, clock, FailingNotifier(fail_on=second.id))

    assert memory_uow.bookings.reminder_sent_at == {}

    working = RecordingNotifier()
    sent = services.send_reminders(memory_uow, clock, working)

    assert by_start(working.received) == [first, second, third]
    assert sent == 3
