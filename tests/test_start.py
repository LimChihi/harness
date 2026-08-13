import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START = ROOT / "skills" / "implement" / "scripts" / "start.py"


def run(*arguments, cwd=None, env=None, check=True):
    return subprocess.run(
        arguments,
        cwd=cwd,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


class ImpStartTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="harness-start-"))
        self.repo = self.temp / "repo"
        self.remote = self.temp / "remote.git"
        run("git", "init", "--bare", "--initial-branch=trunk", str(self.remote))
        run("git", "init", "--initial-branch=trunk", str(self.repo))
        run("git", "config", "user.email", "agent@example.com", cwd=self.repo)
        run("git", "config", "user.name", "Agent", cwd=self.repo)
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        run("git", "add", "README.md", cwd=self.repo)
        run("git", "commit", "-m", "Initial", cwd=self.repo)
        run("git", "remote", "add", "origin", str(self.remote), cwd=self.repo)
        run("git", "push", "-u", "origin", "trunk", cwd=self.repo)

        self.state = self.temp / "gh-state.json"
        self.state.write_text(
            json.dumps({"issues": {}, "prs": {}}), encoding="utf-8"
        )
        fake_bin = self.temp / "bin"
        fake_bin.mkdir()
        fake_gh = fake_bin / "gh"
        fake_gh.write_text(
            """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

path = Path(os.environ["FAKE_GH_STATE"])
state = json.loads(path.read_text())
args = sys.argv[1:]

def issue(number):
    return state["issues"].setdefault(
        str(number),
        {"state": "OPEN", "assignees": [], "subIssues": [], "blockedBy": []},
    )

def link(number):
    current = issue(number)
    return {
        "number": int(number),
        "state": current["state"],
        "repository": {"nameWithOwner": "owner/project"},
    }

if args[:2] == ["repo", "view"]:
    print(json.dumps({
        "nameWithOwner": "owner/project",
        "defaultBranchRef": {"name": "trunk"},
    }))
elif args[:2] == ["api", "user"]:
    print("agent")
elif args[:2] == ["issue", "view"]:
    current = issue(args[2])
    fields = args[args.index("--json") + 1].split(",")
    result = {}
    for field in fields:
        if field == "assignees":
            result[field] = [{"login": value} for value in current[field]]
        elif field in ("subIssues", "blockedBy"):
            nodes = [link(number) for number in current[field]]
            result[field] = {"nodes": nodes, "totalCount": len(nodes)}
        else:
            result[field] = current[field]
    print(json.dumps(result))
elif args[:2] == ["issue", "edit"]:
    current = issue(args[2])
    if "--add-assignee" in args and "agent" not in current["assignees"]:
        current["assignees"].append("agent")
    if "--remove-assignee" in args and "agent" in current["assignees"]:
        current["assignees"].remove("agent")
    path.write_text(json.dumps(state))
elif args[:2] == ["pr", "list"]:
    branch = args[args.index("--head") + 1]
    print(json.dumps(state["prs"].get(branch, [])))
else:
    print(f"unexpected gh arguments: {args}", file=sys.stderr)
    sys.exit(1)
""",
            encoding="utf-8",
        )
        fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IXUSR)
        self.env = os.environ.copy()
        self.env["PATH"] = f"{fake_bin}{os.pathsep}{self.env['PATH']}"
        self.env["FAKE_GH_STATE"] = str(self.state)

    def tearDown(self):
        shutil.rmtree(self.temp)

    def start(self, issue):
        return run(
            "python3",
            str(START),
            str(issue),
            cwd=self.repo,
            env=self.env,
            check=False,
        )

    def update_issue(self, number, **values):
        state = json.loads(self.state.read_text(encoding="utf-8"))
        current = state["issues"].setdefault(
            str(number),
            {"state": "OPEN", "assignees": [], "subIssues": [], "blockedBy": []},
        )
        current.update(values)
        self.state.write_text(json.dumps(state), encoding="utf-8")

    def update_prs(self, branch, pull_requests):
        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["prs"][branch] = pull_requests
        self.state.write_text(json.dumps(state), encoding="utf-8")

    def assignments(self, issue):
        state = json.loads(self.state.read_text(encoding="utf-8"))
        return state["issues"].get(str(issue), {}).get("assignees", [])

    def report_value(self, result, label):
        prefix = f"{label}: "
        return next(
            line.removeprefix(prefix)
            for line in result.stdout.splitlines()
            if line.startswith(prefix)
        )

    def test_claims_and_reuses_a_ticket_worktree(self):
        first = self.start("#17")

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(first.stdout.startswith("TICKET owner/project#17\n"))
        self.assertEqual(self.report_value(first, "BRANCH"), "task/17")
        worktree = Path(self.report_value(first, "WORKTREE").removesuffix(" (created)"))
        self.assertEqual(self.report_value(first, "ASSIGNMENT"), "claimed")
        self.assertIn("clean; HEAD ", self.report_value(first, "STATE"))
        self.assertEqual(self.report_value(first, "PR"), "none")
        self.assertEqual(self.assignments(17), ["agent"])
        self.assertEqual(
            run("git", "branch", "--show-current", cwd=worktree).stdout.strip(),
            "task/17",
        )

        second = self.start(17)

        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(
            self.report_value(second, "WORKTREE"), f"{worktree} (recovered)"
        )
        self.assertEqual(self.report_value(second, "ASSIGNMENT"), "already claimed")

    def test_reports_a_spec_frontier_without_claiming_or_creating_a_worktree(self):
        self.update_issue(1, subIssues=[29, 30])
        self.update_issue(29)
        self.update_issue(30, blockedBy=[29])

        result = self.start(1)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "SPEC owner/project#1\n"
            "READY: #29\n"
            "BLOCKED: #30 by #29\n"
            "COMPLETE: no\n",
        )
        self.assertEqual(self.assignments(1), [])
        self.assertFalse((self.temp / ".worktrees" / "owner-project-1").exists())
        self.assertNotEqual(
            run(
                "git",
                "show-ref",
                "--verify",
                "--quiet",
                "refs/heads/task/1",
                cwd=self.repo,
                check=False,
            ).returncode,
            0,
        )

    def test_reports_a_completed_spec(self):
        self.update_issue(1, subIssues=[29, 30])
        self.update_issue(29, state="CLOSED")
        self.update_issue(30, state="CLOSED")

        result = self.start(1)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "SPEC owner/project#1\n"
            "READY: none\n"
            "BLOCKED: none\n"
            "COMPLETE: yes\n",
        )

    def test_reports_recovered_worktree_state(self):
        first = self.start(17)
        worktree = Path(
            self.report_value(first, "WORKTREE").removesuffix(" (created)")
        )
        (worktree / "ticket.txt").write_text("ticket\n", encoding="utf-8")
        run("git", "add", "ticket.txt", cwd=worktree)
        run("git", "commit", "-m", "Ticket", cwd=worktree)
        (worktree / "dirty.txt").write_text("dirty\n", encoding="utf-8")

        (self.repo / "base.txt").write_text("base\n", encoding="utf-8")
        run("git", "add", "base.txt", cwd=self.repo)
        run("git", "commit", "-m", "Base", cwd=self.repo)
        run("git", "push", "origin", "trunk", cwd=self.repo)
        self.update_prs(
            "task/17",
            [
                {
                    "number": 9,
                    "state": "OPEN",
                    "url": "https://github.com/owner/project/pull/9",
                }
            ],
        )

        result = self.start(17)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "dirty; HEAD ",
            self.report_value(result, "STATE"),
        )
        self.assertIn(
            "ahead 1, behind 1 vs origin/trunk",
            self.report_value(result, "STATE"),
        )
        self.assertEqual(
            self.report_value(result, "PR"),
            "#9 OPEN https://github.com/owner/project/pull/9",
        )

    def test_restores_a_remote_task_branch(self):
        run("git", "switch", "-c", "task/23", cwd=self.repo)
        (self.repo / "ticket.txt").write_text("remote branch\n", encoding="utf-8")
        run("git", "add", "ticket.txt", cwd=self.repo)
        run("git", "commit", "-m", "Ticket", cwd=self.repo)
        run("git", "push", "origin", "task/23", cwd=self.repo)
        run("git", "switch", "trunk", cwd=self.repo)
        run("git", "branch", "-D", "task/23", cwd=self.repo)

        result = self.start(23)

        self.assertEqual(result.returncode, 0, result.stderr)
        worktree = Path(
            self.report_value(result, "WORKTREE").removesuffix(" (created)")
        )
        self.assertEqual((worktree / "ticket.txt").read_text(), "remote branch\n")

    def test_refuses_a_ticket_assigned_to_someone_else(self):
        self.update_issue(31, assignees=["other"])

        result = self.start(31)

        self.assertEqual(result.returncode, 1)
        self.assertIn("assigned to other", result.stderr)
        self.assertNotEqual(
            run(
                "git",
                "show-ref",
                "--verify",
                "--quiet",
                "refs/heads/task/31",
                cwd=self.repo,
                check=False,
            ).returncode,
            0,
        )

    def test_rolls_back_claim_when_worktree_creation_fails(self):
        hook = self.repo / ".git" / "hooks" / "post-checkout"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)

        result = self.start(41)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.assignments(41), [])
        self.assertFalse((self.temp / ".worktrees" / "owner-project-41").exists())
        self.assertNotEqual(
            run(
                "git",
                "show-ref",
                "--verify",
                "--quiet",
                "refs/heads/task/41",
                cwd=self.repo,
                check=False,
            ).returncode,
            0,
        )


if __name__ == "__main__":
    unittest.main()
