# TASK-119 — External Platform Integration & Security Hardening

## Authorization
This task is explicitly authorized to modify `C:\Dev\CotS` through the fixed campaign production lifecycle adapter. Shardlands remains read-only. Website, Platform API and CotS-Game peers are read-only unless a later explicit task authorizes mutation in those repositories.

## Objective
Bind the production game to reachable platform identity/session/discovery contracts without weakening TASK-102 authority, and harden the resulting network/security boundary.

## Required work
- re-check reachable Website / Platform API / CotS-Game revisions before coding;
- define a versioned authenticated adapter preserving token secrecy and character ownership;
- integrate secure server/session discovery and negative authorization paths;
- add bounded RPC fuzz/rate-limit/invalid-input tests and audit events;
- add moderation/security telemetry needed by operations;
- if peers remain inaccessible, implement only the game-side adapter contract and exact mocks, recording the limitation rather than inventing peer schemas.

## Acceptance
- positive and negative identity/session/ownership/discovery integration proofs;
- rate-limit, malformed request and unauthorized mutation tests pass;
- production editor/game/server builds pass;
- no secret/token material is persisted in gameplay saves or logs;
- exact peer revision/access evidence and reuse decision recorded before COMPLETE_VERIFIED.
