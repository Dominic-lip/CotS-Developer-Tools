# CotS Existing-Work Index

## Purpose and use

This TASK-100 shallow index supports just-in-time production work. It is not a
migration plan and does not authorize donor writes or bulk copies. Each
TASK-101+ task must follow `Docs/EXISTING_WORK_REUSE_POLICY.md`, start here,
then inspect only the identified subsystem slice deeply enough to record its
reuse decision.

## Production baseline

| Source | Revision / freshness | Capability summary | Use in later tasks |
| --- | --- | --- | --- |
| `C:\Dev\CotS` | clean at `8e744c7da1fafb1f8321cadb0ccc481e38b75f4d` on 2026-09-02 | UE 5.8 `CotS` runtime/editor/game/server target declarations; `/Game/Maps/CotS_Entry`; native MCP enabled; fixed lifecycle bridge. | Destination only. Reconcile before every production task through `Scripts/CotSProductionLifecycle.py status`. |
| `C:\Dev\CotSDeveloperTools` | TASK-100 working baseline | Fixed production lifecycle/build/smoke bridge, source-control completion wrapper, ToolLab MCP tooling, donor audit. | Reuse fixed operations; do not replace them with ad-hoc host commands. |

The deterministic production operations established by TASK-015 remain the
baseline: `build --target editor`, `build --target game`, `open`,
`wait-mcp`, `smoke`, `close`, and `git-complete`. Canonical editor UBT success,
game-build exit 0, saved entry map, native MCP readiness, and smoke exit 0 are
recorded in `Docs/Validation/TASK-015_PRODUCTION_BOOTSTRAP.md`. The installed
engine distribution refuses server targets; TASK-101 must establish the
dedicated-server plan rather than treating that target as built.

## Shardlands donor (read-only)

| Source | Revision / freshness | Capability summary | Likely production relevance |
| --- | --- | --- | --- |
| `C:\Dev\Shardlands` | local `64f5ca409fab5ccb62d09edde013cdc4fa67649c`; branch `feature/shard-115-embodied-player` is ahead 1/behind 7 and has modified, deleted, and untracked files. | UE 5.8 `Shardlands` and `ShardlandsMetaHuman` modules; Enhanced Input, UMG, AI, StateTree/GameplayStateTree; physical inventory/equipment/interaction, combat prototypes, ecology/world subsystems, MetaHuman presentation, and canonical data compiler/registry. | Treat local content as potentially newer than remote. Inspect narrowly by task; never modify, clean, reset, or bulk-migrate it. |
| `C:\Dev\Shardlands\Data` and `sharddata.py` | present locally; generated registry includes items, actions, processes, recipes, resources, materials, fluids, herbs and botanical forms. | CSV/JSON canonical-data compiler and typed identity/reference validation. | Primary candidate for TASK-103 adaptation; preserve source IDs and regeneration, not hand-maintained generated files. |
| `C:\Dev\Shardlands\Source\Shardlands\Items`, `Interaction`, `World`, `Combat` | present locally; detailed classification in `Docs/Validation/TASK-014_SHARDLANDS_DONOR_AUDIT.md`. | Server-authoritative item/container/equipment and interaction contracts; prototype ecology/world and combat components. | TASK-105, 106–112 inspect their relevant slices. Most require adaptation to production authority, persistence, networking, UI, and project paths. |
| `C:\Dev\Shardlands\Source\ShardlandsMetaHuman` | present locally; optional MetaHuman presentation module. | Appearance recipe/presentation seam and collection/palette integration. | TASK-104 may adapt the seam, but must rebuild the asset and retarget pipeline against CotS policy. |

The TASK-014 donor audit is authoritative for its high-level classifications:
canonical data is the strongest direct candidate; inventory/interaction/world
systems are adaptation candidates; combat/UI/maps/test fixtures are reference
or rebuild candidates. `AGENTS.md` in the donor retains the multiplayer,
server-authority, stable-identity, and physical-first constraints as useful
design evidence, but CotS production architecture remains controlling.

## Peer repositories and availability

| Source | Observed availability | Expected relevance | Freshness caveat |
| --- | --- | --- | --- |
| `Dominic-lip/CotS-Game` | no local checkout at TASK-100 indexing time; direct remote lookup was unavailable to this adapter. | Prior/parallel production game work. | Reconcile through a permitted checkout or accessible remote before relying on it; do not infer its contents. |
| `Dominic-lip/CotS-Website` | no local checkout; direct remote lookup unavailable. | Account, public/editorial, and player-facing integration assumptions. | TASK-102 and TASK-114 must inspect it when contracts cross the website boundary. |
| `Dominic-lip/CotS-Platform-API` | no local checkout; direct remote lookup unavailable. | Authentication, session, character, persistence, and service contracts. | TASK-101–103 must inspect it before defining an external contract. |

An unavailable peer is not evidence that it has no relevant work. Record the
actual reachable revision and a task-specific decision when a later task can
inspect it.

## Task routing guide

| Task range | First donor/index leads |
| --- | --- |
| TASK-101 | production targets/lifecycle bridge; Shardlands multiplayer and authority conventions; Platform API when service boundaries are introduced. |
| TASK-102–103 | Platform API and Website contract availability first; Shardlands canonical data compiler and persistent identity semantics. |
| TASK-104 | Shardlands character, MetaHuman, animation, and input slices; TASK-013 retargeting policy. |
| TASK-105 | Shardlands Items and Interaction slices; canonical item definitions. |
| TASK-106–113 | corresponding Shardlands World, simulation, economy, law, combat, and authoring slices; retain test fixtures as reference only. |
| TASK-114–115 | Website/Platform API boundaries plus the production contracts established by earlier tasks. |
