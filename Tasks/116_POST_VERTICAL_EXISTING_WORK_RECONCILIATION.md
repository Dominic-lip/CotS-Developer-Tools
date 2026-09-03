# TASK-116 — Post-Vertical-Slice Existing-Work Reconciliation

## Objective
Turn the TASK-115 vertical-slice result and its observed backlog into an evidence-backed next production roadmap without forgetting or duplicating work that already exists.

Reconcile the current CotS production state against the freshest reachable existing work, with special attention to the heavily developed Shardlands 115–119 slices and the CotS Website / Platform API contracts that were not fully reachable during TASK-100.

## Scope and safety boundary

This task is a **read-only reconciliation gate** for all game/donor/peer repositories.

- `C:\Dev\Shardlands` — READ-ONLY. Never edit, clean, reset, checkout, rename, delete, reorganize, or bulk-copy it.
- `C:\Dev\CotS` — READ-ONLY for TASK-116. Inspect current production state and evidence only; do not mutate production code/assets/configuration.
- `Dominic-lip/Shardlands`, `Dominic-lip/CotS-Website`, `Dominic-lip/CotS-Platform-API`, and `Dominic-lip/CotS-Game` — READ-ONLY peers for this task.
- `C:\Dev\CotSDeveloperTools` — may be changed only for TASK-116 evidence, reuse decisions, roadmap/backlog reconciliation, scheduler state, and related deterministic tests.

Do not turn this audit into a wholesale migration. Implementation/migration belongs in explicitly authorized follow-on tasks after this gate establishes what is actually required.

## Required inspection

1. Reconcile the current `C:\Dev\CotS` revision, worktree state, TASK-101 through TASK-115 implementation/evidence, and actual subsystem boundaries.
2. Reconcile the freshest local `C:\Dev\Shardlands` state. Treat local files and Git status as potentially newer than remote history without modifying them.
3. Deepen the existing-work index specifically around Shards 115–119:
   - Shard 115 — embodied player / MetaHuman / animation / input work.
   - Shard 116 — world simulation fabric.
   - Shard 117 — gameplay/event integration.
   - Shard 118 — world authoring toolkit.
   - Shard 119 — discover and describe the actual current implementation; do not infer its purpose from old plans if the repository says otherwise.
4. Inspect other Shardlands slices only when dependency tracing from 115–119 or the current production system requires them.
5. Inspect reachable `CotS-Website` and `CotS-Platform-API` work relevant to account identity, authentication/session handling, characters, persistence/database contracts, server/session discovery, and web-to-game integration. Inspect `CotS-Game` if it contains relevant prior/parallel production work.
6. Reconcile the five TASK-115 backlog areas: scale/soak, operations/observability, security/platform integration, voice, and representative persistent world content.

## Classification

For every significant donor/peer implementation encountered, use the existing policy taxonomy from `Docs/EXISTING_WORK_REUSE_POLICY.md`:

- `REUSE_DIRECTLY`
- `ADAPT`
- `REIMPLEMENT`
- `REFERENCE_ONLY`
- `LEAVE`

Record whether the capability is already present in CotS production separately from the donor classification. Record concrete source paths/revisions, dependencies, confidence, conflicts and validation implications.

## Required deliverables

Create/update durable evidence under `Docs/Production/` including:

1. `TASK-116_RECONCILIATION_BASELINE.md` — exact source revisions/freshness, current CotS capability matrix, Shards 115–119 map, peer-contract map, dependencies, duplicates/conflicts and missing glue.
2. `Reuse/TASK-116.md` — evidence-backed reuse/adapt/reimplement/reference/leave decisions.
3. `TASK-116_NEXT_ROADMAP.md` — prioritized authorization-ready TASK-117+ proposals mapped back to the observed TASK-115 P0/P1 backlog and to already-existing work.
4. Update `Docs/Production/EXISTING_WORK_INDEX.md` only where TASK-116 establishes materially newer or more precise facts.
5. Update the completion ledger/state only after all acceptance evidence below exists and is committed.

## Acceptance criteria

TASK-116 is `COMPLETE_VERIFIED` only when all of the following are durable and inspectable:

- exact reachable revision/freshness evidence for CotS production, local Shardlands, and each reachable peer repository;
- an evidence-backed map of the actual Shards 115, 116, 117, 118 and 119 implementations;
- an evidence-backed Website / Platform API integration-contract map, or an exact recorded access limitation for any still-unreachable peer;
- a current CotS production capability/dependency matrix reconciled against TASK-101..115;
- significant donor/peer material classified under the existing reuse policy with paths/revisions/confidence;
- explicit duplicate, conflict, stale-boundary, missing-glue and genuinely-missing-work lists;
- the TASK-115 P0/P1 backlog reconciled against existing work rather than blindly copied forward;
- a dependency-ordered TASK-117+ roadmap that says what should be implemented next and why;
- proof that TASK-116 made no writes to Shardlands, CotS production, Website, Platform API, CotS-Game, or other donor/peer repositories.

If a source cannot be inspected, record the concrete access failure and continue with independent evidence where possible. Do not invent absent repository contents.
