# TASK-116 Post-Vertical-Slice Reconciliation Baseline

## Scope and method

This is a read-only reconciliation captured on 2026-09-04.  The only changed
repository is `C:\Dev\CotSDeveloperTools`, for this evidence and its roadmap
records.  CotS, Shardlands and the peer repositories were inspected without
checkout, reset, clean, build, editor, asset or source mutation.

## Reachable source revisions and freshness

| Source | Direct observation | Freshness / limitation |
| --- | --- | --- |
| `C:\Dev\CotS` | `699291955328cc2b29e5c4425ef56a77513b040c`, `main`, clean; latest subject `Add TASK-114 social communication authority` (2026-09-03T17:35:53+01:00). | Production is read-only for this task.  TASK-115 validated this same head; no later production commit was observed. |
| `C:\Dev\Shardlands` | `64f5ca409fab5ccb62d09edde013cdc4fa67649c`, `feature/shard-115-embodied-player`; latest subject `Clean up CotS MetaHuman player assets` (2026-08-27T02:14:15+01:00). | Worktree is dirty: two tracked MetaHuman assets deleted, `Shardlands.uproject` and two embodied-character files modified, and untracked audio, MetaHuman, player, `Data`, `SourceAssets`, `CotS_MD` and `sharddata.py` paths.  Local files are therefore newer evidence than the ref where applicable. |
| `origin/feature/shard-115-metahuman-character-framework` | `066c5ca57433df696af89c716a244c11fa7c3848` (2026-08-23). | Reachable local remote-tracking ref. |
| `origin/feature/shard-116-entity-inspector` | `43769a95357d7439d0eb0caedf2e96f67e749bee` (2026-08-17). | Reachable local remote-tracking ref. |
| `origin/feature/shard-117-gameplay-event-bus` | `624ef254670ce90f7709e97f595f0f9208f27b04` (2026-08-17). | Reachable local remote-tracking ref. |
| `origin/feature/shard-118-event-envelope` | `96d591d71edcceb6a9e03af9473518055780fde6` (2026-08-17). | Reachable local remote-tracking ref. |
| `origin/feature/shard-119-world-region-identity` | `0b6ddf04536afc15d8cd2be98d768883e4e1ce30` (2026-08-17). | Reachable local remote-tracking ref. |
| `C:\Dev\CotS-Website`, `C:\Dev\CotS-Platform-API`, `C:\Dev\CotS-Game` | No local checkout exists.  Direct GitHub page fetches for each returned `Cache miss`; search did not return an authoritative repository result. | No revision or contract contents are asserted.  This is an access limitation, not evidence of absence. |

## Development-shard identity map

The map is established from branch names, commit subjects and concrete source or
documentation paths.  `Docs/Roadmap/FeatureCatalogue.md` is a separate
numbered catalogue and was deliberately not used to identify these shards.

| Development shard | Evidence and actual implementation | Expected-domain result | CotS production comparison |
| --- | --- | --- | --- |
| 115 | Local branch `feature/shard-115-embodied-player` at `64f5ca4`; `Docs/SHARD-115-METAHUMAN-CHARACTER-FRAMEWORK.md`; `Source/ShardlandsMetaHuman/Public/ShardlandsMetaHumanPresentationComponent.h`; local modified `Source/Shardlands/Character/ShardlandsEmbodiedCharacterComponent.{h,cpp}`. | Confirmed embodied player, optional MetaHuman presentation, appearance and local camera work.  Its own notes retain real Collection/content validation as incomplete. | TASK-104 already has stable appearance and Enhanced Input, but no verified production MetaHuman Collection/renderer or representative character content. |
| 116 | `origin/feature/shard-116-entity-inspector` at `43769a9`; `Source/Shardlands/Operations/ShardlandsEntityInspectionTypes.h` and `ShardlandsEntityInspectionSubsystem.{h,cpp}`. | Expected world-simulation fabric is **absent from this shard**.  Actual shard is a privileged, non-ordinary-client replicated entity-inspection snapshot with persistent identity, transform, revision and authoritative fields. | No equivalent production operations/diagnostics inspector was found in TASK-101..115 contracts. |
| 117 | `origin/feature/shard-117-gameplay-event-bus` at `624ef25`; `Source/Shardlands/World/ShardlandsGameplayEventBusSubsystem.{h,cpp}`. | Confirmed gameplay-to-world integration: an in-process authoritative fact bus publishes deduplicated facts after state change to telemetry/audit/Chronicle consumers.  It is not the wider world-simulation fabric. | TASK-107 has a server-time, ordered, idempotent ledger, but no producer/consumer integration or telemetry/audit adapters. |
| 118 | `origin/feature/shard-118-event-envelope` at `96d591d`; `Source/Shardlands/World/ShardlandsEventEnvelope.{h,cpp}` and subsystem. | Expected terrain/water/biome/road/river/settlement authoring toolkit is **absent from this shard**.  Actual shard is a durable/auditable, schema-versioned envelope around a gameplay fact. | TASK-113 has a deterministic recipe catalog only; it has neither a real authored-world pipeline nor durable event-envelope persistence. |
| 119 | `origin/feature/shard-119-world-region-identity` at `0b6ddf0`; `Source/Shardlands/World/ShardlandsRegionTypes.h` and `ShardlandsRegionRegistrySubsystem.{h,cpp}`. | Actual implementation discovered: hierarchical realm/crown-land/duchy/barony/settlement/local-area identity and parent validation.  The prior climate/hydrology inference is disproven. | TASK-106 spatial cells and named travel lack a durable hierarchical region identity usable by simulation, authoring and operations. |

