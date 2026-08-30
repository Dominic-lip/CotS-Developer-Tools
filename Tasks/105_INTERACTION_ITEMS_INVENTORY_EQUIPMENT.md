# TASK-105 — Interaction, Items, Inventory & Equipment

## Objective
Establish authoritative player interaction and possession/equipment semantics before crafting, economy and combat depend on them.

## Existing-work check
Inspect Shardlands world-interaction work, item tables/data compiler, inventory/equipment components and older authoritative equipment/combat foundations. Reconcile with TASK-103 IDs and TASK-101 authority rules.

## Requirements
- Generic server-validated interaction contract with distance/authority/target identity checks.
- Item instance vs item definition identity, ownership and persistence semantics.
- Authoritative inventory transfer/add/remove/split where applicable.
- Equipment slots and main-hand/equipped-state replication.
- Player-facing prompt/radial/UI hooks without putting authority in widgets.
- Automated multiplayer possession/equipment/invalid-request tests.
- Record donor decisions in `Docs/Production/Reuse/TASK-105.md`.

## Acceptance criteria
Players can interact with world items, acquire/transfer/equip them under server authority, persistent identity remains stable, invalid client requests are rejected, and replicated state is observable by other clients.
