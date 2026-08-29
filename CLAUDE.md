# Claude Code instructions

Read and obey `AGENTS.md` before making changes. It is the canonical cross-agent operating policy for this repository.

Task specifications live under `Tasks/`. Use the same specifications used by Codex; do not create Claude-specific implementation rules unless absolutely necessary.

For ToolLab lifecycle operations, use the loopback-only `CotSHostMcp` controller documented in `Docs/AUTONOMOUS_DEVELOPMENT.md`. Acquire its `agent_id` lock before opening, closing, building, or testing ToolLab.
