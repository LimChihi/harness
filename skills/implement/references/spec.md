# Spec

Act as the coordinator, integrator, and delivery owner for the complete spec.
Keep decomposition, scheduling, review, integration, and replanning with the
main agent.

## Prepare

Treat the `TRACKER_READY`, `TRACKER_BLOCKED`, and `TRACKER_COMPLETE` values from
`start.py` as tracker facts, not as the implementation plan or completion
decision.

Read the complete spec, its tickets, and the relevant code. Use the current
branch as the spec integration branch when it already represents the spec;
otherwise create or recover an integration branch following the repository's
conventions. Inspect existing worktrees, branches, and pull requests before
creating replacements.

## Plan and execute

Build the task plan from tracker dependencies and technical dependencies. A
task may cover part of a ticket or several tightly coupled tickets. For each
task, record the tracker tickets it covers, acceptance criteria, dependencies,
verification, executor, base revision, and integration target.

Choose whether the main agent or a subagent executes each task. Base the choice
on boundary stability, file overlap, independent verification, context-transfer
cost, and integration risk. Run tasks concurrently when their interfaces and
writes are sufficiently independent.

Tracker ownership and task execution are separate. Before code changes begin
for a ticket, inspect its assignee, branches, worktrees, and pull requests.
Reuse existing work and coordinate with an existing owner. Claim unowned
tickets through the tracker before starting them. Each ticket covered by a
task has one responsible owner.

When delegating, give the subagent:

- one objective and its acceptance criteria;
- the relevant spec and code context;
- its base revision, worktree, and expected integration branch;
- applicable repository instructions and verification commands;
- known neighboring work that may affect integration.

Use isolated branches and worktrees for concurrent writers. A subagent's
deliverable is a tested commit or branch with its changes, tests, assumptions,
risks, and integration notes.

## Review and integrate

Review every returned result against its task and the complete spec. Ask the
same subagent to continue when its task needs more work. Integrate accepted
results into the spec branch using the repository's appropriate Git or pull
request workflow, then run the relevant integration checks.

Update the task plan after every integration or material discovery. Start
newly ready tasks according to the updated plan. Once an integrated task
worktree is clean and no longer needed, remove it and release its branch using
ordinary Git.

The main agent may implement integration glue and spec-wide corrections, or
turn them into new bounded tasks.

## Complete

Completion means the integrated branch satisfies the original spec and its
acceptance criteria; tracker issue state alone does not decide it. Reconcile
assumptions across tasks, run the repository's full checks, and use /code-review
for a final review.

Commit any final integration work, then continue with [delivery](delivery.md).
