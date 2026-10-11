---
description: Propose tests derived from a spec's acceptance criteria
argument-hint: <spec number, e.g. 001>
---

Read `specs/$ARGUMENTS-*.md`, `CLAUDE.md` and any ADR the spec refers to.

1. List every acceptance criterion of the spec. If a criterion is ambiguous or
   contradicts an ADR, stop and ask. Do not guess.
2. For each criterion, decide the right test layer (`unit`, `contract`,
   `integration`, `concurrency`, `property`, `e2e`) and say why in one line.
3. Write exactly one test per criterion, named after it
   (e.g. `test_back_to_back_bookings_do_not_overlap`). Follow the testing rules in
   `CLAUDE.md`: fakes from `adapters/memory.py`, fixed `Clock`, no sleeps.
4. Add only the minimum production code needed for the tests to import (empty
   classes, functions raising `NotImplementedError`). No implementation.
5. Run the tests and show that they fail (red) for the right reason, not because
   of import or syntax errors.
6. Show a table: criterion → test name → layer. Then stop and wait for review.
   Do not start implementing.
