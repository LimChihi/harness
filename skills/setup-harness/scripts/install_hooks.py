#!/usr/bin/env python3

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


CODEX_CONFIG = ".codex/hooks.json"
CURSOR_CONFIG = ".cursor/hooks.json"
CODEX_EDIT_MATCHER = "^apply_patch$"
CURSOR_EDIT_MATCHER = "^(Write|Delete)$"
FILE_SIZE_TIMEOUT = 5
HANDOFF_TIMEOUT = 30
OBSOLETE_FILE_SIZE_PATHS = (
    ".codex/hooks/file_size_hint.py",
    ".codex/hooks/harness/file_size_hint.py",
    ".agents/hooks/harness/file_size_hint.py",
)
OBSOLETE_HANDOFF_PATHS = (
    ".codex/hooks/harness/handoff.py",
    ".agents/hooks/harness/handoff.py",
)


class InstallError(Exception):
    pass


def command_for(relative_path):
    return f'/usr/bin/python3 "$(git rev-parse --show-toplevel)/{relative_path}"'


def repository_root(start):
    result = subprocess.run(
        ["git", "-C", str(Path(start).resolve()), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise InstallError(f"cannot resolve Git repository: {result.stderr.strip()}")
    return Path(result.stdout.strip()).resolve()


def skill_paths(root):
    """The hooks run from the installed skill, so a project install is required."""
    hooks = Path(__file__).resolve().parent.parent / "hooks"
    try:
        relative = hooks.relative_to(root)
    except ValueError:
        raise InstallError(
            f"this skill lives outside {root}; install it into the project with "
            "npx skills@latest add limchihi/harness"
        ) from None
    return {
        "file_size_hint": (relative / "file_size_hint.py").as_posix(),
        "handoff": (relative / "handoff.py").as_posix(),
    }


def read_config(path, defaults):
    if not path.is_file():
        return {**defaults, "hooks": {}}
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise InstallError(f"{path} must contain a JSON object")
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise InstallError(f'{path} field "hooks" must be a JSON object')
    return config


def retained(entries, event, command, obsolete, is_group):
    if not isinstance(entries, list):
        raise InstallError(f"hooks.{event} must be an array")
    for entry in entries:
        if not isinstance(entry, dict):
            raise InstallError(f"hooks.{event} entries must be objects")
        if is_group and not isinstance(entry.get("hooks"), list):
            raise InstallError(f'hooks.{event} entry field "hooks" must be an array')
    return [entry for entry in entries if entry.get("command") not in (command, *obsolete)]


def install_codex(config, event, command, timeout, matcher, obsolete):
    groups = []
    for group in retained(config["hooks"].get(event, []), event, command, obsolete, True):
        handlers = [
            handler
            for handler in group["hooks"]
            if handler.get("command") not in (command, *obsolete)
        ]
        if handlers:
            groups.append({**group, "hooks": handlers})
    entry = {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}
    if matcher is not None:
        entry["matcher"] = matcher
    config["hooks"][event] = [*groups, entry]


def install_cursor(config, event, entry, obsolete):
    kept = retained(
        config["hooks"].get(event, []), event, entry["command"], obsolete, False
    )
    config["hooks"][event] = [*kept, entry]


def write(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(contents)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def install(start):
    root = repository_root(start)
    paths = skill_paths(root)
    file_size = command_for(paths["file_size_hint"])
    handoff = command_for(paths["handoff"])
    obsolete_file_size = [command_for(path) for path in OBSOLETE_FILE_SIZE_PATHS]
    obsolete_handoff = [command_for(path) for path in OBSOLETE_HANDOFF_PATHS]

    codex_path = root / CODEX_CONFIG
    codex = read_config(codex_path, {"description": "Project-local Codex hooks."})
    for event in ("PreToolUse", "PostToolUse"):
        install_codex(
            codex, event, file_size, FILE_SIZE_TIMEOUT, CODEX_EDIT_MATCHER,
            obsolete_file_size,
        )
    install_codex(codex, "Stop", handoff, HANDOFF_TIMEOUT, None, obsolete_handoff)

    cursor_path = root / CURSOR_CONFIG
    cursor = read_config(cursor_path, {"version": 1})
    for event in ("preToolUse", "postToolUse"):
        install_cursor(
            cursor,
            event,
            {
                "command": file_size,
                "matcher": CURSOR_EDIT_MATCHER,
                "timeout": FILE_SIZE_TIMEOUT,
            },
            obsolete_file_size,
        )
    install_cursor(
        cursor,
        "stop",
        {"command": handoff, "timeout": HANDOFF_TIMEOUT, "loop_limit": None},
        obsolete_handoff,
    )

    write(codex_path, json.dumps(codex, indent=2) + "\n")
    write(cursor_path, json.dumps(cursor, indent=2) + "\n")
    for relative in (*OBSOLETE_FILE_SIZE_PATHS, *OBSOLETE_HANDOFF_PATHS):
        (root / relative).unlink(missing_ok=True)

    return "\n".join(
        [
            f"WROTE: {CODEX_CONFIG}",
            f"WROTE: {CURSOR_CONFIG}",
            f"HOOKS: {paths['file_size_hint']}",
            f"HOOKS: {paths['handoff']}",
        ]
    )


def main():
    parser = argparse.ArgumentParser(
        description="Point this repository's Codex and Cursor hooks at the skill."
    )
    parser.add_argument("--repo", default=".")
    print(install(parser.parse_args().repo))


if __name__ == "__main__":
    try:
        main()
    except (InstallError, json.JSONDecodeError, ValueError) as error:
        print(f"install hooks: {error}", file=sys.stderr)
        sys.exit(1)
