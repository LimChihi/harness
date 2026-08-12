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


def issue_view(root, repository, issue, fields):
    return json.loads(
        gh(
            root,
            "issue",
            "view",
            str(issue),
            "--repo",
            repository,
            "--json",
            ",".join(fields),
        )
    )


def claim(root, repository, issue, current):
    viewer = gh(root, "api", "user", "--jq", ".login")
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


def issue_ref(value, repository):
    owner = value.get("repository", {}).get("nameWithOwner", repository)
    prefix = "" if owner == repository else owner
    return f"{prefix}#{value['number']}"


def spec_report(root, repository, issue, sub_issues):
    ready = []
    blocked = []
    open_issues = [
        value for value in sub_issues["nodes"] if value["state"] == "OPEN"
    ]
    for value in open_issues:
        owner = value.get("repository", {}).get("nameWithOwner", repository)
        current = issue_view(root, owner, value["number"], ("blockedBy",))
        blockers = [
            blocker
            for blocker in current["blockedBy"]["nodes"]
            if blocker["state"] == "OPEN"
        ]
        if blockers:
            blocked.append((value, blockers))
        else:
            ready.append(value)

    lines = [f"SPEC {repository}#{issue}"]
    lines.append(
        "READY: "
        + (", ".join(issue_ref(value, repository) for value in ready) or "none")
    )
    if blocked:
        for value, blockers in blocked:
            dependencies = ", ".join(
                issue_ref(blocker, repository) for blocker in blockers
            )
            lines.append(f"BLOCKED: {issue_ref(value, repository)} by {dependencies}")
    else:
        lines.append("BLOCKED: none")
    lines.append(f"COMPLETE: {'yes' if not open_issues else 'no'}")
    return "\n".join(lines)


def ticket_report(root, repository, default, issue, branch, worktree, created, claimed):
    dirty = bool(git(worktree, "status", "--porcelain").stdout.strip())
    head = git(worktree, "rev-parse", "--short=12", "HEAD").stdout.strip()
    behind, ahead = git(
        worktree,
        "rev-list",
        "--left-right",
        "--count",
        f"origin/{default}...HEAD",
    ).stdout.split()
    pull_requests = json.loads(
        gh(
            root,
            "pr",
            "list",
            "--repo",
            repository,
            "--head",
            branch,
            "--state",
            "all",
            "--limit",
            "1",
            "--json",
            "number,state,url",
        )
    )

    lines = [f"TICKET {repository}#{issue}"]
    lines.append(f"BRANCH: {branch}")
    lines.append(f"WORKTREE: {worktree} ({'created' if created else 'recovered'})")
    lines.append(f"ASSIGNMENT: {'claimed' if claimed else 'already claimed'}")
    lines.append(
        f"STATE: {'dirty' if dirty else 'clean'}; HEAD {head}; "
        f"ahead {ahead}, behind {behind} vs origin/{default}"
    )
    if pull_requests:
        pull_request = pull_requests[0]
        lines.append(
            f"PR: #{pull_request['number']} {pull_request['state']} "
            f"{pull_request['url']}"
        )
    else:
        lines.append("PR: none")
    return "\n".join(lines)


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
    current = issue_view(
        root, repository, issue, ("state", "assignees", "subIssues")
    )
    if current["subIssues"]["totalCount"]:
        return spec_report(root, repository, issue, current["subIssues"])

    branch = f"task/{issue}"

    git(
        root,
        "fetch",
        "origin",
        f"+refs/heads/{default}:refs/remotes/origin/{default}",
    )
    git(root, "worktree", "prune")
    existing = checked_out_at(root, branch)
    if existing is not None:
        if not existing.is_dir():
            raise StartError(f"worktree is missing: {existing}")
        claimed = claim(root, repository, issue, current)
        return ticket_report(
            root, repository, default, issue, branch, existing, False, claimed
        )

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
        if remote.returncode == 0:
            git(
                root,
                "fetch",
                "origin",
                f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
            )

    claimed = claim(root, repository, issue, current)
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
    return ticket_report(
        root, repository, default, issue, branch, worktree, True, claimed
    )


def main():
    parser = argparse.ArgumentParser(
        description="Inspect a GitHub spec or prepare a ticket worktree."
    )
    parser.add_argument("issue", help="Issue number, with or without a leading #")
    arguments = parser.parse_args()
    match = re.fullmatch(r"#?([1-9][0-9]*)", arguments.issue)
    if match is None:
        raise StartError(f"invalid issue: {arguments.issue}")
    issue = int(match.group(1))
    print(start(issue))


if __name__ == "__main__":
    try:
        main()
    except (StartError, json.JSONDecodeError, KeyError) as error:
        print(f"imp start: {error}", file=sys.stderr)
        sys.exit(1)
