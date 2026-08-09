import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SOURCE_ROOT / "hooks/file_size_hint.py"
SPEC = importlib.util.spec_from_file_location("file_size_hint", MODULE_PATH)
file_size_hint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(file_size_hint)


class FileSizeHintTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        subprocess.run(
            ["git", "init", "--quiet", self.directory],
            check=True,
            capture_output=True,
        )

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def update_patch(path, removed=0, added=0, move_to=None):
        lines = [f"*** Update File: {path}"]
        if move_to is not None:
            lines.append(f"*** Move to: {move_to}")
        lines.append("@@")
        lines.extend(f"-removed {index}" for index in range(removed))
        lines.extend(f"+added {index}" for index in range(added))
        return "\n".join(lines)

    @staticmethod
    def add_patch(path, added):
        lines = [f"*** Add File: {path}"]
        lines.extend(f"+added {index}" for index in range(added))
        return "\n".join(lines)

    def payload(self, command, event=None, cwd=None):
        payload = {
            "cwd": str(cwd or self.directory),
            "tool_input": {"command": f"*** Begin Patch\n{command}\n*** End Patch\n"},
        }
        if event is not None:
            payload.update(
                {
                    "session_id": "test-session",
                    "tool_use_id": f"test-{self.directory.name}",
                    "hook_event_name": event,
                }
            )
        return payload

    def hints_after(self, command, mutate):
        payload = self.payload(command)
        before_counts = file_size_hint.capture_line_counts(payload)
        mutate()
        return file_size_hint.collect_hints(payload, before_counts)

    def test_extracts_source_and_destination_paths(self):
        command = """*** Begin Patch
*** Add File: src/new.py
+new
*** Update File: src/large.py
@@
-old
+new
*** Update File: src/original.py
*** Move to: src/renamed.py
*** Delete File: src/obsolete.py
*** End Patch
"""

        self.assertEqual(
            file_size_hint.edited_files(command),
            [
                (None, "src/new.py"),
                ("src/large.py", "src/large.py"),
                ("src/original.py", "src/renamed.py"),
                ("src/obsolete.py", None),
            ],
        )

    def test_returns_only_the_highest_threshold_hint(self):
        self.assertEqual(
            file_size_hint.hint_for("src/large.py", 801),
            "src/large.py: 801 lines (>800). Check responsibility before adding more code.",
        )
        self.assertEqual(
            file_size_hint.hint_for("src/large.py", 1201),
            "src/large.py: 1,201 lines (>1200). Extract a coherent responsibility before growing it.",
        )
        self.assertEqual(
            file_size_hint.hint_for("src/large.py", 1401),
            "src/large.py: 1,401 lines (>1400). Stop growing this file; split it first unless generated or data-only.",
        )

    def test_does_not_hint_when_growth_is_at_most_30_lines(self):
        path = self.directory / "large.py"
        path.write_text("line\n" * 900, encoding="utf-8")
        command = self.update_patch("large.py", removed=100, added=129)

        hints = self.hints_after(
            command,
            lambda: path.write_text("line\n" * 929, encoding="utf-8"),
        )

        self.assertEqual(hints, [])

    def test_emits_post_tool_context_when_growth_exceeds_30_lines(self):
        path = self.directory / "large.py"
        path.write_text("line\n" * 770, encoding="utf-8")
        command = self.update_patch("large.py", added=31)
        pre_payload = self.payload(command, "PreToolUse")
        post_payload = self.payload(command, "PostToolUse")

        pre = subprocess.run(
            [sys.executable, MODULE_PATH],
            input=json.dumps(pre_payload),
            capture_output=True,
            check=True,
            text=True,
        )
        path.write_text("line\n" * 801, encoding="utf-8")
        post = subprocess.run(
            [sys.executable, MODULE_PATH],
            input=json.dumps(post_payload),
            capture_output=True,
            check=True,
            text=True,
        )

        self.assertEqual(pre.stdout, "")
        self.assertEqual(
            json.loads(post.stdout),
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": (
                        "large.py: 801 lines (>800). "
                        "Check responsibility before adding more code."
                    ),
                }
            },
        )

    def test_new_file_growth_starts_at_zero(self):
        path = self.directory / "new.py"
        command = self.add_patch("new.py", added=801)

        hints = self.hints_after(
            command,
            lambda: path.write_text("line\n" * 801, encoding="utf-8"),
        )

        self.assertEqual(len(hints), 1)
        self.assertIn("new.py: 801 lines", hints[0])

    def test_move_does_not_count_existing_lines_as_growth(self):
        original = self.directory / "original.py"
        renamed = self.directory / "renamed.py"
        original.write_text("line\n" * 801, encoding="utf-8")
        command = self.update_patch("original.py", move_to="renamed.py")

        hints = self.hints_after(command, lambda: original.rename(renamed))

        self.assertEqual(hints, [])

    def test_uses_repository_root_when_started_in_a_subdirectory(self):
        subdirectory = self.directory / "src"
        subdirectory.mkdir()
        path = subdirectory / "large.py"
        path.write_text("line\n" * 770, encoding="utf-8")
        command = self.update_patch("large.py", added=31)
        payload = self.payload(command, cwd=subdirectory)
        counts = file_size_hint.capture_line_counts(payload)
        path.write_text("line\n" * 801, encoding="utf-8")

        hints = file_size_hint.collect_hints(payload, counts)

        self.assertEqual(
            hints,
            ["src/large.py: 801 lines (>800). Check responsibility before adding more code."],
        )


if __name__ == "__main__":
    unittest.main()
