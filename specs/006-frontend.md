# Spec 006: Frontend

- **Status:** Accepted
- **Related ADRs:** 0003 (scope boundaries: no real authentication), 0007 (idempotency
  key in the booking transaction), 0008 (E2E tests against an in-process API with a
  fixed clock)

## Summary

A minimal web frontend for the booking API, with two screens: **Book**, to book a room
for a time slot, and **My bookings**, to see and cancel the current user's bookings.
There is no login: the user picks which seeded user to act as.

The frontend needs two read endpoints that the API does not have yet: the list of rooms
and the list of the current user's bookings. This spec adds them.

## Requirements

### API

**`GET /rooms`** returns `200 OK` and every room, sorted by name:

```json
[
  { "id": "10000000-0000-4000-8000-000000000001", "name": "Room 1" },
  { "id": "10000000-0000-4000-8000-000000000002", "name": "Room 2" }
]
```

**`GET /bookings`** returns `200 OK` and every booking of the user identified by
`X-User-Id`, in the same shape as spec 001, sorted by `start` ascending. It includes
confirmed and cancelled bookings, past and future. It has no filters and no
pagination. A user with no bookings gets an empty array.

```json
[
  {
    "id": "9b2e7c41-5d3a-4f8e-b1c6-7a0d2e4f6b8c",
    "room_id": "10000000-0000-4000-8000-000000000001",
    "user_id": "20000000-0000-4000-8000-00000000000a",
    "start": "2026-10-22T08:00:00Z",
    "end": "2026-10-22T09:00:00Z",
    "status": "confirmed"
  }
]
```

Both endpoints follow the identity rule of spec 001: a missing, malformed or unknown
`X-User-Id` returns `401` with a Problem Details body. Bookings of other users are never
returned.

### Frontend

The frontend is React + Vite, in `frontend/`. It talks to the API through the existing
`/api` proxy. No router library, no state management library, no UI framework.

1. **Acting as.** A header shows a select labelled "Acting as" with the seeded users,
   "User A" and "User B". The user ids are constants in the frontend. User A is
   selected on load. Every request sends the selected id as `X-User-Id`. Changing the
   user reloads the data of the current screen and clears any message.
2. **Navigation.** Two buttons in the header, "Book" and "My bookings", switch between
   the two screens. "Book" is shown on load.
3. **Book screen.** A form with:
   - "Room": a select filled from `GET /rooms`, showing room names;
   - "Start (UTC)" and "End (UTC)": `datetime-local` inputs, read as UTC;
   - a "Book" button.

   Submitting sends `POST /bookings`. On success the screen shows "Booking confirmed:
   {room name}, {start} – {end}" and the form is reset. On error the form keeps its
   values.
4. **My bookings screen.** A table of the bookings from `GET /bookings`, with columns
   Room (name), Start, End and Status. Confirmed bookings have a "Cancel" button, which
   sends `POST /bookings/{id}/cancel` with no confirmation dialog. On success the list
   is reloaded. Cancelled bookings have no button. With no bookings the screen shows
   "No bookings yet."
5. **Time.** All times are UTC. They are shown as `YYYY-MM-DD HH:MM UTC`, for example
   `2026-10-22 08:00 UTC`. The frontend never converts to the browser's time zone.
6. **Idempotency.** Each booking attempt sends an `Idempotency-Key` header (spec 004).
   The key is generated with `crypto.randomUUID()` on the first submit and reused for
   every later submit with the same form values, until a submit succeeds or a field
   changes. A retry after a lost response therefore returns the booking created the
   first time instead of a second booking or a conflict.
7. **Pending requests.** While a request from a button is in flight, that button is
   disabled.
8. **Errors.** An error is shown inline in an element with `role="alert"`. For a Problem
   Details response the message is its `title`, followed by its `detail` if present.
   When the request fails without a response (network error), the message is "Could
   not reach the server. Try again." The frontend has no error texts of its own for
   specific status codes.

### End-to-end test setup

The E2E tests (pytest-playwright, marker `e2e`) run against a stack started by a pytest
fixture, not against Docker Compose:

