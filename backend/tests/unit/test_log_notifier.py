import logging
from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from booking.adapters.notifier import LogNotifier
from booking.domain.booking import Booking, BookingStatus


def test_log_notifier_writes_one_record_per_reminder(
    caplog: pytest.LogCaptureFixture,
    room_1: UUID,
    user_a: UUID,
    today_at: Callable[..., datetime],
) -> None:
    booking = Booking(
        uuid4(), room_1, user_a, today_at(10, 30), today_at(11, 30), BookingStatus.CONFIRMED
    )

    with caplog.at_level(logging.INFO):
        LogNotifier().send_reminder(booking)

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.INFO
    message = record.getMessage()
    assert str(booking.id) in message
    assert str(user_a) in message
    assert str(room_1) in message
    assert "2026-10-20T10:30:00+00:00" in message
