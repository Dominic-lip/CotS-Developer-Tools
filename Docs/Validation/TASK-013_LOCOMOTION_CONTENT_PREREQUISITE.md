# TASK-013 Progress — Verified Locomotion Content Prerequisite

Task spec: `Tasks/013_ANIMATION_METAHUMAN.md`. This is a partial-progress
record, not a completion: it establishes the content prerequisite the
acceptance test requires ("a MetaHuman-compatible target plus a small
locomotion set (idle, four walk directions, jump/fall/land)"); the
AnimationAuthoringToolset itself (skeleton compatibility inspection,
retarget batching, Blend Space/AnimBP/state-machine creation, IK/root-motion
policy checks, locomotion test running) is not yet implemented.

## Why this content, not Shardlands or MetaHuman Bridge

- Shardlands remains read-only reference only, per the task's explicit
  instruction not to copy broken/experimental Shardlands animation assets.
- A real MetaHuman character requires Quixel Bridge/account access to
  download, which is not available in this environment.
- Epic's own bundled `TP_ThirdPerson` template content
  (`Templates/TemplateResources/High/Characters/Content/Mannequins/Anims/Unarmed/`)
  ships on the UE5 standard skeleton — the same skeleton MetaHumans retarget
  onto — with exactly the required locomotion set: `MM_Idle`, four walk
  directions (`MF_Unarmed_Walk_Fwd/Bwd/Left/Right`), and jump/fall/land
  (`MM_Jump`, `MM_Fall_Loop`, `MM_Land`). This is legitimate Epic sample
  content bundled with the engine install, not a donor/migration asset.

## Dependency-safety verification (done before copying anything)

A raw binary scan of `SK_Mannequin.uasset` and `MM_Idle.uasset` (via a
plain-text string scan of the `.uasset` files, entirely outside Unreal, zero
risk) confirmed:
- `SK_Mannequin.uasset`'s authored package path is
  `/Game/Characters/Mannequins/Meshes/SK_Mannequin`, with no external
  PhysicsAsset/Material package reference required.
- Critically, `MM_Idle.uasset` references its skeleton as
  `/Script/Engine.Skeleton'/Game/Characters/Mannequins/Meshes/SK_Mannequin.SK_Mannequin'`
  — the Skeleton object is embedded in the **same package** as the
  SkeletalMesh, not a separate file. Copying just `SK_Mannequin.uasset` at
  the matching relative path is therefore self-contained.

This let the copy proceed with a specific, verified minimal file set (9
files, 5.2 MB) instead of a large, uncertain bulk copy of the full 126 MB
template tree, avoiding the risk of introducing broken references into the
shared, concurrently-used ToolLab project.

## What was copied

Under agent id `supervisor-task-013`: acquired the Host lock, closed
ToolLab, copied the following into `ToolLab/Content/Characters/Mannequins/`
(preserving the exact relative path the assets were authored at), reopened
ToolLab (forcing a fresh Asset Registry scan), and verified:

- `Meshes/SK_Mannequin.uasset`
- `Anims/Unarmed/MM_Idle.uasset`
- `Anims/Unarmed/Walk/MF_Unarmed_Walk_Fwd.uasset`
- `Anims/Unarmed/Walk/MF_Unarmed_Walk_Bwd.uasset`
- `Anims/Unarmed/Walk/MF_Unarmed_Walk_Left.uasset`
- `Anims/Unarmed/Walk/MF_Unarmed_Walk_Right.uasset`
- `Anims/Unarmed/Jump/MM_Jump.uasset`
- `Anims/Unarmed/Jump/MM_Fall_Loop.uasset`
- `Anims/Unarmed/Jump/MM_Land.uasset`

## Post-import verification

- `AssetTools.exists("/Game/Characters/Mannequins/Meshes/SK_Mannequin")` ->
  `true`.
- `AssetTools.get_asset_class(".../SK_Mannequin")` -> `"Skeleton"`.
- `AssetTools.get_dependencies(".../Anims/Unarmed/MM_Idle")` -> a clean list
  of only built-in engine/script modules (`/Script/Engine`,
  `/Script/ControlRig`, `/Script/RigVM`, default compression settings, etc.)
  plus `/Game/Characters/Mannequins/Meshes/SK_Mannequin` — no missing or
  external broken references.
- `LogsToolset.GetLogEntries` for `Error|Missing|Broken` around the reopen
  showed only pre-existing, unrelated engine startup noise (SemanticSearch
  API keys, a missing `Wintab32.dll`, a GameFeatures config warning) and
  `MapCheck: Map check complete: 0 Error(s), 0 Warning(s)` — nothing related
  to the new content.

## Second increment: native skeleton-compatibility inspection

Added `UCotSInspectionToolset::GetSkeletonCompatibility(ObjectPath,
CandidateSkeletonPath)` to the existing Inspection toolset
(`UnrealPlugin/CotSDeveloperTools/Source/CotSDeveloperTools/{Public,Private}/Inspection/CotSInspectionToolset.{h,cpp}`),
directly addressing the first TASK-013 target capability, "Inspect skeleton
compatibility":

- Resolves the skeleton for a `Skeleton`/`SkeletalMesh`/`AnimationAsset`/
  `AnimBlueprint` object (reusing the same resolution pattern as the
  existing `GetAnimationAsset`).
- Reports the skeleton's declared compatible-skeleton list via UE 5.8's
  native `USkeleton::GetCompatibleSkeletonAssets` (asset-registry-based, no
  loading required).
- When a candidate skeleton path is supplied, reports `is_compatible` via
  UE's native `USkeleton::IsCompatibleForEditor(const FAssetData&)` check —
  the real compatibility semantics the Skeleton Editor's own "Compatible
  Skeletons" UI uses, not a custom reimplementation.

**Build**: canonical `Build-ToolLab.cmd` — `Result: Succeeded`, exit 0.

**Test**: added `CotS.Inspection.SkeletonCompatibility` to
`CotSFoundationTests.cpp`, exercising the *committed, permanent* imported
content above (not disposable fixtures): a direct self-compatibility check
on `SK_Mannequin` (`is_compatible: true`), skeleton resolution from
`MM_Idle` back to `SK_Mannequin`, and a clean failure on a nonexistent
path. Full `RunCotSAutomation` pass: 13/13 tests
`Result={Success}`, `TEST COMPLETE. EXIT CODE: 0`.

**Live verification** (native Unreal MCP, post-build): `GetSkeletonCompatibility`
called against `MF_Unarmed_Walk_Fwd` with `SK_Mannequin` as the candidate
returned `"skeleton": ".../SK_Mannequin.SK_Mannequin"`, `"is_compatible": true`,
confirming the capability works end-to-end against the real imported
locomotion content, not just in the automation test process.

## Remaining work (not done here)

- Enable the MetaHuman plugin if/when actual retargeting-to-MetaHuman
  automation is implemented (not required merely to hold this UE5-skeleton
  locomotion content or to check compatibility against it).
- Implement retarget asset inspect/batch, Blend Space create/configure,
  AnimBP/state-machine create/configure, root-motion/IK policy checks,
  locomotion validation and test running. (Skeleton compatibility inspection
  and duplicate-name detection — via the pre-existing `FindDuplicateNames` —
  are now covered.)
- Run the disposable-test-area acceptance test end-to-end and report exact
  assets/results.

Status remains `PARTIAL`, not `COMPLETE_VERIFIED` — this record covers the
content prerequisite plus one of eight target capabilities.
