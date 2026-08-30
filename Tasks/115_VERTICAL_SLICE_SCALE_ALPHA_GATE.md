# TASK-115 — Integrated Vertical Slice, Scale & Alpha Engineering Gate

## Objective
Prove the production architecture end to end and identify the next evidence-backed engineering/content backlog before broad alpha production.

## Existing-work check
Use previous reuse manifests rather than re-crawling donor repositories wholesale. Inspect additional legacy work only where an integration gap points to it.

## Requirements
Build and automate a representative multiplayer vertical slice covering:
- platform identity/character selection and dedicated-server connection;
- persistence/reconnect;
- embodied player/animation/input;
- interaction/items/inventory/equipment;
- streamed world travel;
- world simulation/environment/resource change;
- settlement/NPC embodiment and knowledge;
- economy/crafting;
- law/ownership/property/contract consequence;
- combat;
- authoring pipeline-generated region;
- core UI/chat/voice boundaries.

Run scale/performance/profiling, soak/restart/recovery, persistence-integrity, network/adversarial-security and operational-observability tests at the largest practical automated scope. Record bottlenecks and confidence.

## Acceptance criteria
The vertical slice is reproducibly buildable/testable from clean state, survives representative multiplayer/restart/persistence scenarios, has measured performance/security evidence, and produces a prioritized next backlog based on observed gaps rather than assumptions. Do not declare alpha readiness merely because the slice runs.
