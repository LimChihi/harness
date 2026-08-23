import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "skills/setup-harness/hooks/post-commit"


class PostCommitHookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="harness-post-commit-")
        self.repo = Path(self.temporary.name)
        subprocess.run(
            ["git", "init", "--quiet", "--initial-branch=main", str(self.repo)],
            check=True,
        )
        self.git("config", "user.name", "Harness Tests")
        self.git("config", "user.email", "harness@example.com")
        self.git("commit", "--quiet", "--allow-empty", "-m", "initial")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *arguments):
        return subprocess.run(
            ["git", "-C", str(self.repo), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )

    def run_hook(self):
        return subprocess.run(
            [str(HOOK)],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        )

    def advance_origin_main(self):
        parent = self.git("rev-parse", "refs/remotes/origin/main").stdout.strip()
        tree = self.git("rev-parse", "HEAD^{tree}").stdout.strip()
        commit = subprocess.run(
            ["git", "-C", str(self.repo), "commit-tree", tree, "-p", parent],
            input="upstream\n",
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.git("update-ref", "refs/remotes/origin/main", commit)

    def test_stays_silent_when_not_behind(self):
        self.assertEqual(self.run_hook().stdout, "")

        self.git("commit", "--quiet", "--allow-empty", "-m", "local")

        self.assertEqual(self.run_hook().stdout, "")

    def test_suggests_rebase_when_behind(self):
        self.advance_origin_main()

        self.assertEqual(
            self.run_hook().stdout,
            "Current branch is 1 commit behind origin/main; consider rebasing.\n",
        )

        self.advance_origin_main()

        self.assertEqual(
            self.run_hook().stdout,
            "Current branch is 2 commits behind origin/main; consider rebasing.\n",
        )


if __name__ == "__main__":
    unittest.main()
