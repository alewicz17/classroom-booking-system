from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Classroom Booking")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
