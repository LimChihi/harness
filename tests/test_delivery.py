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
MODULE = ROOT / "hooks" / "delivery.py"
SPEC = importlib.util.spec_from_file_location("delivery", MODULE)
delivery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(delivery)

FAKE_GH = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

path = Path(os.environ["FAKE_GH_STATE"])
state = json.loads(path.read_text())
args = sys.argv[1:]

if args[:2] == ["pr", "view"] and state.get("fail", 0) > 0:
    state["fail"] -= 1
    path.write_text(json.dumps(state))
    print("Connection closed by 20.205.243.166 port 22", file=sys.stderr)
    sys.exit(1)

if args[:2] == ["repo", "view"]:
    print(json.dumps({"nameWithOwner": "owner/project"}))
elif args[:2] == ["pr", "list"]:
    print(json.dumps(state["list"]))
elif args[:2] == ["pr", "view"]:
    print(json.dumps(state["pull_request"]))
elif args[:2] == ["api", "graphql"]:
    print(json.dumps({"data": state["graphql"]}))
elif args[:2] == ["run", "view"]:
    print(state["log"])
else:
    print(f"unexpected gh arguments: {args}", file=sys.stderr)
    sys.exit(1)
"""


def check(name, conclusion, status="COMPLETED", started="2026-01-01T00:00:00Z"):
    return {
        "__typename": "CheckRun",
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "startedAt": started,
        "detailsUrl": "https://github.com/owner/project/actions/runs/1/job/77",
    }


def thread(identifier, resolved=False, comments=None):
    return {
        "id": identifier,
        "isResolved": resolved,
        "isOutdated": False,
        "path": "src/main.py",
        "line": 12,
        "comments": {"nodes": comments or [{"author": {"login": "reviewer"}, "body": "fix this"}]},
    }


class CheckSelectionTests(unittest.TestCase):
    def test_keeps_the_newest_run_of_each_check_name(self):
        checks = delivery.latest_checks(
            [
                check("Integration", "FAILURE", started="2026-01-01T00:00:00Z"),
                check("Integration", "SUCCESS", started="2026-01-02T00:00:00Z"),
                check("Review", "SUCCESS", started="2026-01-02T00:00:00Z"),
            ]
        )

        self.assertEqual(
            sorted((delivery.check_name(c), c["conclusion"]) for c in checks),
            [("Integration", "SUCCESS"), ("Review", "SUCCESS")],
        )
        self.assertEqual(delivery.failed_checks(checks), [])

    def test_skipped_and_neutral_conclusions_are_not_failures(self):
        checks = [check("A", "SKIPPED"), check("B", "NEUTRAL"), check("C", "SUCCESS")]

        self.assertEqual(delivery.failed_checks(checks), [])

    def test_every_failure_conclusion_counts(self):
        for conclusion in ("FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED"):
            with self.subTest(conclusion=conclusion):
                self.assertEqual(
                    len(delivery.failed_checks([check("A", conclusion)])), 1
                )

    def test_incomplete_checks_are_pending(self):
        checks = [check("A", None, status="IN_PROGRESS"), check("B", "SUCCESS")]

        self.assertEqual(len(delivery.pending_checks(checks)), 1)
        self.assertEqual(delivery.failed_checks(checks), [])


class ObservationTests(unittest.TestCase):
    def observe(self, state, mergeable="MERGEABLE", checks=(), threads=()):
        facts = {
            "number": 9,
            "state": state,
            "mergeable": mergeable,
            "baseRefName": "main",
            "headRefOid": "a" * 40,
            "url": "https://github.com/owner/project/pull/9",
            "statusCheckRollup": list(checks),
        }
        delivery.pull_request_facts = lambda *_: facts
        delivery.review_threads = lambda *_: list(threads)
        return delivery.observe(Path("."), "owner/project", 9)["status"]

    def tearDown(self):
        SPEC.loader.exec_module(delivery)

    def test_reports_the_terminal_states_first(self):
        self.assertEqual(self.observe("MERGED"), "MERGED")
        self.assertEqual(self.observe("CLOSED"), "CLOSED")

    def test_conflict_outranks_a_failing_check(self):
        self.assertEqual(
            self.observe("OPEN", mergeable="CONFLICTING", checks=[check("A", "FAILURE")]),
            "CONFLICT",
        )

    def test_a_failing_check_outranks_an_unresolved_thread(self):
        self.assertEqual(
            self.observe(
                "OPEN", checks=[check("A", "FAILURE")], threads=[{"id": "T"}]
            ),
            "CHECK_FAILURE",
        )

    def test_an_unresolved_thread_outranks_a_pending_check(self):
        self.assertEqual(
            self.observe(
                "OPEN",
                checks=[check("A", None, status="IN_PROGRESS")],
                threads=[{"id": "T"}],
            ),
            "THREADS_UNRESOLVED",
        )

    def test_a_pending_check_keeps_waiting(self):
        self.assertEqual(
            self.observe("OPEN", checks=[check("A", None, status="QUEUED")]), "PENDING"
        )

    def test_a_clean_open_pull_request_is_ready(self):
        self.assertEqual(self.observe("OPEN", checks=[check("A", "SUCCESS")]), "READY")


class AwaitTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="harness-delivery-"))
        self.repo = self.temp / "repo"
        run = lambda *a, **k: subprocess.run(a, check=True, capture_output=True, **k)
        run("git", "init", "--initial-branch=task/2", str(self.repo))
        run("git", "config", "user.email", "agent@example.com", cwd=self.repo)
        run("git", "config", "user.name", "Agent", cwd=self.repo)
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        run("git", "add", "README.md", cwd=self.repo)
        run("git", "commit", "-m", "Initial", cwd=self.repo)

        self.state = self.temp / "gh-state.json"
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

    def write_state(self, checks=(), threads=(), log="", state="OPEN", fail=0):
        self.state.write_text(
            json.dumps(
                {
                    "fail": fail,
                    "list": [{"number": 9}],
                    "pull_request": {
                        "number": 9,
                        "state": state,
                        "isDraft": False,
                        "mergeable": "MERGEABLE",
                        "baseRefName": "main",
                        "headRefOid": "b" * 40,
                        "url": "https://github.com/owner/project/pull/9",
                        "statusCheckRollup": list(checks),
                    },
                    "graphql": {
                        "viewer": {"login": "agent"},
                        "repository": {
                            "pullRequest": {"reviewThreads": {"nodes": list(threads)}}
                        },
                    },
                    "log": log,
                }
            ),
            encoding="utf-8",
        )

    def run_await(self):
        return subprocess.run(
            [
                "python3", str(MODULE), "--repo", str(self.repo),
                "--timeout", "0", "--interval", "0",
            ],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def await_report(self):
        result = self.run_await()
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_reports_a_failing_check_with_its_log_tail(self):
        self.write_state(checks=[check("Integration", "FAILURE")], log="boom\nfailed\n")

        report = self.await_report()

        self.assertIn("STATUS: CHECK_FAILURE", report)
        self.assertIn("FAILED_CHECK: Integration FAILURE", report)
        self.assertIn("LOG_TAIL:\nboom\nfailed", report)

    def test_marks_a_thread_the_author_answered_without_resolving(self):
        self.write_state(
            checks=[check("Integration", "SUCCESS")],
            threads=[
                thread(
                    "PRRT_1",
                    comments=[
                        {"author": {"login": "reviewer"}, "body": "fix this"},
                        {"author": {"login": "agent"}, "body": "done"},
                    ],
                ),
                thread("PRRT_2"),
            ],
        )

        report = self.await_report()

        self.assertIn("STATUS: THREADS_UNRESOLVED", report)
        self.assertIn("UNRESOLVED_THREAD: PRRT_1 src/main.py:12 by reviewer answered-not-resolved", report)
        self.assertIn("UNRESOLVED_THREAD: PRRT_2 src/main.py:12 by reviewer unanswered", report)
        self.assertIn("resolveReviewThread", report)

    def test_resolved_threads_leave_a_green_pull_request_ready(self):
        self.write_state(
            checks=[check("Integration", "SUCCESS")],
            threads=[thread("PRRT_1", resolved=True)],
        )

        self.assertIn("STATUS: READY", self.await_report())

    def test_reports_the_merge(self):
        self.write_state(checks=[check("Integration", "SUCCESS")], state="MERGED")

        self.assertIn("STATUS: MERGED", self.await_report())

    def test_a_long_poll_outlives_brief_github_failures(self):
        self.write_state(checks=[check("Integration", "SUCCESS")], fail=2)

        self.assertIn("STATUS: READY", self.await_report())

    def test_a_standing_github_failure_ends_the_poll(self):
        self.write_state(checks=[check("Integration", "SUCCESS")], fail=9)

        result = self.run_await()

        self.assertEqual(result.returncode, 1)
        self.assertIn("Connection closed", result.stderr)

    def test_a_pending_check_times_out_instead_of_blocking(self):
        self.write_state(checks=[check("Integration", None, status="IN_PROGRESS")])

        report = self.await_report()

        self.assertIn("STATUS: TIMEOUT", report)
        self.assertIn("PENDING_CHECKS: Integration", report)


if __name__ == "__main__":
    unittest.main()
