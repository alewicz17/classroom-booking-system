from booking.domain.booking import Booking


class LogNotifier:
    def send_reminder(self, booking: Booking) -> None:
        raise NotImplementedError
