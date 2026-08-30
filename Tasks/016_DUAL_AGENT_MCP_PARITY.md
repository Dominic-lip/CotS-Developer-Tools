# TASK-016 — Dual-Agent MCP Parity (CotS Host MCP + Unreal MCP)

## Objective
Give both agent adapters — Codex and Claude — the same agent-neutral MCP access for native Unreal inspection/mutation. Neither adapter is currently correctly wired to both `Scripts\CotSHostMcp.py` (CotS Host MCP) and the native Unreal MCP server at once.

## Problem statement
Discovered during the post-ba71b42 Claude autonomous-turn repair (`02590ab`, TASK-008C follow-up): the live supervisor acceptance proof exercised Claude turn execution end-to-end, but neither the Codex adapter nor the Claude adapter is currently correctly wired to both CotS Host MCP and Unreal MCP for native inspection/mutation in the same session. This is a gap in agent-neutral tool parity, not a regression in the supervisor's turn-execution logic just fixed.

## Allowed scope
- `C:\Dev\CotSDeveloperTools\Scripts` (supervisor/adapter wiring, `CotSHostMcp.py`)
- Agent-local MCP configuration for Codex and Claude Code
- `C:\Dev\CotSDeveloperTools\ToolLab` for connectivity verification only
- Documentation under `Docs/`

## Forbidden scope
- No production CotS work (`C:\Dev\CotS`)
- No Shardlands mutation
- Do not touch supervisor turn-execution logic beyond what wiring MCP access requires
- Do not begin this task until the Claude-streaming fix (`02590ab`) is committed and pushed — it is

## Requirements
- Both adapters must be able to reach, in the same turn:
  - CotS Host MCP (`Scripts\CotSHostMcp.py`) — ToolLab lifecycle/build/test
  - Unreal MCP — native inspection/mutation per `Tasks/003_MCP_CONNECTIVITY.md` and `Tasks/004_NATIVE_MCP_CAPABILITY_AUDIT.md`
  - Existing CotS toolsets already exposed above those two servers
- Configuration must be symmetric: whatever Codex can reach, Claude must be able to reach, and vice versa. No agent-specific capability carve-outs.
- Preserve the single-mutating-agent lease (`AGENTS.md` "Agent concurrency safety") and the `CotSHostMcp` `agent_id` lock discipline. Read-only dual connectivity is fine; concurrent mutation against the same Unreal project/worktree is not.
- Do not duplicate native MCP functionality per the existing `Tasks/004` gap-first rule.

## Validation
Each adapter independently must, in one session:
1. connect to CotS Host MCP and acquire/release the `agent_id` lock cleanly;
2. connect to Unreal MCP and confirm project/editor identity;
3. enumerate available native Unreal toolsets;
4. enumerate available CotS-specific toolsets;
5. perform one read-only inspection call through each server.

Then verify the one-mutating-agent boundary still holds: with one agent holding the `CotSHostMcp` lock, confirm the other agent's mutation attempt is refused while its read-only MCP connectivity remains unaffected.

## Acceptance criteria
Both Codex and Claude can, without human reconfiguration mid-session, inspect and (when holding the lease) mutate through CotS Host MCP, Unreal MCP, and existing CotS toolsets on equal footing — and the single-mutating-agent lease still rejects concurrent mutation from the standby agent.
