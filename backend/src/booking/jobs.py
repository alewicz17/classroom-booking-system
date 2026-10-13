"""Scheduled commands."""

import logging
import os
import sys

from booking.adapters.clock import SystemClock
from booking.adapters.notifier import LogNotifier
from booking.adapters.postgres import PostgresUnitOfWork
from booking.ports import Clock
from booking.services import send_reminders

logger = logging.getLogger(__name__)


def main(database_url: str, clock: Clock) -> int:
    """Runs one reminder pass and returns the process exit code."""
    try:
        sent = send_reminders(PostgresUnitOfWork(database_url), clock, LogNotifier())
    except Exception:
        # The unit of work has already rolled the pass back.
        logger.exception("Reminder pass failed")
        return 1
    logger.info("Reminders sent: %d", sent)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main(os.environ["DATABASE_URL"], SystemClock()))
