# TASK-116 Next Production Roadmap

These are authorization-ready proposals, not permission to mutate CotS.  Each
task must receive its own explicit scope and repeat the just-in-time reuse
check before any production modification.

| Order | Proposal | Backlog mapping and why now | Existing-work starting point | Required acceptance |
| --- | --- | --- | --- | --- |
| TASK-117 | Operations, event observability and regional diagnostics | P0 operations; makes later soak/recovery measurable. | Adapt Shard 117 fact publication, Shard 118 envelope and, only after role design, Shard 116 inspection; add the Shard 119-compatible region seam. | Server-only event dispatch with durable schema/migration, trace/metric/alert contracts, authorization/audit coverage and failure-injection proof. |
| TASK-118 | Scale, soak and recovery engineering gate | P0 scale/soak; depends on TASK-117 observability. | Extend TASK-101 workers and TASK-103 persistence through fixed production lifecycle operations. | Sustained multi-client CPU/memory/bandwidth measurements, controlled server/persistence restart recovery, corruption/idempotency checks and reproducible thresholds. |
| TASK-119 | External platform integration and security hardening | P1 security/platform; should not invent peers before access evidence. | Re-inspect reachable Website/Platform API/CotS-Game first; retain TASK-102 contracts if peers remain unavailable. | Versioned authenticated contract, ownership/discovery integration, RPC fuzz/rate-limit tests, moderation audit trail and negative authorization proofs. |
| TASK-120 | Real local voice provider and privacy proof | P1 voice; depends on authenticated identity and audit policy. | TASK-114 social/voice policy seam. | Provider integration with positional audio, consent, block/mute propagation, moderation reporting and retention/deletion behaviour under test. |
| TASK-121 | Representative persistent streamed world-content slice | P1 content; consumes operations, regions and scale evidence. | CotS authoring recipes, Shard 119 region model and only selected non-numbered ecology/world concepts. | Authored terrain/water/biome/settlement/no-spawn inputs, deterministic generated-output provenance, persistent streamed multiplayer traversal and recovery proof. |

The order deliberately does not treat numeric Shard 116 or 118 labels as
simulation or authoring implementation.  Those donor capabilities are mapped
by their actual source evidence above.
