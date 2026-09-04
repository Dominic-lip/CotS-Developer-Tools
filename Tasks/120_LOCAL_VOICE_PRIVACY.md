# TASK-120 — Real Local Voice Provider & Privacy Proof

## Authorization
This task is explicitly authorized to modify `C:\Dev\CotS` through the fixed campaign production lifecycle adapter. External provider/account configuration that requires credentials, purchases, billing or irreversible account changes remains a genuine human gate.

## Objective
Replace the TASK-114 voice policy seam with a production-ready local-area voice integration boundary while preserving consent, privacy, moderation and authority requirements.

## Required work
- select/reconcile an available voice-provider integration seam without embedding secrets;
- positional/local-area channel membership driven by authoritative spatial/identity state;
- mute/block/consent propagation and reconnect behaviour;
- moderation/reporting audit events integrated with TASK-117 observability;
- retention/deletion policy hooks and deterministic mocks for provider-unavailable tests;
- graceful degradation when real provider credentials are absent.

## Acceptance
- focused tests prove local-area membership, mute/block/consent, reconnect and unauthorized channel rejection;
- provider-unavailable mode remains playable and deterministic;
- production editor/game/server builds pass;
- no secrets committed or written to gameplay state/logs;
- real-provider credential/account step, if required, is isolated as the only human gate rather than blocking all other engineering.
