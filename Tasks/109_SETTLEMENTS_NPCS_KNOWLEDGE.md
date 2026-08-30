# TASK-109 — Settlements, NPC Population & Knowledge

## Objective
Connect strategic settlement/population simulation to embodied NPC gameplay without simulating every NPC as an always-loaded Actor.

## Existing-work check
Inspect Shardlands settlement, law, knowledge/rumour, strategic movement, routes and NPC prototypes relevant to this task.

## Requirements
- Settlement population/resources/services/state at simulation level.
- NPC identity/state suitable for off-screen strategic simulation and on-screen embodiment handoff.
- Strategic movement/migration/routes integrated with TASK-106/107.
- Knowledge/rumour provenance, propagation and decay suitable for quests/law/economy/social consequences.
- Deterministic spawn/despawn embodiment bridge preserving NPC identity and persistent state.
- Multiplayer/streaming tests for representative NPC handoff.

## Acceptance criteria
A simulated settlement and named NPC population evolve off-screen, relevant NPCs embody correctly when players arrive, state survives unload/reload, and knowledge/events propagate through typed production contracts.
