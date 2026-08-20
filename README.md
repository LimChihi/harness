# harness

Project-local development tools for coding agents, shared by Codex and Cursor.

## Install

```bash
npx skills@latest add limchihi/harness
```

Then run `/setup-harness` once in the repository. It wires the agent hooks into
`.codex/hooks.json` and `.cursor/hooks.json`, and asks how the repository merges
and what a worktree owns. Commit what it writes so the tooling stays a property
of the repository.

## Update

```bash
npx skills@latest update
```

Both skills carry the code they run, so this one command updates it all. The
hook configuration names a path inside the installed skill rather than a copy of
it, so nothing needs rewiring after an update, and `skills-lock.json` records
what changed.

## Skills

- `implement` — claim a ticket or spec, build it in its own worktree, and
  deliver it through review to merge. Also runs without an issue, on work the
  conversation described.
- `setup-harness` — the per-repository wiring above.

## Implementation entry point

`/implement #123` accepts a GitHub ticket or a spec composed of tickets.
Independent tickets in a spec can be coordinated in parallel.

The bundled start script identifies specs before mutation and reports their
ready and blocked tickets. For a leaf ticket, it uses `gh` to claim the issue
and Git to create or recover its `task/123` worktree, then reports the worktree,
branch state, and existing pull request. Repository-specific worktree
initialization remains a property of the target repository.

Checks, commits, pushes, and pull requests stay with the repository's own
command and ordinary Git and GitHub tools. Harness does not wrap those
operations.

## Delivery

`scripts/delivery.py` exists because an agent has no way to wait: every poll of
a pull request costs it a turn. It polls on the agent's behalf and returns only
when the pull request needs its author, reporting `CHECK_FAILURE` with the tail
of the failing log, `UNRESOLVED_THREAD` for each open review thread, `CONFLICT`,
`MERGED`, or `CLOSED`. A thread the author already replied to but left open is
marked `answered-not-resolved`, the state that silently blocks a merge. It waits
through green and pending checks and returns `TIMEOUT` rather than blocking past
its window. It reports; it does not prescribe.

`scripts/cleanup.py` removes every worktree whose pull request merged, together
with its branch, and keeps any that carry uncommitted changes or hold the
current directory. When a repository owns resources beyond the worktree itself,
`/setup-harness` writes an executable `.agents/hooks/cleanup`; cleanup runs it
after a removal and reports its output.

Every call that crosses the network retries up to a bound and re-raises the last
failure past it. Local Git calls stay unwrapped: one of those failing is a fact
worth surfacing.

## File size hints

The hook observes Codex `apply_patch` edits and Cursor `Write` and `Delete`
edits. It emits context when a file grows by more than 30 lines and ends above
one of these thresholds:

- More than 800 lines: check whether the file still has one responsibility.
- More than 1,200 lines: extract a coherent responsibility.
- More than 1,400 lines: split the file before growing it further unless it is
  generated or data-only.

Files with a suffix in `IGNORED_FILE_SUFFIXES` are skipped. The blacklist
currently contains `.lock`.

## Development

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```
