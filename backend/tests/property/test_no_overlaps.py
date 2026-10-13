import contextlib
import itertools
from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    invariant,
    multiple,
    rule,
    run_state_machine_as_test,
)

from booking import services
from booking.adapters.memory import FixedClock
from booking.adapters.postgres import PostgresUnitOfWork
from booking.domain.errors import (
    BookingAlreadyCancelled,
    BookingInPast,
    BookingNotFound,
    CancellationTooLate,
    SlotUnavailable,
)

SLOT = timedelta(minutes=30)
# Starts span the next three days, so some bookings fall inside the 24-hour deadline.
start_slots = st.integers(min_value=0, max_value=144)
duration_slots = st.integers(min_value=1, max_value=6)
# Indexes into the seeded rooms and users: the first two of each.
indexes = st.integers(min_value=0, max_value=1)


class CreateAndCancel(RuleBasedStateMachine):
    bookings = Bundle("bookings")

    def __init__(
        self,
        database_url: str,
        reset: Callable[[], None],
        clock: FixedClock,
        rooms: list[UUID],
        users: list[UUID],
    ) -> None:
        super().__init__()
        reset()
        self.database_url = database_url
        self.clock = clock
        self.rooms = rooms
        self.users = users

    def uow(self) -> PostgresUnitOfWork:
        return PostgresUnitOfWork(self.database_url)

    @rule(target=bookings, user=indexes, room=indexes, start=start_slots, duration=duration_slots)
    def create(self, user: int, room: int, start: int, duration: int) -> object:
        begin = self.clock.now() + start * SLOT
        try:
            booking = services.create_booking(
                self.uow(),
                self.clock,
                self.users[user],
                self.rooms[room],
                begin,
                begin + duration * SLOT,
            )
        except (SlotUnavailable, BookingInPast):
            return multiple()
        return booking.id

    @rule(user=indexes, booking_id=bookings)
    def cancel(self, user: int, booking_id: UUID) -> None:
        with contextlib.suppress(BookingNotFound, BookingAlreadyCancelled, CancellationTooLate):
            services.cancel_booking(self.uow(), self.clock, self.users[user], booking_id)

    @invariant()
    def no_two_confirmed_bookings_overlap(self) -> None:
        now = self.clock.now()
        with self.uow() as uow:
            for room_id in self.rooms:
                confirmed = uow.bookings.find_overlapping(
                    room_id, now - timedelta(days=365), now + timedelta(days=365)
                )
                # Sorted by start, so checking neighbours covers every pair.
                for earlier, later in itertools.pairwise(confirmed):
                    assert earlier.end <= later.start, (earlier, later)


def test_no_two_confirmed_bookings_ever_overlap(
    database_url: str,
    fresh_database: Callable[[], None],
    clock: FixedClock,
    room_1: UUID,
    room_2: UUID,
    user_a: UUID,
    user_b: UUID,
) -> None:
    run_state_machine_as_test(
        lambda: CreateAndCancel(
            database_url, fresh_database, clock, [room_1, room_2], [user_a, user_b]
        ),
        settings=settings(max_examples=30, stateful_step_count=15, deadline=None),
    )
