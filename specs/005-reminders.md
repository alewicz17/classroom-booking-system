# Spec 005: Reminders

- **Status:** Accepted
- **Related ADRs:** 0003 (scope boundaries: reminders as a scheduled command, log-only
  notifications)

## Summary

A user should be reminded shortly before their booking starts. A scheduled command
finds the confirmed bookings that start within the next hour and sends one reminder for
each. Notifications are written to the log. Each booking is reminded at most once, even
when several instances of the command run at the same time.

## Requirements

### Command

`python -m booking.jobs` runs one pass of `send_reminders` against the database in
`DATABASE_URL` and exits:

- on success it logs `Reminders sent: N` and exits with code `0`;
- on any error the transaction is rolled back, the error is logged and the exit code is
  not `0`.

The command does not loop and does not sleep. Scheduling is the job of the environment
(rule 9).

The pass is implemented by `main(database_url: str, clock: Clock) -> int` in `jobs.py`,
which wires the Postgres unit of work and the log notifier, runs `send_reminders`, logs
the result and returns the exit code. The `__main__` entry point only reads
`DATABASE_URL`, calls `main` with the system clock and exits with the returned code, so
tests can run the whole pass with a fixed clock.

### Rules

1. **Due bookings.** A booking is due for a reminder when all of these hold:
   - its status is `confirmed`;
   - no reminder has been sent for it (`reminder_sent_at IS NULL`);
   - `now < start <= now + 1 hour`, where `now` comes from the `Clock` port.

   The lead time of 1 hour is a domain constant.
2. **Missed reminders are skipped.** A booking that has already started (`start <= now`)
   is never reminded, even if no reminder was ever sent for it (for example because the
   command was not running). A late reminder has no value.
3. **One reminder per booking.** For each due booking, the command calls
   `Notifier.send_reminder(booking)` and sets `reminder_sent_at` to `now`. A booking with
   `reminder_sent_at` set is never selected again.
4. **One transaction per pass.** The pass selects all due bookings with
   `SELECT ... FOR UPDATE SKIP LOCKED`, sends the reminders, marks them as sent and
   commits once. If the notifier fails for any booking, the whole pass is rolled back:
   no booking is marked as sent, and the next pass picks them all up again.
5. **At least once.** As stated in ADR 0003, delivery is at least once: if the process
   crashes after a notifier call but before the commit, that reminder is sent again on
   the next pass. With a log notifier this is acceptable.
6. **Concurrent passes.** Several passes may run at the same time. `SKIP LOCKED` makes a
   pass skip the bookings locked by another pass instead of waiting for them. A booking
   is therefore reminded by exactly one pass, and no pass blocks on another.
7. **Result.** `send_reminders` returns the number of reminders sent in the pass.
8. **Log notifier.** The only `Notifier` adapter writes one `INFO` log record per
   reminder, containing the booking id, the user id, the room id and the start time in
   ISO 8601 UTC.
9. **Scheduling.** `docker-compose.yml` gets a `reminders` service, built from the
   backend image, that runs the command every 60 seconds in a shell loop. A failed pass
   does not stop the loop.

### Ports

- New port `Notifier` with one method: `send_reminder(booking: Booking) -> None`.
- `BookingRepository` gets two methods:
  - one that returns the due bookings (rule 1) and locks them with
    `FOR UPDATE SKIP LOCKED`;
  - one that sets `reminder_sent_at` on a booking.
- The `Booking` dataclass does not change. `reminder_sent_at` exists only in the
  database and in the in-memory fake.
- `adapters/memory.py` gets a fake `Notifier` that records the bookings it receives.

### Data

- New column `bookings.reminder_sent_at` (`timestamptz`, nullable, default `NULL`),
  added by a new Alembic migration. Existing bookings get `NULL`.

### API

No change. `reminder_sent_at` is not exposed by any endpoint.

## Edge cases

- A booking that starts exactly 1 hour from now is due (rule 1, upper bound included).
- A booking that starts exactly now is not due (rule 1, lower bound excluded).
- A booking that started 30 minutes ago and was never reminded: skipped forever (rule 2).
- A booking created less than 1 hour before its start (for example at 10:00 for 10:30)
  is reminded on the next pass.
- A cancelled booking inside the window is not reminded. A booking cannot be cancelled
  after its reminder is sent, because the cancellation deadline (24 hours, spec 002) is
  earlier than the reminder window (1 hour).
- Two passes in a row with the same clock: the second sends nothing.
- A pass with no due bookings returns `0` and does not call the notifier.
- The notifier fails on the second of three due bookings: none of the three is marked as
  sent (rule 4), and the next pass sends all three.
- A pass that starts while another pass holds the locks returns `0` without waiting
  (rule 6).

## Impact on existing tests

None. The `Booking` dataclass, the API and the existing repository methods do not
change. The new repository methods are added to the contract suite.

## Out of scope

- Real email or any channel other than the log.
- Exactly-once delivery, an outbox, retries with backoff.
- One transaction per booking, or isolating a failing reminder from the others.
- Reminders for already started bookings, configurable lead times, more than one
  reminder per booking, user preferences.
- A scheduler inside the API process, a `--loop` option, a message queue.
- Exposing `reminder_sent_at` through the API.
- An index for the due-bookings query.

