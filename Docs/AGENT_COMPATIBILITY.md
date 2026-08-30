# Agent Compatibility

## Goal
The CotS toolchain must not depend on one AI vendor. Codex and Claude Code are first-class clients of the same Unreal/MCP tool surface.

## Canonical instructions
- Cross-agent policy: `AGENTS.md`.
- Claude bootstrap: `CLAUDE.md` points to `AGENTS.md`.
- Task specifications: `Tasks/*.md`.

## Avoid
- Business logic hidden only in a Codex prompt/config.
- Claude-only Unreal implementations.
- Tool names that assume a specific model/vendor.
- Agent-specific output formats where a shared JSON/MCP schema works.

## Persistent supervisor

`Scripts\CotSAgentSupervisor.py` (`Tasks/008B_PERSISTENT_AGENT_SUPERVISOR.md`,
`Tasks/008C_SUPERVISOR_DASHBOARD.md`) drives both Codex and Claude through the
same checkpoint/lease contract and rotates between them automatically when one
hits a usage limit. It is the reference example of an agent-neutral
orchestration loop: `CodexAgent` and `ClaudeAgent` implement the same
`activate` / `run_turn` / `deactivate` shape.

## Compatibility gate
A foundation capability is not considered complete until either:
1. both Codex and Claude can invoke it successfully; or
2. the task documents an external client limitation and the underlying tool remains standards-compatible.
