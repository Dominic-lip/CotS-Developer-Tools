# TASK-117 Reuse Decision — Operations, Event Observability and Regional Diagnostics

## Sources reconciled

- `Docs/Production/TASK-116_RECONCILIATION_BASELINE.md` records the actual
  Shardlands development-shard revisions and source paths: Shard 116 entity
  inspection (`43769a9`), Shard 117 gameplay event bus (`624ef25`), Shard 118
  event envelope (`96d591d`), and Shard 119 region registry (`0b6ddf0`).
- `Docs/Production/Reuse/TASK-116.md` records their existing compatibility
  classifications against the TASK-107 ledger and TASK-106 spatial foundation.
- Production inspection is currently limited to the fixed campaign adapter.
  Its `status` result on 2026-09-04 found no running editor; its Git inspection
  is blocked by the sandbox identity's dubious-ownership protection.

## Decisions

| Material | Decision | Production direction |
| --- | --- | --- |
| Shard 117 gameplay fact bus | ADAPT | Publish only after an authoritative state change, deduplicate event IDs and isolate audit/telemetry consumers. It must not become a second gameplay authority store. |
| Shard 118 event envelope | ADAPT | Use an explicit schema version and migration seam linked to the current event ledger/persistence contract; do not copy donor subsystem coupling. |
| Shard 116 entity inspection | ADAPT | Keep diagnostics server-only and role-gated; no authoritative fields may be replicated to ordinary clients. |
| Shard 119 region registry | ADAPT | Carry an opaque hierarchy-compatible region ID in operational envelopes; region ownership remains a later durable registry concern. |
| Non-numbered prototype world subsystems | REIMPLEMENT | Their world/actor coupling is unsuitable for the production authority and persistence boundaries. |

## Current implementation checkpoint

`task-117-operations.json` is a bounded manifest for a new server-only
observability subsystem and its focused automation test. It has not been
applied: the fixed `CotSProductionLifecycleCampaign.py apply-manifest` operation
returned `WinError 5` for the destination production directory. No source was
written, compiled, or staged in `C:\Dev\CotS`.
