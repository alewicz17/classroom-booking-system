# ADR 0006: Per-user booking limit, enforced by `SELECT ... FOR UPDATE` on the user row

- **Status:** Accepted
- **Refines:** ADR 0005

## Context

A user may hold at most 3 future bookings: confirmed, with `start` strictly after now
(spec 003). Requests from the same user can arrive concurrently, so counting in
application code is not enough on its own. Under `READ COMMITTED`, two transactions can
both count "2 of 3", both insert, and the user ends up with 4.

The exclusion constraint from ADR 0004 cannot express this rule. The bookings involved
are in different rooms and do not overlap, and the rule is about how many rows exist,
not about a conflict between two of them.

The count also depends on time. A booking stops counting when it starts, with no write
to the database. Any value stored to track the count would go stale on its own.

## Decision

The create-booking transaction locks the user's row before it counts the user's future
bookings and before it inserts:

```sql
SELECT id FROM users WHERE id = %s FOR UPDATE;

SELECT count(*) FROM bookings
WHERE user_id = %s AND status = 'confirmed' AND lower(period) > %s;  -- now, from Clock
```

The lock is held until commit or rollback. A second request from the same user waits
on the lock. Under `READ COMMITTED` each statement takes a fresh snapshot, so once it
gets the lock, its count includes the booking the first request just committed.
Requests from different users lock different rows and never wait for each other.

The rule itself lives in the domain: the service reads the count through the
repository port and the domain decides whether the limit is reached. An in-memory
repository, if one is added for unit tests, can implement the lock as a no-op, because
unit tests are single-threaded. The guarantee under concurrency comes from PostgreSQL,
as in ADR 0004.

Cancellation does not take the lock. A cancellation only lowers the count, so a
concurrent one can at worst make a request see a count that is too high and be
rejected when it could have succeeded. The limit is never exceeded.

### Effect on ADR 0005

ADR 0005 maps `40P01` on the booking `INSERT` to `SlotUnavailable`. It argues that the
transaction holds no row locks before the insert, so a deadlock there can only come
from overlapping bookings. This ADR adds a row lock, so the argument has to be checked
again.

It still holds, as long as the user lock is taken before the insert. A transaction
waiting for a user lock has not inserted anything yet, so no other transaction can be
waiting on it. Every transaction that is blocked on the exclusion constraint already
holds its own user lock and waits for nothing else. Any wait cycle is therefore made
only of waits on uncommitted overlapping bookings: the slot is contested, and
`SlotUnavailable` is the correct answer. Spec 003 AC-14 checks this, with two users
booking the same slot concurrently.

## Consequences

**Positive**

- The limit holds under any concurrency. Spec 003 AC-12 and AC-13 check this with 50
  threads.
- The lock is as narrow as the rule: one user's row. Other users, and the overlap rule,
  are unaffected.
- No schema change, no retry loop, no new isolation level.

**Negative**

- Requests from the same user run one at a time. This is acceptable: a single user
  rarely sends several bookings at the same time.
- `FOR UPDATE` also blocks foreign-key checks from other transactions that insert
  bookings for that user. All of them take the same lock first, so in practice nothing
  changes. `FOR NO KEY UPDATE` would be enough here, but `FOR UPDATE` is the more
  familiar form and it matches the intent.
- ADR 0005 now depends on the order of statements: the user lock before the insert. A
  future spec that adds writes to this transaction must check that order again.

## Alternatives considered

- **Optimistic locking with a version column on `users`.** Concurrent requests from the
  same user would fail and need a retry loop. A request that would have fit within the
  limit could still be rejected.
- **`SERIALIZABLE` isolation.** PostgreSQL would detect the anomaly, but every
  transaction then has to retry on `40001`. That is more machinery than one row lock.
- **Advisory lock (`pg_advisory_xact_lock`) on a hash of the user id.** It works, but it
  turns a UUID into a number and locks something that is not a row. The user row
  already exists, and it is the natural thing to lock.
- **Counter column on `users` with a `CHECK (count <= 3)`.** The count changes when a
  booking starts, without any write, so the column would be wrong as soon as time
  passes.
- **Locking the room row.** It is the wrong granularity: the limit is across rooms, and
  ADR 0004 rejected serializing bookings per room.
