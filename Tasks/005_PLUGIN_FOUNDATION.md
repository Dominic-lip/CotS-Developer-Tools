# TASK-005 — CotSDeveloperTools Plugin Foundation

## Objective
Turn the initial plugin scaffold into the stable base for future high-level CotS MCP/editor tools.

## Prerequisite
TASK-004 capability audit complete.

## Allowed scope
CotSDeveloperTools plugin, Tool Lab, schemas, tests and docs.

## Forbidden scope
No production game or Shardlands mutation.

## Requirements
- Compile the existing plugin against the actual UE 5.8 installation and fix API drift.
- Preserve editor-only packaging unless a runtime dependency is justified.
- Establish shared result/error structures compatible with `Schemas/tool-result.schema.json`.
- Establish scoped logging and operation IDs.
- Add transaction/undo support conventions for editor mutations.
- Add domain folders/interfaces for Inspection, Assets, Blueprint, Animation, MetaHuman, World, Data, Validation and Testing without prematurely implementing all domains.
- Bind custom MCP toolsets only after inspecting actual local UE 5.8 MCP APIs.

## Validation
Clean build, editor startup, module load, existing console smoke tests and one automated plugin test.

## Acceptance criteria
A small, boring, stable plugin base that later toolsets can extend without coupling to a specific AI client.
