#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path


CONFIG = Path(__file__).resolve().parents[1] / "mcp.json"


def mcporter(*arguments):
    result = subprocess.run(
        [
            "npm", "exec", "--yes", "--package=mcporter@0.13.11", "--",
            "mcporter", "--config", str(CONFIG), *arguments,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode:
        sys.stdout.write(result.stdout)
        raise SystemExit(result.returncode if result.returncode > 0 else 1)
    return result.stdout


def catalog():
    result = json.loads(mcporter("list", "xcode", "--json"))
    if result["status"] != "ok":
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result["tools"]


def main():
    parser = argparse.ArgumentParser(description="Discover Xcode MCP tools on demand.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="Show every current tool name.")
    describe = commands.add_parser(
        "describe", help="Show selected tools' full descriptions and schemas.",
        description="Read selected contracts from one catalog fetch; one JSON object per line.",
    )
    describe.add_argument("tools", nargs="+", metavar="TOOL")
    call = commands.add_parser("call", help="Invoke a discovered tool with JSON arguments.")
    call.add_argument("tool")
    call.add_argument("--args-file", type=Path, required=True)
    call.add_argument("--timeout-ms", type=int, default=180000)
    call.add_argument("--output-file", type=Path, help="Save the full response instead of printing it.")
    call.add_argument("--save-images", type=Path, help="Directory for returned inline images.")
    args = parser.parse_args()

    if args.command == "list":
        for tool in catalog():
            print(tool["name"])
    elif args.command == "describe":
        tools = {tool["name"]: tool for tool in catalog()}
        selected = [tools[name] for name in args.tools]
        for tool in selected:
            contract = {key: tool[key] for key in ("name", "description", "inputSchema")}
            if "outputSchema" in tool:
                contract["outputSchema"] = tool["outputSchema"]
            print(json.dumps(
                contract, ensure_ascii=False, separators=(",", ":"),
            ))
    else:
        arguments = json.loads(args.args_file.read_text(encoding="utf-8"))
        if not isinstance(arguments, dict):
            parser.error("--args-file must contain a JSON object")
        if args.timeout_ms <= 0:
            parser.error("--timeout-ms must be positive")
        command = [
            "call", f"xcode.{args.tool}", "--args", json.dumps(arguments),
            "--timeout", str(args.timeout_ms), "--output", "json",
        ]
        if args.save_images:
            command.extend(["--save-images", str(args.save_images)])
        destination = (
            args.output_file.open("w", encoding="utf-8")
            if args.output_file else nullcontext(sys.stdout)
        )
        with destination as stream:
            output = mcporter(*command)
            result = json.loads(output)
            if result.get("isError") is True:
                sys.stdout.write(output)
                raise SystemExit(1)
            stream.write(output)
        if args.output_file:
            print(f"Saved response: {args.output_file.resolve()}")


if __name__ == "__main__":
    main()
