---
name: implement
description: "Implement a ticket, a spec, or work described in the conversation, and deliver it through review to merge."
argument-hint: "A tracker issue, or nothing to build what the conversation described"
disable-model-invocation: true
---

Implement the work the user named, then deliver it.

## Route

When the user named a tracker issue, run this skill's `scripts/start.py ISSUE`.
Follow [the ticket workflow](references/ticket.md) when its report begins with
`TICKET`. Follow [the spec workflow](references/spec.md) when its report begins
with `SPEC`.

When the user described the work instead, read the relevant code before
choosing the implementation, then follow [the ticket workflow](references/ticket.md)
from Build in the current branch.

Read [delivery](references/delivery.md) when the top-level ticket or spec branch
is ready for review and merge.
