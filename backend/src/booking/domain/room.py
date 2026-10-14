from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Room:
    id: UUID
    name: str