Relevant non-numbered donor evidence exists under
`Source/Shardlands/World/`: `ShardlandsEcologySubsystem`,
`ShardlandsMarketBoardActor`, `ShardlandsEconomySubsystem`,
`ShardlandsEnvironmentTransitionSubsystem`, and playable-world subsystems.
They are prototype/development-world dependencies, not proof that development
Shard 116 is the required complete simulation fabric.  No self-contained
Shard-118 world-authoring toolkit was found; TASK-113's earlier finding remains
valid.

## Current production capability and dependency matrix

| Production area | Verified current boundary | Existing-work relationship / missing glue |
| --- | --- | --- |
| Runtime/networking (101) | Dedicated-server build and two-worker authority/reconnect automation. | Needs measured soak, restart recovery and telemetry before scale claims. |
| Identity/persistence (102-103) | Token-free account/character/session seam; versioned canonical data and deterministic persistence adapter. | Website/Platform API issuer, credential, database and discovery contracts remain uninspected and unintegrated. |
| Embodiment/items/combat (104-105,112) | Stable appearance/input, owner-gated inventory and authoritative combat intents. | Shard 115 offers an optional renderer adapter only; real MetaHuman assets/content remain a later proof. |
| Spatial/simulation/economy/law (106-111) | Spatial travel, event ledger, renewable, settlement knowledge, goods and warrant contracts. | Missing region hierarchy, fact-bus/envelope adapters, world-time orchestration, material simulation and observability. |
| Authoring/social (113-114) | Recipe catalog; authenticated social text and local-voice policy seam. | Missing actual terrain/water/biome content pipeline, provider voice integration, consent/block/mute propagation and moderation retention. |

## Duplicates, conflicts, stale boundaries and missing work

- **Duplicate concepts:** CotS event ledger overlaps Shard 117 fact identity and
  Shard 118 envelopes; retain CotS authority and adapt only a compatible
  producer/consumer and audit shape, rather than run parallel ledgers.
- **Conflict:** Shard 115 is coupled to experimental UE 5.8 MetaHuman
  Collection/Instance APIs and locally dirty assets; production's stable
  renderer-independent recipe remains controlling.
- **Stale boundary:** TASK-102/103/114 correctly avoided inventing external
  contracts, but this means platform integration is still explicitly deferred.
- **Missing glue:** CotS has no region hierarchy between spatial cells and
  settlements, no event dispatch/audit persistence, and no operations-grade
  metrics/traces/alerts.
- **Genuinely missing work:** soak/recovery measurement, operational failure
  injection, authenticated abuse testing, real voice-provider validation, and
  representative persistent streamed terrain/water/biome content.

## TASK-115 backlog reconciliation

| TASK-115 item | Existing work found | Remaining authorization target |
| --- | --- | --- |
| P0 scale/soak | TASK-101 two-worker lifecycle and TASK-115 contract gate; no soak or restart/recovery measurements. | TASK-118. |
| P0 operations | Shard 116 privileged inspection; Shards 117-118 event/audit shapes. | TASK-117 adapts these without exposing privileged fields to clients. |
| P1 security/platform | CotS policy seams and Shardlands identity/persistence concepts; Website/Platform API unavailable. | TASK-119 begins with peer access/contract reconciliation, then authenticated fuzz/rate-limit/audit work. |
| P1 voice | CotS local-voice policy seam only. | TASK-120 validates a provider and privacy/moderation propagation. |
| P1 content | CotS recipe catalog, Shard 119 region identity, and non-numbered donor ecology/world prototypes; no authoring toolkit in Shard 118. | TASK-121 builds a compatible persistent streamed content slice. |

## No-write proof

The audit used read-only revision/status/log/show/path inspection and read-only
web lookup.  Before this documentation change, the DeveloperTools Git wrapper
reported no workspace diff.  No production lifecycle, editor, build, Host MCP,
or donor/peer write operation was called.  The external paths above retain the
same observed revisions/worktree state recorded in this document.
