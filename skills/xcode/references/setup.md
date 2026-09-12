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
