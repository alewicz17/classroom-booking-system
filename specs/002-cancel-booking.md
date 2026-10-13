# Spec 002: Cancel a booking

- **Status:** Accepted
- **Related ADRs:** 0003 (scope boundaries), 0004 (no overlaps via exclusion
  constraint)

## Summary

A user cancels one of their own bookings, as long as the booking starts more than 24
hours from now. A cancelled booking is kept, with status `cancelled`, and no longer
blocks its slot. A booking can be cancelled only once, including when several requests
arrive at the same time.

## Requirements

### API

**`POST /bookings/{id}/cancel`** cancels the booking for the user identified by
`X-User-Id`. The request has no body.

On success it returns `200 OK` and the booking, in the same shape as spec 001, with
`status` set to `cancelled`:

```json
{
  "id": "9b2e7c41-5d3a-4f8e-b1c6-7a0d2e4f6b8c",
  "room_id": "3f1c2a9e-8b4d-4e2f-9a6c-1d2e3f4a5b6c",
  "user_id": "c5a8d1f3-2e7b-4c9a-8d6f-0b1e3a5c7d9e",
  "start": "2026-10-22T08:00:00Z",
  "end": "2026-10-22T09:00:00Z",
  "status": "cancelled"
}
```

The booking is not deleted: `GET /bookings/{id}` keeps returning it, with status
`cancelled`.

All error responses use Problem Details (RFC 9457).

### Rules

1. **Identity.** Same as spec 001: a missing, malformed or unknown `X-User-Id` returns
   `401`.
2. **Visibility.** The endpoint returns `404` (`BookingNotFound`) both when the booking
   does not exist and when it belongs to another user. An `{id}` that is not a valid
   UUID is rejected with `422`.
3. **Already cancelled.** Cancelling a booking whose status is already `cancelled`
   returns `409` (`BookingAlreadyCancelled`).
4. **Cancellation deadline.** A booking can be cancelled only while "now", as given by
   the `Clock` port, is strictly before `start - 24 hours`. Otherwise the request is
   rejected with `422` (`CancellationTooLate`). This also covers bookings that have
   already started or ended. The 24-hour deadline is a constant in the domain, not a
   configuration setting.
5. **Order of checks.** Rules are checked in the order above: identity, visibility,
   already cancelled, deadline. A cancelled booking inside the deadline therefore
   returns `409`, not `422`.
6. **Freed slot.** A cancelled booking does not block its slot: the same room and range
   can be booked again (spec 001, rule 6).
7. **One cancellation wins.** The change from `confirmed` to `cancelled` is a single
   conditional update (`... WHERE status = 'confirmed'`). When several requests cancel
   the same booking at the same time, exactly one succeeds and the others fail with
   `BookingAlreadyCancelled`.

### Data

- No schema change. `status` already accepts `cancelled`, and the exclusion constraint
  already ignores cancelled bookings.
- A cancelled booking cannot be confirmed again. To get the slot back, the user creates
  a new booking.

## Edge cases

- `now == start - 24h` is rejected as too late.
- `now` one minute before `start - 24h` is allowed.
- A booking created less than 24 hours before its start can never be cancelled. This is
  accepted: the deadline applies to every booking the same way.
- A booking that has already started or ended is rejected as too late, not as a
  separate error.
- Cancelling another user's booking returns `404`, even if that booking is already
  cancelled or past the deadline: nothing about it is revealed.
- After a cancellation, the same user or another user can book the same slot.

## Out of scope

- Maximum duration and per-user booking limit (spec 003). Whether cancelled bookings
  count toward the limit is decided there.
- `Idempotency-Key` on cancellation (spec 004).
- Reinstating a cancelled booking, cancelling on behalf of another user, cancellation
  reasons, partial cancellation (shortening a booking).
- Listing bookings.

## Acceptance criteria

The clock is fixed at 2026-10-20T10:00Z unless stated otherwise.

### Cancelling a booking

**AC-01: A user cancels their own booking**
- **Given** user A has a confirmed booking X from 2026-10-22T08:00Z to 09:00Z
- **When** user A requests `POST /bookings/{X}/cancel`
- **Then** the response is `200` with booking X and status `cancelled`

**AC-02: A cancelled booking is still readable**
- **Given** user A has cancelled booking X
- **When** user A requests `GET /bookings/{X}`
- **Then** the response is `200` with status `cancelled`

**AC-03: A cancelled booking frees its slot**
- **Given** user A has cancelled booking X in room 1 from 2026-10-22T08:00Z to 09:00Z
- **When** user B books room 1 from 2026-10-22T08:00Z to 09:00Z
- **Then** the booking is created

### Deadline

**AC-04: Cancelling just before the deadline is allowed**
- **Given** user A has a confirmed booking starting at 2026-10-21T10:01Z
- **When** user A cancels it at 2026-10-20T10:00Z (24 hours and 1 minute before start)
- **Then** the response is `200`

**AC-05: Cancelling exactly at the deadline is rejected**
- **Given** user A has a confirmed booking starting at 2026-10-21T10:00Z
- **When** user A cancels it at 2026-10-20T10:00Z (exactly 24 hours before start)
- **Then** the response is `422` and the booking is still `confirmed`

**AC-06: A booking that has already started cannot be cancelled**
- **Given** user A has a confirmed booking from 2026-10-20T09:00Z to 11:00Z
- **When** user A cancels it at 2026-10-20T10:00Z
- **Then** the response is `422` and the booking is still `confirmed`

### Errors

**AC-07: Cancelling twice is a conflict**
- **Given** user A has cancelled booking X
- **When** user A requests `POST /bookings/{X}/cancel` again
- **Then** the response is `409`

**AC-08: Already cancelled takes precedence over the deadline**
- **Given** user A has a cancelled booking X starting at 2026-10-20T12:00Z
- **When** user A requests `POST /bookings/{X}/cancel`
- **Then** the response is `409`

**AC-09: Another user's booking cannot be cancelled**
- **Given** user A has a confirmed booking X
- **When** user B requests `POST /bookings/{X}/cancel`
- **Then** the response is `404`, the same as for a booking that does not exist, and X
  is still `confirmed`

**AC-10: A booking that does not exist returns 404**
- **When** a user cancels an `{id}` that is a valid UUID but matches no booking
- **Then** the response is `404`

**AC-11: Malformed input is rejected**
- **When** a user cancels an `{id}` that is not a valid UUID
- **Then** the response is `422`

**AC-12: A missing or unknown user returns 401**
- **When** a cancel request has no `X-User-Id` header, one that is not a valid UUID, or
  one that matches no user
- **Then** the response is `401`

**AC-13: Errors use Problem Details**
- **When** any of the errors above is returned
- **Then** the body is `application/problem+json` with at least `type`, `title` and
  `status`

### Database guarantee and concurrency

**AC-14: Concurrent cancellations of the same booking: exactly one wins**
- **Given** user A has a confirmed booking X
- **When** 50 threads, each with its own connection, start together (`threading.Barrier`)
  and cancel X
- **Then** exactly 1 request succeeds, the other 49 fail with `BookingAlreadyCancelled`,
  and X is `cancelled`

**AC-15: No two confirmed bookings ever overlap**
- **Given** any sequence of create and cancel operations on rooms 1 and 2, generated by
  a Hypothesis stateful test
- **When** each operation is applied through the services
- **Then** after every step no two confirmed bookings in the same room overlap
