class SlotUnavailable(Exception):
    """The room already has a confirmed booking that overlaps the requested range."""


class InvalidTimeRange(Exception):
    """The start of the booking is not strictly before its end."""


class BookingInPast(Exception):
    """The booking does not start strictly after now."""


class RoomNotFound(Exception):
    """No room has the requested id."""


class BookingNotFound(Exception):
    """No booking with the requested id is visible to the user."""


class BookingAlreadyCancelled(Exception):
    """The booking is already cancelled."""


class CancellationTooLate(Exception):
    """Now is not strictly before the booking's cancellation deadline."""


class BookingTooLong(Exception):
    """The booking lasts longer than the maximum duration."""


class BookingLimitReached(Exception):
    """The user already holds the maximum number of future bookings."""
