"""Composition root: wires adapters to services by hand."""

import os

from booking.adapters.api import create_app
from booking.adapters.clock import SystemClock
from booking.adapters.postgres import PostgresUnitOfWork


def unit_of_work() -> PostgresUnitOfWork:
    return PostgresUnitOfWork(os.environ["DATABASE_URL"])


app = create_app(uow_factory=unit_of_work, clock=SystemClock())
