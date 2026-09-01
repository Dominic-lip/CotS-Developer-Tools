# CotS Tooling Backlog — Non-Gating Capabilities

This backlog records useful developer-factory capabilities that are deliberately **not** production-admission gates. Moving a capability here does not claim it has been implemented; it means the current verified task acceptance does not require it and production work should not remain blocked solely for it.

The authoritative roadmap completion state remains `Docs/FOUNDATION_COMPLETION_STATE.json`.

## IK Rig authoring

**Status:** not implemented.

**Origin:** TASK-013 Animation and MetaHuman Automation.

TASK-013's literal disposable locomotion acceptance was completed and live-proven: the agent created the locomotion setup, compiled it, ran PIE, and independently observed the state machine cycling. The subsequent twenty-sixth validation increment established that the remaining distinct-skeleton retarget proof is not missing content discovery; the installed MetaHuman retargeter is a MetaHuman-to-MetaHuman self-retargeter and there is no native/CotS MCP operation that authors a new IK Rig.

A future implementation should wrap the relevant UE 5.8 `UIKRigController` / `UIKRigDefinition` editor APIs with the same CotS principles used elsewhere:

- exact object paths;
- inspection before mutation;
- dry-run/preflight;
- idempotent chain/root/goal creation where practical;
- explicit source/target skeleton identity;
- compile/validation and independent reinspection;
- no dependence on Shardlands mutation.

This capability should be implemented when a production animation task actually needs to author a new cross-skeleton IK Rig. It must not be silently simulated by copying experimental donor assets.

## Production-scoped high-level mutation composites

The existing high-level animation mutation helpers intentionally remain restricted to `/Game/CotSMutationLive/`. V4 does **not** widen those paths globally because that would weaken a proven safety boundary merely to make the tools appear more complete.

When a production task has a repeated need for a high-level composite, add a production-specific operation with an explicit `/Game/CotS/...` scope and task-relevant preflight/validation. Epic native MCP remains available for generic production mutations where sufficient.
