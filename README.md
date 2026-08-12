# harness

Project-local development tools for coding agents.

## Install

Run this command from a Git repository or one of its subdirectories:

```bash
npx @limchihi/harness install
```

The installer writes:

```text
.codex/
├── hooks.json
└── hooks/
    └── harness/
        └── file_size_hint.py
.agents/
└── skills/
    └── imp/
        ├── SKILL.md
        ├── agents/openai.yaml
        └── scripts/start.py
```

Existing hooks in `.codex/hooks.json` are preserved. Re-running the command updates the harness-owned hook and skill without adding duplicate configuration.
Commit the generated `.codex/` and `.agents/` files so the tools remain properties of the repository.

After installation, open `/hooks` in Codex and trust the project hook.

## Implementation entry point

`$imp #123` accepts a GitHub ticket or a spec composed of tickets. It provides an isolated worktree for each selected ticket and delegates the work to the existing `/implement` skill. Independent tickets in a spec can be coordinated in parallel.

The bundled start script identifies specs before mutation and reports their ready and blocked tickets. For a leaf ticket, it uses `gh` to claim the issue and Git to create or recover its `task/123` worktree, then reports the worktree, branch state, and existing pull request. Repository-specific worktree initialization remains a property of the target repository.

## File size hints

The hook observes `apply_patch` edits. It emits context when a file grows by more than 30 lines and ends above one of these thresholds:

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
