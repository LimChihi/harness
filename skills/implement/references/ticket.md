# Ticket

Act as the implementer and delivery owner for one ticket.

## Prepare

Work only in the worktree reported by `start.py`. Inspect reported dirty state
before editing. If the branch is behind the default branch, follow the
repository's synchronization workflow first.

Read the ticket and the relevant code before choosing the implementation.

## Build

Use /tdd where possible, at pre-agreed seams.

Build until the requested behavior and any acceptance criteria are satisfied.
Run typechecking and focused tests regularly, then finish with the full test
suite green.

Use /code-review to review the work. Commit the completed work to the current
branch.

Continue with [delivery](delivery.md).
