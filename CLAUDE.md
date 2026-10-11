# Classroom Booking System

An **MVP** of a classroom booking system: users book a room for a time slot, with no
double bookings even under concurrent requests. The scope is intentionally small. The
goal is a correct, well-tested core, not a feature-complete product.

Out of scope: real authentication (users are identified by the `X-User-Id` header and
seeded), room management via API, pending/confirmation flows, message queues, real
email delivery. Do not add any of these unless a spec asks for it.

## Ground rules for Claude

- **Never commit.** Do not run `git commit`, `git push`, `git add`, `git stash`,
  `git reset`, `git rebase` or anything that changes git history or the index. The
  user makes every commit by hand. Read-only git (`status`, `diff`, `log`) is fine.
  When a unit of work is done, suggest a commit message and stop.
- **English only** in the project: code, comments, docstrings, specs, ADRs, commit
  messages, docs. The conversation with the user may be in Italian.
- **Approved tests are the contract.** Once the user has reviewed and approved the
  tests for a spec, do not modify, skip, weaken or delete them to make code pass. If
  a test looks wrong, stop and explain why.
- **No scope creep.** Implement what the spec asks, nothing more. No speculative
  abstractions, no extra layers, no new dependencies without asking.
- **Prefer simple over clever.** The user must be able to explain every line in a
  job interview.

## Workflow: spec-driven development

One feature = one spec = one PR.

1. The user writes the spec in `specs/NNN-name.md`: requirements, edge cases,
   acceptance criteria in Given/When/Then.
2. `/spec-to-tests NNN`: Claude proposes tests derived from the acceptance criteria.
   One test per criterion, named after it. The user reviews them. They must fail
   (red) before any implementation.
3. `/implement-spec NNN`: Claude proposes a short plan and waits for approval, then
   implements until all tests pass.
4. The user reviews the diff and commits.

If a spec is ambiguous or contradicts an ADR, ask. Do not guess.

## Architecture

A light hexagonal architecture. The code lives in `backend/src/booking/`:

```
domain/      pure Python: dataclasses, rules, domain errors. No I/O.
ports.py     typing.Protocol interfaces: BookingRepository, UnitOfWork, Clock, Notifier
services.py  use cases (create_booking, cancel_booking). Depend on ports only.
adapters/    api.py (FastAPI), postgres.py (psycopg 3), memory.py (test fakes), notifier.py
jobs.py      scheduled commands (e.g. send_reminders)
main.py      composition root: wires adapters to services by hand
```

**Dependency rule:** `domain` imports nothing outside the standard library, and
`services` imports only `domain` and `ports`. Infrastructure packages (fastapi,
psycopg, etc.) appear only in `adapters/`, `jobs.py` and `main.py`. This is enforced
by import-linter in CI.

Not wanted: DI containers, ORMs, DTO/mapper layers, generic base repositories.

Key decisions live in `docs/adr/`. Read the relevant ADR before touching that area:

- **No overlaps:** a PostgreSQL exclusion constraint on `(room_id, period)` where
  `status = 'confirmed'`. The domain pre-checks to give clear errors; the database is
  the real guarantee. The adapter maps SQLSTATE `23P01` to the domain error
  `SlotUnavailable`.
- **Per-user booking limit:** `SELECT ... FOR UPDATE` on the user row, inside the
  same transaction as the insert.
- **Idempotency:** `Idempotency-Key` is stored in the same transaction as the booking.
  Same key with the same payload returns the stored response; same key with a
  different payload returns `422`.

## Conventions

- Python 3.12, full type hints, `mypy --strict` must pass.
- Formatting and linting: `ruff`. Do not disable rules inline without a reason in a
  comment.
- SQL is written by hand, only in `adapters/postgres.py` and in Alembic migrations.
  Always use parameterized queries.
- Time:
  - always use timezone-aware UTC datetimes;
  - get "now" only through the `Clock` port, never `datetime.now()` in domain or services.
- Time ranges are half-open `[start, end)`, so back-to-back bookings do not overlap.
- Errors:
  - the domain raises specific exceptions from `domain/errors.py`;
  - the API maps them to HTTP status codes (`409` for conflicts, `422` for
    validation and rule violations, `404` for not found) using Problem Details
    (RFC 9457) bodies.
- Schema changes go through a new Alembic migration only. Never edit an existing
  migration.
- Comments explain *why*, not *what*. Keep them rare.

## Testing

Tests are organized as layers, each selected with a pytest marker:

| Marker | Folder | What it covers |
|---|---|---|
| `unit` | `tests/unit` | domain and services with in-memory fakes. No Docker. |
| `contract` | `tests/contract` | the same repository suite against the in-memory and the Postgres adapter. |
| `integration` | `tests/integration` | Postgres adapter and API against a real database (Testcontainers). |
| `concurrency` | `tests/concurrency` | parallel requests on the same slot or user. Exactly one must win. |
| `property` | `tests/property` | Hypothesis stateful tests: no two confirmed bookings ever overlap. |
| `e2e` | `tests/e2e` | Playwright, main user flows only. |

Rules:

- Use fakes from `adapters/memory.py`, not `unittest.mock`, for ports.
- Never mock PostgreSQL in integration tests. Use the Testcontainers database.
- Tests must be deterministic: inject a fixed `Clock`, no sleeps, no real time.
- Concurrency tests:
  - use a `threading.Barrier` and one connection per thread;
  - assert the exact number of winners.

## Commands

Run the backend commands from `backend/`:

```bash
uv sync                                    # install dependencies
uv run pytest -m unit                      # fast tests, no Docker
uv run pytest                              # all tests (needs Docker)
uv run pytest --cov=booking --cov-fail-under=80
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run lint-imports                        # architecture rules
uv run alembic upgrade head                # apply migrations
```

From the repo root:

```bash
docker compose up --build                  # db, api, reminders, frontend
```

## Definition of done

A change is done when all of these hold:

- [ ] Every acceptance criterion in the spec is covered by a test, and all tests pass.
- [ ] `ruff`, `mypy` and `lint-imports` are clean.
- [ ] Coverage is at least 80%.
- [ ] No approved test was changed without the user's explicit agreement.
- [ ] A new architectural decision has its own ADR in `docs/adr/`.
- [ ] Claude has summarized what changed, flagged anything the user should look at
  closely, and proposed a commit message. The user commits.
