# ADR 0003: Scope boundaries: header-based identity, no message queue, reminders as a scheduled command

- **Status:** Accepted

## Context

The system is an MVP. Its value is a small core that is correct under concurrency: no
overlapping bookings, a per-user limit that holds under parallel requests and
idempotent creation. Every feature outside that core adds code, infrastructure and tests
that compete for the same effort.

A booking system usually also has authentication, room administration, tentative
bookings that expire, asynchronous notifications and a deployment pipeline. Leaving them
out without saying so would look like an oversight, and would invite them back in one
spec at a time. This ADR records what is deliberately excluded, why, and where each
piece would plug in if it were added later.

## Decision

**Identity: the `X-User-Id` header, no authentication.** Users are seed data. The API
adapter reads the header and passes a plain user id to the services; nothing below the
adapter knows how the user was identified. There are no passwords, sessions or tokens.

**Rooms and users are seed data.** There is no API to create, edit or delete them.

**Bookings are confirmed immediately.** There is no pending state, no hold with an
expiry and no confirmation step. A booking is either `confirmed` or `cancelled`, which
keeps the exclusion constraint condition (`status = 'confirmed'`) the only rule that
decides whether a slot is taken.

**Reminders are a scheduled command, not a queue.** `jobs.py` exposes a
`send_reminders` command that runs one pass and exits:

- it selects confirmed bookings that start within the next hour and have
  `reminder_sent_at IS NULL`, using `FOR UPDATE SKIP LOCKED`;
- for each one it calls the `Notifier` port and sets `reminder_sent_at`, in the same
  transaction as the lock.

`SKIP LOCKED` lets several job instances run at once without picking the same booking:
a row locked by one instance is skipped by the others instead of blocking them. Locally
a container runs the command in a loop; in production it would be triggered by cron or
an equivalent scheduler.

**Notifications are written to the log.** The only `Notifier` adapter logs the reminder.
No email is sent.

**No deployment.** The system runs with `docker compose up`.

## Consequences

**Positive**

- The effort goes into the parts that are hard to get right: concurrency, the
  database guarantees and the test suite around them.
- No broker, worker framework or extra datastore: PostgreSQL is the only stateful
  component, and the reminder job reuses its locking instead of adding a new mechanism.
- Every excluded feature has a clear extension point. Real authentication replaces the
  header lookup in the API adapter; real email is a new `Notifier` adapter; neither
  touches the domain or the services.
- The reminder job is a plain function that can be tested with a fixed `Clock`, without
  a scheduler or real time.

**Negative**

- Anyone who can reach the API can act as any user by changing a header. The system
  must not be exposed outside a local or test environment as it is.
- Reminder delivery is at least once, not exactly once: if the process crashes after the
  notifier call but before the commit, the booking is picked up again on the next run.
  With a log notifier this is harmless; with real email it would require an outbox or an
  idempotent provider.
- Reminder latency depends on how often the command runs; a booking can be reminded up
  to one interval late.
- Room data changes require a new seed or migration rather than an API call.

## Alternatives considered

- **JWT or OAuth2/OpenID Connect authentication.** Rejected for this scope: it adds
  token handling, user management and test fixtures without exercising any booking rule.
  Because identity is resolved only in the API adapter, it can be added later without
  changing the core.
- **Celery or RQ with Redis.** Rejected: a broker and a worker process to run one
  periodic query. Duplicate prevention would still need a database-level guarantee.
- **Transactional outbox.** Rejected: it is the right tool for reliable delivery to an
  external system, but with log-only notifications there is nothing to deliver reliably.
- **An in-process scheduler inside the API** Rejected: it ties the
  job to the web process, runs once per API replica and makes the job harder to run and
  test in isolation.
