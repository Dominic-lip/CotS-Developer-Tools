# TASK-102 — Platform Identity, Authentication & Character Contract

## Objective
Make website/platform identity and the game/server identity model one coherent contract rather than parallel implementations.

## Existing-work check
Deep-inspect the relevant portions of `Dominic-lip/CotS-Website` and `Dominic-lip/CotS-Platform-API` plus any Shardlands account/login assumptions before creating new schemas or endpoints.

## Requirements
- Inventory existing account/auth/session/character/database/server-discovery contracts and migrations.
- Define stable account, character and game-session identifiers and trust boundaries.
- Implement the game/server side of authentication/session validation and character ownership/selection against an explicit versioned interface.
- Avoid embedding website-only implementation details in Unreal runtime code.
- Add integration-contract tests with safe local/test doubles where live services are inappropriate.
- Any cross-repository API/database change must be explicit, backward-compatible where practical, and included in task scope before mutation.
- Record donor/integration decisions in `Docs/Production/Reuse/TASK-102.md`.

## Acceptance criteria
A test account/session can be validated through the production contract, character ownership/selection is authoritative and unambiguous, identifiers persist across boundaries, and Website/Platform/Game assumptions no longer conflict.
