# ADR 0002: Lightweight hexagonal architecture, enforced by import-linter

- **Status:** Accepted

## Context

The business rules (no overlaps, maximum duration, per-user limit, cancellation deadline)
are the part of the system that must be tested most thoroughly. If they are tangled with
FastAPI handlers and SQL, every rule test needs an HTTP client and a running database,
which makes the fast feedback loop slow and dependent on Docker.

At the same time the system is small. A full layered architecture with DTOs, mappers and
a dependency-injection container would add more code than the features themselves.

## Decision

Use a lightweight ports-and-adapters (hexagonal) structure in `backend/src/booking/`:

| Module | Responsibility | May import |
|---|---|---|
| `domain/` | dataclasses, rules, domain errors | standard library only |
| `ports.py` | `typing.Protocol` interfaces: `BookingRepository`, `UnitOfWork`, `Clock`, `Notifier` | `domain` |
| `services.py` | use cases (`create_booking`, `cancel_booking`) | `domain`, `ports` |
| `adapters/` | FastAPI, PostgreSQL, in-memory fakes, log notifier | anything |
| `jobs.py`, `main.py` | scheduled commands, composition root | anything |

Dependencies are wired by hand in `main.py`.

Deliberately left out: dependency-injection containers, DTO and mapper layers, generic
base repositories. Domain dataclasses are used directly across layers; the only
translation happens at the edges (Pydantic models in the API adapter, rows in the
Postgres adapter).

The dependency rule is enforced in CI with **import-linter**, using two `forbidden`
contracts in `pyproject.toml`:

- `booking.domain` must not import `ports`, `services`, `adapters`, `jobs`, `main` or any
  infrastructure package (`fastapi`, `psycopg`, `alembic`, `uvicorn`);
- `booking.services` must not import `adapters`, `jobs`, `main` or any infrastructure
  package.

## Consequences

**Positive**

- Domain rules and use cases are tested with in-memory fakes from `adapters/memory.py`:
  the unit suite runs in milliseconds, without Docker or a database.
- Infrastructure can be swapped in tests by passing a different adapter, with no mocking
  library and no framework magic.
- Architectural rules are checked automatically on every change instead of relying on
  code review; a violation fails the build with a precise message.
- Wiring by hand in `main.py` keeps the object graph explicit and easy to follow.

**Negative**

- In-memory fakes can drift from the real PostgreSQL behavior. This is mitigated by
  contract tests that run the same repository suite against both adapters.
- Some invariants (no overlaps) are guaranteed by the database, not by the domain; the
  domain only pre-checks them. The architecture does not hide this split.
- The forbidden-package lists must be updated when a new infrastructure dependency is
  added, otherwise the contract would not catch it.
- Slightly more files and indirection than calling the database from route handlers.

## Alternatives considered

- **Route handlers calling the database directly.** Rejected: business rules could only
  be tested through HTTP and a real database, and would be scattered across handlers.
- **Full clean architecture with DTOs, mappers and a DI container.** Rejected: the extra
  layers add boilerplate without a corresponding benefit at this size.
- **Enforcing the rule by convention and code review only.** Rejected: unchecked
  architectural rules erode over time; a CI check is cheap and unambiguous.
