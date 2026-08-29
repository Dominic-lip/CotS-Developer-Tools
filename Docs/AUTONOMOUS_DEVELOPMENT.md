# Autonomous ToolLab development

`Scripts\CotSHostMcp.py` is the local, agent-neutral lifecycle controller. Start it with `Scripts\Start-CotSHostMcp.cmd`; it binds exclusively to `http://127.0.0.1:8010/mcp`.

It exposes only these fixed MCP operations: `GetToolLabStatus`, lock acquire and release, `OpenToolLab`, `CloseToolLab`, `WaitForUnrealMcp`, `BuildToolLab`, and `RunCotSAutomation`. Every operation that can change ToolLab state requires an `agent_id` that owns the controller's single-writer lock. The controller records only its own launched editor PID in `.cots/host-state.local.json`.

`CloseToolLab` opens a UE 5.8 HTTP MCP session internally and invokes only `CotSDeveloperTools.CotSLifecycleToolset.RequestToolLabShutdown` through UE's `call_tool` search dispatcher. That editor-only tool rejects non-ToolLab contexts, active Slate modals, active PIE (after requesting a clean PIE stop), and persistent dirty packages; it then calls UE's normal non-forced `FPlatformMisc::RequestExit(false)`. The Host verifies the exact recorded PID and MCP endpoint disappear before reporting a graceful `unreal_mcp` close. WM_CLOSE is a constrained fallback only when the recorded process owns a suitable top-level window; the controller has no generic Unreal-MCP proxy or public force-kill operation.

If the lifecycle tool refuses its safety preconditions, `CloseToolLab` returns that structured refusal and does not try WM_CLOSE. This preserves dirty-package safety rather than converting a refusal into a close attempt.

The controller does not accept shell text, executable paths, arbitrary command arguments, filesystem paths, or target PIDs. Build and test commands are fixed to the canonical build script and the `CotS` automation invocation with the in-memory DDC workaround. Local lock/checkpoint state is intentionally ignored.

Typical agent sequence: acquire a stable agent ID, close ToolLab, build, run tests, open, wait for `http://127.0.0.1:8000/mcp`, use native Unreal MCP for inspection/mutation, close when finished, then release the lock. Do not use this controller to evade the repository's broader single-mutating-agent policy.
