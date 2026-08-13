# harness

Project-local development tools for coding agents. Codex and Cursor share one copy of each hook.

## Install

Run this command from a Git repository or one of its subdirectories:

```bash
npx @limchihi/harness install
```

The installer writes:

```text
.agents/
├── hooks/
│   └── harness/
│       ├── file_size_hint.py
│       └── handoff.py
└── skills/
    └── imp/
        ├── SKILL.md
        ├── agents/openai.yaml
        └── scripts/start.py
.codex/hooks.json
.cursor/hooks.json
```

Existing hooks in `.codex/hooks.json` and `.cursor/hooks.json` are preserved. Re-running the command updates the harness-owned hooks and skill without adding duplicate configuration, and removes hooks left at their previous `.codex/hooks/` locations.
Commit the generated `.agents/`, `.codex/`, and `.cursor/` files so the tools remain properties of the repository.

After installation, open `/hooks` in Codex and trust the project hook. Cursor reloads `.cursor/hooks.json` on save.

## Implementation entry point

`$imp #123` accepts a GitHub ticket or a spec composed of tickets. It provides an isolated worktree for each selected ticket and delegates the work to the existing `/implement` skill. Independent tickets in a spec can be coordinated in parallel.

The bundled start script identifies specs before mutation and reports their ready and blocked tickets. For a leaf ticket, it uses `gh` to claim the issue and Git to create or recover its `task/123` worktree, then reports the worktree, branch state, and existing pull request. Repository-specific worktree initialization remains a property of the target repository.

After implementation, use the repository's normal check command followed by ordinary `git commit`, `git push`, and GitHub pull-request tools. Harness does not wrap those operations.

## Handoff state

Inspect the current worktree, default-branch relationship, remote publication, and pull request without changing repository state:

```bash
npx @limchihi/harness state
```

The installed stop hook consumes the same state. It asks the agent to continue when committing, pushing, or opening a pull request is the single clear missing step. While a pull request is open, it keeps the agent monitoring reviews, checks, and mergeability every four minutes so feedback, CI failures, and conflicts are resolved before merge. Codex receives the guidance as a blocking `Stop` decision and Cursor as a `followup_message`.

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
