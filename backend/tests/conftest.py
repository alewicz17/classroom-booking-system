from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.command import downgrade, upgrade
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

from booking.adapters.memory import FixedClock, InMemoryUnitOfWork
from booking.adapters.postgres import PostgresUnitOfWork
from booking.domain.booking import Booking, BookingStatus
from booking.domain.idempotency import IdempotencyKey

LAYERS = {"unit", "contract", "integration", "concurrency", "property", "e2e"}
BACKEND_DIR = Path(__file__).parent.parent

# Seed data created by the migrations. The names match the labels in the specs.
ROOM_1 = UUID("10000000-0000-4000-8000-000000000001")
ROOM_2 = UUID("10000000-0000-4000-8000-000000000002")
USER_A = UUID("20000000-0000-4000-8000-00000000000a")
USER_B = UUID("20000000-0000-4000-8000-00000000000b")

NOW = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # The folder decides the layer, so a test can never be run with the wrong marker.
    for item in items:
        layer = Path(item.fspath).relative_to(Path(__file__).parent).parts[0]
        if layer in LAYERS:
            item.add_marker(layer)


@pytest.fixture
def room_1() -> UUID:
    return ROOM_1


@pytest.fixture
def room_2() -> UUID:
    return ROOM_2


@pytest.fixture
def user_a() -> UUID:
    return USER_A


@pytest.fixture
def user_b() -> UUID:
    return USER_B


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def memory_uow() -> InMemoryUnitOfWork:
    """An in-memory unit of work seeded with the same rooms and users as the migrations."""
    return InMemoryUnitOfWork(room_ids={ROOM_1, ROOM_2}, user_ids={USER_A, USER_B})


@pytest.fixture
def at() -> Callable[..., datetime]:
    """Returns a function giving a UTC time on the day after NOW."""
    tomorrow = NOW + timedelta(days=1)

    def at(hour: int, minute: int = 0) -> datetime:
        return tomorrow.replace(hour=hour, minute=minute)

    return at


@pytest.fixture
def today_at() -> Callable[..., datetime]:
    """Returns a function giving a UTC time on the day of NOW."""

    def at(hour: int, minute: int = 0) -> datetime:
        return NOW.replace(hour=hour, minute=minute)

    return at


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16", driver=None) as postgres:
        yield postgres.get_connection_url()


def reset_database() -> None:
    """Recreates the schema and seed data from the migrations, using DATABASE_URL."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    downgrade(config, "base")
    upgrade(config, "head")


@pytest.fixture
def database_url(postgres_url: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    # Every test starts from exactly the schema and seed data the migrations define.
    reset_database()
    return postgres_url


@pytest.fixture
def fresh_database(database_url: str) -> Callable[[], None]:
    """Returns a function that resets the database, for tests that need it more than once."""
    return reset_database


@pytest.fixture
def given_booking(database_url: str) -> Callable[..., Booking]:
    """Returns a function that inserts a booking through the repository, bypassing the service."""

    def insert(
        room_id: UUID,
        user_id: UUID,
        start: datetime,
        end: datetime,
        status: BookingStatus = BookingStatus.CONFIRMED,
    ) -> Booking:
        booking = Booking(uuid4(), room_id, user_id, start, end, status)
        with PostgresUnitOfWork(database_url) as uow:
            uow.bookings.add(booking)
            uow.commit()
        return booking

    return insert


@pytest.fixture
def confirmed_bookings(database_url: str) -> Callable[[UUID], list[Booking]]:
    """Returns a function listing the confirmed bookings of a room within a year of NOW."""

    def find(room_id: UUID) -> list[Booking]:
        with PostgresUnitOfWork(database_url) as uow:
            return uow.bookings.find_overlapping(
                room_id, NOW - timedelta(days=365), NOW + timedelta(days=365)
            )

    return find


@pytest.fixture
def stored_reminder_sent_at(database_url: str) -> Callable[[UUID], datetime | None]:
    """Returns a function reading bookings.reminder_sent_at, which no port exposes."""

    def find(booking_id: UUID) -> datetime | None:
        with PostgresUnitOfWork(database_url) as uow:
            row = uow.connection.execute(
                "SELECT reminder_sent_at FROM bookings WHERE id = %s", (booking_id,)
            ).fetchone()
        assert row is not None
        sent_at: datetime | None = row[0]
        return sent_at

    return find


@pytest.fixture
def stored_key(database_url: str) -> Callable[[UUID, UUID], IdempotencyKey | None]:
    """Returns a function reading the stored idempotency key of a user, if any."""

    def find(user_id: UUID, key: UUID) -> IdempotencyKey | None:
        with PostgresUnitOfWork(database_url) as uow:
            return uow.idempotency_keys.get(user_id, key)

    return find
