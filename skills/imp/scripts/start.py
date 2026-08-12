#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


class StartError(Exception):
    pass


def run(arguments, cwd=None, allowed=(0,)):
    try:
        result = subprocess.run(
            arguments, cwd=cwd, check=False, capture_output=True, text=True
        )
    except OSError as error:
        raise StartError(str(error)) from error
    if result.returncode not in allowed:
        detail = result.stderr.strip() or result.stdout.strip()
        raise StartError(f"{' '.join(arguments)}: {detail}")
    return result


def git(root, *arguments, allowed=(0,)):
    return run(["git", *arguments], root, allowed)


def gh(root, *arguments):
    return run(["gh", *arguments], root).stdout.strip()


def branch_exists(root, branch):
    return (
        git(
            root,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
            allowed=(0, 1),
        ).returncode
        == 0
    )


def checked_out_at(root, branch):
    expected = f"refs/heads/{branch}"
    for block in git(root, "worktree", "list", "--porcelain").stdout.split("\n\n"):
        record = dict(line.partition(" ")[::2] for line in block.splitlines())
        if record.get("branch") == expected:
            return Path(record["worktree"]).resolve()
    return None


def claim(root, repository, issue):
    viewer = gh(root, "api", "user", "--jq", ".login")
    current = json.loads(
        gh(
            root,
            "issue",
            "view",
            str(issue),
            "--repo",
            repository,
            "--json",
            "state,assignees",
        )
    )
    if current["state"] != "OPEN":
        raise StartError(f"issue #{issue} is not open")
    assignees = [value["login"] for value in current["assignees"]]
    if viewer in assignees:
        return False
    if assignees:
        raise StartError(f"issue #{issue} is assigned to {', '.join(assignees)}")
    gh(
        root,
        "issue",
        "edit",
        str(issue),
        "--repo",
        repository,
        "--add-assignee",
        "@me",
    )
    return True


def start(issue):
    root = Path(
        run(["git", "rev-parse", "--show-toplevel"]).stdout.strip()
    ).resolve()
    common = Path(
        git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        .stdout.strip()
    ).resolve()
    primary = common.parent if common.name == ".git" else root
    metadata = json.loads(
        gh(root, "repo", "view", "--json", "nameWithOwner,defaultBranchRef")
    )
    repository = metadata["nameWithOwner"]
    default = metadata["defaultBranchRef"]["name"]
    branch = f"task/{issue}"

    git(root, "worktree", "prune")
    existing = checked_out_at(root, branch)
    if existing is not None:
        if not existing.is_dir():
            raise StartError(f"worktree is missing: {existing}")
        claimed = claim(root, repository, issue)
        return repository, branch, existing, False, claimed

    worktree = (
        primary.parent / ".worktrees" / f"{repository.replace('/', '-')}-{issue}"
    ).resolve()
    if worktree.exists():
        raise StartError(f"worktree path already exists: {worktree}")

    create_branch = not branch_exists(root, branch)
    source = branch
    if create_branch:
        remote = git(
            root,
            "ls-remote",
            "--exit-code",
            "--heads",
            "origin",
            f"refs/heads/{branch}",
            allowed=(0, 2),
        )
        source = f"origin/{branch}" if remote.returncode == 0 else f"origin/{default}"
        source_branch = branch if remote.returncode == 0 else default
        git(
            root,
            "fetch",
            "origin",
            f"+refs/heads/{source_branch}:refs/remotes/origin/{source_branch}",
        )

    claimed = claim(root, repository, issue)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    try:
        arguments = ["worktree", "add"]
        if create_branch:
            arguments.extend(["-b", branch])
        git(root, *arguments, str(worktree), source)
    except StartError:
        git(root, "worktree", "remove", "--force", str(worktree), allowed=(0, 128))
        if create_branch and branch_exists(root, branch):
            git(root, "branch", "-D", branch, allowed=(0, 1))
        if claimed:
            gh(
                root,
                "issue",
                "edit",
                str(issue),
                "--repo",
                repository,
                "--remove-assignee",
                "@me",
            )
        raise
    return repository, branch, worktree, True, claimed


def main():
    parser = argparse.ArgumentParser(
        description="Claim a GitHub issue and prepare its task worktree."
    )
    parser.add_argument("issue", help="Issue number, with or without a leading #")
    arguments = parser.parse_args()
    match = re.fullmatch(r"#?([1-9][0-9]*)", arguments.issue)
    if match is None:
        raise StartError(f"invalid issue: {arguments.issue}")
    issue = int(match.group(1))
    repository, branch, worktree, created, claimed = start(issue)
    print(
        json.dumps(
            {
                "repository": repository,
                "issue": issue,
                "branch": branch,
                "worktree": str(worktree),
                "created": created,
                "claimed": claimed,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (StartError, json.JSONDecodeError, KeyError) as error:
        print(f"imp start: {error}", file=sys.stderr)
        sys.exit(1)
