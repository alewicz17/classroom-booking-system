from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID

from booking.domain.idempotency import request_hash

At = Callable[..., datetime]


def test_same_instant_in_different_timezones_gives_same_hash(room_1: UUID, at: At) -> None:
    rome = timezone(timedelta(hours=2))

    utc_hash = request_hash(room_1, at(10), at(11))
    rome_hash = request_hash(room_1, at(10).astimezone(rome), at(11).astimezone(rome))

    assert utc_hash == rome_hash


def test_different_room_start_or_end_gives_different_hash(
    room_1: UUID, room_2: UUID, at: At
) -> None:
    original = request_hash(room_1, at(10), at(11))

    assert request_hash(room_2, at(10), at(11)) != original
    assert request_hash(room_1, at(9), at(11)) != original
    assert request_hash(room_1, at(10), at(12)) != original
