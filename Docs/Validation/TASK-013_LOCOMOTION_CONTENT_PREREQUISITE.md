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

## Third increment: clip policy metadata inspection

`GetAnimationAsset` now includes two direct `UAnimSequence` properties needed
by the later locomotion policy validator: `is_looping` (`bLoop`) and
`has_root_motion` (`HasRootMotion()`). This stays in the existing read-only
Inspection toolset; it does not claim to author or retarget animation assets.

- The extended `CotS.Inspection.SkeletonCompatibility` automation test reads
  the permanent `MM_Idle` asset and asserts both returned fields. The actual
  bundled template setting is `is_looping: false`, `has_root_motion: false`;
  the test deliberately reports that authored truth rather than assuming an
  idle policy.
- Canonical fixed Host `BuildToolLab` succeeded (UBT `Result: Succeeded`, exit
  0) after compiling the shared CotSDeveloperTools module. Fixed
  `RunCotSAutomation` returned exit 0.
- Native UE MCP live readback (operation
  `2443a141-4286-b7fc-af0a-a29403606998`) returned the exact idle path,
  `AnimSequence` class, the Mannequin skeleton, `play_length_seconds:
  7.5666666030883789`, `sampled_keys: 228`, `is_looping: false`, and
  `has_root_motion: false`, with no warnings or errors.

## Fourth increment: UE 5.8 IK Retargeter inspection

`UCotSInspectionToolset::GetIKRetargeter(ObjectPath)` adds the next
read-only TASK-013 slice using UE 5.8's public `IKRig` runtime API. It reports
the exact retargeter path; whether source and target rigs are assigned; each
side's assigned rig, preview mesh, root/pelvis bones, current pose, and sorted
retarget-chain descriptions; plus sorted operation-stack struct paths. It
uses only `UIKRetargeter::GetIKRig`, `GetCurrentRetargetPoseName`, and
`GetRetargetOps`, and `UIKRigDefinition` read accessors. It deliberately does
not use the `IKRigEditor` batch-retarget API or any controller/writeable
accessor.

- The plugin descriptor now declares its `IKRig` dependency alongside the
  module dependency, eliminating Unreal's undeclared-plugin warning.
- The existing `CotS.Inspection.SkeletonCompatibility` automation test now
  creates an unsaved transient `UIKRetargeter` only, inspects it by exact
  object path, and verifies the typed response reports no assigned source or
  target rig. This exercises the actual public API without creating or saving
  a ToolLab content asset.
- Canonical `Build-ToolLab.cmd` succeeded after compiling the shared plugin
  module (`Result: Succeeded`, exit 0). Fixed Host
  `RunCotSAutomation` operation `36dc9455-2e9e-4ee4-841c-d749315ea79d`
  returned exit 0. The Host mutation lock was acquired and released under
  `supervisor-task-013`; ToolLab remained closed.

## Fifth increment: guarded native batch retarget operation

`UCotSMutationToolset::BatchRetargetAnimationAssets` now wraps UE 5.8's
public `UIKRetargetBatchOperation::RunBatchRetarget` rather than recreating
retarget behavior. It is intentionally narrower than Epic's raw operation:

- Source assets must be unique exact object paths resolving to
  `UAnimationAsset` instances on the source preview mesh's exact skeleton.
- The provided `UIKRetargeter` must expose distinct source and target preview
  meshes; an unconfigured retargeter is rejected before any asset operation.
- Output is restricted to a package path below
  `/Game/CotSMutationLive/`; it cannot write beside permanent locomotion
  content, and `bUseSourcePath`/`bOverwriteExistingFiles` are always false.
- `bDryRun` performs the same path, rig, source-skeleton, and output-scope
  preflight without invoking Epic's package-backed operation. Actual results
  return every exact output object path for independent inspection.

The existing inspection automation test exercises the no-source rejection
path, proving batch execution cannot begin without an explicit asset set. The
canonical ToolLab build compiled the shared plugin with `IKRigEditor` and
returned `Result: Succeeded`, exit 0. Fixed Host `RunCotSAutomation` operation
`3e27d97c-4b71-433b-beb2-d80f05ee81bb` returned exit 0; its Host lock was
released under `supervisor-task-013`.

## Remaining work (not done here)

- Enable the MetaHuman plugin if/when actual retargeting-to-MetaHuman
  automation is implemented (not required merely to hold this UE5-skeleton
  locomotion content or to check compatibility against it).
- Configure a disposable IK Retargeter with a genuine distinct target and
  perform/inspect/clean up a guarded batch retarget proof; implement Blend Space create/configure,
  AnimBP/state-machine create/configure, root-motion/IK policy checks,
  locomotion validation and test running. (Skeleton compatibility inspection
  and duplicate-name detection — via the pre-existing `FindDuplicateNames` —
  are now covered.)
- Run the disposable-test-area acceptance test end-to-end and report exact
  assets/results.

Status remains `PARTIAL`, not `COMPLETE_VERIFIED` — this record covers the
content prerequisite plus one of eight target capabilities.
