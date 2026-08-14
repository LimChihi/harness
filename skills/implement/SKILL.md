---
name: implement
description: "Implement a ticket, a spec, or work described in the conversation, and deliver it through review to merge."
argument-hint: "A tracker issue, or nothing to build what the conversation described"
disable-model-invocation: true
---

Implement the work the user named, then deliver it.

## Start

When the user named a tracker issue, run this skill's `scripts/start.py ISSUE`.
Its report begins with `TICKET` or `SPEC`; follow that branch. When the user
described the work instead, build it where you already are and skip to Build.

For `TICKET`, work only in the reported worktree. Inspect any reported dirty
state before editing. If the branch is behind the default branch, follow the
repository's synchronization workflow first.

For `SPEC`, create no worktree for the spec itself. Start every `READY` ticket
that fits the available workers: run the script for that ticket, then have a
worker carry it from Build in its reported worktree. `BLOCKED` tickets wait.
After a ticket's pull request merges, rerun the script for the spec to refresh
the frontier. The spec is complete only when the report says `COMPLETE: yes`.
When the remaining frontier depends on review, merge, or another external
action, report that boundary and stop.

## Build

Use /tdd where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite
once at the end.

Once done, use /code-review to review the work.

Commit your work to the current branch.

## Deliver

Delivery ends when the pull request merges. Merging itself belongs to the
repository.

1. Run the repository's checks and reach green.
2. Push the branch and open a pull request against the default branch, using
   ordinary Git and GitHub commands.
3. Run this skill's `scripts/delivery.py`. It blocks until the pull request
   needs you, then reports what it found. Answer the report, run it again, and
   repeat until it reports `MERGED`.

Each `STATUS` the report can carry:

- `FAILED_CHECK` — the report names the check and carries the tail of its
  failing log. Fix the cause and push.
- `UNRESOLVED_THREAD` — act on the comment, reply with what you did, and
  resolve the thread. Acting is either changing the code or deciding against
  the change, and a decision against it is a reply carrying the reason. Threads
  on your own pull request are yours to close, and the report carries the
  command that closes one. A thread marked `answered-not-resolved` already has
  your reply and needs only the resolve. Every thread ends resolved.
- `CONFLICT` — reconcile the branch against the default branch and push.
- `MERGED` — the work landed.
- `TIMEOUT` — nothing changed within the window. Run it again.

Once the pull request has merged, run this skill's `scripts/cleanup.py` from
outside the ticket's worktree to remove it and release what it held.
