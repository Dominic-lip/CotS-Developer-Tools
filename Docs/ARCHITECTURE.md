# CotS Developer Tools Architecture

## Purpose

CotS Developer Tools is the development factory for Chronicles of the Sigilarium. It is not the game and it is not a continuation of the Shardlands prototype. Its purpose is to let AI coding agents inspect, modify, compile, validate and test Unreal Engine projects through stable, reusable operations.

## Separation of concerns

```text
C:\Dev\
├── Shardlands\          donor/reference project
├── CotSDeveloperTools\  reusable factory (this repo)
└── CotS\                production MMO (created later)
```

Git histories remain separate.

## Agent-neutral control plane

```text
Codex ---------\
                >--- MCP / CLI contracts ---> CotS tools ---> Unreal Engine 5.8
Claude Code ---/
```

Epic's native Unreal MCP server is the preferred transport. CotS-specific toolsets add high-level domain operations only where native capabilities are missing or too low-level/unreliable.

## Layers

### 1. Native capability layer
Unreal MCP, Unreal Python, commandlets, editor scripting, Automation Framework, UnrealBuildTool and standard CLI tooling.

### 2. CotS core tooling layer
Stable result structures, diagnostics, asset addressing, transactions, validation conventions, safety/impact reporting and common helpers.

### 3. Domain toolsets
Inspection, Assets, Blueprint, Animation, MetaHuman, World, Data, Validation, Testing and later Shardlands migration.

### 4. Task orchestration
Markdown task specifications are intentionally client-neutral. `Scripts/Run-CotSTask.ps1` starts either Codex or Claude with the same specification.

## Tool contract
A mature mutating tool should be able to return equivalent information to:

```json
{
  "success": true,
  "operation": "example.operation",
  "dry_run": false,
  "changed_objects": [],
  "warnings": [],
  "errors": [],
  "validation": [],
  "duration_ms": 0
}
```

The exact MCP schema may evolve, but the semantic contract should remain stable.

## Safety model
Inspection is broadly allowed. Mutation is scoped. Bulk/destructive operations should expose impact before execution. Shardlands is read-only by policy until a task explicitly opts in. Git is a safety net, not permission to destroy work.

## Development strategy
Use the disposable Tool Lab first. Prove a generic capability there, turn repeated sequences into a high-level tool, test it with both agents, then use it against donor/production projects.
