"""Use cases. Depend only on domain and ports."""

from datetime import datetime
from uuid import UUID

from booking.domain.booking import Booking
from booking.ports import Clock, UnitOfWork


def create_booking(
    uow: UnitOfWork,
    clock: Clock,
    user_id: UUID,
    room_id: UUID,
    start: datetime,
    end: datetime,
) -> Booking:
    raise NotImplementedError
