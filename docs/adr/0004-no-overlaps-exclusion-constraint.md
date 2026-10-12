# ADR 0004: No overlapping bookings, enforced by a PostgreSQL exclusion constraint

- **Status:** Accepted

## Context

Two confirmed bookings for the same room must never overlap (spec 001). Requests arrive
concurrently, so a check in application code is not enough on its own. Two transactions
can both read "the slot is free", then both insert, and neither sees the other's
uncommitted row.

The conflict is between two **inserts** of rows that do not exist yet. No existing row
can be versioned or locked to detect it, so the usual locking strategies do not apply
directly.

Time ranges are half-open `[start, end)`, so back-to-back bookings (10:00–11:00 and
11:00–12:00) are allowed. Cancelled bookings must not block a slot (ADR 0003: a booking
is either `confirmed` or `cancelled`).

## Decision

Store the booking time as a `tstzrange` column `period` with `[)` bounds, and add a
partial exclusion constraint:

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE bookings ADD CONSTRAINT no_overlap
  EXCLUDE USING gist (room_id WITH =, period WITH &&)
  WHERE (status = 'confirmed');
```

- `btree_gist` lets the GiST index combine equality on `room_id` with range overlap
  (`&&`) on `period`.
- The `WHERE` clause makes the constraint partial: only confirmed bookings take part, so
  cancelling a booking frees its slot without deleting the row.
- When two transactions insert conflicting rows, PostgreSQL makes the second wait for
  the first. If the first commits, the second fails with SQLSTATE `23P01`
  (`exclusion_violation`).

The responsibilities are split across the layers (ADR 0002):

- **Service:** pre-checks for overlaps through the repository and raises
  `SlotUnavailable`. This gives a clear error in the common, non-concurrent case and
  keeps the rule testable with the in-memory fake.
- **Database:** the exclusion constraint is the real guarantee and covers the race the
  pre-check cannot see.
- **Postgres adapter:** maps SQLSTATE `23P01` to `SlotUnavailable`, so callers see the
  same domain error whichever check fired.

## Consequences

**Positive**

- The invariant holds no matter which code path writes to the table, including a future
  bug that skips the service check.
- No explicit locks in application code. Concurrent requests for *different* rooms, or
  for non-overlapping slots in the same room, do not wait for each other.
- The rule is declared in one place in the schema, where it is easy to review.
- The in-memory fake and the Postgres adapter raise the same `SlotUnavailable`, which
  contract tests verify.

**Negative**

- The invariant lives in the database, not in the domain. The domain check is a
  convenience, not a guarantee. This split is explicit in the code and in this ADR.
- The design depends on PostgreSQL (range types, `btree_gist`, exclusion constraints).
  This is accepted in ADR 0001.
- Each insert pays for a GiST index check. This is negligible at the expected volume.
- The pre-check and the constraint express the same rule twice. Contract and
  concurrency tests keep them consistent.

## Alternatives considered

- **Optimistic locking (version column).** Rejected: there is no existing row whose
  version can be compared, because the conflict is between two new rows.
- **Pessimistic lock on the room row (`SELECT ... FOR UPDATE` on `rooms`).** Workable,
  but it serializes *every* booking for a room, including non-overlapping ones. It also
  only works if every writer remembers to take the lock first.
- **`SERIALIZABLE` isolation.** Rejected: it would detect the conflict, but as a generic
  serialization failure that must be retried, and it would apply to every transaction.
  The exclusion constraint gives a specific, deterministic error.
- **Application-level check only.** Rejected: it is subject to the race described in the
  context and fails under concurrent requests.
- **Unique constraint on `(room_id, start)`.** Rejected: it only catches identical start
  times, not partial overlaps.
