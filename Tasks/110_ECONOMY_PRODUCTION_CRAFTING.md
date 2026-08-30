# TASK-110 — Economy, Production & Crafting

## Objective
Build a real goods/resource economy and production/crafting loop on top of canonical data, resources, settlements and inventory.

## Existing-work check
Inspect Shardlands markets/resources/recipes/processes/materials and any existing economy/crafting prototypes before implementing new chains.

## Requirements
- Goods supply/demand, stocks, shortages, prices and market state.
- Production chains consuming/producing canonical resources/goods with settlement capacity constraints.
- Player gathering/crafting/processing using authoritative inventory and canonical recipes/processes.
- Quality/provenance where already supported by design/data.
- Persistence and simulation-tier behavior for markets/production.
- Deterministic economy/crafting tests covering scarcity and invalid/duplicate transactions.

## Acceptance criteria
A representative raw resource can be gathered/produced, processed/crafted, traded through a market affected by supply/demand, persisted and observed consistently by multiple clients.
