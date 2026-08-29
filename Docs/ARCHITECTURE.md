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

Each domain begins as an interface under `UnrealPlugin/CotSDeveloperTools/Source/CotSDeveloperTools/Public/Domains`. Domain toolsets depend on Core/common facilities and must not form dependencies on other domains.

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

The foundation implementation additionally emits `operation_id`, `status`, `schema_version`, `affected_object_paths`, and `error_details` (`code` and `message`). `changed_objects` remains for compatibility with the original schema. Tools return this envelope as JSON text, so it is machine-readable through both direct MCP registration and tool-search dispatch.

The development-only Execution toolset is intentionally a constrained read-only query
surface, not arbitrary Python, console, shell, or UObject invocation. UE 5.8's Python
plugin has useful result/log capture but no reliable sandbox for submitted code. See
`Docs/EXECUTION_BRIDGE.md`; expand novel workflows into typed domain toolsets rather
than broadening the execution surface.

## Mutation convention

Future mutating tools validate and enumerate their impact before opening a transaction. They accept a dry-run/preview mode where practical, open `FCotSEditorMutationScope` only for a real mutation, call `Modify()` on every changed UObject, and return every affected object path in the shared result envelope. Repeatable operations should detect an already-satisfied desired state and report it without creating duplicate content.

### Safe mutation primitives (TASK-008)

`CotSMutationToolset` is a guarded composite layer, not a replacement for Epic's native MCP `AssetTools`, `ActorTools`, `BlueprintTools`, `DataAssetTools`, or `DataTableTools`. Agents should use those native tools directly for ordinary atomic lifecycle, compile, and schema operations. CotS adds exact `/Game/...Asset.Asset` identity validation, preview/impact envelopes, disposable-delete boundaries, typed `UCurveFloat.bIsEventCurve` mutation, idempotent actor/component operations, transaction reporting, and re-inspection guidance.

Asset creation, rename/move, duplicate, deletion, and save are package-backed and explicitly reported as non-undoable. Typed UObject property changes and scene actor/component changes open `FCotSEditorMutationScope` and call `Modify()` before mutation. Deletion is restricted to `/Game/CotSMutationLive/`; disposable actors and components require the `CotSMutation_` prefix.

## MCP registration

UE 5.8 registers a `UToolsetDefinition` with `UToolsetRegistry::RegisterToolsetClass`. Its static `UFUNCTION(meta=(AICallable))` methods become tool definitions. The installed `ModelContextProtocolEditor` module observes Toolset Registry registration and adapts the toolset into MCP; with tool search enabled it is available via `list_toolsets`, `describe_toolset`, and `call_tool`, otherwise it is exposed directly in `tools/list`. `UCotSFoundationToolset::GetStatus` is the deliberately minimal registration proof.

## Safety model
Inspection is broadly allowed. Mutation is scoped. Bulk/destructive operations should expose impact before execution. Shardlands is read-only by policy until a task explicitly opts in. Git is a safety net, not permission to destroy work.

## Development strategy
Use the disposable Tool Lab first. Prove a generic capability there, turn repeated sequences into a high-level tool, test it with both agents, then use it against donor/production projects.