- PostgreSQL from Testcontainers, migrated with Alembic (seed rooms and users included);
- the API from `create_app(...)` with a fixed `Clock`, served by uvicorn in a thread on
  a free port;
- the built frontend served by `vite preview`, proxying `/api` to that API.

Each test starts with no bookings. The production code gets no test-only switches: the
fixed clock is injected the same way the unit and integration tests inject it.

## Edge cases

- A user who switches from User A to User B on My bookings sees only User B's bookings.
- Two bookings of the same user with the same `start` keep a stable order. (Tie-break on
  `id`, so the order does not depend on the database.)
- A cancelled booking stays in the list, with status `cancelled` and no button.
- Submitting the same form values again after a success is a new attempt with a new
  key, and normally fails with `409` (the slot is now taken).
- The `422` validation-error body of FastAPI has a technical `detail`. It is shown as
  is; the inputs are `required` so that empty fields are caught before the request.

## Out of scope

- Real authentication, `GET /users`, editing users or rooms.
- Filtering, paginating or searching bookings; a calendar or availability view.
- Editing a booking, cancellation confirmation dialogs, cancellation reasons.
- The browser's local time zone, localisation, translations of error messages.
- Frontend unit tests (Vitest or similar). The frontend is covered by the E2E tests,
  and type-checked by `tsc --noEmit` in `npm run build`.
- Styling beyond what makes the screens usable; responsive or mobile layout.
- Running the E2E tests against Docker Compose.

## Acceptance criteria

The clock is fixed at 2026-10-20T10:00Z. Room 1, Room 2, User A and User B are the
seeded rooms and users.

### Read API

**AC-01: Rooms are listed sorted by name**
- **Given** the seeded rooms
- **When** user A requests `GET /rooms`
- **Then** the response is `200` with Room 1 and Room 2, in that order, each with `id`
  and `name`

**AC-02: A user lists only their own bookings, sorted by start**
- **Given** user A has a confirmed booking in room 1 from 2026-10-23T08:00Z to 09:00Z,
  a cancelled booking in room 2 from 2026-10-22T08:00Z to 09:00Z, and user B has a
  booking in room 1 from 2026-10-22T08:00Z to 09:00Z
- **When** user A requests `GET /bookings`
- **Then** the response is `200` with exactly user A's two bookings: first the
  cancelled one, then the confirmed one

**AC-03: A user with no bookings gets an empty list**
- **Given** user B has no bookings
- **When** user B requests `GET /bookings`
- **Then** the response is `200` with `[]`

**AC-04: The read endpoints require a known user**
- **When** `GET /rooms` or `GET /bookings` has no `X-User-Id` header, one that is not a
  valid UUID, or one that matches no user
- **Then** the response is `401` with a Problem Details body

### Frontend (E2E)

**AC-05: A user books a room**
- **Given** user A on the Book screen
- **When** they select Room 1, enter 2026-10-22 08:00 and 09:00, and click "Book"
- **Then** the screen shows "Booking confirmed: Room 1, 2026-10-22 08:00 UTC – 2026-10-22
  09:00 UTC"
- **And** My bookings shows that booking with status `confirmed` and a "Cancel" button

**AC-06: A user cancels a booking**
- **Given** user A has a confirmed booking in Room 1 from 2026-10-22T08:00Z to 09:00Z
- **When** they open My bookings and click "Cancel" on it
- **Then** the booking is shown with status `cancelled` and has no "Cancel" button

**AC-07: A taken slot shows the API error**
- **Given** user B has a confirmed booking in Room 1 from 2026-10-22T08:00Z to 09:00Z
- **When** user A tries to book Room 1 from 2026-10-22 08:30 to 09:30
- **Then** an alert shows the `title` of the `409` Problem Details response
- **And** the form still holds Room 1, 08:30 and 09:30

**AC-08: A retry after a lost response does not book twice**
- **Given** user A on the Book screen, and the response to the first `POST /bookings` is
  dropped after the API has handled it (Playwright route: fetch, then abort)
- **When** they click "Book", see the network error, and click "Book" again without
  changing the form
- **Then** the second attempt shows "Booking confirmed"
- **And** My bookings shows exactly one booking for that slot
