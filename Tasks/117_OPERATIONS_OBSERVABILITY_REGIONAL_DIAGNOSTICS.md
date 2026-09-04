# TASK-117 — Operations, Event Observability & Regional Diagnostics

## Authorization
This task is explicitly authorized to modify `C:\Dev\CotS` through the fixed campaign production lifecycle adapter. `C:\Dev\Shardlands` remains read-only. Website/API/Game peers are read-only unless this task only records integration contracts.

## Objective
Build the operational/event-observability foundation required before serious soak and recovery testing. Reconcile existing CotS TASK-107/103/106/114 work and the TASK-116 donor findings first; implement only the missing production delta.

## Required work
- production event envelope tied to stable event IDs/server time and versioned persistence;
- metrics/traces/structured operational events for authoritative gameplay boundaries;
- region-aware diagnostics compatible with CotS spatial cells and Shard-119 region concepts;
- privileged diagnostic access policy with authorization/audit, never ordinary-client replication of sensitive authority state;
- alertable failure counters and deterministic failure-injection seams;
- no competing gameplay authority store.

## Acceptance
- production editor/game/server builds pass;
- focused Unreal automation proves server-only dispatch, stable event identity, deduplication, persistence/migration and authorization rejection;
- failure injection produces observable metrics/traces without corrupting authoritative state;
- existing-work decision recorded under `Docs/Production/Reuse/TASK-117.md`;
- durable validation evidence committed before marking COMPLETE_VERIFIED.
