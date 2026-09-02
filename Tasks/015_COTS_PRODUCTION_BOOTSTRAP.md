# TASK-015 — CotS Production Project Bootstrap

## Objective
Create/reconcile the clean production Chronicles of the Sigilarium UE 5.8 project only after the developer factory has passed the autonomous proof and required foundation gates.

## Prerequisites
TASK-012 passed by both Codex and Claude; TASK-014 donor audit complete; toolchain build/validation reliable.

## Explicit production authorization
This task is explicitly authorized to create and modify `C:\Dev\CotS` for the bootstrap work below. That authorization is bounded to TASK-015 and does **not** authorize arbitrary writes elsewhere under `C:\Dev`.

Host filesystem/lifecycle/build/Git operations against the production project must use the reviewed fixed bridge `Scripts\CotSProductionLifecycle.py`. Provider sandbox escalation may be requested only for that exact adapter invocation and remains subject to the configured auto-reviewer. `C:\Dev\Shardlands` remains read-only donor/reference material.

The fixed helper `Scripts\CotSCreateBootstrapMap.py` is also explicitly authorized for TASK-015 when `/Game/Maps/CotS_Entry` is absent and native production MCP exposes no reliable direct level-creation primitive. It performs one audited operation only: create `C:\Dev\CotS\Content\Maps\CotS_Entry.umap` through `UnrealEditor-Cmd.exe` using fixed editor `MAP NEW`/`MAP SAVE` commands. It accepts no arbitrary filesystem path, executable, shell text or Unreal command and must verify that the durable `.umap` exists before reporting success. Do not retry the Slate `New Level...` UI action when this fixed non-UI path is available.

Allowed TASK-015 production operations include:
- initialize/reconcile the `C:\Dev\CotS` production tree and local Git baseline;
- create/reconcile the `.uproject`, Config conventions, source module, editor/game/server targets, project-local agent rules and bootstrap documentation;
- apply bounded text manifests through the fixed production lifecycle adapter;
- create the fixed `CotS_Entry` bootstrap map through `Scripts\CotSCreateBootstrapMap.py` when native MCP lacks a deterministic direct map-creation tool;
- open/close the fixed production editor, wait for its Unreal MCP endpoint, run the fixed production build/smoke operations, and use native Unreal MCP against that production editor where needed for bootstrap validation/test-map work;
- stage/commit exact production-relative files through the adapter's bounded Git completion operation.

Forbidden operations remain: broad donor migration, Shardlands mutation, arbitrary shell/process execution, arbitrary filesystem writes, destructive Git (`reset --hard`, force-push, history rewrite, broad clean), or work belonging to TASK-100+.

## Requirements
Create/validate the production UE project architecture, source-control baseline, build targets, server target plan, Config conventions, plugin linkage, validation gates, test map and foundational modules. Do not migrate broad content during bootstrap.

The bootstrap must be reproducible and idempotent: rerunning a fixed lifecycle operation must either report no change or refuse a conflicting existing file rather than silently overwrite unknown production work.

## Acceptance criteria
- `Scripts\CotSProductionLifecycle.py status` recognizes the fixed production project and reports its lifecycle state without provider assistance.
- The production project has a reviewable source-control baseline and deterministic UE 5.8 editor/client/server target plan.
- The canonical production editor build succeeds through the fixed adapter.
- `C:\Dev\CotS\Content\Maps\CotS_Entry.umap` exists and is produced through a deterministic fixed path; native MCP may validate/inspect it but lack of a direct MCP level-creation primitive is not itself a blocker.
- A fixed production smoke/editor launch path succeeds and, where required for asset/test-map acceptance, the production Unreal MCP endpoint becomes reachable.
- Required bootstrap validation/test-map evidence is recorded durably.
- The resulting baseline is suitable for beginning runtime/networking/persistence foundations in the planned production order without broad content migration.
