# TASK-006 — Inspection Foundation

## Objective
Give agents reliable read-only understanding of an Unreal project before broad mutation is allowed.

## Target capabilities
- get Unreal/editor/project status
- search assets by path/name/class
- inspect exact asset object path/class/basic properties
- get dependencies and referencers
- inspect Blueprint metadata/components/variables/graphs where native APIs permit
- inspect skeleton/animation/AnimBP/Blend Space metadata
- inspect plugins/modules
- detect duplicate display names and return exact object paths

## Constraints
Use native MCP tools directly where adequate. Add CotS high-level tools only for missing/composite/reliability cases identified by TASK-004.

## Validation
Create ambiguous disposable assets with identical display names in different Tool Lab paths and prove the agent returns exact paths without confusing them.

## Acceptance criteria
An agent can answer 'what exactly is this asset and what does it depend on?' without screenshots or human clicking.
