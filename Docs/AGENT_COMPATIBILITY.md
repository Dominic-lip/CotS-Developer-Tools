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

## Compatibility gate
A foundation capability is not considered complete until either:
1. both Codex and Claude can invoke it successfully; or
2. the task documents an external client limitation and the underlying tool remains standards-compatible.
