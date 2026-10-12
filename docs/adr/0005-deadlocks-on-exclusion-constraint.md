# ADR 0005: Deadlocks on the exclusion constraint are reported as `SlotUnavailable`

- **Status:** Accepted
- **Refines:** ADR 0004

## Context

ADR 0004 states that when two transactions insert conflicting rows, PostgreSQL makes
the second wait for the first, and the second fails with SQLSTATE `23P01` if the first
commits. That holds when the inserts are not simultaneous.

PostgreSQL checks an exclusion constraint *after* inserting the new tuple into the heap
and the index. When two transactions insert overlapping rows at the same moment, each
finds the other's uncommitted tuple during the check and waits for the other to
finish. The deadlock detector breaks the cycle after `deadlock_timeout` (1s by default):
it aborts one transaction with SQLSTATE `40P01` (`deadlock_detected`) and lets the other
continue.

The concurrency tests for spec 001 (AC-17, AC-18) start 50 threads on the same slot
together. The invariant always holds: exactly one booking is committed. But in some
runs the losers received `DeadlockDetected` instead of `SlotUnavailable`, so callers
saw an infrastructure error for what is a booking conflict.

## Decision

The Postgres adapter maps `40P01` raised by the booking `INSERT` to `SlotUnavailable`,
alongside the existing `23P01` mapping. The mapping is limited to that single statement
in `PostgresBookingRepository.add`. It is not a general deadlock handler.

The mapping is sound because of how the create-booking transaction is shaped. Before
the insert it only runs plain `SELECT`s, which take no row locks, so the insert is its
only write. A deadlock on that statement can only come from waiting on another
transaction's uncommitted overlapping booking, which means the slot is contested.

## Consequences

**Positive**

- Callers see the same domain error (`409` at the API) whether the conflict was caught
  by the service pre-check, by the constraint (`23P01`) or by deadlock detection
  (`40P01`).
- There are still no explicit locks. Non-overlapping bookings still never wait for each
  other, as ADR 0004 intends.
- The concurrency tests are deterministic about the outcome: one winner, every other
  request fails with `SlotUnavailable`.

**Negative**

- Under a burst of simultaneous conflicting inserts, deadlocks are resolved one at a
  time, each after `deadlock_timeout`. In the 50-thread test this can take tens of
  seconds. At realistic contention (a few users on the same slot) the cost is at most
  about a second, and only for requests that lose anyway.
- In theory a request can be told `SlotUnavailable` while the transaction that survived
  the deadlock later fails for an unrelated reason (for example a lost connection), which
  would leave the slot free. This is acceptable: `409` means "conflict, the state may have
  changed", and a client that retries sees the real state.
- The mapping depends on the insert staying the only write in the transaction. If a
  future spec adds a write before it (for example the per-user limit's
  `SELECT ... FOR UPDATE` in spec 003), this reasoning must be revisited, because a
  deadlock could then involve other locks.

## Alternatives considered

- **Lock the room row (`SELECT ... FOR UPDATE` on `rooms`) before inserting.** This
  removes the deadlocks, but it serializes every booking for a room, including
  non-overlapping ones. ADR 0004 rejected it for that reason.
- **Retry the transaction on `40P01`.** The retry would run the pre-check, find the
  winner's booking and fail with `SlotUnavailable` anyway. It adds a retry loop and
  connection handling for the same result.
- **Expose `40P01` to callers as a `500` or `503`.** Rejected: it reports a normal booking
  conflict as an infrastructure failure.
- **Lower `deadlock_timeout`.** This only shortens the wait. It is a server-wide setting
  that affects every other transaction, and the error would still need to be mapped.
