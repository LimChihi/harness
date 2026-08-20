import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "setup-harness"
MODULE = SKILL / "scripts" / "install_hooks.py"
SPEC = importlib.util.spec_from_file_location("install_hooks", MODULE)
install_hooks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(install_hooks)

FILE_SIZE_HOOK = ".agents/skills/setup-harness/hooks/file_size_hint.py"
HANDOFF_HOOK = ".agents/skills/setup-harness/hooks/handoff.py"


def command(relative_path):
    return f'/usr/bin/python3 "$(git rev-parse --show-toplevel)/{relative_path}"'


class InstallHooksTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="harness-install-")).resolve()
        subprocess.run(
            ["git", "init", "--quiet", str(self.repo)], check=True, capture_output=True
        )
        target = self.repo / ".agents/skills/setup-harness"
        target.parent.mkdir(parents=True)
        shutil.copytree(SKILL, target)
        self.script = target / "scripts/install_hooks.py"

    def tearDown(self):
        shutil.rmtree(self.repo)

    def install(self, check=True):
        result = subprocess.run(
            ["python3", str(self.script), "--repo", str(self.repo)],
            capture_output=True,
            text=True,
            check=False,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def config(self, relative_path):
        return json.loads((self.repo / relative_path).read_text(encoding="utf-8"))

    def write_config(self, relative_path, value):
        path = self.repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    @staticmethod
    def handlers(config, event):
        return [handler for group in config["hooks"][event] for handler in group["hooks"]]

    def test_points_both_agents_at_the_installed_skill(self):
        self.install()

        codex = self.config(".codex/hooks.json")
        for event in ("PreToolUse", "PostToolUse"):
            self.assertEqual(
                codex["hooks"][event],
                [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": command(FILE_SIZE_HOOK),
                                "timeout": 5,
                            }
                        ],
                        "matcher": "^apply_patch$",
                    }
                ],
            )
        self.assertNotIn("Stop", codex["hooks"])

        cursor = self.config(".cursor/hooks.json")
        self.assertEqual(cursor["version"], 1)
        for event in ("preToolUse", "postToolUse"):
            self.assertEqual(
                cursor["hooks"][event],
                [
                    {
                        "command": command(FILE_SIZE_HOOK),
                        "matcher": "^(Write|Delete)$",
                        "timeout": 5,
                    }
                ],
            )
        self.assertNotIn("stop", cursor["hooks"])

    def test_preserves_hooks_the_repository_already_had(self):
        self.write_config(
            ".codex/hooks.json",
            {
                "description": "Existing configuration.",
                "custom": True,
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "^Bash$",
                            "hooks": [{"type": "command", "command": "./check-bash"}],
                        }
                    ],
                    "Stop": [
                        {
                            "hooks": [
                                {"type": "command", "command": "./keep-stop"}
                            ]
                        }
                    ],
                },
            },
        )
        self.write_config(
            ".cursor/hooks.json",
            {
                "version": 1,
                "hooks": {
                    "beforeShellExecution": [{"command": "./audit-shell"}],
                    "preToolUse": [{"command": "./scan-secrets", "matcher": "^Write$"}],
                    "stop": [{"command": "./keep-stop"}],
                },
            },
        )

        self.install()

        codex = self.config(".codex/hooks.json")
        self.assertEqual(codex["description"], "Existing configuration.")
        self.assertIs(codex["custom"], True)
        self.assertEqual(
            [handler["command"] for handler in self.handlers(codex, "PreToolUse")],
            ["./check-bash", command(FILE_SIZE_HOOK)],
        )
        self.assertEqual(
            self.handlers(codex, "Stop"),
            [{"type": "command", "command": "./keep-stop"}],
        )

        cursor = self.config(".cursor/hooks.json")
        self.assertEqual(cursor["hooks"]["beforeShellExecution"], [{"command": "./audit-shell"}])
        self.assertEqual(
            [entry["command"] for entry in cursor["hooks"]["preToolUse"]],
            ["./scan-secrets", command(FILE_SIZE_HOOK)],
        )
        self.assertEqual(cursor["hooks"]["stop"], [{"command": "./keep-stop"}])

    def test_reinstall_is_idempotent(self):
        self.install()
        first = [
            (self.repo / path).read_text(encoding="utf-8")
            for path in (".codex/hooks.json", ".cursor/hooks.json")
        ]

        self.install()

        self.assertEqual(
            [
                (self.repo / path).read_text(encoding="utf-8")
                for path in (".codex/hooks.json", ".cursor/hooks.json")
            ],
            first,
        )

    def test_migrates_file_size_hooks_and_removes_handoff_hooks(self):
        for relative in (
            ".codex/hooks/file_size_hint.py",
            ".codex/hooks/harness/file_size_hint.py",
            ".agents/hooks/harness/file_size_hint.py",
            ".agents/hooks/harness/handoff.py",
        ):
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("stale hook\n", encoding="utf-8")
        self.write_config(
            ".codex/hooks.json",
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "^apply_patch$",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": command(
                                        ".agents/hooks/harness/file_size_hint.py"
                                    ),
                                    "timeout": 5,
                                }
                            ],
                        }
                    ],
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": command(HANDOFF_HOOK),
                                    "timeout": 30,
                                },
                                {
                                    "type": "command",
                                    "command": command(".agents/hooks/harness/handoff.py"),
                                    "timeout": 30,
                                }
                            ]
                        }
                    ],
                }
            },
        )
        self.write_config(
            ".cursor/hooks.json",
            {
                "version": 1,
                "hooks": {
                    "stop": [
                        {
                            "command": command(HANDOFF_HOOK),
                            "timeout": 30,
                            "loop_limit": None,
                        }
                    ]
                },
            },
        )

        self.install()

        codex = self.config(".codex/hooks.json")
        self.assertEqual(
            [handler["command"] for handler in self.handlers(codex, "PreToolUse")],
            [command(FILE_SIZE_HOOK)],
        )
        self.assertNotIn("Stop", codex["hooks"])
        self.assertNotIn("stop", self.config(".cursor/hooks.json")["hooks"])
        for relative in (
            ".codex/hooks/file_size_hint.py",
            ".agents/hooks/harness/file_size_hint.py",
            ".agents/hooks/harness/handoff.py",
        ):
            self.assertFalse((self.repo / relative).exists(), relative)

    def test_installs_from_a_subdirectory(self):
        subdirectory = self.repo / "src/feature"
        subdirectory.mkdir(parents=True)

        result = subprocess.run(
            ["python3", str(self.script), "--repo", str(subdirectory)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.repo / ".codex/hooks.json").is_file())
        self.assertTrue((self.repo / ".cursor/hooks.json").is_file())

    def test_writes_nothing_when_a_configuration_is_invalid(self):
        for relative in (".codex/hooks.json", ".cursor/hooks.json"):
            with self.subTest(configuration=relative):
                self.setUp()
                path = self.repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{", encoding="utf-8")

                result = self.install(check=False)

                self.assertEqual(result.returncode, 1)
                self.assertTrue(result.stderr.startswith("install hooks:"))
                self.assertEqual(path.read_text(encoding="utf-8"), "{")

    def test_refuses_to_wire_a_skill_outside_the_repository(self):
        result = subprocess.run(
            ["python3", str(MODULE), "--repo", str(self.repo)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("install it into the project", result.stderr)
        self.assertFalse((self.repo / ".codex/hooks.json").exists())


if __name__ == "__main__":
    unittest.main()
