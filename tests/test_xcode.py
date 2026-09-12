import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "skills/xcode/scripts/xcode.py"
FAKE_NPM = '''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state = json.loads(Path(os.environ["XCODE_TEST_STATE"]).read_text())
with Path(os.environ["XCODE_TEST_CALLS"]).open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
print(state["stdout"], end="")
print(state["stderr"], end="", file=sys.stderr)
sys.exit(state["exit"])
'''


class XcodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness-xcode-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        fake_npm = self.root / "npm"
        fake_npm.write_text(FAKE_NPM, encoding="utf-8")
        fake_npm.chmod(0o755)
        self.state = self.root / "state.json"
        self.calls = self.root / "calls.jsonl"
        self.env = {
            **os.environ,
            "PATH": f"{self.root}{os.pathsep}{os.environ['PATH']}",
            "XCODE_TEST_STATE": str(self.state),
            "XCODE_TEST_CALLS": str(self.calls),
        }
        self.arguments = self.root / "arguments with spaces.json"
        self.arguments.write_text("{}", encoding="utf-8")

    def response(self, value, code=0, stderr=""):
        self.state.write_text(json.dumps({
            "stdout": json.dumps(value), "stderr": stderr, "exit": code,
        }), encoding="utf-8")

    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, arguments)],
            cwd=self.root, env=self.env, capture_output=True, text=True,
        )

    def recorded(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def call(self, *arguments):
        return self.run_cli("call", "FutureTelemetry", "--args-file", self.arguments, *arguments)

    def test_discovers_future_tools_and_discloses_only_selected_contract(self):
        contract = {
            "name": "FutureTelemetry", "description": "Reads telemetry. Requires an active session.",
            "inputSchema": {"type": "object", "properties": {"session": {"type": "string"}}},
            "outputSchema": {"type": "object", "properties": {"value": {"type": "number"}}},
        }
        self.response({"status": "ok", "tools": [
            {**contract, "options": [{"cliName": "session"}]},
            {"name": "UnrelatedFutureTool", "description": "Does something else.",
             "inputSchema": {"type": "object", "properties": {"secretSchema": {"type": "string"}}}},
        ]})
        index = self.run_cli("list")
        self.assertEqual(index.returncode, 0, index.stderr)
        self.assertEqual(index.stdout.splitlines(), [
            "FutureTelemetry", "UnrelatedFutureTool",
        ])
        described = self.run_cli("describe", "FutureTelemetry")
        self.assertEqual(described.returncode, 0, described.stderr)
        self.assertEqual(json.loads(described.stdout), contract)

    def test_unknown_tool_is_an_explicit_failure(self):
        self.response({"status": "ok", "tools": []})
        result = self.run_cli("describe", "MissingTool")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MissingTool", result.stderr)

    def test_batch_describe_fetches_once_and_preserves_requested_order(self):
        contracts = [{
            "name": name, "description": f"Contract for {name}.",
            "inputSchema": {"type": "object", "properties": {}},
        } for name in ("Alpha", "Beta", "Unrelated")]
        contracts[0]["outputSchema"] = {"type": "object", "properties": {}}
        self.response({"status": "ok", "tools": contracts})

        result = self.run_cli("describe", "Beta", "Alpha")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [json.loads(line) for line in result.stdout.splitlines()],
            [contracts[1], contracts[0]],
        )
        self.assertEqual(len(self.recorded()), 1)

    def test_unknown_batch_member_fails_without_partial_output(self):
        self.response({"status": "ok", "tools": [{
            "name": "Known", "description": "A known tool.",
            "inputSchema": {"type": "object", "properties": {}},
        }]})

        result = self.run_cli("describe", "Known", "MissingTool")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MissingTool", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(self.recorded()), 1)

    def test_failed_catalog_does_not_look_like_an_empty_index(self):
        self.response({"status": "error", "error": "Bridge unavailable"})
        result = self.run_cli("list")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Bridge unavailable", result.stderr)

    def test_arguments_survive_shell_metacharacters_and_config_is_isolated(self):
        payload = {"command": "po `thing` $(touch unwanted)\n路径", "timeout": 120}
        self.arguments.write_text(json.dumps(payload), encoding="utf-8")
        self.response({"content": [], "isError": False})
        result = self.call("--timeout-ms", "240000")
        self.assertEqual(result.returncode, 0, result.stderr)
        command = self.recorded()[0]
        self.assertEqual(command[:5], ["exec", "--yes", "--package=mcporter@0.13.11", "--", "mcporter"])
        config = json.loads(Path(command[command.index("--config") + 1]).read_text())
        self.assertEqual(config["imports"], [])
        self.assertEqual(set(config["mcpServers"]), {"xcode"})
        self.assertEqual(config["mcpServers"]["xcode"]["lifecycle"], "keep-alive")
        self.assertEqual(json.loads(command[command.index("--args") + 1]), payload)
        self.assertEqual(command[command.index("--timeout") + 1], "240000")
        self.assertEqual(command[command.index("--output") + 1], "json")
        self.assertFalse((self.root / "unwanted").exists())

    def test_nonzero_exit_and_evidence_propagate_without_retry(self):
        self.response({"isError": True, "message": "Not authorized"}, code=7, stderr="bridge failed\n")
        result = self.call()
        self.assertEqual(result.returncode, 7)
        self.assertIn("Not authorized", result.stdout)
        self.assertIn("bridge failed", result.stderr)
        self.assertEqual(len(self.recorded()), 1)

    def test_mcp_error_is_failure_even_when_transport_exits_zero(self):
        self.response({"isError": True, "content": [{"type": "text", "text": "Tool failed"}]})
        result = self.call()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Tool failed", result.stdout)

    def test_invalid_arguments_fail_before_invocation(self):
        for value in ([], "not an object", "{invalid"):
            with self.subTest(value=value):
                self.arguments.write_text(value if value == "{invalid" else json.dumps(value))
                result = self.call()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.calls.exists())

    def test_large_response_stays_in_file(self):
        response = {"content": [{"type": "text", "text": "log\n" * 10000}]}
        self.response(response)
        output = self.root / "output with spaces.json"
        result = self.call("--output-file", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(output.read_text()), response)
        self.assertLess(len(result.stdout), 200)

    def test_unwritable_output_fails_before_invocation(self):
        self.response({"content": []})
        result = self.call("--output-file", self.root / "missing" / "output.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
