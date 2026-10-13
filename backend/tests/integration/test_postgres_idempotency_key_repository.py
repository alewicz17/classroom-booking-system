from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from booking.adapters.postgres import PostgresUnitOfWork
from booking.domain.booking import Booking, BookingStatus
from booking.domain.errors import SlotUnavailable
from booking.domain.idempotency import IdempotencyKey

KEY_K = UUID("7e4b2c19-3a5d-4f6e-8b1c-9d0a2e3f4b5c")


def test_key_and_booking_are_committed_together(
    database_url: str,
    given_booking: Callable[..., Booking],
    stored_key: Callable[[UUID, UUID], IdempotencyKey | None],
    at: Callable[..., datetime],
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
) -> None:
    given_booking(room_1, user_b, at(8), at(9))
    overlapping = Booking(uuid4(), room_1, user_a, at(8), at(9), BookingStatus.CONFIRMED)

    # The key is written first, so only the rollback can explain its absence.
    with pytest.raises(SlotUnavailable), PostgresUnitOfWork(database_url) as uow:
        uow.idempotency_keys.add(IdempotencyKey(user_a, KEY_K, "hash", overlapping))
        uow.bookings.add(overlapping)
        uow.commit()

    assert stored_key(user_a, KEY_K) is None


def test_rolled_back_transaction_stores_neither_booking_nor_key(
    database_url: str,
    stored_key: Callable[[UUID, UUID], IdempotencyKey | None],
    at: Callable[..., datetime],
    user_a: UUID,
    room_1: UUID,
) -> None:
    booking = Booking(uuid4(), room_1, user_a, at(8), at(9), BookingStatus.CONFIRMED)

    with PostgresUnitOfWork(database_url) as uow:
        uow.bookings.add(booking)
        uow.idempotency_keys.add(IdempotencyKey(user_a, KEY_K, "hash", booking))

    with PostgresUnitOfWork(database_url) as uow:
        assert uow.bookings.get(booking.id) is None
    assert stored_key(user_a, KEY_K) is None
