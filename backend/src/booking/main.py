"""Composition root: wires adapters to services by hand."""

import os
from datetime import UTC, datetime

from booking.adapters.api import create_app
from booking.adapters.postgres import PostgresUnitOfWork


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def unit_of_work() -> PostgresUnitOfWork:
    return PostgresUnitOfWork(os.environ["DATABASE_URL"])


app = create_app(uow_factory=unit_of_work, clock=SystemClock())
