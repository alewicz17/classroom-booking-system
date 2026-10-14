# AI log

A diary of working with Claude Code, written while working. One entry per notable
mistake or correction: what Claude did, how it was caught, what changed.

| Date | Spec | What happened | How it was caught | Fix |
|---|---|---|---|---|
| 2026-10-13 | 001 | Concurrency tests passed once and Claude called it done. They were flaky: sometimes the losers got a deadlock error (`40P01`) instead of `SlotUnavailable`. ADR 0004 only mentioned `23P01`. | Reran the concurrency tests a few times, about 1 in 4 failed. | `40P01` on the insert now maps to `SlotUnavailable`, see ADR 0005. Rerun concurrency tests several times before trusting them. |
| 2026-10-14 | 006 | Spec 006 was called done with all tests green locally, but `ci.yml` was not updated. ADR 0008 says CI must install Node, the frontend deps and the Playwright browsers for the e2e tests, so `pytest` failed in the backend job. | The backend CI job failed on the PR; the frontend job passed. | Backend job now sets up Node, runs `npm ci` and `playwright install --with-deps chromium`. A spec is done only when CI is green, not just local tests. |
