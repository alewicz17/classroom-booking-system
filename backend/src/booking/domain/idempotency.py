import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from booking.domain.booking import Booking


@dataclass(frozen=True)
class IdempotencyKey:
    """A key used by a user, with the hash of its request and the booking it created."""

    user_id: UUID
    key: UUID
    request_hash: str
    response: Booking


def request_hash(room_id: UUID, start: datetime, end: datetime) -> str:
    """Hash of the payload with start and end converted to UTC (spec 004, rule 7)."""
    start_utc = start.astimezone(UTC).isoformat()
    end_utc = end.astimezone(UTC).isoformat()
    normalized = f"{room_id}|{start_utc}|{end_utc}"
    return hashlib.sha256(normalized.encode()).hexdigest()
