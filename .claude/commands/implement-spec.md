---
description: Implement a spec until its approved tests pass
argument-hint: <spec number, e.g. 001>
---

Read `specs/$ARGUMENTS-*.md`, its approved tests, `CLAUDE.md` and the relevant ADRs.

1. Propose a short plan: files to touch, migrations, and any new architectural
   decision that needs an ADR. Then stop and wait for approval.
2. After approval, implement until all tests pass. The approved tests are the
   contract: never modify, skip, weaken or delete them. If a test looks wrong,
   stop and explain why.
3. Run the full definition of done from `backend/`:
   `uv run ruff check . && uv run ruff format --check .`, `uv run mypy src`,
   `uv run lint-imports`, `uv run pytest --cov=booking --cov-fail-under=80`.
4. Summarize what changed, flag anything the user should look at closely, and
   propose a commit message. Do not commit.
