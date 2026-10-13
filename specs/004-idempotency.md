# Spec 004: Idempotency

- **Status:** Accepted
- **Related ADRs:** 0005 (deadlocks on the exclusion constraint), 0006 (per-user limit
  via `SELECT ... FOR UPDATE`), 0007 (idempotency key stored in the booking
  transaction)

## Summary

A client that does not receive the response to `POST /bookings` (timeout, dropped
connection) cannot tell whether the booking was created. If it retries, it may create a
second booking. With an `Idempotency-Key` header, a retry returns the response of the
original request instead of creating a new booking. The guarantee must hold when the
original request and its retries arrive at the same time.

## Requirements

### API

`POST /bookings` accepts an optional `Idempotency-Key` header whose value is a UUID:

```
POST /bookings
X-User-Id: c5a8d1f3-2e7b-4c9a-8d6f-0b1e3a5c7d9e
Idempotency-Key: 7e4b2c19-3a5d-4f6e-8b1c-9d0a2e3f4b5c
```

No other endpoint reads the header. The request and response shapes of
`POST /bookings` do not change. Errors are returned as Problem Details (RFC 9457).

### Rules

1. **Optional header.** Without `Idempotency-Key`, `POST /bookings` behaves exactly as
   in specs 001 and 003.
2. **Key format.** The value must be a UUID, otherwise `422` and no booking is created.
3. **Scope.** A key belongs to the user identified by `X-User-Id`. The same key sent by
   two different users identifies two unrelated requests.
4. **First use.** When a key is used for the first time and the booking is created, the
   key, a hash of the request and the response are stored in the **same transaction**
   as the booking. The booking and the key are either both committed or both rolled
   back.
5. **Only successes are stored.** If the request fails for any reason (`404`, `409`,
   `422`), the transaction is rolled back and nothing is stored for the key. A retry
   with the same key is processed as a new request.
6. **Replay.** When a key is reused with the same payload, the stored response is
   returned: `201`, the same `Location` header and the same body. No new booking is
   created. The response is the one stored when the booking was created, even if the
   booking has since been cancelled. The current state is available through
   `GET /bookings/{id}`.
7. **Same payload.** Two payloads are the same when they have the same `room_id`,
   `start` and `end` after `start` and `end` are converted to UTC. `10:00+02:00` and
   `08:00Z` are therefore the same payload. The request hash is computed on this
   normalized form.
8. **Different payload.** When a key is reused with a different payload, the request is
   rejected with `422` (`IdempotencyKeyMismatch`) and no booking is created.
9. **Replay before the rules.** A replay returns the stored response even if the
   request would now fail the rules of specs 001 and 003 (for example, `start` is now
   in the past, or the user is at the limit). The order of checks becomes:
   1. identity (`401`, spec 001);
   2. malformed input, including a malformed `Idempotency-Key` (`422`);
   3. idempotency key lookup: replay, or `422` (`IdempotencyKeyMismatch`);
   4. invalid range, booking in the past, booking too long (`422`);
   5. unknown room (`404`);
   6. per-user limit (`422`);
   7. overlap (`409`).

   Without the header, step 3 is skipped and the order is that of spec 003.
10. **Concurrency.** Requests with the same key from the same user are serialized by
    the user lock of ADR 0006. The key is looked up after the lock is taken, so a
    request that waited on the lock sees the key committed by the request it waited
    for. The primary key on `(user_id, key)` is the database guarantee: a second row
    for the same key can never be stored.
11. **Lock order.** The user lock is still the first lock taken in the create-booking
    transaction, before the booking `INSERT` and the key `INSERT`. As required by ADR
    0006, the reasoning of ADR 0005 stays valid: the key `INSERT` never waits, because
    every other transaction that could insert the same key waits on the user lock
    first.
12. **No expiry.** Keys are kept forever. There is no TTL and no cleanup.

### Data

- New table `idempotency_keys`, created by a new Alembic migration:
  - `user_id` (`uuid`, references `users`);
  - `key` (`uuid`);
  - `request_hash` (`text`): hash of the normalized payload (rule 7);
  - `response` (`jsonb`): a snapshot of the booking as it was created. The API renders
    a replay exactly as it renders a new booking;
  - primary key `(user_id, key)`.
- The status code of a replay is always `201`, because only successes are stored
  (rule 5), so it is not stored.

## Edge cases

- Same key, same instant written with a different UTC offset: replay (rule 7).
- Same key, same room and times, different `X-User-Id`: a different request (rule 3).
  It is processed normally and will usually fail with `409` on the overlap.
- First request fails with `409`; the slot is then freed by a cancellation; a retry
  with the same key creates the booking.
- First request fails with `422` because of a malformed body: nothing is stored, and a
  corrected request with the same key is processed as a first use.
- Replay after the booking has started: `201` with the original body, not
  `BookingInPast`.
- Replay when the user is at the limit, with the booking created by that key among the
  3: `201` with the original body, not `BookingLimitReached`.
- Replay after the booking was cancelled: `201` with `status` `confirmed`, as stored.
- Mismatched payload that is also invalid (for example `start` after `end`):
  `IdempotencyKeyMismatch`, because the key is looked up first (rule 9).
- An empty `Idempotency-Key` header is not a UUID: `422`.
- Many concurrent requests from the same user with the same key and payload: exactly
  one booking is created and all requests return it.

## Impact on existing tests

None. The header is optional (rule 1) and, without it, the order of checks is
unchanged (rule 9). No approved test of specs 001 to 003 needs to change.

