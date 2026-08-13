#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path


POLL_SECONDS = 30
TIMEOUT_SECONDS = 25 * 60
LOG_TAIL_LINES = 60
FAILED_CONCLUSIONS = frozenset(
    {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"}
)
JOB_URL = re.compile(r"/actions/runs/\d+/job/(\d+)")
THREAD_QUERY = """
query($owner:String!,$name:String!,$number:Int!){
  viewer{login}
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      reviewThreads(first:100){
        nodes{
          id
          isResolved
          isOutdated
          path
          line
          comments(first:50){nodes{author{login} body}}
        }
      }
    }
  }
}
"""
RESOLVE_REFERENCE = (
    "Resolve a thread with:\n"
    "  gh api graphql -f query='mutation($id:ID!){"
    "resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' -f id=<THREAD>"
)


class DeliveryError(Exception):
    pass


def run(arguments, cwd=None, allowed=(0,)):
    try:
        result = subprocess.run(
            arguments, cwd=cwd, check=False, capture_output=True, text=True
        )
    except OSError as error:
        raise DeliveryError(str(error)) from error
    if result.returncode not in allowed:
        detail = result.stderr.strip() or result.stdout.strip()
        raise DeliveryError(f"{' '.join(arguments)}: {detail}")
    return result


def repository_root(start):
    return Path(
        run(["git", "-C", str(Path(start).resolve()), "rev-parse", "--show-toplevel"])
        .stdout.strip()
    ).resolve()


def branch_name(root):
    result = run(
        ["git", "-C", str(root), "symbolic-ref", "--quiet", "--short", "HEAD"],
        allowed=(0, 1),
    )
    if result.returncode != 0:
        raise DeliveryError("HEAD is detached; check out the delivery branch")
    return result.stdout.strip()


def repository_name(root):
    return json.loads(
        run(["gh", "repo", "view", "--json", "nameWithOwner"], cwd=root).stdout
    )["nameWithOwner"]


def pull_request(root, repository, branch):
    values = json.loads(
        run(
            [
                "gh",
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
                "number",
            ],
            cwd=root,
        ).stdout
    )
    return values[0]["number"] if values else None


def pull_request_facts(root, repository, number):
    return json.loads(
        run(
            [
                "gh",
                "pr",
                "view",
                str(number),
                "--repo",
                repository,
                "--json",
                "number,state,isDraft,mergeable,baseRefName,headRefOid,url,"
                "statusCheckRollup",
            ],
            cwd=root,
        ).stdout
    )


def review_threads(root, repository, number):
    owner, name = repository.split("/", 1)
    value = json.loads(
        run(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={THREAD_QUERY}",
                "-f",
                f"owner={owner}",
                "-f",
                f"name={name}",
                "-F",
                f"number={number}",
            ],
            cwd=root,
        ).stdout
    )["data"]
    viewer = value["viewer"]["login"]
    threads = []
    for node in value["repository"]["pullRequest"]["reviewThreads"]["nodes"]:
        if node["isResolved"]:
            continue
        comments = node["comments"]["nodes"]
        threads.append(
            {
                "id": node["id"],
                "path": node["path"],
                "line": node["line"],
                "outdated": node["isOutdated"],
                "author": comments[0]["author"]["login"] if comments else "unknown",
                "body": comments[0]["body"] if comments else "",
                "answered": any(
                    (comment["author"] or {}).get("login") == viewer
                    for comment in comments[1:]
                ),
            }
        )
    return threads


def check_name(check):
    return check.get("name") or check.get("context")


def latest_checks(rollup):
    """The rollup carries one entry per run, so keep the newest run of each name."""
    newest = {}
    for check in rollup or []:
        name = check_name(check)
        if name is None:
            continue
        started = check.get("startedAt") or check.get("completedAt") or ""
        if name not in newest or started >= newest[name][0]:
            newest[name] = (started, check)
    return [check for _, check in newest.values()]


def check_conclusion(check):
    value = check.get("conclusion") or check.get("state") or ""
    return value.upper()


def is_pending(check):
    status = (check.get("status") or "").upper()
    if status:
        return status != "COMPLETED"
    return check_conclusion(check) in {"PENDING", "EXPECTED"}


