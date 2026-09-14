#!/usr/bin/env python3

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


CODEX_CONFIG = ".codex/hooks.json"
CURSOR_CONFIG = ".cursor/hooks.json"
CODEX_EDIT_MATCHER = "^(apply_patch|exec)$"
CODEX_SHELL_MATCHER = "^(Bash|exec)$"
CURSOR_EDIT_MATCHER = "^(Write|Delete)$"
FILE_SIZE_TIMEOUT = 5
GIT_SYNC_TIMEOUT = 5
POST_COMMIT_HOOK = "post-commit"
PROJECT_SKILL_HOOKS = ".agents/skills/setup-harness/hooks"
OBSOLETE_FILE_SIZE_PATHS = (
    ".codex/hooks/file_size_hint.py",
    ".codex/hooks/harness/file_size_hint.py",
    ".agents/hooks/harness/file_size_hint.py",
)
REMOVED_HANDOFF_PATHS = (
    ".codex/hooks/harness/handoff.py",
    ".agents/hooks/harness/handoff.py",
)


class InstallError(Exception):
    pass


def command_for(relative_path):
    if relative_path.startswith("~/"):
        return f'/usr/bin/python3 "$HOME"/{shlex.quote(relative_path[2:])}'
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
    hooks = Path(__file__).resolve().parent.parent / "hooks"
    home = Path.home().resolve()
    if hooks.is_relative_to(root):
        relative = hooks.relative_to(root)
    elif hooks == home / PROJECT_SKILL_HOOKS:
        relative = Path("~") / hooks.relative_to(home)
    else:
        raise InstallError(
            f"this skill lives outside {root}; install it into the project with "
            "npx skills@latest add limchihi/harness, or into user scope with --global"
        ) from None
    return {
        "file_size_hint": (relative / "file_size_hint.py").as_posix(),
        "git_sync_policy": (relative / "git_sync_policy.py").as_posix(),
        "post_commit": (relative / POST_COMMIT_HOOK).as_posix(),
        "removed_handoff": (relative / "handoff.py").as_posix(),
    }


def git_hook_path(root, name):
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-path", f"hooks/{name}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise InstallError(f"cannot resolve Git hook path: {result.stderr.strip()}")
    path = Path(result.stdout.strip())
    if not path.is_absolute():
        path = root / path
    return Path(os.path.abspath(path))


def git_hook_launcher(relative_path):
    if relative_path.startswith("~/"):
        return f'#!/bin/sh\nexec "$HOME"/{shlex.quote(relative_path[2:])} "$@"\n'
    target = shlex.quote(relative_path)
    return (
        "#!/bin/sh\n"
        f'exec "$(git rev-parse --show-toplevel)"/{target} "$@"\n'
    )


def install_git_hook(root, relative_source):
    source = (
        Path(relative_source).expanduser()
        if relative_source.startswith("~/") else root / relative_source
    ).resolve()
    destination = git_hook_path(root, POST_COMMIT_HOOK)
    if not os.access(source, os.X_OK):
        raise InstallError(f"Git hook is not executable: {source}")
    launcher = git_hook_launcher(relative_source)
    if destination.exists() and not destination.is_symlink():
        managed = {
            git_hook_launcher(path).encode()
            for path in (
                relative_source,
                f"{PROJECT_SKILL_HOOKS}/{POST_COMMIT_HOOK}",
                f"~/{PROJECT_SKILL_HOOKS}/{POST_COMMIT_HOOK}",
            )
        }
        if destination.is_file() and destination.read_bytes() in managed:
            if destination.read_bytes() != launcher.encode():
                write(destination, launcher)
            destination.chmod(0o755)
            return destination
        raise InstallError(f"refusing to replace existing Git hook: {destination}")
    if destination.is_symlink():
        raise InstallError(f"refusing to replace existing Git hook: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    write(destination, launcher)
    destination.chmod(0o755)
    return destination


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


def remove_codex(config, event, commands):
    if event not in config["hooks"]:
        return
    groups = []
    for group in retained(
        config["hooks"][event], event, commands[0], commands[1:], True
    ):
        handlers = [
            handler
            for handler in group["hooks"]
            if handler.get("command") not in commands
        ]
        if handlers:
            groups.append({**group, "hooks": handlers})
    if groups:
        config["hooks"][event] = groups
    else:
        del config["hooks"][event]


def remove_cursor(config, event, commands):
    if event not in config["hooks"]:
        return
    entries = retained(
        config["hooks"][event], event, commands[0], commands[1:], False
    )
    if entries:
        config["hooks"][event] = entries
    else:
        del config["hooks"][event]


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
    git_sync = command_for(paths["git_sync_policy"])
    obsolete_file_size = [command_for(path) for path in OBSOLETE_FILE_SIZE_PATHS]
    obsolete_file_size.extend(
        command_for(f"{prefix}{PROJECT_SKILL_HOOKS}/file_size_hint.py")
        for prefix in ("", "~/")
    )
    obsolete_git_sync = [
        command_for(f"{prefix}{PROJECT_SKILL_HOOKS}/git_sync_policy.py")
        for prefix in ("", "~/")
    ]
    removed_handoff = [
        command_for(paths["removed_handoff"]),
        *(command_for(f"{prefix}{PROJECT_SKILL_HOOKS}/handoff.py") for prefix in ("", "~/")),
        *(command_for(path) for path in REMOVED_HANDOFF_PATHS),
    ]

    codex_path = root / CODEX_CONFIG
    codex = read_config(codex_path, {"description": "Project-local Codex hooks."})
    for event in ("PreToolUse", "PostToolUse"):
        install_codex(
            codex, event, file_size, FILE_SIZE_TIMEOUT, CODEX_EDIT_MATCHER,
            obsolete_file_size,
        )
    install_codex(
        codex, "PreToolUse", git_sync, GIT_SYNC_TIMEOUT, CODEX_SHELL_MATCHER, obsolete_git_sync
    )
    remove_codex(codex, "Stop", removed_handoff)

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
        "beforeShellExecution",
        {"command": git_sync, "timeout": GIT_SYNC_TIMEOUT},
        obsolete_git_sync,
    )
    remove_cursor(cursor, "stop", removed_handoff)

    post_commit = install_git_hook(root, paths["post_commit"])

    write(codex_path, json.dumps(codex, indent=2) + "\n")
    write(cursor_path, json.dumps(cursor, indent=2) + "\n")
    for relative in (*OBSOLETE_FILE_SIZE_PATHS, *REMOVED_HANDOFF_PATHS):
        (root / relative).unlink(missing_ok=True)

    return "\n".join(
        [
            f"WROTE: {CODEX_CONFIG}",
            f"WROTE: {CURSOR_CONFIG}",
            f"HOOKS: {paths['file_size_hint']}",
            f"HOOKS: {paths['git_sync_policy']}",
            f"GIT HOOK: {post_commit}",
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
