"""One suite for every adapter: a fake that disagrees with Postgres would make unit tests lie."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest

from booking.adapters.memory import FixedClock, InMemoryUnitOfWork
from booking.adapters.postgres import PostgresUnitOfWork
from booking.domain.booking import Booking, BookingStatus
from booking.domain.errors import SlotUnavailable
from booking.domain.idempotency import IdempotencyKey
from booking.ports import UnitOfWork

At = Callable[..., datetime]
UowFactory = Callable[[], UnitOfWork]

# Services check these preconditions first, so a violation is a bug, not a domain error.
# Both adapters must reject it; the exception type is adapter-specific.
INTEGRITY_ERRORS = (ValueError, psycopg.IntegrityError)


@pytest.fixture(params=["memory", "postgres"])
def uow_factory(request: pytest.FixtureRequest, memory_uow: InMemoryUnitOfWork) -> UowFactory:
    if request.param == "memory":
        # One instance plays the database: each use sees what earlier uses committed.
        return lambda: memory_uow
    # Requested only here, so the memory variant runs without Docker.
    database_url: str = request.getfixturevalue("database_url")
    return lambda: PostgresUnitOfWork(database_url)


def booking(
    room_id: UUID,
    user_id: UUID,
    start: datetime,
    end: datetime,
    status: BookingStatus = BookingStatus.CONFIRMED,
) -> Booking:
    return Booking(uuid4(), room_id, user_id, start, end, status)


def store(uow_factory: UowFactory, *bookings: Booking) -> None:
    with uow_factory() as uow:
        for each in bookings:
            uow.bookings.add(each)
        uow.commit()


def store_key(uow_factory: UowFactory, key: IdempotencyKey) -> None:
    with uow_factory() as uow:
        uow.bookings.add(key.response)
        uow.idempotency_keys.add(key)
        uow.commit()


def test_added_booking_can_be_read_back(
    uow_factory: UowFactory, room_1: UUID, user_a: UUID, at: At
) -> None:
    added = booking(room_1, user_a, at(10), at(11))
    store(uow_factory, added)

    with uow_factory() as uow:
        assert uow.bookings.get(added.id) == added


def test_get_unknown_booking_returns_none(uow_factory: UowFactory) -> None:
    with uow_factory() as uow:
        assert uow.bookings.get(uuid4()) is None


def test_find_overlapping_finds_partial_containing_and_contained(
    uow_factory: UowFactory, room_1: UUID, user_a: UUID, at: At
) -> None:
    partial = booking(room_1, user_a, at(9), at(10, 30))
    contained = booking(room_1, user_a, at(10, 45), at(11))
    store(uow_factory, partial, contained)

    with uow_factory() as uow:
        assert uow.bookings.find_overlapping(room_1, at(10), at(12)) == [partial, contained]
        assert uow.bookings.find_overlapping(room_1, at(10, 50), at(10, 55)) == [contained]


def test_find_overlapping_ignores_back_to_back(
    uow_factory: UowFactory, room_1: UUID, user_a: UUID, at: At
) -> None:
    before = booking(room_1, user_a, at(9), at(10))
    after = booking(room_1, user_a, at(11), at(12))
    store(uow_factory, before, after)

    with uow_factory() as uow:
        assert uow.bookings.find_overlapping(room_1, at(10), at(11)) == []


def test_find_overlapping_ignores_other_rooms_and_cancelled(
    uow_factory: UowFactory, room_1: UUID, room_2: UUID, user_a: UUID, at: At
) -> None:
    store(
        uow_factory,
        booking(room_2, user_a, at(10), at(11)),
        booking(room_1, user_a, at(10), at(11), BookingStatus.CANCELLED),
    )

    with uow_factory() as uow:
        assert uow.bookings.find_overlapping(room_1, at(10), at(11)) == []


def test_find_overlapping_is_ordered_by_start(
    uow_factory: UowFactory, room_1: UUID, user_a: UUID, at: At
) -> None:
    late = booking(room_1, user_a, at(14), at(15))
    early = booking(room_1, user_a, at(8), at(9))
    middle = booking(room_1, user_a, at(11), at(12))
    store(uow_factory, late, early, middle)

    with uow_factory() as uow:
        assert uow.bookings.find_overlapping(room_1, at(0), at(23)) == [early, middle, late]


def test_add_overlapping_confirmed_raises_slot_unavailable(
    uow_factory: UowFactory, room_1: UUID, user_a: UUID, user_b: UUID, at: At
) -> None:
    store(uow_factory, booking(room_1, user_a, at(10), at(11)))

    with pytest.raises(SlotUnavailable), uow_factory() as uow:
        uow.bookings.add(booking(room_1, user_b, at(10, 30), at(11, 30)))


def test_add_overlapping_cancelled_is_accepted(
    uow_factory: UowFactory, room_1: UUID, user_a: UUID, user_b: UUID, at: At
) -> None:
    store(uow_factory, booking(room_1, user_a, at(10), at(11)))
    cancelled = booking(room_1, user_b, at(10), at(11), BookingStatus.CANCELLED)

    store(uow_factory, cancelled)

    with uow_factory() as uow:
        assert uow.bookings.get(cancelled.id) == cancelled


def test_add_booking_for_unknown_room_is_rejected(
    uow_factory: UowFactory, user_a: UUID, at: At
) -> None:
    with pytest.raises(INTEGRITY_ERRORS), uow_factory() as uow:
        uow.bookings.add(booking(uuid4(), user_a, at(10), at(11)))


def test_add_booking_for_unknown_user_is_rejected(
    uow_factory: UowFactory, room_1: UUID, at: At
) -> None:
    with pytest.raises(INTEGRITY_ERRORS), uow_factory() as uow:
        uow.bookings.add(booking(room_1, uuid4(), at(10), at(11)))


def test_cancel_returns_true_once_then_false(
    uow_factory: UowFactory, room_1: UUID, user_a: UUID, at: At
) -> None:
    added = booking(room_1, user_a, at(10), at(11))
    store(uow_factory, added)

    with uow_factory() as uow:
        assert uow.bookings.cancel(added.id) is True
        assert uow.bookings.cancel(added.id) is False
        cancelled = uow.bookings.get(added.id)
        assert cancelled is not None
        assert cancelled.status == BookingStatus.CANCELLED


def test_cancel_unknown_returns_false(uow_factory: UowFactory) -> None:
    with uow_factory() as uow:
        assert uow.bookings.cancel(uuid4()) is False


def test_count_future_counts_only_confirmed_of_user_starting_after_now(
    uow_factory: UowFactory,
    clock: FixedClock,
    room_1: UUID,
    room_2: UUID,
    user_a: UUID,
    user_b: UUID,
    at: At,
) -> None:
    now = clock.now()
    hour = timedelta(hours=1)
    store(
        uow_factory,
        booking(room_1, user_a, at(10), at(11)),
        booking(room_2, user_a, now, now + hour),
        booking(room_1, user_a, now - 2 * hour, now - hour),
        booking(room_2, user_a, at(10), at(11), BookingStatus.CANCELLED),
        booking(room_1, user_b, at(12), at(13)),
    )

    with uow_factory() as uow:
        assert uow.bookings.count_future(user_a, now) == 1


def test_seeded_room_and_user_exist_unknown_do_not(
    uow_factory: UowFactory, room_1: UUID, user_a: UUID
) -> None:
    with uow_factory() as uow:
        assert uow.rooms.exists(room_1)
        assert uow.users.exists(user_a)
        assert not uow.rooms.exists(uuid4())
        assert not uow.users.exists(uuid4())


def test_added_key_can_be_read_back(
    uow_factory: UowFactory, room_1: UUID, user_a: UUID, at: At
) -> None:
    key = IdempotencyKey(user_a, uuid4(), "hash", booking(room_1, user_a, at(10), at(11)))
    store_key(uow_factory, key)

    with uow_factory() as uow:
        assert uow.idempotency_keys.get(user_a, key.key) == key


def test_key_is_scoped_to_user(
    uow_factory: UowFactory, room_1: UUID, user_a: UUID, user_b: UUID, at: At
) -> None:
    key = IdempotencyKey(user_a, uuid4(), "hash", booking(room_1, user_a, at(10), at(11)))
    store_key(uow_factory, key)

    with uow_factory() as uow:
        assert uow.idempotency_keys.get(user_b, key.key) is None
        assert uow.idempotency_keys.get(user_a, uuid4()) is None


def test_add_same_key_twice_is_rejected(
    uow_factory: UowFactory, room_1: UUID, user_a: UUID, at: At
) -> None:
    key = IdempotencyKey(user_a, uuid4(), "hash", booking(room_1, user_a, at(10), at(11)))
    store_key(uow_factory, key)
    again = IdempotencyKey(user_a, key.key, "other", booking(room_1, user_a, at(14), at(15)))

    with pytest.raises(INTEGRITY_ERRORS), uow_factory() as uow:
        uow.bookings.add(again.response)
        uow.idempotency_keys.add(again)


def test_uncommitted_changes_are_discarded(
    uow_factory: UowFactory, room_1: UUID, user_a: UUID, at: At
) -> None:
    key = IdempotencyKey(user_a, uuid4(), "hash", booking(room_1, user_a, at(10), at(11)))
    with uow_factory() as uow:
        uow.bookings.add(key.response)
        uow.idempotency_keys.add(key)

    with uow_factory() as uow:
        assert uow.bookings.get(key.response.id) is None
        assert uow.idempotency_keys.get(user_a, key.key) is None


def test_committed_changes_are_visible_in_new_unit_of_work(
    uow_factory: UowFactory, room_1: UUID, user_a: UUID, at: At
) -> None:
    added = booking(room_1, user_a, at(12), at(13))
    store(uow_factory, added)
    with uow_factory() as uow:
        uow.bookings.cancel(added.id)
        uow.commit()

    with uow_factory() as uow:
        cancelled = uow.bookings.get(added.id)
        assert cancelled is not None
        assert cancelled.status == BookingStatus.CANCELLED


def stored_reminder_sent_at(uow: UnitOfWork, booking_id: UUID) -> datetime | None:
    # reminder_sent_at is not on Booking, so each adapter is read where it keeps it.
    if isinstance(uow, PostgresUnitOfWork):
        row = uow.connection.execute(
            "SELECT reminder_sent_at FROM bookings WHERE id = %s", (booking_id,)
        ).fetchone()
        assert row is not None
        sent_at: datetime | None = row[0]
        return sent_at
    assert isinstance(uow, InMemoryUnitOfWork)
    return uow.bookings.reminder_sent_at.get(booking_id)


def by_start(bookings: list[Booking]) -> list[Booking]:
    return sorted(bookings, key=lambda each: each.start)


def test_due_bookings_query_follows_rule_1(
    uow_factory: UowFactory,
    clock: FixedClock,
    room_1: UUID,
    room_2: UUID,
    user_a: UUID,
    today_at: At,
) -> None:
    quarter = timedelta(minutes=15)

    # 15 minutes long: with the full ranges of AC-01 to AC-05, two rooms are not enough.
    def short(
        room_id: UUID, start: datetime, status: BookingStatus = BookingStatus.CONFIRMED
    ) -> Booking:
        return booking(room_id, user_a, start, start + quarter, status)

    within_the_hour = short(room_1, today_at(10, 30))
    at_one_hour = short(room_1, today_at(11))
    after_the_window = short(room_1, today_at(11, 30))
    starting_now = short(room_1, today_at(10))
    started = short(room_1, today_at(9, 30))
    cancelled = short(room_1, today_at(10, 30), BookingStatus.CANCELLED)
    already_reminded = short(room_2, today_at(10, 30))
    store(
        uow_factory,
        within_the_hour,
        at_one_hour,
        after_the_window,
        starting_now,
        started,
        cancelled,
        already_reminded,
    )
    with uow_factory() as uow:
        uow.bookings.mark_reminder_sent(already_reminded.id, clock.now() - quarter)
        uow.commit()

    with uow_factory() as uow:
        due = uow.bookings.find_due_for_reminder(clock.now())

    assert by_start(due) == [within_the_hour, at_one_hour]


def test_booking_marked_as_sent_is_no_longer_due(
    uow_factory: UowFactory, clock: FixedClock, room_1: UUID, user_a: UUID, today_at: At
) -> None:
    added = booking(room_1, user_a, today_at(10, 30), today_at(11, 30))
    store(uow_factory, added)
    with uow_factory() as uow:
        assert uow.bookings.find_due_for_reminder(clock.now()) == [added]
        uow.bookings.mark_reminder_sent(added.id, clock.now())
        uow.commit()

    with uow_factory() as uow:
        assert uow.bookings.find_due_for_reminder(clock.now()) == []
        assert stored_reminder_sent_at(uow, added.id) == clock.now()


def test_rolled_back_mark_is_not_kept(
    uow_factory: UowFactory, clock: FixedClock, room_1: UUID, user_a: UUID, today_at: At
) -> None:
    added = booking(room_1, user_a, today_at(10, 30), today_at(11, 30))
    store(uow_factory, added)
    with uow_factory() as uow:
        uow.bookings.mark_reminder_sent(added.id, clock.now())

    with uow_factory() as uow:
        assert uow.bookings.find_due_for_reminder(clock.now()) == [added]
