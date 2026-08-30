# TASK-113 — World Authoring & Content Production Pipeline

## Objective
Turn the useful world-authoring work into production tools that generate/edit world content reproducibly against current simulation/spatial contracts.

## Existing-work check
Deep-inspect the current local Shardlands Shard-118 World Authoring Toolkit and related terrain/water/biome/route/settlement/no-spawn/macro tooling before building replacements.

## Requirements
- Production-safe terrain raise/lower/flatten and macro terrain operations where appropriate.
- River/stream/coastal/water-type authoring integrated with hydrology and seabed/biome rules.
- Biome/forest/desert masks, roads/routes, settlement placement and no-spawn/constraint masks.
- Deterministic preview/validation, undo/transaction semantics and affected-area reporting.
- Generated outputs must be inspectable/reproducible and compatible with world partition/source control.
- Separate reusable production tools from experimental Shardlands-only code.

## Acceptance criteria
An agent can author and validate a representative production region through tools rather than manual click sequences, generated world data integrates with streaming/simulation, and the workflow is repeatable from source-controlled inputs.
