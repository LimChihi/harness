# Delivery

Deliver only the top-level ticket or spec integration branch. Delivery succeeds
only when its pull request merges. A closed pull request stops delivery without
completing it. Merging itself belongs to the repository.

1. Run the repository's checks and reach green.
2. Push the branch and open a pull request against the default branch, using
   ordinary Git and GitHub commands.
3. Run this skill's `scripts/delivery.py`. It blocks until the pull
   request needs you, then reports what it found. Answer the report, run it
   again, and repeat until it reports `MERGED` or `CLOSED`.

Handle each reported state:

- `CHECK_FAILURE` — inspect each `FAILED_CHECK`, fix the cause, and push.
- `THREADS_UNRESOLVED` — act on each `UNRESOLVED_THREAD`, reply with what you
  did, and resolve it. Acting is either changing the code or deciding against
  the change with a reason. A thread marked `answered-not-resolved` needs only
  the resolve. Every thread ends resolved.
- `CONFLICT` — reconcile the branch against the default branch and push.
- `MERGED` — the work landed.
- `CLOSED` — report that the pull request closed without merging and stop.
- `TIMEOUT` — nothing changed within the window; run it again.

After merge, run this skill's `scripts/cleanup.py` from outside the delivered
worktree to remove it and release what it held.
