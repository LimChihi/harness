# PR delivery

## Acceptance evidence

Publish the accepted implementation and initiate the repository's CI and review workflow; both can proceed concurrently. Diagnose failures, fix valid review findings, and explain disagreements with evidence. Preserve existing approval requirements and branch protections.

Merge eligibility requires spec acceptance, required checks, completed expected reviews, and resolved blocking feedback. Repository conventions and explicit requests determine expected reviews; require positive completion evidence. After new commits or integration changes, reassess which check and review results still apply.

Merge the revision covered by that evidence. Auto-merge requests and queue entries remain pending until the PR is actually merged.

## Waiting and resuming

The main agent retains ownership during pending checks, reviews, and merge-queue processing. Continue useful independent work or use supported waits with backoff. Notify only on meaningful changes or required user action.

Before yielding until later, record the PR URL, head commit, pending conditions, and continuation identifier in the handoff note. Promise automatic resumption only after registering and verifying a real continuation. When none is available, report the pending work and that execution needs to be resumed.

Resume from current PR and branch state. If an external decision or unresolved failure prevents progress, preserve unmerged work and report the exact condition.

## Merge and cleanup

Confirm the intended changes have merged into the target. Preserve the merge result and acceptance evidence outside the worktree, and follow repository conventions for ticket closure and branch deletion.

With all work preserved, release task-owned resources, remove the spec worktree and implementation branches as appropriate, and end its continuations. Report cleanup failures as "merged, cleanup pending", identifying remaining resources.
