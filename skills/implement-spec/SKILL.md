---
name: implement-spec
description: "Deliver a spec's existing tickets through implementation, PR review, merge, and cleanup."
disable-model-invocation: true
---

Deliver the user's spec through its existing tickets. Completion means the spec is satisfied, its changes are merged, and task-owned temporary resources are cleaned up.

## Context

The parent spec defines the outcome and constraints; tickets organize the work. Read the spec, accepted decisions, sub-issues, and declared blocking dependencies. Ticket status alone is not implementation evidence, and requirements omitted from tickets still belong to the spec.

Use one dedicated branch and worktree for the spec, targeting the user's chosen branch or the repository's default integration branch. Reuse this workspace when resuming.

## Ownership

The main agent owns dependency decisions, acceptance, cross-ticket integration, and delivery. Delegate one executable ticket at a time to an implementation subagent. A ticket is executable when its declared prerequisite conditions hold and the required code is available in the spec branch.

Give the subagent source links, relevant decisions, dependency evidence, and acceptance criteria; leave implementation choices to it. Its delivery consists of commits, verification evidence, and unmet criteria or blockers.

The worktree has one writer at a time, with explicit ownership transfer for edits and Git mutations. While the subagent implements, the main agent assesses spec coverage and plans integration. Reviews read fixed commits; fixes belong to the current writer.

## Acceptance and continuity

Use /tdd where appropriate at the spec's agreed test seams. Verify changed behavior during implementation and run the repository's full required checks on the integrated result. Use /code-review for completed tickets and the integrated spec, with their recorded baselines. Address findings and verify affected behavior after fixes.

Accept deliveries against the actual diff and criteria before advancing. Every spec requirement needs evidence, including any cross-ticket behavior, migration, cleanup, or nonfunctional requirements.

Keep a concise handoff note outside the disposable worktree: source links, integration target, spec and ticket starting commits, branch/worktree, accepted deliveries, evidence, and next action. Reconcile it with actual state on resume. Surface unresolved scope or delivery decisions while continuing independent work that remains valid.

When preparing the PR, read [PR delivery](references/land-pr.md) for CI, review, merge, and cleanup.
