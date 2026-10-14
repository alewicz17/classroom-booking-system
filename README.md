# Classroom Booking System

Book a room for a time slot, with no double bookings even under concurrent requests.

## Quick start

```bash
docker compose up --build
```

- API: http://localhost:8000 (OpenAPI docs at `/docs`)
- Frontend: http://localhost:5173

## Development

Requires [uv](https://docs.astral.sh/uv/) and Docker. From `backend/`:

```bash
uv sync
uv run pytest -m unit      # fast tests, no Docker
uv run pytest              # all tests (needs Docker)
```

The E2E tests (`-m e2e`) also need Node: run `npm ci` in `frontend/` and
`uv run playwright install chromium` once.

See `CLAUDE.md` for the full list of commands, conventions and architecture.