## Out of scope

- `Idempotency-Key` on `POST /bookings/{id}/cancel` or any other endpoint. A repeated
  cancellation is already safe: it fails with `409` (spec 002).
- Making the header mandatory.
- Storing failed responses.
- Key expiry, cleanup of old keys, keys in any format other than UUID.
- A response header that tells the client whether the response is a replay.
- Returning `409` while a request with the same key is still in progress: concurrent
  requests wait on the user lock instead (rule 10).

## Acceptance criteria

The clock is fixed at 2026-10-20T10:00Z unless stated otherwise. "Future" times are on
2026-10-21 unless stated otherwise. "Key K" is a fixed UUID.

### First use and replay

**AC-01: A request with a new key creates the booking**
- **Given** room 1 has no bookings
- **When** user A books room 1 from 08:00Z to 09:00Z with key K
- **Then** the response is `201` with a `Location` header and the booking, and the key
  is stored for user A

**AC-02: A retry with the same key and payload replays the response**
- **Given** user A has booked room 1 from 08:00Z to 09:00Z with key K
- **When** user A sends the same request again with key K
- **Then** the response is `201` with the same `Location` header and the same body, and
  the database holds exactly 1 booking for that request

**AC-03: The payload is compared after normalization to UTC**
- **Given** user A has booked room 1 from 08:00Z to 09:00Z with key K
- **When** user A books room 1 from 10:00+02:00 to 11:00+02:00 with key K
- **Then** the response is `201` with the same body as the first request, and no new
  booking is created

**AC-04: A retry with the same key and a different payload is rejected**
- **Given** user A has booked room 1 from 08:00Z to 09:00Z with key K
- **When** user A books room 1 from 12:00Z to 13:00Z with key K
- **Then** the response is `422` (`IdempotencyKeyMismatch`) and no booking is created

**AC-05: A replay ignores rules that no longer pass**
- **Given** user A has booked room 1 from 08:00Z to 09:00Z on 2026-10-21 with key K
- **And** the clock is now 2026-10-21T08:30Z
- **When** user A sends the same request again with key K
- **Then** the response is `201` with the original body, not `422`

**AC-06: A replay is not blocked by the per-user limit**
- **Given** user A has 3 future confirmed bookings, one of which was created with key K
- **When** user A sends the request for that booking again with key K
- **Then** the response is `201` with the original body, not `422`

**AC-07: A replay returns the stored response even after a cancellation**
- **Given** user A has booked room 1 with key K, and has then cancelled that booking
- **When** user A sends the same request again with key K
- **Then** the response is `201` with the original body, with `status` `confirmed`, and
  no new booking is created

### What is stored

**AC-08: A failed request does not store the key**
- **Given** room 1 has a confirmed booking of user B from 08:00Z to 09:00Z
- **And** user A books room 1 from 08:00Z to 09:00Z with key K and gets `409`
- **And** user B cancels their booking
- **When** user A sends the same request again with key K
- **Then** the response is `201` and the booking is created

**AC-09: A key is scoped to its user**
- **Given** user A has booked room 1 from 08:00Z to 09:00Z with key K
- **When** user B books room 2 from 08:00Z to 09:00Z with key K
- **Then** the response is `201` and a new booking is created for user B

**AC-10: Without the header nothing changes**
- **Given** user A has booked room 1 from 08:00Z to 09:00Z without `Idempotency-Key`
- **When** user A sends the same request again without `Idempotency-Key`
- **Then** the response is `409`

### Validation

**AC-11: A malformed key is rejected**
- **When** user A books a free slot with an `Idempotency-Key` that is empty or not a
  valid UUID
- **Then** the response is `422` and no booking is created

**AC-12: The key mismatch is checked before the rules**
- **Given** user A has booked room 1 from 08:00Z to 09:00Z with key K
- **When** user A books room 1 from 09:00Z to 08:00Z with key K
- **Then** the response is `422` (`IdempotencyKeyMismatch`), not `InvalidTimeRange`

**AC-13: Errors use Problem Details**
- **When** `IdempotencyKeyMismatch` or a malformed key error is returned
- **Then** the body is `application/problem+json` with at least `type`, `title` and
  `status`

### Database guarantee and concurrency

**AC-14: The key and the booking are committed together**
- **Given** room 1 has a confirmed booking from 08:00Z to 09:00Z
- **When** an overlapping booking with key K is created through the Postgres adapter,
  bypassing the service pre-check, and the insert fails with `SlotUnavailable`
- **Then** no row for key K exists in `idempotency_keys`

**AC-15: A rolled-back transaction stores neither the booking nor the key**
- **Given** room 1 has no bookings
- **When** a booking and key K are added through the Postgres adapter in one
  transaction, and the transaction is rolled back instead of committed
- **Then** neither the booking nor a row for key K exists

**AC-16: Concurrent retries with the same key: one booking, same response for all**
- **Given** room 1 has no bookings
- **When** 50 threads, each with its own connection, start together (`threading.Barrier`)
  and each books room 1 from 08:00Z to 09:00Z for user A with key K
- **Then** all 50 requests succeed with the same booking, and the database holds
  exactly 1 booking for that room and exactly 1 row for key K

**AC-17: Concurrent requests with the same key and different payloads: exactly one
wins**
- **Given** user A has no bookings
- **When** 50 threads start together and each books a different, non-overlapping free
  slot for user A with key K
- **Then** exactly 1 request succeeds, the other 49 fail with
  `IdempotencyKeyMismatch`, and the database holds exactly 1 booking for user A
