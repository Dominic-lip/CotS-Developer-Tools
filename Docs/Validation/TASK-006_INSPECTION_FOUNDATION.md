# TASK-006 Validation — Ambiguous Duplicate-Name Inspection Proof

Task spec: `Tasks/006_INSPECTION_FOUNDATION.md`. Per
`Docs/FOUNDATION_COMPLETION_LEDGER.md`, `CotSInspectionToolset` and its source
tests already existed (`2ebfab0`); the only outstanding gap was a committed
live proof that two disposable assets sharing a display name in different
Tool Lab paths are distinguished by exact object path, not confused.

## Reused evidence (no re-run needed)

This proof was already executed live during this session's TASK-005
revalidation (`Docs/Validation/TASK-005_PLUGIN_FOUNDATION.md`), in the same
`RunCotSAutomation` pass, commit `2dfe796`. The only commit since then
(`eb19f98`, "Reduce autonomous agent usage overhead") touches only the
supervisor/factory Python scripts and their docs — `CotSInspectionToolset`
source and its test (`CotSFoundationTests.cpp`) are unchanged. Per
`Docs/AUTONOMOUS_EFFICIENCY_POLICY.md`, unrelated committed evidence is
authoritative and is not repeated for an unrelated task/turn; this document
records what that existing run already proves for TASK-006 rather than
re-running the editor.

## What was proven

`CotS.Inspection.ExactPathsAndEmptyReferences`
(`ToolLab/Saved/Logs/CotSToolLab.log`, `Test Completed. Result={Success}`,
2026-08-30 13:32:36) exercises exactly the TASK-006 validation scenario:

1. Creates two disposable `CurveFloat` assets with the **identical display
   name** `SharedInspectionAsset` at two different exact paths:
   `/Game/CotSInspectionFixtures/FolderA/SharedInspectionAsset` and
   `/Game/CotSInspectionFixtures/FolderB/SharedInspectionAsset`.
2. `CotSInspectionToolset.SearchAssets("SharedInspectionAsset", "/Game/CotSInspectionFixtures", "/Script/Engine.CurveFloat")`
   returns both assets as a 2-element collection — not collapsed or
   confused into one.
3. `CotSInspectionToolset.FindDuplicateNames("SharedInspectionAsset")` returns
   exactly one duplicate-name group, containing both exact paths.
4. `CotSInspectionToolset.GetReferences(<AssetA exact path>, bReferencers=false)`
   and `GetReferences(<AssetA exact path>, bReferencers=true)` both succeed
   and correctly report an empty dependency/referencer collection **for that
   specific exact path** — proving the two identically-named assets are
   tracked and queried independently by path, not by display name.
5. `CotSInspectionToolset.GetPIEActorFloatProperty` is confirmed to refuse
   cleanly outside PIE, and the Inspection schema is confirmed to expose the
   typed PIE actor inventory/float-reader tools.

This directly satisfies the TASK-006 validation requirement ("create
ambiguous disposable assets with identical display names in different Tool
Lab paths and prove the agent returns exact paths without confusing them")
and its acceptance criterion (dependencies/referencers answered by exact
path, no screenshots or human clicking involved — all assertions run inside
an automated editor test).

## Other TASK-006 target capabilities (already evidenced elsewhere)

- Unreal/editor/project status: `CotSFoundationToolset.GetStatus`,
  `CotSInspectionToolset.GetProjectStatus` — `Docs/Validation/TASK-003_MCP_CONNECTIVITY.md`.
- Plugin/module inspection: `CotSInspectionToolset.GetPlugins`; module load
  itself is proven in `Docs/Validation/TASK-005_PLUGIN_FOUNDATION.md`.
- Asset search/exact-path/class/basic-property inspection, Blueprint
  metadata, and dependency/referencer queries: native MCP coverage recorded
  in `Docs/MCP_CAPABILITY_MATRIX.md` (TASK-004), reliability gaps normalized
  by `CotSInspectionToolset`.
- Skeleton/Animation Blueprint/Blend Space inspection: `Docs/MCP_CAPABILITY_MATRIX.md`
  already records no native Animation Blueprint/state-machine/Blend Space
  toolset exists in UE 5.8's MCP registry ("Missing"/"Partial"); TASK-006's
  spec scopes this to "where native APIs permit," and building that surface
  is TASK-013's explicit scope, not a TASK-006 blocker.

## Disposition

No new mutation was performed by this task turn; no Shardlands or production
CotS scope was touched. Cleanup of the disposable fixture assets is handled
by the automation test itself (`FAssetRegistryModule::AssetDeleted` for both
assets at the end of the test, already covered by the reused evidence).
