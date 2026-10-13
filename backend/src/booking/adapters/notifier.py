import logging
from datetime import UTC

from booking.domain.booking import Booking

logger = logging.getLogger(__name__)


class LogNotifier:
    def send_reminder(self, booking: Booking) -> None:
        logger.info(
            "Reminder: booking %s, user %s, room %s, starts at %s",
            booking.id,
            booking.user_id,
            booking.room_id,
            booking.start.astimezone(UTC).isoformat(),
        )
