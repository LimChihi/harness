import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "harness.js"
HOOK = ROOT / "hooks" / "handoff.py"


def run(*arguments, cwd=None, env=None, check=True, input=None):
    return subprocess.run(
        arguments,
        cwd=cwd,
        env=env,
        check=check,
        input=input,
        capture_output=True,
        text=True,
    )


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="harness-handoff-"))
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
        self.state.write_text(json.dumps({"prs": {}}), encoding="utf-8")
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
    print(json.dumps({
        "nameWithOwner": "owner/project",
        "defaultBranchRef": {"name": "trunk"},
    }))
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

    def create_task_commit(self):
        run("git", "switch", "-c", "task/2", cwd=self.repo)
        (self.repo / "ticket.txt").write_text("ticket\n", encoding="utf-8")
        run("git", "add", "ticket.txt", cwd=self.repo)
        run("git", "commit", "-m", "Ticket", cwd=self.repo)

    def hook(self, payload=None):
        return run(
            "python3",
            str(HOOK),
            cwd=self.repo,
            env=self.env,
            check=False,
            input=json.dumps(
                payload
                if payload is not None
                else {"hook_event_name": "Stop", "cwd": str(self.repo)}
            ),
        )

    def cursor_payload(self, status="completed"):
        return {
            "hook_event_name": "stop",
            "status": status,
            "loop_count": 0,
            "workspace_roots": [str(self.repo)],
        }

    def set_pull_request(self, pr_state="OPEN", base="trunk"):
        state = json.loads(self.state.read_text(encoding="utf-8"))
        head = run("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip()
        state["prs"]["task/2"] = [
            {
                "number": 9,
                "state": pr_state,
                "url": "https://github.com/owner/project/pull/9",
                "headRefOid": head,
                "baseRefName": base,
            }
        ]
        self.state.write_text(json.dumps(state), encoding="utf-8")

    def test_state_command_reports_git_and_github_facts(self):
        self.create_task_commit()

        result = run(
            "node",
            str(CLI),
            "state",
            "--repo",
            str(self.repo),
            cwd=self.repo,
            env=self.env,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("REPOSITORY: owner/project\n", result.stdout)
        self.assertIn("BRANCH: task/2\n", result.stdout)
        self.assertIn("WORKTREE_STATE: clean\n", result.stdout)
        self.assertIn("DEFAULT_RELATION: ahead 1, behind 0 vs origin/trunk\n", result.stdout)
        self.assertIn("REMOTE: unpublished\n", result.stdout)
        self.assertTrue(result.stdout.endswith("PR: none\n"))

    def test_stop_guides_commit_push_and_pull_request(self):
        run("git", "switch", "-c", "task/2", cwd=self.repo)
        (self.repo / "ticket.txt").write_text("ticket\n", encoding="utf-8")

        dirty = self.hook()
        self.assertEqual(dirty.returncode, 0, dirty.stderr)
        self.assertEqual(
            json.loads(dirty.stdout),
            {
                "decision": "block",
                "reason": "Handoff incomplete: commit the working tree with git commit.",
            },
        )

        run("git", "add", "ticket.txt", cwd=self.repo)
        run("git", "commit", "-m", "Ticket", cwd=self.repo)
        unpublished = self.hook()
        self.assertIn("git push -u origin task/2", unpublished.stdout)

        run("git", "push", "-u", "origin", "task/2", cwd=self.repo)
        published = self.hook()
        self.assertIn("gh pr create --base trunk --head task/2", published.stdout)

        self.set_pull_request()
        opened = self.hook()
        self.assertEqual(opened.returncode, 0, opened.stderr)
        self.assertEqual(opened.stdout, "")

    def test_stop_is_silent_on_the_default_branch(self):
        result = self.hook()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_stop_blocks_closed_unmerged_pull_request(self):
        self.create_task_commit()
        run("git", "push", "-u", "origin", "task/2", cwd=self.repo)
        self.set_pull_request(pr_state="CLOSED")

        result = self.hook()

        self.assertIn("PR #9 was closed without merging", result.stdout)
        self.assertIn("reopen it or create a replacement", result.stdout)

    def test_stop_blocks_diverged_local_and_remote_histories(self):
        self.create_task_commit()
        run("git", "push", "-u", "origin", "task/2", cwd=self.repo)
        remote_head = run("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip()
        run("git", "reset", "--hard", "HEAD^", cwd=self.repo)
        (self.repo / "replacement.txt").write_text("replacement\n", encoding="utf-8")
        run("git", "add", "replacement.txt", cwd=self.repo)
        run("git", "commit", "-m", "Replacement", cwd=self.repo)

        result = self.hook()

        self.assertNotEqual(
            run("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip(), remote_head
        )
        self.assertIn("local task/2 and origin/task/2 have diverged", result.stdout)
        self.assertIn("reconcile them explicitly", result.stdout)

    def test_cursor_stop_returns_a_followup_message_from_workspace_roots(self):
        self.create_task_commit()
        run("git", "push", "-u", "origin", "task/2", cwd=self.repo)

        result = self.hook(self.cursor_payload())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "followup_message": (
                    "Handoff incomplete: open a pull request with gh pr create "
                    "--base trunk --head task/2."
                )
            },
        )

    def test_stop_leaves_an_open_pull_request_to_the_delivery_loop(self):
        self.create_task_commit()
        run("git", "push", "-u", "origin", "task/2", cwd=self.repo)
        self.set_pull_request()

        result = self.hook()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_cursor_stop_is_silent_when_the_turn_did_not_complete(self):
        self.create_task_commit()

        result = self.hook(self.cursor_payload(status="aborted"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_stop_requires_pull_request_to_target_default_branch(self):
        self.create_task_commit()
        run("git", "push", "-u", "origin", "task/2", cwd=self.repo)
        self.set_pull_request(base="staging")

        result = self.hook()

        self.assertIn("PR #9 targets staging", result.stdout)
        self.assertIn("against trunk", result.stdout)


if __name__ == "__main__":
    unittest.main()
