"""Use cases. Depend only on domain and ports."""

from datetime import datetime
from uuid import UUID

from booking.domain.booking import Booking, cancel, check_booking_limit, new_booking
from booking.domain.errors import (
    BookingAlreadyCancelled,
    BookingNotFound,
    RoomNotFound,
    SlotUnavailable,
)
from booking.ports import Clock, UnitOfWork


def create_booking(
    uow: UnitOfWork,
    clock: Clock,
    user_id: UUID,
    room_id: UUID,
    start: datetime,
    end: datetime,
    idempotency_key: UUID | None = None,
) -> Booking:
    if idempotency_key is not None:
        raise NotImplementedError
    now = clock.now()
    booking = new_booking(room_id, user_id, start, end, now)
    with uow:
        if not uow.rooms.exists(room_id):
            raise RoomNotFound
        # Serializes this user's requests; taken before the insert to keep ADR 0005 valid
        # (ADR 0006).
        uow.users.lock(user_id)
        check_booking_limit(uow.bookings.count_future(user_id, now))
        # Pre-check for a clear error; the exclusion constraint is the real guarantee.
        if uow.bookings.find_overlapping(room_id, booking.start, booking.end):
            raise SlotUnavailable
        uow.bookings.add(booking)
        uow.commit()
    return booking


def get_booking(uow: UnitOfWork, user_id: UUID, booking_id: UUID) -> Booking:
    with uow:
        booking = uow.bookings.get(booking_id)
    # Another user's booking looks exactly like a missing one, so ids are not leaked.
    if booking is None or booking.user_id != user_id:
        raise BookingNotFound
    return booking


def cancel_booking(uow: UnitOfWork, clock: Clock, user_id: UUID, booking_id: UUID) -> Booking:
    with uow:
        booking = uow.bookings.get(booking_id)
        if booking is None or booking.user_id != user_id:
            raise BookingNotFound
        cancelled = cancel(booking, clock.now())
        # The read above may be stale: a concurrent request may have cancelled it since.
        if not uow.bookings.cancel(booking_id):
            raise BookingAlreadyCancelled
        uow.commit()
    return cancelled
