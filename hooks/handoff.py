#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
from pathlib import Path


class HandoffError(Exception):
    pass


def run(arguments, cwd=None, allowed=(0,)):
    try:
        result = subprocess.run(
            arguments, cwd=cwd, check=False, capture_output=True, text=True
        )
    except OSError as error:
        raise HandoffError(str(error)) from error
    if result.returncode not in allowed:
        detail = result.stderr.strip() or result.stdout.strip()
        raise HandoffError(f"{' '.join(arguments)}: {detail}")
    return result


def git(root, *arguments, allowed=(0,)):
    return run(["git", *arguments], root, allowed)


def gh(root, *arguments):
    return run(["gh", *arguments], root).stdout.strip()


def repository_root(start):
    return Path(
        run(
            ["git", "-C", str(Path(start).resolve()), "rev-parse", "--show-toplevel"]
        ).stdout.strip()
    ).resolve()


def branch_name(root):
    result = git(root, "symbolic-ref", "--quiet", "--short", "HEAD", allowed=(0, 1))
    return result.stdout.strip() if result.returncode == 0 else None


def remote_commit(root, branch):
    result = git(
        root,
        "ls-remote",
        "--exit-code",
        "--heads",
        "origin",
        f"refs/heads/{branch}",
        allowed=(0, 2),
    )
    if result.returncode == 2:
        return None
    fields = result.stdout.split()
    if len(fields) != 2:
        raise HandoffError(f"invalid git ls-remote output for {branch}")
    return fields[0]


def pull_request(root, repository, branch):
    values = json.loads(
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
            "number,state,url,headRefOid,baseRefName",
        )
    )
    return values[0] if values else None


def collect_state(start):
    root = repository_root(start)
    metadata = json.loads(
        gh(root, "repo", "view", "--json", "nameWithOwner,defaultBranchRef")
    )
    repository = metadata["nameWithOwner"]
    default = metadata["defaultBranchRef"]["name"]
    branch = branch_name(root)
    head = git(root, "rev-parse", "HEAD").stdout.strip()
    behind, ahead = git(
        root,
        "rev-list",
        "--left-right",
        "--count",
        f"origin/{default}...HEAD",
    ).stdout.split()
    remote = remote_commit(root, branch) if branch is not None else None
    pull = pull_request(root, repository, branch) if branch is not None else None
    return {
        "repository": repository,
        "worktree": str(root),
        "branch": branch,
        "default": default,
        "head": head,
        "dirty": bool(git(root, "status", "--porcelain").stdout.strip()),
        "ahead": int(ahead),
        "behind": int(behind),
        "remote": remote,
        "pull_request": pull,
    }


def state_report(state):
    branch = state["branch"] or "detached"
    remote = state["remote"]
    if state["branch"] is None:
        remote_text = "not applicable"
    elif remote is None:
        remote_text = "unpublished"
    elif remote == state["head"]:
        remote_text = f"{remote[:12]} (at HEAD)"
    else:
        remote_text = f"{remote[:12]} (HEAD differs)"

    pull = state["pull_request"]
    if pull is None:
        pull_text = "none"
    else:
        pull_text = (
            f"#{pull['number']} {pull['state']} -> {pull['baseRefName']} "
            f"at {pull['headRefOid'][:12]} {pull['url']}"
        )

    return "\n".join(
        [
            f"REPOSITORY: {state['repository']}",
            f"WORKTREE: {state['worktree']}",
            f"BRANCH: {branch}",
            f"DEFAULT: {state['default']}",
            f"HEAD: {state['head'][:12]}",
            f"WORKTREE_STATE: {'dirty' if state['dirty'] else 'clean'}",
            f"DEFAULT_RELATION: ahead {state['ahead']}, behind {state['behind']} "
            f"vs origin/{state['default']}",
            f"REMOTE: {remote_text}",
            f"PR: {pull_text}",
        ]
    )


def is_ancestor(root, ancestor, descendant):
    return (
        git(
            root,
            "merge-base",
            "--is-ancestor",
            ancestor,
            descendant,
            allowed=(0, 1),
        ).returncode
        == 0
    )


def lifecycle_hint(state):
    branch = state["branch"]
    pull = state["pull_request"]
    if branch is None or branch == state["default"]:
        return None
    if pull is not None and pull["state"] == "MERGED":
        return None
    if state["dirty"]:
        return "Handoff incomplete: commit the working tree with git commit."
    if state["ahead"] == 0 and pull is None:
        return None
    if state["remote"] is None:
        return f"Handoff incomplete: publish {branch} with git push -u origin {branch}."
    if state["remote"] != state["head"]:
        if is_ancestor(Path(state["worktree"]), state["remote"], state["head"]):
            return "Handoff incomplete: publish HEAD with git push."
        return (
            f"Handoff incomplete: local {branch} and origin/{branch} have diverged; "
            "inspect both histories, reconcile them explicitly, and publish the result."
        )
    if pull is None:
        return (
            f"Handoff incomplete: open a pull request with gh pr create --base "
            f"{state['default']} --head {branch}."
        )
    if pull["state"] == "CLOSED":
        return (
            f"Handoff incomplete: PR #{pull['number']} was closed without merging; "
            "inspect it, then reopen it or create a replacement pull request."
        )
    if pull["baseRefName"] != state["default"]:
        return (
            f"Handoff incomplete: PR #{pull['number']} targets {pull['baseRefName']}; "
            f"open the delivery pull request against {state['default']}."
        )
    return None


def hook_cwd(payload):
    cwd = payload.get("cwd")
    if cwd:
        return cwd
    roots = payload.get("workspace_roots") or []
    if roots:
        return roots[0]
    raise HandoffError("missing cwd/workspace_roots")


def run_hook(payload):
    event = payload["hook_event_name"]
    if event not in {"Stop", "stop"}:
        raise HandoffError(f"unsupported hook event: {event}")
    status = payload.get("status")
    if status is not None and status != "completed":
        return
    hint = lifecycle_hint(collect_state(hook_cwd(payload)))
    if hint is None:
        return
    if event == "stop":
        print(json.dumps({"followup_message": hint}))
        return
    print(json.dumps({"decision": "block", "reason": hint}))


def main():
    parser = argparse.ArgumentParser(description="Inspect Git and GitHub handoff state.")
    subparsers = parser.add_subparsers(dest="command")
    state_parser = subparsers.add_parser("state")
    state_parser.add_argument("--repo", default=".")
    arguments = parser.parse_args()
    if arguments.command == "state":
        print(state_report(collect_state(arguments.repo)))
        return
    if arguments.command is not None:
        raise HandoffError(f"unsupported command: {arguments.command}")
    run_hook(json.load(sys.stdin))


if __name__ == "__main__":
    try:
        main()
    except (HandoffError, json.JSONDecodeError, KeyError, ValueError) as error:
        print(f"harness handoff: {error}", file=sys.stderr)
        sys.exit(1)