## Acceptance criteria

The clock is fixed at 2026-10-20T10:00Z unless stated otherwise. All bookings are on
2026-10-20 and confirmed unless stated otherwise. Bookings are created directly through
the repository, so the rules of specs 001 and 003 do not get in the way.

### Selection

**AC-01: A booking that starts within the hour is reminded**
- **Given** user A has a booking in room 1 from 10:30Z to 11:30Z
- **When** `send_reminders` runs
- **Then** the notifier receives that booking once, its `reminder_sent_at` is
  2026-10-20T10:00Z, and the result is `1`

**AC-02: A booking that starts exactly one hour from now is reminded**
- **Given** user A has a booking in room 1 from 11:00Z to 12:00Z
- **When** `send_reminders` runs
- **Then** the notifier receives that booking and the result is `1`

**AC-03: A booking that starts after the window is not reminded**
- **Given** user A has a booking in room 1 from 11:30Z to 12:30Z
- **When** `send_reminders` runs
- **Then** the notifier receives nothing, the result is `0`, and `reminder_sent_at` is
  still `NULL`

**AC-04: A booking that starts now or has started is not reminded**
- **Given** user A has a booking in room 1 from 10:00Z to 11:00Z and a booking in room 2
  from 09:30Z to 10:30Z, and no reminder was sent for either
- **When** `send_reminders` runs
- **Then** the notifier receives nothing and the result is `0`

**AC-05: A cancelled booking is not reminded**
- **Given** user A has a cancelled booking in room 1 from 10:30Z to 11:30Z
- **When** `send_reminders` runs
- **Then** the notifier receives nothing and the result is `0`

**AC-06: All due bookings are reminded in one pass**
- **Given** user A has a booking in room 1 from 10:30Z to 11:30Z, user B has a booking
  in room 2 from 10:45Z to 11:45Z, and user B has a booking in room 1 from 12:00Z to
  13:00Z
- **When** `send_reminders` runs
- **Then** the notifier receives the first two bookings, not the third, and the result
  is `2`

**AC-07: With nothing due, the notifier is not called**
- **Given** there are no bookings
- **When** `send_reminders` runs
- **Then** the notifier receives nothing and the result is `0`

### Once only

**AC-08: A second pass does not send the reminder again**
- **Given** user A has a booking in room 1 from 10:30Z to 11:30Z, and `send_reminders`
  has already run once
- **When** `send_reminders` runs again, first with the clock at 10:00Z and then at
  10:20Z
- **Then** the notifier has received that booking exactly once in total, and both later
  passes return `0`

**AC-09: A notifier failure rolls back the whole pass**
- **Given** three bookings start at 10:15Z, 10:30Z and 10:45Z, and the notifier fails
  on the second
- **When** `send_reminders` runs
- **Then** the error propagates and no booking has `reminder_sent_at` set
- **And when** `send_reminders` runs again with a working notifier
- **Then** the notifier receives all three bookings and the result is `3`

### Repository contract (in-memory and Postgres)

**AC-10: The due-bookings query follows rule 1**
- **Given** the bookings of AC-01 to AC-05 and a booking from 10:30Z to 11:30Z whose
  `reminder_sent_at` is already set
- **When** the due bookings are requested for now = 10:00Z
- **Then** exactly the bookings starting at 10:30Z (not yet reminded) and at 11:00Z are
  returned

**AC-11: A booking marked as sent is no longer due**
- **Given** a booking from 10:30Z to 11:30Z, returned as due
- **When** it is marked as sent at 10:00Z and the transaction is committed
- **Then** it is not returned as due anymore, and on Postgres its `reminder_sent_at` is
  2026-10-20T10:00Z

**AC-12: A rolled-back mark is not kept**
- **Given** a booking from 10:30Z to 11:30Z
- **When** it is marked as sent and the transaction is rolled back instead of committed
- **Then** it is still returned as due

### Log notifier and command

**AC-13: The log notifier writes one record per reminder**
- **Given** a booking from 10:30Z to 11:30Z
- **When** the log notifier sends a reminder for it
- **Then** exactly one `INFO` record is logged, containing the booking id, the user id,
  the room id and `2026-10-20T10:30:00+00:00`

**AC-14: The command runs one pass and reports the count**
- **Given** the test database holds a booking from 10:30Z to 11:30Z
- **When** `jobs.main` runs with the test database URL and the fixed clock
- **Then** it returns exit code `0`, logs `Reminders sent: 1`, and the booking has
  `reminder_sent_at` set

### Concurrency (Postgres)

**AC-15: Concurrent passes send each reminder exactly once**
- **Given** 20 due bookings
- **When** 10 threads, each with its own connection, start together
  (`threading.Barrier`) and each runs `send_reminders` with a fixed clock and a shared
  recording notifier
- **Then** the notifier has received each of the 20 bookings exactly once, the results
  of the 10 passes sum to `20`, and all 20 bookings have `reminder_sent_at` set

**AC-16: A pass does not wait for the locks of another pass**
- **Given** a due booking, locked by an open transaction that has selected it as due
  and not yet committed
- **When** another pass runs `send_reminders` on its own connection with
  `lock_timeout` set to 1 second
- **Then** it returns `0` without a lock timeout error, and the notifier receives
  nothing
