from collections.abc import Callable

from fastapi import FastAPI

from booking.ports import Clock, UnitOfWork


def create_app(uow_factory: Callable[[], UnitOfWork], clock: Clock) -> FastAPI:
    app = FastAPI(title="Classroom Booking")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/bookings")
    def create_booking() -> None:
        raise NotImplementedError

    @app.get("/bookings/{booking_id}")
    def get_booking() -> None:
        raise NotImplementedError

    return app
