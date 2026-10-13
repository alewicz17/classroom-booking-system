"""Use cases. Depend only on domain and ports."""

from datetime import datetime
from uuid import UUID

from booking.domain.booking import Booking, cancel, check_booking_limit, new_booking
from booking.domain.errors import (
    BookingAlreadyCancelled,
    BookingNotFound,
    IdempotencyKeyMismatch,
    RoomNotFound,
    SlotUnavailable,
)
from booking.domain.idempotency import IdempotencyKey, request_hash
from booking.ports import Clock, Notifier, UnitOfWork


def create_booking(
    uow: UnitOfWork,
    clock: Clock,
    user_id: UUID,
    room_id: UUID,
    start: datetime,
    end: datetime,
    idempotency_key: UUID | None = None,
) -> Booking:
    now = clock.now()
    with uow:
        if idempotency_key is not None:
            # Same-key requests wait here, so the lookup sees a key committed meanwhile
            # (ADR 0007). Replay and mismatch leave the transaction to be rolled back.
            uow.users.lock(user_id)
            stored = uow.idempotency_keys.get(user_id, idempotency_key)
            if stored is not None:
                if stored.request_hash != request_hash(room_id, start, end):
                    raise IdempotencyKeyMismatch
                return stored.response
        booking = new_booking(room_id, user_id, start, end, now)
        if not uow.rooms.exists(room_id):
            raise RoomNotFound
        # Serializes this user's requests; taken before the insert to keep ADR 0005 valid
        # (ADR 0006). Already held, and so a no-op, on the keyed path.
        uow.users.lock(user_id)
        check_booking_limit(uow.bookings.count_future(user_id, now))
        # Pre-check for a clear error; the exclusion constraint is the real guarantee.
        if uow.bookings.find_overlapping(room_id, booking.start, booking.end):
            raise SlotUnavailable
        uow.bookings.add(booking)
        if idempotency_key is not None:
            uow.idempotency_keys.add(
                IdempotencyKey(user_id, idempotency_key, request_hash(room_id, start, end), booking)
            )
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


def send_reminders(uow: UnitOfWork, clock: Clock, notifier: Notifier) -> int:
    raise NotImplementedError
