#!/usr/bin/env python3
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


FILE_MARKER = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+)$")
MOVE_MARKER = re.compile(r"^\*\*\* Move to: (.+)$")
IGNORED_FILE_SUFFIXES = frozenset({".lock"})
MAX_UNPROMPTED_GROWTH = 30
SNAPSHOT_VERSION = 1


def edited_files(command):
    files = []
    kind = None
    source = None
    target = None

    def finish_section():
        if kind is not None:
            files.append((source, target))

    for line in command.splitlines():
        file_match = FILE_MARKER.fullmatch(line)
        if file_match:
            finish_section()
            kind = file_match.group(1)
            path = file_match.group(2)
            source = None if kind == "Add" else path
            target = None if kind == "Delete" else path
            continue

        move_match = MOVE_MARKER.fullmatch(line)
        if move_match:
            if kind != "Update":
                raise ValueError("Move to must follow an Update File section")
            target = move_match.group(1)

    finish_section()
    return files


def repository_root(payload):
    cwd = Path(payload["cwd"]).resolve()
    result = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"failed to resolve Git root: {result.stderr.strip()}")
    return Path(result.stdout.strip()).resolve()


def repository_path(root, cwd, value):
    path = Path(value)
    if not path.is_absolute():
        path = cwd / path
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def file_line_count(path):
    if not path.is_file():
        return None
    with path.open("rb") as file:
        return sum(1 for _ in file)


def is_ignored_file(path):
    return Path(path).suffix.casefold() in IGNORED_FILE_SUFFIXES


def capture_line_counts(payload):
    root = repository_root(payload)
    cwd = Path(payload["cwd"]).resolve()
    counts = {}
    for source, target in edited_files(payload["tool_input"]["command"]):
        if target is None or is_ignored_file(target):
            continue
        for edited_path in (source, target):
            if edited_path is None:
                continue
            path = repository_path(root, cwd, edited_path)
            if path is not None and str(path) not in counts:
                counts[str(path)] = file_line_count(path)
    return counts


def hint_for(path, line_count):
    count = f"{line_count:,}"
    if line_count > 1400:
        return (
            f"{path}: {count} lines (>1400). Stop growing this file; "
            "split it first unless generated or data-only."
        )
    if line_count > 1200:
        return (
            f"{path}: {count} lines (>1200). "
            "Extract a coherent responsibility before growing it."
        )
    if line_count > 800:
        return (
            f"{path}: {count} lines (>800). "
            "Check responsibility before adding more code."
        )
    return None


def collect_hints(payload, before_counts):
    root = repository_root(payload)
    cwd = Path(payload["cwd"]).resolve()
    hints = []
    visited = set()

    for source, target in edited_files(payload["tool_input"]["command"]):
        if target is None or is_ignored_file(target):
            continue
        path = repository_path(root, cwd, target)
        if path is None or path in visited:
            continue
        visited.add(path)

        before_path = repository_path(root, cwd, source or target)
        if before_path is None or str(before_path) not in before_counts:
            raise ValueError(f"missing pre-edit line count for {target}")
        before_count = before_counts[str(before_path)] or 0
        line_count = file_line_count(path)
        if line_count is None or line_count - before_count <= MAX_UNPROMPTED_GROWTH:
            continue

        hint = hint_for(path.relative_to(root).as_posix(), line_count)
        if hint:
            hints.append((line_count, hint))

    return [hint for _, hint in sorted(hints, reverse=True)]


def snapshot_path(payload):
    root = repository_root(payload)
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"failed to resolve Git common dir: {result.stderr.strip()}")
    identity = f"{payload['session_id']}\0{payload['tool_use_id']}".encode()
    name = hashlib.sha256(identity).hexdigest()
    return Path(result.stdout.strip()) / "harness/hooks/file-size-hint" / f"{name}.json"


def command_digest(payload):
    command = payload["tool_input"]["command"].encode()
    return hashlib.sha256(command).hexdigest()


def write_snapshot(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "version": SNAPSHOT_VERSION,
        "cwd": str(Path(payload["cwd"]).resolve()),
        "command": command_digest(payload),
        "line_counts": capture_line_counts(payload),
    }
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}."
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_snapshot(path, payload):
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        value.get("version") != SNAPSHOT_VERSION
        or value.get("cwd") != str(Path(payload["cwd"]).resolve())
        or value.get("command") != command_digest(payload)
        or not isinstance(value.get("line_counts"), dict)
    ):
        raise ValueError(f"invalid file-size snapshot: {path}")
    return value["line_counts"]


def post_tool_output(hints):
    if not hints:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "\n".join(hints),
        }
    }


def main():
    payload = json.load(sys.stdin)
    path = snapshot_path(payload)
    event = payload["hook_event_name"]
    if event == "PreToolUse":
        write_snapshot(path, payload)
        return
    if event != "PostToolUse":
        raise ValueError(f"unsupported hook event: {event}")

    before_counts = read_snapshot(path, payload)
    try:
        output = post_tool_output(collect_hints(payload, before_counts))
    finally:
        path.unlink()
    if output is not None:
        print(json.dumps(output))


if __name__ == "__main__":
    main()
