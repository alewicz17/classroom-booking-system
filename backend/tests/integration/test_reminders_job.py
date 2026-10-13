import logging
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

import pytest

from booking import jobs
from booking.adapters.memory import FixedClock
from booking.domain.booking import Booking


def test_command_runs_one_pass_and_reports_the_count(
    database_url: str,
    clock: FixedClock,
    caplog: pytest.LogCaptureFixture,
    given_booking: Callable[..., Booking],
    stored_reminder_sent_at: Callable[[UUID], datetime | None],
    room_1: UUID,
    user_a: UUID,
    today_at: Callable[..., datetime],
) -> None:
    booking = given_booking(room_1, user_a, today_at(10, 30), today_at(11, 30))

    with caplog.at_level(logging.INFO):
        exit_code = jobs.main(database_url, clock)

    assert exit_code == 0
    assert "Reminders sent: 1" in caplog.messages
    assert stored_reminder_sent_at(booking.id) == clock.now()
