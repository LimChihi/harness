---
name: xcode
description: "Xcode tools for iOS and Apple-platform projects: builds, tests, SwiftUI previews, app/device logs, LLDB debugging, simulator/device interaction, project configuration, and localization."
---

# Xcode

The entry point is `python3 <skill-dir>/scripts/xcode.py`, where `<skill-dir>` is
the directory containing this SKILL.md.

| Command | Available information or action |
| --- | --- |
| `list` | All tool names from the selected Xcode installation. |
| `describe TOOL [TOOL ...]` | Full descriptions and input/output schemas, including prerequisites. Multiple names share one catalog fetch; each contract is a JSON line. |
| `call TOOL --args-file /absolute/args.json` | Executes a tool with arguments from a JSON object file (`{}` for tools without parameters) and returns its result. |
| `call --help` | Timeout and image-output options; `--output-file` saves the raw response, including failures. |

Tool names are navigation hints; full contracts describe their capabilities,
scope, and execution requirements. Catalogs and contracts already in context
can serve later requests on the same Xcode installation and connection. Changes
to either can make that information stale.

Before workspace-dependent calls, match the target project's path in
`XcodeListWorkspaces` and use the returned identifier. When opening a project
with `XcodeOpenWorkspace`, use that call's returned identifier.

Session keys refer to existing execution state. Tool contracts describe resource
lifecycles and side effects; release only resources this task created. Results
can include application status, errors, and paths to logs or images, beyond the
invocation's exit status.
The CLI and some tools have separate timeouts; a CLI timeout leaves the tool's
completion and any mutation's outcome uncertain.

[Runtime setup](references/setup.md) covers first-time configuration, replacing
an eager MCP registration, and runtime or authorization problems.

For device interaction, follow [Device interaction](references/device-interaction.md)
to obtain the selected Xcode's upstream skill and delegate verification.
