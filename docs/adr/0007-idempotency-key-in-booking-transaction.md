# ADR 0007: Idempotency key stored in the booking transaction, serialized by the user lock

- **Status:** Accepted
- **Refines:** ADR 0006

## Context

A client that times out on `POST /bookings` cannot tell whether the booking was
created. If it retries, it may create a second booking. Spec 004 adds an optional
`Idempotency-Key` header: a retry with the same key and payload must return the
original response, and a reuse with a different payload must be rejected.

Three things must hold:

- **Atomicity.** A booking must never exist without its key, and a key must never exist
  without its booking. Otherwise a retry either creates a duplicate or replays a
  booking that was never committed.
- **Concurrency.** The original request and its retries can arrive at the same time,
  for example when a client retries after a short timeout while the first request is
  still running. Exactly one booking must be created.
- **Lock order.** ADR 0006 requires any new write in the create-booking transaction to
  be checked against the deadlock reasoning of ADR 0005.

## Decision

**A table in the same database, written in the same transaction.** A new table holds
one row per key:

```sql
CREATE TABLE idempotency_keys (
    user_id      uuid  NOT NULL REFERENCES users (id),
    key          uuid  NOT NULL,
    request_hash text  NOT NULL,
    response     jsonb NOT NULL,
    PRIMARY KEY (user_id, key)
);
```

The key is inserted in the create-booking transaction, right after the booking. Both
rows are committed together or not at all. Only successful requests are stored: a
request that fails rolls back, and a retry is processed as a new request.

**The key is looked up after the user lock.** With a key, the transaction runs:

```sql
SELECT id FROM users WHERE id = %s FOR UPDATE;              -- ADR 0006

SELECT request_hash, response FROM idempotency_keys
WHERE user_id = %s AND key = %s;
-- found, same hash:      return the stored response, write nothing
-- found, different hash: IdempotencyKeyMismatch, write nothing

-- not found: the rules of specs 001 and 003, then
INSERT INTO bookings ...;
INSERT INTO idempotency_keys ...;
```

A key belongs to a user, and every create-booking transaction for that user already
takes the user lock. Two requests with the same key therefore run one at a time. The
second waits on the lock and, under `READ COMMITTED`, its lookup sees the key the first
one committed. No new lock is introduced. The primary key on `(user_id, key)` remains
the database guarantee: a second row for the same key can never be committed.

The lookup comes before the domain rules, so a late retry receives the original `201`
even if the booking has since started or the user has reached the limit. Without a key,
the transaction is unchanged.

**The hash is computed in the domain.** "Same payload" is a domain rule: the same
`room_id`, `start` and `end` once the times are in UTC. A pure domain function builds
this normalized form and hashes it with SHA-256 from `hashlib`, which is in the
standard library, so the dependency rule holds. Unit tests cover it without Docker.

**The response is a snapshot.** `response` stores the booking as it was created. The
API renders a replay exactly as it renders a new booking: `201`, `Location` and body.
A later cancellation changes the booking, not the snapshot. The current state is
available through `GET /bookings/{id}`.

**A new port, next to the existing ones.** `IdempotencyKeyRepository` (`get` and `add`)
is exposed on the unit of work as `uow.idempotency_keys`, next to the other
repositories.

### Effect on ADR 0005 and ADR 0006

The transaction now has two writes after the user lock: the booking `INSERT` and the
key `INSERT`.

The key `INSERT` never waits. It could only wait on an uncommitted row with the same
`(user_id, key)`, which only a transaction for the same user could have inserted.
That transaction would have needed the user lock, which this one holds. The foreign
key check on `user_id` takes `FOR KEY SHARE` on the user row, which this transaction
already holds `FOR UPDATE`, so it does not wait either.

The user lock is still the first lock taken, and the booking `INSERT` is still the
only statement that can wait on another transaction's uncommitted row. The reasoning of
ADR 0005 holds: a deadlock on that `INSERT` can only come from overlapping bookings,
and the `40P01` to `SlotUnavailable` mapping is unchanged.

## Consequences

**Positive**

- The booking and its key are atomic. A crash between the two writes commits neither,
  because they are in one transaction.
- Concurrent retries are handled with no new lock, no retry loop and no "in progress"
  state. Spec 004 AC-16 and AC-17 check this with 50 threads.
- A replay is a single read under the lock and returns exactly what was stored.

**Negative**

- Keys are never deleted, so the table grows with every keyed booking. Expiry and
  cleanup are out of scope for spec 004. A `created_at` column and a periodic delete
  would be enough to add them later.
- A keyed request takes the user lock before the domain rules are checked, so even an
  invalid keyed request holds the lock briefly. Requests from other users are not
  affected.
- The guarantee that the key `INSERT` never waits relies on every writer of
  `idempotency_keys` taking the user lock first. A future writer that skips the lock
  would make the `INSERT` wait on the primary key, and fail with `23505` instead of
  replaying.
- The snapshot stores the booking, not the HTTP bytes. If the API changes how a booking
  is rendered, replays of old keys are rendered the new way.

## Alternatives considered

- **Insert the key first and handle `23505`.** The second request waits on the primary
  key, fails with `unique_violation`, rolls back and reads the stored response in a
  new transaction. It works without the user lock, but it needs two transactions and
  error-driven control flow, for a lock that is already there.
- **Return `409` while the first request is in progress.** This is a common design for
  public payment APIs. It needs an "in progress" state that must be cleaned up if the
  request dies, and the client has to retry. Waiting on the user lock gives the same
  safety with no extra state.
- **Store the key in a separate transaction**, before or after the booking. A failure
  between the two leaves a booking without a key (a retry duplicates it) or a key
  without a booking (a retry replays something that does not exist).
- **Columns on `bookings`** (`idempotency_key`, `request_hash`) with a unique
  constraint. There is no extra table, but the booking table takes on a concern of the
  HTTP layer, and a replay would show the current booking instead of the original
  response.
- **Store only `booking_id` and rebuild the response.** It avoids duplication, but the
  replay would depend on the booking's current state and would have to force the
  status back to `confirmed`.
- **An external store such as Redis.** It cannot share a transaction with PostgreSQL,
  so atomicity is lost, and it adds infrastructure that ADR 0003 avoids.
- **Compute the hash in the API adapter.** The normalization to UTC is a domain rule.
  In the adapter it would be invisible to unit tests.
