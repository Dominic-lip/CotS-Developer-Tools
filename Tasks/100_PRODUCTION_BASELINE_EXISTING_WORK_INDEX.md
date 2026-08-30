# TASK-100 — Production Baseline & Existing-Work Index

## Objective
Start Phase 2 by reconciling the actual production state and creating a shallow, efficient index of existing work that future tasks can query just in time.

## Existing-work check
Follow `Docs/EXISTING_WORK_REUSE_POLICY.md`. This task is an index, not a deep migration audit.

Inspect at high level:
- `C:\Dev\CotS` / `Dominic-lip/CotS-Game`.
- read-only `C:\Dev\Shardlands` including actual local Git state and notable module/shard areas.
- `Dominic-lip/CotS-Website`.
- `Dominic-lip/CotS-Platform-API`.
- existing CotSDeveloperTools migration/reuse reports and generated data.

## Requirements
- Verify what TASK-015 actually produced in the production project and reconcile it with current disk/Git state.
- Establish/verify deterministic production build, test and editor/server lifecycle entry points; do not rely on ad-hoc commands.
- Create `Docs/Production/EXISTING_WORK_INDEX.md` containing source/revision/location, high-level capabilities, likely production-task relevance and freshness caveats.
- Record that local Shardlands may contain newer/unpushed work and must remain read-only.
- Do not deep-read every legacy file, migrate broad content, or rewrite existing systems in this task.

## Acceptance criteria
Production baseline is buildable/testable through deterministic entry points, the existing-work index is sufficient for later task-scoped searches, no donor repository was modified, and the next task can begin without rediscovering the entire estate.
