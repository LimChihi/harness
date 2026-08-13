---
name: implement
description: "Implement a piece of work based on a spec or set of tickets, and deliver it through review."
disable-model-invocation: true
---

Implement the work described by the user in the spec or tickets.

Use /tdd where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite
once at the end.

Once done, use /code-review to review the work.

Commit your work to the current branch, then deliver it.

## Delivery

Delivery ends when the pull request carries every condition its repository
merges on. Merging itself belongs to the repository.

1. Run the repository's checks and reach green.
2. Push the branch and open a pull request against the default branch, using
   ordinary Git and GitHub commands.
3. Run `npx @limchihi/harness await`. It blocks until the pull request needs
   you, then reports what it found. Answer the report, run it again, and repeat
   until it reports `MERGED` or `READY`.

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
- `READY` — every condition holds. If the repository merges on its own, the
  next `await` reports the merge; otherwise delivery is complete and the merge
  belongs to the reviewer.
- `MERGED` — the work landed.
- `TIMEOUT` — nothing changed within the window. Run `await` again.

Once the pull request has merged, run `npx @limchihi/harness cleanup` from
outside the ticket's worktree to remove it and release what it held.
