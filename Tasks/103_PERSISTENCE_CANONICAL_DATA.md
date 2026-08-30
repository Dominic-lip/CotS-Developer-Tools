# TASK-103 — Persistence & Canonical Data Foundation

## Objective
Create production-grade persistent identity/state and canonical gameplay-data foundations before higher-level systems depend on unstable formats.

## Existing-work check
Inspect Shardlands persistence orchestration, canonical data/compiler work, item/material/fluid/action/recipe/process/herb/resource datasets, plus relevant Platform API/database migrations.

## Requirements
- Define stable IDs, schema/version rules and migration strategy for persistent game state.
- Separate runtime simulation state, character/account state and canonical static data appropriately.
- Implement/test storage interfaces without coupling core gameplay to a single database transport.
- Productionize useful existing data compilers/loaders rather than manually recreating datasets.
- Add deterministic save/load/round-trip/version-migration tests and failure diagnostics.
- Record donor decisions in `Docs/Production/Reuse/TASK-103.md`.

## Acceptance criteria
Canonical data loads deterministically, persisted representative world/character state round-trips across process restart, incompatible versions fail/migrate explicitly, and later systems can depend on stable IDs/contracts.