def failed_checks(checks):
    return [
        check
        for check in checks
        if not is_pending(check) and check_conclusion(check) in FAILED_CONCLUSIONS
    ]


def pending_checks(checks):
    return [check for check in checks if is_pending(check)]


def failure_log(root, check):
    url = check.get("detailsUrl") or check.get("targetUrl") or ""
    match = JOB_URL.search(url)
    if match is None:
        return None
    result = run(
        ["gh", "run", "view", "--job", match.group(1), "--log-failed"],
        cwd=root,
        allowed=(0, 1),
    )
    if result.returncode != 0:
        return f"(log unavailable: {result.stderr.strip()})"
    lines = result.stdout.splitlines()
    return "\n".join(lines[-LOG_TAIL_LINES:])


def observe(root, repository, number):
    facts = pull_request_facts(root, repository, number)
    checks = latest_checks(facts.get("statusCheckRollup"))
    state = facts["state"].upper()
    threads = [] if state != "OPEN" else review_threads(root, repository, number)
    failures = failed_checks(checks)

    if state == "MERGED":
        status = "MERGED"
    elif state == "CLOSED":
        status = "CLOSED"
    elif (facts.get("mergeable") or "").upper() == "CONFLICTING":
        status = "CONFLICT"
    elif failures:
        status = "CHECK_FAILURE"
    elif threads:
        status = "THREADS_UNRESOLVED"
    elif pending_checks(checks):
        status = "PENDING"
    else:
        status = "READY"

    return {
        "status": status,
        "facts": facts,
        "checks": checks,
        "failures": failures,
        "threads": threads,
    }


def report(root, observation):
    facts = observation["facts"]
    lines = [
        f"PR: #{facts['number']} {facts['state']} -> {facts['baseRefName']} "
        f"at {facts['headRefOid'][:12]} {facts['url']}",
        f"STATUS: {observation['status']}",
    ]

    pending = pending_checks(observation["checks"])
    if pending:
        lines.append(
            "PENDING_CHECKS: " + ", ".join(sorted(check_name(c) for c in pending))
        )

    for check in observation["failures"]:
        lines.append(
            f"FAILED_CHECK: {check_name(check)} {check_conclusion(check)} "
            f"{check.get('detailsUrl') or check.get('targetUrl') or ''}"
        )
        log = failure_log(root, check)
        if log:
            lines.append(f"LOG_TAIL:\n{log}")

    for thread in observation["threads"]:
        location = thread["path"]
        if thread["line"] is not None:
            location = f"{location}:{thread['line']}"
        marks = " outdated" if thread["outdated"] else ""
        marks += " answered-not-resolved" if thread["answered"] else " unanswered"
        lines.append(
            f"UNRESOLVED_THREAD: {thread['id']} {location} "
            f"by {thread['author']}{marks}\n{thread['body'].strip()}"
        )

    if observation["threads"]:
        lines.append(RESOLVE_REFERENCE)

    return "\n".join(lines)


def await_pull_request(start, timeout, interval):
    root = repository_root(start)
    repository = repository_name(root)
    branch = branch_name(root)
    number = pull_request(root, repository, branch)
    if number is None:
        return f"BRANCH: {branch}\nSTATUS: NO_PULL_REQUEST"

    deadline = time.monotonic() + timeout
    while True:
        observation = observe(root, repository, number)
        if observation["status"] != "PENDING":
            return report(root, observation)
        if time.monotonic() >= deadline:
            observation["status"] = "TIMEOUT"
            return report(root, observation)
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(
        description="Wait for a pull request to need its author."
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--timeout", type=float, default=TIMEOUT_SECONDS)
    parser.add_argument("--interval", type=float, default=POLL_SECONDS)
    arguments = parser.parse_args()
    print(await_pull_request(arguments.repo, arguments.timeout, arguments.interval))


if __name__ == "__main__":
    try:
        main()
    except (DeliveryError, json.JSONDecodeError, KeyError, ValueError) as error:
        print(f"harness await: {error}", file=sys.stderr)
        sys.exit(1)
