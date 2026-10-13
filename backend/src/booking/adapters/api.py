from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel

from booking import services
from booking.domain.booking import Booking
from booking.domain.errors import (
    BookingAlreadyCancelled,
    BookingInPast,
    BookingLimitReached,
    BookingNotFound,
    BookingTooLong,
    CancellationTooLate,
    InvalidTimeRange,
    RoomNotFound,
    SlotUnavailable,
)
from booking.ports import Clock, UnitOfWork


class BookingRequest(BaseModel):
    room_id: UUID
    # AwareDatetime rejects datetimes without an explicit offset.
    start: AwareDatetime
    end: AwareDatetime


class Unauthorized(Exception):
    """The request does not identify a known user."""


# Exception -> (status, type, title, detail).
PROBLEMS: dict[type[Exception], tuple[int, str, str, str]] = {
    Unauthorized: (
        401,
        "/problems/unauthorized",
        "Unauthorized",
        "The X-User-Id header must identify a known user.",
    ),
    RoomNotFound: (404, "/problems/room-not-found", "Room not found", "The room does not exist."),
    BookingNotFound: (
        404,
        "/problems/booking-not-found",
        "Booking not found",
        "The booking does not exist.",
    ),
    SlotUnavailable: (
        409,
        "/problems/slot-unavailable",
        "Slot unavailable",
        "The room already has a confirmed booking that overlaps the requested range.",
    ),
    BookingAlreadyCancelled: (
        409,
        "/problems/booking-already-cancelled",
        "Booking already cancelled",
        "The booking is already cancelled.",
    ),
    InvalidTimeRange: (
        422,
        "/problems/invalid-time-range",
        "Invalid time range",
        "The start must be strictly before the end.",
    ),
    BookingInPast: (
        422,
        "/problems/booking-in-past",
        "Booking in the past",
        "The booking must start in the future.",
    ),
    BookingTooLong: (
        422,
        "/problems/booking-too-long",
        "Booking too long",
        "A booking can last at most 6 hours.",
    ),
    BookingLimitReached: (
        422,
        "/problems/booking-limit-reached",
        "Booking limit reached",
        "A user can hold at most 3 future bookings.",
    ),
    CancellationTooLate: (
        422,
        "/problems/cancellation-too-late",
        "Cancellation too late",
        "A booking can be cancelled only until 24 hours before it starts.",
    ),
}


def problem(status: int, type_: str, title: str, detail: str) -> JSONResponse:
    """A Problem Details (RFC 9457) response."""
    return JSONResponse(
        status_code=status,
        content={"type": type_, "title": title, "status": status, "detail": detail},
        media_type="application/problem+json",
    )


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _to_json(booking: Booking) -> dict[str, str]:
    return {
        "id": str(booking.id),
        "room_id": str(booking.room_id),
        "user_id": str(booking.user_id),
        "start": _utc(booking.start),
        "end": _utc(booking.end),
        "status": booking.status.value,
    }


def create_app(uow_factory: Callable[[], UnitOfWork], clock: Clock) -> FastAPI:
    app = FastAPI(title="Classroom Booking")

    async def handle_problem(request: Request, error: Exception) -> JSONResponse:
        return problem(*PROBLEMS[type(error)])

    for error_type in PROBLEMS:
        app.add_exception_handler(error_type, handle_problem)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return problem(422, "/problems/validation-error", "Invalid request", str(error.errors()))

    def current_user(x_user_id: Annotated[str | None, Header()] = None) -> UUID:
        # Identity is resolved only here (ADR 0003): a malformed id identifies nobody.
        if x_user_id is None:
            raise Unauthorized
        try:
            user_id = UUID(x_user_id)
        except ValueError:
            raise Unauthorized from None
        with uow_factory() as uow:
            if not uow.users.exists(user_id):
                raise Unauthorized
        return user_id

    User = Annotated[UUID, Depends(current_user)]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/bookings", status_code=201)
    def create_booking(
        request: BookingRequest, user_id: User, response: Response
    ) -> dict[str, str]:
        booking = services.create_booking(
            uow_factory(), clock, user_id, request.room_id, request.start, request.end
        )
        response.headers["Location"] = f"/bookings/{booking.id}"
        return _to_json(booking)

    @app.get("/bookings/{booking_id}")
    def get_booking(booking_id: UUID, user_id: User) -> dict[str, str]:
        return _to_json(services.get_booking(uow_factory(), user_id, booking_id))

    @app.post("/bookings/{booking_id}/cancel")
    def cancel_booking(booking_id: UUID, user_id: User) -> dict[str, str]:
        return _to_json(services.cancel_booking(uow_factory(), clock, user_id, booking_id))

    return app
