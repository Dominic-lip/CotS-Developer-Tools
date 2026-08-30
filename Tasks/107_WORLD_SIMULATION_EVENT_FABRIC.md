# TASK-107 — World Simulation Fabric & Gameplay Event Integration

## Objective
Productionize the useful world-simulation and gameplay-event foundations without blindly transplanting legacy shard structure.

## Existing-work check
Deep-inspect the current local Shardlands implementations associated with Shard-116 world simulation and Shard-117 gameplay event integration, including dependencies and any newer/unpushed files. Treat Shardlands as read-only.

## Requirements
- Reconcile simulation-cell model with TASK-106 spatial tiers and TASK-103 persistence/versioning.
- Integrate deterministic simulation stepping/orchestration for relevant domains already implemented.
- Establish typed world-to-gameplay event contracts with ordering/idempotency expectations where required.
- Ensure simulation can run without requiring every represented entity to be a loaded Actor.
- Provide snapshot/restore and deterministic/replay-oriented tests for representative cells/events.
- Do not deepen every environmental domain here; TASK-108 owns that depth.
- Record detailed reuse/adapt/reimplement decisions in `Docs/Production/Reuse/TASK-107.md`.

## Acceptance criteria
A representative world cell can simulate, persist/restore and emit typed gameplay-relevant events through production contracts, with deterministic automated evidence and no dependency on wholesale Shardlands migration.
