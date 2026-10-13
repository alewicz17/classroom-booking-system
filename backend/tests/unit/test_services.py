from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest

from booking import services
from booking.adapters.memory import FixedClock, InMemoryUnitOfWork
from booking.domain.booking import Booking, BookingStatus
from booking.domain.errors import (
    BookingAlreadyCancelled,
    BookingLimitReached,
    BookingNotFound,
    IdempotencyKeyMismatch,
    RoomNotFound,
    SlotUnavailable,
)

At = Callable[..., datetime]


@pytest.fixture
def given_memory_booking(memory_uow: InMemoryUnitOfWork) -> Callable[..., Booking]:
    """Returns a function that stores a confirmed booking, bypassing the service."""

    def store(room_id: UUID, user_id: UUID, start: datetime, end: datetime) -> Booking:
        booking = Booking(uuid4(), room_id, user_id, start, end, BookingStatus.CONFIRMED)
        memory_uow.bookings.add(booking)
        memory_uow.commit()
        return booking

    return store


def test_create_booking_stores_confirmed_booking(
    memory_uow: InMemoryUnitOfWork, clock: FixedClock, user_a: UUID, room_1: UUID, at: At
) -> None:
    booking = services.create_booking(memory_uow, clock, user_a, room_1, at(10), at(11))

    assert memory_uow.bookings.get(booking.id) == booking
    assert booking.status == BookingStatus.CONFIRMED


def test_create_booking_in_unknown_room_raises_room_not_found(
    memory_uow: InMemoryUnitOfWork, clock: FixedClock, user_a: UUID, at: At
) -> None:
    with pytest.raises(RoomNotFound):
        services.create_booking(memory_uow, clock, user_a, uuid4(), at(10), at(11))


def test_create_booking_overlapping_raises_slot_unavailable(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    given_memory_booking: Callable[..., Booking],
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
    at: At,
) -> None:
    given_memory_booking(room_1, user_a, at(10), at(11))

    with pytest.raises(SlotUnavailable):
        services.create_booking(memory_uow, clock, user_b, room_1, at(10, 30), at(11, 30))


def test_create_booking_back_to_back_is_accepted(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    given_memory_booking: Callable[..., Booking],
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
    at: At,
) -> None:
    given_memory_booking(room_1, user_a, at(10), at(11))

    services.create_booking(memory_uow, clock, user_b, room_1, at(11), at(12))
    services.create_booking(memory_uow, clock, user_b, room_1, at(9), at(10))

    assert len(memory_uow.bookings.find_overlapping(room_1, at(9), at(12))) == 3


def test_cancelled_booking_does_not_block_slot(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    given_memory_booking: Callable[..., Booking],
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
    at: At,
) -> None:
    given = given_memory_booking(room_1, user_a, at(12), at(13))
    services.cancel_booking(memory_uow, clock, user_a, given.id)

    booking = services.create_booking(memory_uow, clock, user_b, room_1, at(12), at(13))

    assert booking.status == BookingStatus.CONFIRMED


def test_create_booking_over_limit_raises_limit_reached(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    given_memory_booking: Callable[..., Booking],
    user_a: UUID,
    room_1: UUID,
    at: At,
) -> None:
    for hour in (8, 9, 10):
        given_memory_booking(room_1, user_a, at(hour), at(hour + 1))

    with pytest.raises(BookingLimitReached):
        services.create_booking(memory_uow, clock, user_a, room_1, at(14), at(15))


def test_past_bookings_do_not_count_toward_limit(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    given_memory_booking: Callable[..., Booking],
    user_a: UUID,
    room_1: UUID,
    at: At,
) -> None:
    for days in (1, 2, 3):
        start = clock.now() - timedelta(days=days)
        given_memory_booking(room_1, user_a, start, start + timedelta(hours=1))

    booking = services.create_booking(memory_uow, clock, user_a, room_1, at(10), at(11))

    assert booking.status == BookingStatus.CONFIRMED


def test_replay_with_same_key_returns_stored_booking(
    memory_uow: InMemoryUnitOfWork, clock: FixedClock, user_a: UUID, room_1: UUID, at: At
) -> None:
    key = uuid4()

    first = services.create_booking(memory_uow, clock, user_a, room_1, at(10), at(11), key)
    second = services.create_booking(memory_uow, clock, user_a, room_1, at(10), at(11), key)

    assert second == first
    assert memory_uow.bookings.count_future(user_a, clock.now()) == 1


def test_same_key_different_payload_raises_mismatch(
    memory_uow: InMemoryUnitOfWork, clock: FixedClock, user_a: UUID, room_1: UUID, at: At
) -> None:
    key = uuid4()
    services.create_booking(memory_uow, clock, user_a, room_1, at(10), at(11), key)

    with pytest.raises(IdempotencyKeyMismatch):
        services.create_booking(memory_uow, clock, user_a, room_1, at(14), at(15), key)


def test_same_key_for_different_users_is_independent(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
    at: At,
) -> None:
    key = uuid4()

    first = services.create_booking(memory_uow, clock, user_a, room_1, at(10), at(11), key)
    second = services.create_booking(memory_uow, clock, user_b, room_1, at(14), at(15), key)

    assert second.id != first.id
    assert second.user_id == user_b


def test_rejected_request_stores_no_key(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    given_memory_booking: Callable[..., Booking],
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
    at: At,
) -> None:
    given_memory_booking(room_1, user_a, at(10), at(11))
    key = uuid4()

    with pytest.raises(SlotUnavailable):
        services.create_booking(memory_uow, clock, user_b, room_1, at(10), at(11), key)

    assert memory_uow.idempotency_keys.get(user_b, key) is None


def test_get_booking_of_another_user_raises_not_found(
    memory_uow: InMemoryUnitOfWork,
    given_memory_booking: Callable[..., Booking],
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
    at: At,
) -> None:
    booking = given_memory_booking(room_1, user_a, at(10), at(11))

    with pytest.raises(BookingNotFound):
        services.get_booking(memory_uow, user_b, booking.id)


def test_cancel_booking_frees_the_slot(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    given_memory_booking: Callable[..., Booking],
    user_a: UUID,
    room_1: UUID,
    at: At,
) -> None:
    booking = given_memory_booking(room_1, user_a, at(12), at(13))

    cancelled = services.cancel_booking(memory_uow, clock, user_a, booking.id)

    assert cancelled.status == BookingStatus.CANCELLED
    assert memory_uow.bookings.find_overlapping(room_1, at(12), at(13)) == []


def test_cancel_booking_of_another_user_raises_not_found(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    given_memory_booking: Callable[..., Booking],
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
    at: At,
) -> None:
    booking = given_memory_booking(room_1, user_a, at(12), at(13))

    with pytest.raises(BookingNotFound):
        services.cancel_booking(memory_uow, clock, user_b, booking.id)


def test_cancel_booking_twice_raises_already_cancelled(
    memory_uow: InMemoryUnitOfWork,
    clock: FixedClock,
    given_memory_booking: Callable[..., Booking],
    user_a: UUID,
    room_1: UUID,
    at: At,
) -> None:
    booking = given_memory_booking(room_1, user_a, at(12), at(13))
    services.cancel_booking(memory_uow, clock, user_a, booking.id)

    with pytest.raises(BookingAlreadyCancelled):
        services.cancel_booking(memory_uow, clock, user_a, booking.id)
