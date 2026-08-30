# TASK-003 Validation — Claude Independent Unreal MCP Connection

Task spec: `Tasks/003_MCP_CONNECTIVITY.md`.

## Prior state (Codex)

Recorded in `Docs/MCP_CAPABILITY_MATRIX.md`: Codex connected directly to the
native UE 5.8.1 Streamable HTTP MCP endpoint at `http://127.0.0.1:8000/mcp`
in `CotSToolLab`, negotiated protocol `2025-11-25`, enumerated 40+ toolsets,
and read project/level/selection state. That same audit found Claude's
`claude mcp add --transport http unreal-native-audit ...` reported success but
`claude mcp get`/`claude mcp list` immediately showed no configured server, so
the required independent Claude read proof was left unverified — a
client/configuration issue, not evidence the endpoint was unavailable.

## Current configuration state

`.mcp.json` (repo root) and `ToolLab/.mcp.json` both now declare, as
project-local MCP servers:

```json
{
  "mcpServers": {
    "cots-host": { "type": "http", "url": "http://127.0.0.1:8010/mcp" },
    "unreal-mcp": { "type": "http", "url": "http://127.0.0.1:8000/mcp" }
  }
}
```

This supersedes the earlier `claude mcp add` non-persistence problem: the
server is declared in checked-in project configuration rather than relying on
a local `claude mcp add` mutation.

## This turn's finding: a session-start ordering gap, not a configuration failure

At the start of this turn, Claude Code attempted to connect the configured
`unreal-mcp` server and reported it failed with `ConnectionRefused`. Host
status at that moment confirmed why:

```
GetToolLabStatus -> {"editor_running": false, "mcp_ready": false, ...}
```

ToolLab was not running yet, so there was nothing listening on
`127.0.0.1:8000/mcp` when this Claude process started and made its one
connection attempt. This session then:

1. Acquired the Host mutation lock as `supervisor-task-003`.
2. Called `OpenToolLab` — `editor_pid 36516`.
3. Called `WaitForUnrealMcp` — returned `{"ready": true, "mcp_url": "http://127.0.0.1:8000/mcp"}`.
4. Re-checked `GetToolLabStatus` — `{"editor_running": true, "mcp_ready": true, "editor_pid": 36516}`.
5. Searched for native `unreal-mcp` tools again (`list_toolsets`/`describe_toolset`
   equivalents) — none were discoverable, confirming this Claude process's MCP
   client does not retry a server that failed at startup, even after the
   endpoint becomes reachable mid-session.
6. Released the Host mutation lock (no further lifecycle mutation was needed).

This is a validation-topology/ordering gap, not a broken endpoint or a broken
Claude MCP configuration: the endpoint is real and ready, and the declared
config is correct and persistent. The one requirement Claude's HTTP MCP
client actually has is that the server be reachable when the client process
starts.

## Disposition

ToolLab was deliberately left running (`editor_pid 36516`, `mcp_ready: true`)
at the end of this turn so that the next Claude process (this supervisor
architecture starts a fresh `claude -p` process per turn) begins with a
connectable `unreal-mcp` endpoint and can perform the five Validation-section
reads in `Tasks/003_MCP_CONNECTIVITY.md` (confirm connection, identify UE
version, identify `CotSToolLab`, report level/selection, enumerate toolsets)
using the same native calls Codex already used. No production CotS or
Shardlands scope was touched; no ToolLab content asset was created, changed,
or deleted this turn.
