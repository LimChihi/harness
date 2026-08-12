---
name: imp
description: Start implementation from a ticket or spec.
disable-model-invocation: true
---

Read the repository guidance that governs implementation, worktrees, and pull requests.

Run the bundled `scripts/start.py ISSUE`. Its report begins with `TICKET` or `SPEC`; follow that branch.

For `TICKET`, work only in the reported worktree. Inspect any reported dirty state before editing. If the branch is behind the default branch, follow the repository's synchronization workflow before running `/implement` there. After `/implement`, run the repository's normal checks, then use ordinary Git and GitHub tools to commit, push, and open a pull request to the default branch. Run `npx @limchihi/harness state` when the branch, remote, or pull-request relationship needs orientation. Leave merging to the repository's review workflow.

For `SPEC`, create no worktree for the spec itself. Start every `READY` ticket that fits the available workers. For each, run this skill's script for that ticket, then have a worker run `/implement` in its reported worktree. `BLOCKED` tickets wait. After a ticket pull request merges, rerun the script for the spec to refresh the frontier.

The spec is complete only when the report says `COMPLETE: yes`. When the remaining frontier depends on review, merge, or another external action, report that boundary and stop.
