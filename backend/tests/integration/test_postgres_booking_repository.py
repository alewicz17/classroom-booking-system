from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from booking.adapters.postgres import PostgresUnitOfWork
from booking.domain.booking import Booking, BookingStatus
from booking.domain.errors import SlotUnavailable


def test_database_rejects_overlap_without_domain_check(
    database_url: str,
    given_booking: Callable[..., Booking],
    at: Callable[..., datetime],
    user_a: UUID,
    user_b: UUID,
    room_1: UUID,
) -> None:
    given_booking(room_1, user_a, at(10), at(11))
    overlapping = Booking(uuid4(), room_1, user_b, at(10, 30), at(11, 30), BookingStatus.CONFIRMED)

    with pytest.raises(SlotUnavailable), PostgresUnitOfWork(database_url) as uow:
        uow.bookings.add(overlapping)
        uow.commit()
