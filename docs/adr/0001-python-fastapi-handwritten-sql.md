# ADR 0001: Python, FastAPI and hand-written SQL without an ORM

- **Status:** Accepted

## Context

The system is an MVP whose core value is correctness under concurrency: no two confirmed
bookings for the same room may overlap, and per-user limits must hold even when requests
arrive in parallel. The scope is intentionally small (see ADR 0003), so the stack should
add as little incidental complexity as possible.

The correctness guarantees rely on PostgreSQL-specific features:

- a `tstzrange` column with an `EXCLUDE USING gist` constraint;
- row-level locking with `SELECT ... FOR UPDATE`;
- `FOR UPDATE SKIP LOCKED` for the reminder job (ADR 0003);
- SQLSTATE codes (e.g. `23P01`) that the adapter maps to domain errors.

These features are central to the design, so the data-access layer must expose them
directly rather than hide them.

## Decision

- **Language: Python 3.12**, managed with `uv`. It is well suited to data processing,
  has a mature testing ecosystem (pytest, Hypothesis, Testcontainers) and is the language
  the author is most productive in. The code is fully type-hinted and checked with
  `mypy --strict`.
- **HTTP layer: FastAPI.** It generates the OpenAPI schema from type hints, validates
  request bodies with Pydantic, and keeps the API adapter thin. Its `TestClient` makes
  API-level integration tests straightforward.
- **Database access: psycopg 3 with hand-written, parameterized SQL**, no ORM. SQL lives
  only in `adapters/postgres.py` and in Alembic migrations. Schema changes go through
  Alembic migrations written with explicit SQL (`op.execute`).

## Consequences

**Positive**

- Every query that matters for correctness is visible and reviewable in one place; there
  is no generated SQL whose locking or isolation behavior has to be inferred.
- PostgreSQL features (range types, exclusion constraints, `SKIP LOCKED`) are used
  natively, without ORM extensions or raw-SQL escape hatches.
- The domain stays free of persistence concerns: plain dataclasses, no ORM base classes
  or session state leaking into business logic (ADR 0002).
- Fewer dependencies and less framework behavior to configure.

**Negative**

- Mapping rows to domain dataclasses is written by hand, which means more repetitive code
  in the Postgres adapter.
- The system is tied to PostgreSQL. This is accepted: the scope is a proof of concept,
  and the core guarantee depends on PostgreSQL features anyway.
- No automatic migration generation; every migration is written manually.

## Alternatives considered

- **SQLAlchemy (ORM) or SQLModel.** Rejected: range types and exclusion constraints
  need dialect-specific extensions or raw SQL, so the ORM would add a layer without
  removing the need to write SQL for the parts that matter most.
- **Django + Django REST Framework.** Rejected: a full framework with its own ORM, admin
  and project structure is more than this scope needs, and its active-record models
  conflict with keeping the domain independent of persistence.
- **Flask.** Rejected: workable, but request validation and OpenAPI documentation would
  require additional libraries that FastAPI provides out of the box.
