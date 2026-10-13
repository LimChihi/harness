# Runtime setup

Requires macOS, Python 3, Node.js/npm, and Xcode with `xcrun mcpbridge` support.
The script pins mcporter and runs it through `npm exec`; the first invocation
downloads it into npm's cache. There is no global npm installation.

Commands for inspecting the selected installation and Xcode MCP status:

```sh
xcode-select -p
xcodebuild -version
xcrun mcp-server status
```

The selected Xcode installation determines the available tools. External agent
access is configured in Xcode's Intelligence settings. Opening a project through
its tool initiates Xcode's project authorization, which can require user action.

The bundled `mcp.json` is private to this CLI and imports no other MCP servers.
Its keep-alive lifecycle lets mcporter retain the bridge across calls. The daemon
can serve other tasks; stopping it affects their connections too.

The skill's metadata supports implicit discovery. An eager Xcode MCP registration
in the agent's own configuration exposes tools in addition to this skill, retaining
their static token cost. Disabling that registration takes effect in a new session;
installing the skill alone does not remove tools already exposed by it.

## Troubleshooting

Bridge connectivity, workspace availability, and verification operations are
separate states. Diagnose the layer named by the error.

- **Connection or authorization:** Inspect the selected installation and MCP
  status with the commands above. Use that installation's command help and Xcode
  settings to choose the supported startup or authorization path. Confirm access
  by enumerating workspaces.
- **Workspace or file resolution:** Use workspace identifiers returned by
  enumeration and file paths returned by project search. These can differ from
  filesystem paths.
- **Verification could not run:** Preserve the tool or runtime error and try another
  appropriate verification path, such as a project build, tests, or the project's
  command-line checks. Choose its scope to match the change. Report each check's
  result separately; a file diagnostic failure establishes only that this check
  failed, not whether the project can build or run.

Retry after correcting an identified cause or changing the verification path.
If no usable path remains, report what was attempted and the remaining blocker.
