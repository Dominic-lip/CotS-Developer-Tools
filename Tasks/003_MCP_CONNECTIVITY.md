# TASK-003 — Codex and Claude Unreal MCP Connectivity

## Objective
Connect both Codex and Claude Code to Epic's native Unreal Engine 5.8 MCP server in the Tool Lab.

## Allowed scope
Tool Lab, agent-local MCP config and documentation. Local user configuration may be changed only as necessary for the MCP connection.

## Forbidden scope
No production CotS work. No Shardlands mutation.

## Requirements
- Inspect the installed UE 5.8 MCP plugin/settings rather than relying on stale tutorials.
- Enable/start the native MCP server and necessary native toolsets.
- Configure Codex against the Tool Lab endpoint.
- Configure Claude Code against the same endpoint.
- Do not expose the MCP server beyond localhost.
- Record exact configuration steps that were verified locally, but do not commit secrets/tokens.

## Validation
Each agent independently must:
1. confirm connection to Unreal MCP;
2. identify Unreal version;
3. identify `CotSToolLab` as the open project;
4. report the current level/selection where supported;
5. enumerate or otherwise prove access to available Unreal toolsets.

## Acceptance criteria
Both clients can inspect the same running Unreal Editor without human editor manipulation beyond initial plugin/settings enablement where unavoidable.
