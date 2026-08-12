import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START = ROOT / "skills" / "imp" / "scripts" / "start.py"


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
        self.temp = Path(tempfile.mkdtemp(prefix="harness-imp-"))
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
            json.dumps({"state": "OPEN", "assignees": []}), encoding="utf-8"
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
if args[:2] == ["repo", "view"]:
    print(json.dumps({"nameWithOwner": "owner/project", "defaultBranchRef": {"name": "trunk"}}))
elif args[:2] == ["api", "user"]:
    print("agent")
elif args[:2] == ["issue", "view"]:
    print(json.dumps({"state": state["state"], "assignees": [{"login": value} for value in state["assignees"]]}))
elif args[:2] == ["issue", "edit"]:
    if "--add-assignee" in args and "agent" not in state["assignees"]:
        state["assignees"].append("agent")
    if "--remove-assignee" in args and "agent" in state["assignees"]:
        state["assignees"].remove("agent")
    path.write_text(json.dumps(state))
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

    def assignments(self):
        return json.loads(self.state.read_text(encoding="utf-8"))["assignees"]

    def test_claims_and_reuses_a_ticket_worktree(self):
        first = self.start("#17")

        self.assertEqual(first.returncode, 0, first.stderr)
        created = json.loads(first.stdout)
        self.assertEqual(created["branch"], "task/17")
        self.assertTrue(created["created"])
        self.assertTrue(created["claimed"])
        self.assertEqual(self.assignments(), ["agent"])
        self.assertEqual(
            run("git", "branch", "--show-current", cwd=created["worktree"]).stdout.strip(),
            "task/17",
        )

        second = self.start(17)

        self.assertEqual(second.returncode, 0, second.stderr)
        reused = json.loads(second.stdout)
        self.assertEqual(reused["worktree"], created["worktree"])
        self.assertFalse(reused["created"])
        self.assertFalse(reused["claimed"])

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
        worktree = Path(json.loads(result.stdout)["worktree"])
        self.assertEqual((worktree / "ticket.txt").read_text(), "remote branch\n")

    def test_refuses_a_ticket_assigned_to_someone_else(self):
        self.state.write_text(
            json.dumps({"state": "OPEN", "assignees": ["other"]}), encoding="utf-8"
        )

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
        self.assertEqual(self.assignments(), [])
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
