# harness

Project-local development hooks for coding agents.

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
```

Existing hooks in `.codex/hooks.json` are preserved. Re-running the command updates the harness-owned hook without adding duplicate configuration.
Commit the generated `.codex/` files so the hook remains a property of the repository.

After installation, open `/hooks` in Codex and trust the project hook.

## File size hints

The hook observes `apply_patch` edits. It emits context when a file grows by more than 30 lines and ends above one of these thresholds:

- More than 800 lines: check whether the file still has one responsibility.
- More than 1,200 lines: extract a coherent responsibility.
- More than 1,400 lines: split the file before growing it further unless it is generated or data-only.

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
