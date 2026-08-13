import importlib.util
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "skills" / "implement" / "scripts" / "cleanup.py"
SPEC = importlib.util.spec_from_file_location("cleanup", MODULE)
cleanup_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cleanup_module)

FAKE_GH = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state = json.loads(Path(os.environ["FAKE_GH_STATE"]).read_text())
args = sys.argv[1:]

if args[:2] == ["repo", "view"]:
    print(json.dumps({"nameWithOwner": "owner/project"}))
elif args[:2] == ["pr", "list"]:
    branch = args[args.index("--head") + 1]
    print(json.dumps(state["prs"].get(branch, [])))
else:
    print(f"unexpected gh arguments: {args}", file=sys.stderr)
    sys.exit(1)
"""


def run(*arguments, cwd=None, env=None, check=True):
    return subprocess.run(
        arguments, cwd=cwd, env=env, check=check, capture_output=True, text=True
    )


class NetworkRetryTests(unittest.TestCase):
    def setUp(self):
        self.delay = cleanup_module.NETWORK_RETRY_SECONDS
        cleanup_module.NETWORK_RETRY_SECONDS = 0

    def tearDown(self):
        cleanup_module.NETWORK_RETRY_SECONDS = self.delay

    def test_gives_up_at_the_attempt_limit(self):
        attempts = []

        def call():
            attempts.append(1)
            raise cleanup_module.CleanupError("Connection closed by 20.205.243.166")

        with self.assertRaises(cleanup_module.CleanupError):
            cleanup_module.over_network(call)
        self.assertEqual(len(attempts), cleanup_module.NETWORK_ATTEMPTS)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="harness-cleanup-")).resolve()
        self.repo = self.temp / "repo"
        run("git", "init", "--initial-branch=main", str(self.repo))
        run("git", "config", "user.email", "agent@example.com", cwd=self.repo)
        run("git", "config", "user.name", "Agent", cwd=self.repo)
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        run("git", "add", "README.md", cwd=self.repo)
        run("git", "commit", "-m", "Initial", cwd=self.repo)

        self.state = self.temp / "gh-state.json"
        self.state.write_text(json.dumps({"prs": {}}), encoding="utf-8")
        fake_bin = self.temp / "bin"
        fake_bin.mkdir()
        fake_gh = fake_bin / "gh"
        fake_gh.write_text(FAKE_GH, encoding="utf-8")
        fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IXUSR)
        self.env = os.environ.copy()
        self.env["PATH"] = f"{fake_bin}{os.pathsep}{self.env['PATH']}"
        self.env["FAKE_GH_STATE"] = str(self.state)

    def tearDown(self):
        shutil.rmtree(self.temp)

    def worktree(self, issue):
        path = self.temp / f"worktree-{issue}"
        run("git", "worktree", "add", "-b", f"task/{issue}", str(path), cwd=self.repo)
        return path

    def set_pull_request(self, branch, number, state):
        value = json.loads(self.state.read_text(encoding="utf-8"))
        value["prs"][branch] = [{"number": number, "state": state}]
        self.state.write_text(json.dumps(value), encoding="utf-8")

    def cleanup(self, cwd=None):
        result = run(
            "python3",
            str(MODULE),
            "--repo",
            str(self.repo),
            cwd=cwd or self.temp,
            env=self.env,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_removes_a_worktree_whose_pull_request_merged(self):
        path = self.worktree(2)
        self.set_pull_request("task/2", 9, "MERGED")

        report = self.cleanup()

        self.assertIn(f"REMOVED: {path} task/2 PR #9", report)
        self.assertFalse(path.exists())
        self.assertNotIn(
            "task/2", run("git", "branch", "--list", cwd=self.repo).stdout
        )

    def test_keeps_a_worktree_whose_pull_request_is_open(self):
        path = self.worktree(3)
        self.set_pull_request("task/3", 10, "OPEN")

        report = self.cleanup()

        self.assertEqual(report.strip(), "REMOVED: none")
        self.assertTrue(path.exists())

    def test_keeps_a_merged_worktree_that_carries_uncommitted_changes(self):
        path = self.worktree(4)
        (path / "scratch.txt").write_text("work\n", encoding="utf-8")
        self.set_pull_request("task/4", 11, "MERGED")

        report = self.cleanup()

        self.assertIn("uncommitted changes", report)
        self.assertTrue(path.exists())

    def test_keeps_the_worktree_holding_the_current_directory(self):
        path = self.worktree(5)
        self.set_pull_request("task/5", 12, "MERGED")

        report = self.cleanup(cwd=path)

        self.assertIn("holds the current directory", report)
        self.assertTrue(path.exists())

    def test_runs_the_repository_hook_after_removing_a_worktree(self):
        path = self.worktree(6)
        self.set_pull_request("task/6", 13, "MERGED")
        hook = self.repo / ".agents/hooks/cleanup"
        hook.parent.mkdir(parents=True)
        hook.write_text("#!/bin/sh\necho pruned resources\n", encoding="utf-8")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)

        report = self.cleanup()

        self.assertIn(f"REMOVED: {path}", report)
        self.assertIn(".agents/hooks/cleanup: exit 0", report)
        self.assertIn("pruned resources", report)

    def test_leaves_the_repository_hook_alone_when_nothing_was_removed(self):
        self.worktree(7)
        self.set_pull_request("task/7", 14, "OPEN")
        hook = self.repo / ".agents/hooks/cleanup"
        hook.parent.mkdir(parents=True)
        hook.write_text("#!/bin/sh\necho pruned resources\n", encoding="utf-8")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)

        self.assertNotIn("pruned resources", self.cleanup())

    def test_never_removes_the_main_worktree(self):
        self.set_pull_request("main", 15, "MERGED")

        report = self.cleanup()

        self.assertEqual(report.strip(), "REMOVED: none")
        self.assertTrue((self.repo / "README.md").exists())


if __name__ == "__main__":
    unittest.main()
