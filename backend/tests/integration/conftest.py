from collections.abc import Callable
from datetime import datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from booking.adapters.api import create_app
from booking.adapters.memory import FixedClock
from booking.adapters.postgres import PostgresUnitOfWork


@pytest.fixture
def client(database_url: str, clock: FixedClock) -> TestClient:
    app = create_app(uow_factory=lambda: PostgresUnitOfWork(database_url), clock=clock)
    return TestClient(app)


@pytest.fixture
def book(client: TestClient) -> Callable[[UUID, UUID, datetime, datetime], Response]:
    """Returns a function that sends POST /bookings as the given user."""

    def post(user_id: UUID, room_id: UUID, start: datetime, end: datetime) -> Response:
        return client.post(
            "/bookings",
            headers={"X-User-Id": str(user_id)},
            json={"room_id": str(room_id), "start": start.isoformat(), "end": end.isoformat()},
        )

    return post
