#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


REPOSITORY_HOOK = ".agents/hooks/cleanup"
NETWORK_ATTEMPTS = 3
NETWORK_RETRY_SECONDS = 2


class CleanupError(Exception):
    pass


def over_network(call):
    """A sweep spans many worktrees; one dropped connection should not end it."""
    for attempt in range(1, NETWORK_ATTEMPTS + 1):
        try:
            return call()
        except CleanupError:
            if attempt == NETWORK_ATTEMPTS:
                raise
            time.sleep(NETWORK_RETRY_SECONDS)


def run(arguments, cwd=None, allowed=(0,)):
    try:
        result = subprocess.run(
            arguments, cwd=cwd, check=False, capture_output=True, text=True
        )
    except OSError as error:
        raise CleanupError(str(error)) from error
    if result.returncode not in allowed:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CleanupError(f"{' '.join(arguments)}: {detail}")
    return result


def repository_root(start):
    return Path(
        run(["git", "-C", str(Path(start).resolve()), "rev-parse", "--show-toplevel"])
        .stdout.strip()
    ).resolve()


def main_worktree(root):
    common = Path(
        run(
            ["git", "-C", str(root), "rev-parse", "--path-format=absolute",
             "--git-common-dir"]
        ).stdout.strip()
    ).resolve()
    return common.parent if common.name == ".git" else root


def worktrees(root):
    values = []
    current = {}
    for line in run(["git", "-C", str(root), "worktree", "list", "--porcelain"]).stdout.splitlines():
        if not line:
            if current:
                values.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current = {"path": Path(value).resolve(), "branch": None}
        elif key == "branch":
            current["branch"] = value.removeprefix("refs/heads/")
    if current:
        values.append(current)
    return values


def repository_name(root):
    return json.loads(
        over_network(
            lambda: run(["gh", "repo", "view", "--json", "nameWithOwner"], cwd=root)
        ).stdout
    )["nameWithOwner"]


def merged_pull_request(root, repository, branch):
    values = json.loads(
        over_network(
            lambda: run(
                [
                    "gh", "pr", "list", "--repo", repository, "--head", branch,
                    "--state", "all", "--limit", "1", "--json", "number,state",
                ],
                cwd=root,
            )
        ).stdout
    )
    if not values or values[0]["state"].upper() != "MERGED":
        return None
    return values[0]["number"]


def is_dirty(path):
    return bool(run(["git", "-C", str(path), "status", "--porcelain"]).stdout.strip())


def remove(primary, worktree, branch):
    run(["git", "-C", str(primary), "worktree", "remove", str(worktree["path"])])
    run(["git", "-C", str(primary), "branch", "-D", branch], allowed=(0, 1))


def repository_hook(primary):
    hook = primary / REPOSITORY_HOOK
    if not hook.is_file():
        return None
    result = run([str(hook)], cwd=primary, allowed=(0, 1))
    detail = (result.stdout.strip() + "\n" + result.stderr.strip()).strip()
    return f"{REPOSITORY_HOOK}: exit {result.returncode}" + (
        f"\n{detail}" if detail else ""
    )


def cleanup(start):
    root = repository_root(start)
    primary = main_worktree(root)
    repository = repository_name(root)
    here = Path.cwd().resolve()

    lines = []
    removed = 0
    for worktree in worktrees(primary):
        branch = worktree["branch"]
        if worktree["path"] == primary or branch is None:
            continue
        number = merged_pull_request(primary, repository, branch)
        if number is None:
            continue
        if here == worktree["path"] or worktree["path"] in here.parents:
            lines.append(
                f"KEPT: {worktree['path']} PR #{number} merged, "
                "but it holds the current directory; run cleanup from elsewhere"
            )
            continue
        if is_dirty(worktree["path"]):
            lines.append(
                f"KEPT: {worktree['path']} PR #{number} merged, "
                "but the worktree carries uncommitted changes"
            )
            continue
        remove(primary, worktree, branch)
        removed += 1
        lines.append(f"REMOVED: {worktree['path']} {branch} PR #{number}")

    run(["git", "-C", str(primary), "worktree", "prune"])
    if removed:
        hook = repository_hook(primary)
        if hook is not None:
            lines.append(hook)

    if not lines:
        lines.append("REMOVED: none")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Remove worktrees whose pull request merged."
    )
    parser.add_argument("--repo", default=".")
    arguments = parser.parse_args()
    print(cleanup(arguments.repo))


if __name__ == "__main__":
    try:
        main()
    except (CleanupError, json.JSONDecodeError, KeyError, ValueError) as error:
        print(f"harness cleanup: {error}", file=sys.stderr)
        sys.exit(1)
