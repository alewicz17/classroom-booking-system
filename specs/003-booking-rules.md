# Spec 003: Booking rules: maximum duration and per-user limit

- **Status:** Accepted
- **Related ADRs:** 0004 (no overlaps via exclusion constraint), 0005 (deadlocks on the
  exclusion constraint), 0006 (per-user limit via `SELECT ... FOR UPDATE`)

## Summary

Two new rules apply when a booking is created. A booking may last at most 6 hours, and
a user may hold at most 3 future confirmed bookings at any time. The limit must hold
when several requests from the same user arrive at the same time.

## Requirements

### API

No new endpoints and no change to the request or response shape of `POST /bookings`.
The new rules add two error cases, returned as Problem Details (RFC 9457).

### Rules

1. **Maximum duration.** `end - start` must be at most 6 hours, otherwise `422`
   (`BookingTooLong`). A booking of exactly 6 hours is allowed. The maximum is a
   constant in the domain, not a configuration setting.
2. **Per-user limit.** A user may hold at most 3 future bookings. A future booking is a
   booking of that user with status `confirmed` and `start` strictly after "now", as
   given by the `Clock` port. A request that would bring the count above 3 is rejected
   with `422` (`BookingLimitReached`). The limit is a constant in the domain, not a
   configuration setting.
3. **What does not count.** Cancelled bookings and bookings that have already started
   (`start <= now`), including ones still in progress, do not count toward the limit.
   The limit applies across all rooms.
4. **Database guarantee.** Rule 2 is checked inside the create-booking transaction,
   after locking the user's row with `SELECT ... FOR UPDATE`. The lock serializes
   concurrent requests from the same user, so two requests cannot both read "2 of 3"
   and both succeed. Requests from different users never wait for each other on this
   lock.
5. **Lock before insert.** The user lock is taken before the booking `INSERT`. This
   keeps the reasoning of ADR 0005 valid: a transaction waiting on a user lock has not
   inserted anything yet, so no other transaction can be waiting on it, and a deadlock
   on the `INSERT` can still only come from overlapping bookings. The `40P01` to
   `SlotUnavailable` mapping is unchanged.
6. **Order of checks.** Errors are reported in this order:
   1. identity (`401`, spec 001);
   2. malformed input (`422`, spec 001);
   3. invalid range, booking in the past, booking too long (`422`);
   4. unknown room (`404`);
   5. per-user limit (`422`);
   6. overlap (`409`).

   A user at the limit who requests a taken slot therefore gets `422`, not `409`.

### Data

- No schema change. The `users` table already exists and its rows are locked as they
  are.
- Overlapping bookings by the same user in different rooms remain allowed, as in spec
  001. Only their number is limited.

## Edge cases

- A booking of exactly 6 hours is allowed; 6 hours and 1 minute is rejected.
- A booking that crosses midnight is subject to the same maximum, nothing else changes.
- A user with 3 future bookings can book again after cancelling one of them.
- A user with 3 future bookings can book again once one of them starts, without any
  cancellation: at `now == start` that booking stops counting.
- A booking in progress at "now" does not count, even though it has not ended.
- The limit is per user: user B is not affected by user A's bookings.
- Many concurrent requests from the same user for different free slots: exactly as
  many succeed as the limit allows.

## Impact on existing tests

The approved Hypothesis test from spec 002 (AC-15,
`tests/property/test_no_overlaps.py`) creates bookings for two users in random
sequences, so it will now hit `BookingLimitReached`. The `create` rule must treat
`BookingLimitReached` as an expected rejection, like `SlotUnavailable` and
`BookingInPast`. This is the only change allowed to approved tests in this spec. The
invariant it checks is unchanged.

## Out of scope

- A minimum duration, opening hours, slot granularity, or a maximum booking horizon
  (how far in the future a booking may start).
- Per-room or per-user configurable limits.
- Preventing a user from holding overlapping bookings in different rooms.
- Telling the client how many bookings it has left.
- `Idempotency-Key` (spec 004).

## Acceptance criteria

The clock is fixed at 2026-10-20T10:00Z unless stated otherwise. "Future" times are on
2026-10-21 unless stated otherwise.

### Maximum duration

**AC-01: A booking of exactly the maximum duration is allowed**
- **Given** room 1 has no bookings
- **When** user A books room 1 from 08:00Z to 14:00Z
- **Then** the response is `201`

**AC-02: A booking longer than the maximum is rejected**
- **Given** room 1 has no bookings
- **When** user A books room 1 from 08:00Z to 14:01Z
- **Then** the response is `422` and no booking is created

### Per-user limit

**AC-03: A user below the limit can book**
- **Given** user A has 2 future confirmed bookings
- **When** user A books a free slot
- **Then** the response is `201`

**AC-04: A user at the limit is rejected**
- **Given** user A has 3 future confirmed bookings
- **When** user A books a free slot
- **Then** the response is `422` and no booking is created

**AC-05: Cancelled bookings do not count**
- **Given** user A has 2 future confirmed bookings and 1 future cancelled booking
- **When** user A books a free slot
- **Then** the response is `201`

**AC-06: A booking in progress does not count**
- **Given** user A has 2 future confirmed bookings and 1 confirmed booking from
  2026-10-20T09:00Z to 11:00Z
- **When** user A books a free slot
- **Then** the response is `201`

**AC-07: A booking starting exactly now does not count**
- **Given** user A has 2 future confirmed bookings and 1 confirmed booking starting at
  2026-10-20T10:00Z
- **When** user A books a free slot
- **Then** the response is `201`

**AC-08: The limit applies across rooms**
- **Given** user A has 2 future confirmed bookings in room 1 and 1 in room 2
- **When** user A books a free slot in room 2
- **Then** the response is `422`

**AC-09: The limit is per user**
- **Given** user A has 3 future confirmed bookings
- **When** user B books a free slot
- **Then** the response is `201`

**AC-10: The limit is checked before the overlap**
- **Given** user A has 3 future confirmed bookings, and room 1 has a confirmed booking
  from 08:00Z to 09:00Z
- **When** user A books room 1 from 08:00Z to 09:00Z
- **Then** the response is `422`, not `409`

**AC-11: Errors use Problem Details**
- **When** `BookingTooLong` or `BookingLimitReached` is returned
- **Then** the body is `application/problem+json` with at least `type`, `title` and
  `status`

### Database guarantee and concurrency

**AC-12: Concurrent requests from the same user: exactly the limit wins**
- **Given** user A has no bookings
- **When** 50 threads, each with its own connection, start together (`threading.Barrier`)
  and each books a different, non-overlapping slot for user A
- **Then** exactly 3 requests succeed, the other 47 fail with `BookingLimitReached`, and
  the database holds exactly 3 confirmed bookings for user A

**AC-13: Concurrent requests near the limit: exactly one wins**
- **Given** user A has 2 future confirmed bookings
- **When** 50 threads start together and each books a different, non-overlapping slot
  for user A
- **Then** exactly 1 request succeeds, the other 49 fail with `BookingLimitReached`, and
  the database holds exactly 3 confirmed bookings for user A

**AC-14: Different users on the same slot: the overlap rule still decides**
- **Given** room 1 has no bookings
- **When** 50 threads start together, alternating between user A and user B, and each
  books room 1 from 08:00Z to 09:00Z
- **Then** exactly 1 request succeeds, the other 49 fail with `SlotUnavailable` (not
  with a deadlock or any other error), and the database holds exactly 1 confirmed
  booking for room 1
