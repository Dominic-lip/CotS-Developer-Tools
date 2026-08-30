# TASK-114 — Player UI, Social, Text Chat & Local Voice

## Objective
Build production player-facing interfaces and social communication on top of authoritative gameplay services rather than embedding game truth in widgets.

## Existing-work check
Inspect Shardlands interaction/inventory/debug UI, existing CotS website identity/social assumptions and any existing chat/voice integration work relevant to the production contract.

## Requirements
- Production HUD/status, interaction prompts/radials, inventory/equipment and key system feedback.
- Text chat channels appropriate to current design with identity/moderation hooks.
- Local-area voice architecture with positional/proximity boundaries, mute/block/privacy/moderation interfaces and server/session integration.
- Social identity hooks suitable for party/guild/company expansion without requiring all future features now.
- UI automation/accessibility/state tests where practical.

## Acceptance criteria
Multiple authenticated players can interact through the core UI, exchange authorized text chat and exercise the local-voice integration boundary in a test environment, while gameplay authority remains outside UI code.
