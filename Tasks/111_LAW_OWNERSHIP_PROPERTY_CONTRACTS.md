# TASK-111 — Law, Ownership, Property & Contracts

## Objective
Create authoritative legal/ownership systems that can support warrants, bounties, crime, property and durable player/NPC agreements.

## Existing-work check
Inspect Shardlands law/settlement/ownership/warrant prototypes plus persistence/identity assumptions. Reuse design/implementation only where consistent with current contracts.

## Requirements
- Durable ownership/permission model for items, property and relevant world entities.
- Crime/witness/recognition/warrant/bounty state with clear authoritative evidence rules.
- Property/tenancy/access primitives appropriate to the game design.
- Versioned contract/agreement records and fulfillment/breach hooks for later content systems.
- Integration with NPC knowledge, settlements, economy and persistence.
- Adversarial multiplayer tests for spoofed ownership/crime/contract requests.

## Acceptance criteria
Representative theft/crime/warrant/property/contract flows execute under server authority, persist across reconnect/restart, propagate relevant knowledge/consequences and reject forged client state.
