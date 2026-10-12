# AI log

A diary of working with Claude Code, written while working. One entry per notable
mistake or correction: what Claude did, how it was caught, what changed.

| Date | Spec | What happened | How it was caught | Fix |
|---|---|---|---|---|
| 2026-10-13 | 001 | Concurrency tests passed once and Claude called it done. They were flaky: sometimes the losers got a deadlock error (`40P01`) instead of `SlotUnavailable`. ADR 0004 only mentioned `23P01`. | Reran the concurrency tests a few times, about 1 in 4 failed. | `40P01` on the insert now maps to `SlotUnavailable`, see ADR 0005. Rerun concurrency tests several times before trusting them. |
