---
name: imp
description: Start implementation from a ticket or spec.
disable-model-invocation: true
---

Read the repository guidance and tracker context around the referenced work. A leaf ticket is an implementation scope; a spec with delivery tickets is a coordination scope.

The bundled `scripts/start.py ISSUE` discovers the current Git repository, claims an open GitHub issue for the current user, and creates or recovers its isolated `task/ISSUE` worktree. Its JSON output provides the repository, branch, worktree, and actions taken.

For a ticket, prepare its worktree and run `/implement` there.

For a spec, the current agent can coordinate its unblocked ticket frontier. Independent tickets can run in parallel in separate prepared worktrees, with each worker running `/implement` for its ticket. Repository guidance, dependencies, and available workers inform the grouping.

Completed ticket branches integrate through the repository's normal pull-request workflow.
