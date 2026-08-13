# harness

Project-local development tools for coding agents. Codex and Cursor share one copy of each hook.

## Install

Run this command from a Git repository or one of its subdirectories:

```bash
npx @limchihi/harness install
```

The installer writes:

```text
.agents/hooks/harness/
├── file_size_hint.py
└── handoff.py
.codex/hooks.json
.cursor/hooks.json
```

Existing hooks in `.codex/hooks.json` and `.cursor/hooks.json` are preserved. Re-running the command updates the harness-owned hooks without adding duplicate configuration, and removes hooks left at their previous `.codex/hooks/` locations.
Commit the generated `.agents/`, `.codex/`, and `.cursor/` files so the tools remain properties of the repository.

After installation, open `/hooks` in Codex and trust the project hook. Cursor reloads `.cursor/hooks.json` on save.

## Skills

```bash
npx skills@latest add limchihi/harness
```

`skills` owns `.agents/skills/` and records what it installed in `skills-lock.json`, so the hooks and the skills each have one installer:

- `implement` — claim a ticket or spec, build it in its own worktree, and deliver it through review to merge.
- `setup-harness` — configure a repository for that delivery loop. Run it once per repository, before the first `/implement`.

## Implementation entry point

`/implement #123` accepts a GitHub ticket or a spec composed of tickets, and also runs without an issue on work the conversation described. Independent tickets in a spec can be coordinated in parallel.

The bundled start script identifies specs before mutation and reports their ready and blocked tickets. For a leaf ticket, it uses `gh` to claim the issue and Git to create or recover its `task/123` worktree, then reports the worktree, branch state, and existing pull request. Repository-specific worktree initialization remains a property of the target repository.

Checks, commits, pushes, and pull requests stay with the repository's own command and ordinary Git and GitHub tools. Harness does not wrap those operations.

## Handoff state

Inspect the current worktree, default-branch relationship, remote publication, and pull request without changing repository state:

```bash
npx @limchihi/harness state
```

The installed stop hook consumes the same state. It asks the agent to continue when committing, pushing, or opening a pull request is the single clear missing step, and falls silent once the pull request exists — an open pull request belongs to the delivery loop below, not to a per-turn reminder. Codex receives the guidance as a blocking `Stop` decision and Cursor as a `followup_message`.

## Delivery

```bash
npx @limchihi/harness await
```

An agent has no way to wait: every poll costs it a turn. `await` polls the current branch's pull request on its behalf and returns only when the pull request needs its author, reporting `CHECK_FAILURE` with the tail of the failing log, `UNRESOLVED_THREAD` for each open review thread, `CONFLICT`, `READY`, `MERGED`, or `CLOSED`. A thread the author already replied to but left open is marked `answered-not-resolved`, which is the state that silently blocks a merge. It waits through pending checks, and returns `TIMEOUT` rather than blocking past its window.

`await` reports; it does not prescribe. Committing, pushing, and opening the pull request stay with ordinary Git and GitHub commands, which the agent already knows.

```bash
npx @limchihi/harness cleanup
```

Removes every worktree whose pull request merged, together with its branch, and keeps any that carry uncommitted changes or hold the current directory. When a repository owns resources beyond the worktree itself, it puts an executable at `.agents/hooks/cleanup`; `cleanup` runs it after a removal and reports its output. Repositories without that file need no configuration.

## File size hints

The hook observes Codex `apply_patch` edits and Cursor `Write` and `Delete` edits. It emits context when a file grows by more than 30 lines and ends above one of these thresholds:

- More than 800 lines: check whether the file still has one responsibility.
- More than 1,200 lines: extract a coherent responsibility.
- More than 1,400 lines: split the file before growing it further unless it is generated or data-only.

Files with a suffix in `IGNORED_FILE_SUFFIXES` are skipped. The blacklist currently contains `.lock`.

## Update

Install a newer package version over the existing project hook:

```bash
npx @limchihi/harness@latest install
```

## Development

```bash
npm test
npm pack --dry-run
```
