import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "skills/setup-harness/hooks/git_sync_policy.py"
SPEC = importlib.util.spec_from_file_location("git_sync_policy", MODULE_PATH)
git_sync_policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(git_sync_policy)


class GitSyncPolicyTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="git-sync-policy-")).resolve()
        subprocess.run(
            ["git", "init", "--quiet", "--initial-branch", "main", str(self.repo)],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repo),
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/main",
            ],
            check=True,
        )

    def tearDown(self):
        shutil.rmtree(self.repo)

    def violation(self, command):
        return git_sync_policy.policy_violation(command, self.repo)

    def run_hook(self, payload):
        result = subprocess.run(
            ["python3", str(MODULE_PATH)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout else None

    def codex_payload(self, command):
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(self.repo),
        }

    def cursor_payload(self, command):
        return {
            "hook_event_name": "beforeShellExecution",
            "command": command,
            "cwd": str(self.repo),
        }

    def test_blocks_default_branch_merges(self):
        commands = (
            "git merge main",
            "git merge origin/main",
            "git merge refs/heads/main",
            "git merge refs/remotes/origin/main",
            "git merge remotes/origin/main",
            "git merge origin/HEAD",
            "git merge origin/main~1",
            "git merge --no-commit origin/main",
            "git merge --squash origin/main",
            "git merge FETCH_HEAD",
            "git merge @{u}",
            "git merge",
            "git merge --continue",
        )

        for command in commands:
            with self.subTest(command=command):
                self.assertIn("must use rebase", self.violation(command))

    def test_blocks_pull_without_explicit_rebase_or_fast_forward(self):
        commands = (
            "git pull",
            "git pull origin main",
            "git pull --no-rebase",
            "git pull --rebase=false",
            "git pull --ff-only --no-rebase",
        )

        for command in commands:
            with self.subTest(command=command):
                self.assertIn("must use rebase", self.violation(command))

    def test_allows_safe_git_operations(self):
        commands = (
            "git fetch origin && git rebase origin/main",
            "git pull --rebase",
            "git pull -r",
            "git pull -pr",
            "git pull --rebase=merges",
            "git pull --ff-only",
            "git merge --ff-only origin/main",
            "git merge --abort",
            "git merge --quit",
            "git merge feature/one",
            "git merge-base origin/main HEAD",
            "gh pr merge --merge",
            "printf '%s' 'git merge origin/main'",
            "git status",
        )

        for command in commands:
            with self.subTest(command=command):
                self.assertIsNone(self.violation(command))

    def test_blocks_forbidden_command_anywhere_in_a_compound_command(self):
        commands = (
            "git fetch origin && git merge origin/main",
            "git status; git merge origin/main; git status",
            "git status\ngit merge origin/main",
            "(git fetch origin && git merge origin/main)",
            "git fetch origin | git merge origin/main",
            "{ git fetch origin; git merge origin/main; }",
            "echo $(git merge origin/main)",
            "bash -lc 'git fetch origin && git merge origin/main'",
            "eval 'git merge origin/main'",
            "env MODE=test git merge origin/main",
            "command git merge origin/main",
            "/usr/bin/git merge origin/main",
            "git -C . merge origin/main",
        )

        for command in commands:
            with self.subTest(command=command):
                self.assertIsNotNone(self.violation(command))

    def test_ignores_comments_and_line_continuations(self):
        self.assertIsNone(self.violation("# git merge origin/main\ngit status"))
        self.assertIsNotNone(
            self.violation(
                "git fetch origin && \\\n"
                "git merge origin/main"
            )
        )

    def test_resolves_origin_head_from_git_c_directory(self):
        nested = self.repo / "nested"
        nested.mkdir()

        invocations = git_sync_policy.git_invocations(
            "git -C nested merge origin/main", self.repo
        )

        self.assertEqual(invocations[0].cwd, nested)
        self.assertEqual(git_sync_policy.default_ref(nested), "origin/main")

    def test_codex_hook_denies_before_tool_use(self):
        output = self.run_hook(
            self.codex_payload("git fetch origin && git merge origin/main")
        )

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        self.assertIn(
            "git rebase origin/main",
            output["hookSpecificOutput"]["permissionDecisionReason"],
        )

    def test_cursor_hook_denies_before_shell_execution(self):
        output = self.run_hook(self.cursor_payload("git pull origin main"))

        self.assertEqual(output["permission"], "deny")
        self.assertEqual(output["user_message"], output["agent_message"])
        self.assertIn("git pull --rebase", output["agent_message"])

    def test_safe_hook_command_emits_no_output(self):
        self.assertIsNone(
            self.run_hook(self.codex_payload("git fetch origin && git rebase origin/main"))
        )
        self.assertIsNone(
            self.run_hook(self.cursor_payload("git pull --ff-only"))
        )

    def test_missing_origin_head_denies_merge_with_configuration_error(self):
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repo),
                "symbolic-ref",
                "--delete",
                "refs/remotes/origin/HEAD",
            ],
            check=True,
        )

        output = self.run_hook(self.codex_payload("git merge origin/main"))

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        self.assertIn(
            "cannot resolve the default branch",
            output["hookSpecificOutput"]["permissionDecisionReason"],
        )

    def test_safe_recovery_does_not_require_origin_head(self):
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repo),
                "symbolic-ref",
                "--delete",
                "refs/remotes/origin/HEAD",
            ],
            check=True,
        )

        for command in (
            "git merge --abort",
            "git merge --quit",
            "git merge --ff-only feature/one",
            "git pull --rebase",
            "git pull --ff-only",
        ):
            with self.subTest(command=command):
                self.assertIsNone(self.violation(command))


if __name__ == "__main__":
    unittest.main()
