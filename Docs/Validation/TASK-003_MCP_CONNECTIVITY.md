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

## Disposition (superseded by the completed proof below)

ToolLab was deliberately left running (`editor_pid 36516`, `mcp_ready: true`)
at the end of the prior turn so that the next Claude process (this supervisor
architecture starts a fresh `claude -p` process per turn) would begin with a
connectable `unreal-mcp` endpoint. That is exactly what happened.

## Claude — independent native connection/read proof

Date: 2026-08-30. At the start of this turn `unreal-mcp` (`http://127.0.0.1:8000/mcp`)
was already listed as a successfully connected MCP server (ToolLab had been
left running from the prior turn), and `mcp__unreal-mcp__list_toolsets`,
`describe_toolset`, and `call_tool` were available without any additional
configuration step. `GetToolLabStatus` confirmed the same long-lived editor
process (`editor_pid: 36516`, unchanged) was still running, with no mutation
lock held. All five Validation-section reads were performed directly against
the native endpoint, no filesystem or manual-editor substitute:

1. **Connection confirmed**: `list_toolsets` returned the live registry (40+
   toolsets — `CotSDeveloperTools.*`, `EditorToolset.*`, `editor_toolset.toolsets.*`,
   Niagara/Sequencer/GAS/PCG/UMG/etc. — the same registry Codex enumerated).
2. **Unreal version**: `CotSDeveloperTools.CotSFoundationToolset.GetStatus` ->
   `"unreal_version": "5.8.1-56057345+++UE5+Release-5.8"`.
3. **Open project**: `CotSDeveloperTools.CotSInspectionToolset.GetProjectStatus` ->
   `"project_name": "CotSToolLab"`, `"project_path": "../../../../../../Dev/CotSDeveloperTools/ToolLab/CotSToolLab.uproject"`,
   `"cots_plugin_enabled": true`, `"cots_module_loaded": true`.
4. **Current level/selection**: `editor_toolset.toolsets.scene.SceneTools.get_current_level` ->
   `"/Temp/Untitled_1"` (matches `GetProjectStatus`'s `"current_map"`); `EditorToolset.EditorAppToolset.GetSelectedActors` ->
   `[]` (no actor currently selected); `GetProjectStatus` also reports `"pie_running": false`.
5. **Toolset enumeration**: same `list_toolsets` call as (1); `describe_toolset`
   was additionally used on `EditorToolset.EditorAppToolset`,
   `editor_toolset.toolsets.scene.SceneTools`, `CotSDeveloperTools.CotSFoundationToolset`,
   and `CotSDeveloperTools.CotSInspectionToolset` to confirm full tool/schema
   access, not just names.

Claude's project (`CotSToolLab`), engine version (`5.8.1-56057345+++UE5+Release-5.8`),
and level (`/Temp/Untitled_1`) match Codex's `Docs/MCP_CAPABILITY_MATRIX.md`
values exactly, confirming both clients independently inspected the *same*
running Unreal Editor instance, not two separate editors. This was a purely
read-only proof: no asset, actor, or level was created, changed, or deleted;
no production CotS or Shardlands scope was touched.

## Disposition

Both required independent client proofs now exist: Codex's in
`Docs/MCP_CAPABILITY_MATRIX.md`, Claude's above. The remaining gap identified
during this task's investigation is process-level, not scope-level: a
Claude Code MCP HTTP client binds at process start and does not retry a
server that was unreachable at that moment, so ToolLab must already be
running before a Claude turn begins for its native connection to succeed.
That is now recorded as operating guidance for future turns/tasks rather than
an open acceptance item for TASK-003.
