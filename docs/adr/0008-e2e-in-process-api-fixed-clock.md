# ADR 0008: End-to-end tests run against an in-process API with a fixed clock

- **Status:** Accepted
- **Related:** spec 006, ADR 0002, ADR 0003

## Context

Spec 006 adds a React frontend and end-to-end tests with pytest-playwright. The tests
drive a real browser through the main flows: book a room, cancel a booking, see an API
error, retry after a lost response.

The business rules depend on "now": a booking cannot start in the past (spec 001), a
user may hold at most 3 future bookings (spec 003), and a booking can be cancelled only
more than 24 hours before its start (spec 002). Every other test layer injects a fixed
`Clock`, and the project rule is that tests use no real time.

The Docker Compose stack wires the API with `SystemClock`. End-to-end tests run against
it would depend on the wall clock: dates would have to be computed relative to the real
"now", and a test near a deadline could pass or fail depending on when it runs.

## Decision

**A pytest fixture starts the whole stack inside the test session:**

1. PostgreSQL from Testcontainers, migrated with Alembic, as in the integration tests.
   The migration seeds the rooms and users.
2. The API built with `create_app(uow_factory=..., clock=FixedClock(...))`, served by
   uvicorn in a background thread on a free local port. This is the same composition
   the integration tests use, with the Postgres unit of work.
3. The frontend built with `npm run build` and served by `vite preview`, started as a
   subprocess, with the `/api` proxy pointed at the API from step 2.

Playwright opens the `vite preview` URL. Bookings are removed between tests, so each
test starts from the seeded rooms and users and no bookings.

The fixed clock is injected through the existing `Clock` port. The production code gets
no flag, environment variable or endpoint for setting the time.

## Consequences

**Positive**

- End-to-end tests are deterministic. Acceptance criteria use literal dates, such as
  2026-10-22T08:00Z with the clock at 2026-10-20T10:00Z, exactly as the other specs do.
- No test-only code path ships in the API. The hexagonal wiring of ADR 0002 is what
  makes it possible: swapping `SystemClock` for `FixedClock` is a constructor argument.
- The tests exercise the real Postgres adapter, the real API and the built frontend,
  including the `/api` proxy.
- Failures show up in one pytest run with one stack trace, not across container logs.

**Negative**

- The Docker Compose wiring itself (`main.py`, the Dockerfiles, `docker-compose.yml`)
  is not covered by the end-to-end tests. A broken `main.py` or Compose file is caught
  only by starting the stack by hand.
- The frontend is served by `vite preview`, not by the Vite dev server used in Compose.
  The two share the proxy configuration, but they are not the same server.
- The test run needs Node, the frontend build and the Playwright browsers, in addition
  to Docker. CI has to install all of them for the `e2e` job.
- One clock value is shared by the whole stack for a test, so a flow that needs time to
  pass (for example, "the cancellation deadline expires") cannot be expressed. Spec 006
  has no such flow.

## Alternatives considered

- **Run against Docker Compose with dates relative to the real clock.** Simplest to set
  up, but it breaks the "no real time" rule and makes deadline-related assertions
  depend on when the test runs.
- **A fake-time environment variable in the API** (for example `FAKE_NOW`). It would let
  the Compose stack be tested with a fixed time, but it puts a test hook in the
  production composition root, and a misconfigured deployment could run with a frozen
  clock.
- **A test-only endpoint to set the clock.** The same problem as the environment
  variable, plus an endpoint that must never be reachable in production.
- **Mock the API in the browser** (Playwright route interception for every request).
  Fast and deterministic, but it no longer tests the API, the database or the proxy, so
  the tests would not be end-to-end.
