# TASK-116 Reuse Decisions

All source paths and revisions are recorded in
`Docs/Production/TASK-116_RECONCILIATION_BASELINE.md`.  Classifications are
donor suitability decisions, separate from whether CotS already has a related
capability.

| Material | Classification | CotS present? | Decision, dependencies and confidence |
| --- | --- | --- | --- |
| Shard 115 stable appearance/presentation separation | ADAPT | Partly: TASK-104 stable recipe and input boundary. | Keep renderer-independent identity and local-only presentation rules.  Do not couple CotS authority to `ShardlandsCharacter` or dirty assets. High confidence. |
| Shard 115 MetaHuman Collection/Instance adapter | REFERENCE_ONLY | No verified renderer/content pipeline. | Experimental UE 5.8 API and donor notes record incomplete real content validation; use as a later proof checklist, not production code. High confidence. |
| Shard 116 entity-inspection snapshot/subsystem | ADAPT | No. | Potential privileged operations diagnostic after authentication/role/audit design.  Never replicate its authoritative fields to ordinary clients. Medium confidence. |
| Shard 117 gameplay fact bus | ADAPT | Partly: TASK-107 ledger. | Preserve post-authoritative-change publication, deduplication and isolated consumers; map facts to CotS event IDs/server time and do not introduce a competing authority store. High confidence. |
| Shard 118 event envelope/subsystem | ADAPT | No durable audit envelope. | Adopt only if persisted through CotS schema/migration/storage contracts and linked to the TASK-107 ledger. Medium confidence. |
| Shard 119 region types/registry | ADAPT | Partly: cells/travel only. | Add a production region hierarchy above spatial cells; reconcile stable IDs with persistence, settlement knowledge and authoring recipes. High confidence. |
| Non-numbered ecology/market/environment/playable-world subsystems | REIMPLEMENT | Contract fragments only. | Preserve domain questions and simulation inputs, but donor prototype actors/development subsystems are too coupled to Shardlands test worlds and lack a verified production orchestration/persistence boundary. Medium confidence. |
| Shardlands world authoring assets/toolkit | LEAVE | Recipe catalog only. | No actual development Shard-118 authoring toolkit was found.  Do not infer one from catalogue entries or bulk-copy assets. High confidence. |
| Website / Platform API / CotS-Game | REFERENCE_ONLY | External seams only. | Local checkouts and authoritative remote content were unavailable; retain the integration requirements as explicit work and do not fabricate protocol/database shapes. High confidence for access limitation; no code-suitability claim. |
