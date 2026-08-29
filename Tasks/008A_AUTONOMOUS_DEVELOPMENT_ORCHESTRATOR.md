# TASK-008A — Autonomous Development Orchestrator

## Objective

Provide an agent-neutral, loopback-only Host MCP controller so Codex and Claude can safely manage the disposable ToolLab lifecycle without manual editor clicks.

## Scope

- fixed ToolLab status, open, graceful-close, MCP-readiness, build, and CotS automation operations;
- a persistent single-mutating-agent lock and ignored local resume checkpoint;
- a launcher and compatible MCP connection documentation.

## Explicit non-goals

The host must not expose arbitrary shell/PowerShell/cmd execution, arbitrary process launch or PID termination, or arbitrary filesystem operations. It binds only to `127.0.0.1` and may close only the ToolLab process it recorded as having launched itself.

## Lifecycle proof

Acquire the lock, open ToolLab, close it automatically, build, test, reopen, wait for Unreal MCP, perform a harmless inspection, close, reopen, and verify that the lifecycle remains ready. Release the lock after the proof.

## Final shutdown architecture

The primary close path is the fixed editor-only `CotSDeveloperTools.CotSLifecycleToolset.RequestToolLabShutdown` UE MCP tool, reached only through UE 5.8's fixed `call_tool` dispatcher parameters. It validates ToolLab context, modal/PIE state, and persistent dirty packages before issuing `FPlatformMisc::RequestExit(false)`. The Host independently observes the exact launched PID and loopback UE MCP endpoint; acknowledgement means only that exit was requested. A lifecycle refusal (including `dirty_packages_present`) is returned without a WM_CLOSE fallback. WM_CLOSE is retained solely as a constrained fallback for MCP transport failure and an owned ToolLab window.
