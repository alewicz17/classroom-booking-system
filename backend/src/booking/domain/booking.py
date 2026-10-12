from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class BookingStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Booking:
    id: UUID
    room_id: UUID
    user_id: UUID
    start: datetime
    end: datetime
    status: BookingStatus
