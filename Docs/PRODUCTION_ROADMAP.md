# CotS Production Roadmap

## Operating model
Execute tasks in dependency order. Every task starts with the just-in-time existing-work check in `Docs/EXISTING_WORK_REUSE_POLICY.md`, then implements only the production delta still required.

A task may conclude that substantial donor code can be reused or that production already satisfies part of the objective. That is desirable when verified; do not manufacture rewrites to make a task look larger.

## Sequence

### TASK-100 — Production Baseline & Existing-Work Index
Reconcile `C:\Dev\CotS`, establish a shallow source index across Shardlands/Website/Platform-API and verify deterministic production build/test/lifecycle foundations. Do not deep-audit every subsystem yet.

### TASK-101 — Runtime, Networking & Dedicated-Server Foundation
Establish production module boundaries, authority/replication conventions, dedicated-server targets, network test harness and runtime service boundaries.

### TASK-102 — Platform Identity, Authentication & Character Contract
Reconcile game identity with CotS Website/Platform API work: accounts, authentication/session contract, character ownership/selection and server/session discovery boundaries.

### TASK-103 — Persistence & Canonical Data Foundation
Create authoritative persistent identity/data contracts, storage interfaces, versioning/migrations, canonical gameplay data loading and deterministic save/restore tests.

### TASK-104 — Embodied Player, MetaHuman, Animation & Input
Build the production player embodiment and locomotion stack, using Shardlands/Shard-115 work and existing animation tooling where valuable.

### TASK-105 — Interaction, Items, Inventory & Equipment
Establish server-authoritative interaction/item ownership/inventory/equipment flows and integrate canonical item definitions.

### TASK-106 — World Partition, Streaming & Spatial/Travel Foundation
Create world-space, partition/streaming, spawn/travel and spatial service foundations suitable for the MMO and simulation layers.

### TASK-107 — World Simulation Fabric & Gameplay Event Integration
Integrate/productionize the relevant Shard-116 world-simulation fabric and Shard-117 gameplay event work around current production authority, streaming and persistence contracts.

### TASK-108 — Climate, Hydrology, Ecology, Resources & Disturbances
Deepen environmental simulation domains: seasons/climate, water, flora/fauna, resources, fire/flood/disease and recovery/propagation.

### TASK-109 — Settlements, NPC Population & Knowledge
Build settlement simulation, NPC population/runtime boundaries, strategic movement, knowledge/rumour propagation and player-facing handoff from simulation to embodied NPCs.

### TASK-110 — Economy, Production & Crafting
Implement goods, supply/demand, prices, shortages, production chains, crafting/gathering and resource-to-market integration.

### TASK-111 — Law, Ownership, Property & Contracts
Implement authority-backed ownership, warrants/bounties, crime/recognition, property, contracts and persistence/integration boundaries.

### TASK-112 — Combat & Adversarial Runtime Security
Productionize server-authoritative combat and equipment interaction, then validate exploit boundaries, RPC/input validation and anti-cheat/security assumptions.

### TASK-113 — World Authoring & Content Production Pipeline
Productionize the useful Shard-118 authoring toolkit: terrain/water/biomes/routes/settlements/masks/macro authoring and reproducible generated-content workflows.

### TASK-114 — Player UI, Social, Text Chat & Local Voice
Build production HUD/interaction/inventory/social flows plus text chat and local-area voice boundaries, integrated with authority/privacy/moderation requirements.

### TASK-115 — Integrated Vertical Slice, Scale & Alpha Engineering Gate
Prove an end-to-end multiplayer slice across identity, server authority, persistence, player embodiment, interaction, world streaming/simulation, economy/NPC/law/combat and authoring. Perform scale/performance/security/observability tests and produce the evidence-backed next backlog rather than assuming alpha readiness.

### TASK-116 — Post-Vertical-Slice Existing-Work Reconciliation
Before authorizing the next implementation wave, reconcile current CotS production against the freshest reachable Shardlands work — especially Shards 115–119 — and the Website/Platform-API/CotS-Game peers. Produce an evidence-backed dependency/capability/reuse matrix and a TASK-117+ roadmap. TASK-116 is read-only for CotS production, Shardlands and peer repositories; only DeveloperTools evidence/roadmap/scheduler artifacts may be changed.

## Completion rule
Do not skip foundational dependencies simply because a donor implementation exists. Conversely, do not rewrite a subsystem when the donor/production implementation already meets the current contracts and passes production validation. The acceptance evidence decides. TASK-116 must complete before any post-115 implementation backlog item is promoted into an authorized production-mutation task.
