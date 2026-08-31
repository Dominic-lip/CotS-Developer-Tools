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

## Sixth increment: guarded locomotion Blend Space authoring

Two typed mutation operations now cover the Blend Space authoring boundary:

- `CreateDisposableLocomotionBlendSpace` creates only under
  `/Game/CotSMutationLive/`, uses UE's `UBlendSpaceFactoryNew`, and configures
  the verified editable `UBlendSpace.BlendParameters` contract as `Speed`
  (`0..600`, six divisions) and `Direction` (`-180..180`, eight divisions).
  The protected engine property is accessed only after runtime reflection
  confirms its `FBlendParameter[3]` type and cardinality, then normal editor
  change notifications and sample validation are invoked.
- `AddLocomotionBlendSpaceSample` accepts only an exact-skeleton
  `UAnimSequence`, finite coordinates inside those configured axes, and a
  Blend Space in the same disposable root. It refuses duplicate samples and
  reports the exact coordinate for independent inspection.

The operation accepts an explicit preview mesh, or asks the Skeleton's native
preview resolver when that argument is empty. The deliberately minimal
Mannequin import exposes a real prerequisite: its Skeleton resolves its
configured preview to missing `SKM_Quinn_Simple`. The dry-run automation test
therefore asserts a safe refusal rather than fabricating a mesh or writing an
incomplete asset. This is why no Blend Space was created in this increment.

Canonical `Build-ToolLab.cmd` succeeded (`Result: Succeeded`, exit 0). Fixed
Host `RunCotSAutomation` operation `d3f88bbc-7579-46dd-bc64-05fa4a046e87`
returned exit 0; the editor log records 13 CotS tests and `TEST COMPLETE. EXIT
CODE: 0`. The Host lock was released under `supervisor-task-013`.

## Seventh increment: root-motion and IK policy validation

`UCotSValidationToolset::ValidateLocomotionPolicy` is a read-only validator
for an explicit Skeleton, expected-looping clip set, expected-one-shot clip
set, required IK/root bone names, and an explicit root-motion mode. It reports
each clip's exact path, skeleton identity, authored looping flag, authored
root-motion flag, and per-bone presence; policy mismatches remain structured
failures with the collected data retained for review.

The permanent imported Mannequin content verifies the tool against actual
authored data: `MM_Idle` passes as a non-looping, in-place clip with no root
motion, and the Skeleton contains `root`, `pelvis`, `ik_foot_l`, and
`ik_foot_r`. The names were read from the imported skeleton asset before
adding the test; they are not inferred from display labels. This does not
claim the whole locomotion set follows the policy yet.

Canonical `Build-ToolLab.cmd` succeeded (`Result: Succeeded`, exit 0). Fixed
Host `RunCotSAutomation` operation `0ab964bb-d951-47f3-add3-982e1b62c4d8`
returned exit 0 and released the Host lock under `supervisor-task-013`.

## Eighth increment: AnimBlueprint state-machine inspection

`UCotSInspectionToolset::GetAnimBlueprintStateMachines` supplies the required
read-before-write view for later AnimBP authoring. For an exact
`UAnimBlueprint` path it reports target Skeleton, preview mesh, compiler
status, and every state-machine graph reachable from the AnimBlueprint's
event graphs. Each machine includes sorted state names/bound graph paths and
transition source/target names, crossfade duration, automatic-rule, and
bidirectional settings. It uses public UE 5.8 `AnimGraph` graph/node types
only and does not construct, rename, connect, compile, or save a graph.

The automation test constructs an unsaved transient `UAnimBlueprint` and
verifies the typed response is successful with zero state machines. This is a
no-write contract test; ToolLab does not yet contain an authored AnimBP on the
incomplete imported preview-mesh dependency chain.

Canonical `Build-ToolLab.cmd` succeeded (`Result: Succeeded`, exit 0). Fixed
Host `RunCotSAutomation` operation `5be10975-c657-4c92-b65d-44c8b92f0b2e`
returned exit 0 and released the Host lock under `supervisor-task-013`.

## Ninth increment: guarded AnimBlueprint asset authoring

`UCotSMutationToolset::CreateDisposableAnimBlueprint` now creates only an
exact-path `UAnimBlueprint` under `/Game/CotSMutationLive/`. It uses UE 5.8's
public `UAnimBlueprintFactory`, explicitly supplies `UAnimInstance` as the
parent class, and requires both an exact `USkeleton` and an exact-skeleton
preview mesh (or a native Skeleton preview-mesh resolution). Its structured
result reports the skeleton, preview mesh, parent class, and that graph
topology is `none_created`; state-machine creation, connections, compilation,
and saving remain explicit later operations.

The current imported Mannequin Skeleton still resolves the missing
`SKM_Quinn_Simple` preview asset. The focused automation test therefore proves
the new factory's dry-run safely refuses before package creation, matching the
existing Blend Space prerequisite rather than fabricating a preview mesh.

Canonical `Build-ToolLab.cmd` succeeded (`Result: Succeeded`, exit 0). Fixed
Host `RunCotSAutomation` operation `16189380-1899-4b14-a7cb-501de9f5bdae`
returned exit 0; the editor log records 13 CotS tests and `TEST COMPLETE. EXIT
CODE: 0`. The Host lock was released under `supervisor-task-013`.

## Tenth increment: guarded AnimBlueprint State Machine authoring

`UCotSMutationToolset::AddDisposableAnimBlueprintStateMachine` accepts only
an existing exact-path `UAnimBlueprint` under `/Game/CotSMutationLive/`. It
locates the Blueprint's factory-supplied `UAnimationGraph` and uses UE 5.8's
public `FGraphNodeCreator<UAnimGraphNode_StateMachine>` lifecycle. That calls
the engine node's normal initialization, including its owned
`UAnimationStateMachineGraph` and default entry node. The operation is
idempotent: an existing machine is reported without further mutation.

It intentionally creates neither state nodes nor transitions, does not wire
the State Machine to an AnimGraph output, and does not compile or save. Those
are separate correctness boundaries. The focused test proves a missing
disposable AnimBlueprint is rejected before any graph mutation.

Canonical `Build-ToolLab.cmd` succeeded (`Result: Succeeded`, exit 0). Fixed
Host `RunCotSAutomation` operation `555b6bbf-fb66-4769-91fb-0201af316e4c`
returned exit 0; the editor log records 13 CotS tests and `TEST COMPLETE. EXIT
CODE: 0`. The Host lock was released under `supervisor-task-013`.

## Eleventh increment: guarded AnimBlueprint State authoring

`UCotSMutationToolset::AddDisposableAnimBlueprintState` adds a requested,
valid Unreal State name only to an exact disposable `UAnimBlueprint` that has
exactly one initialized State Machine. It uses the public
`FEdGraphSchemaAction_NewStateNode::SpawnNodeFromTemplate` lifecycle, which
creates the State's own animation graph and default result node, then wires
the State Machine entry node through UE's schema. The resulting graph paths
and actual entry-wiring status are returned. Repeating the same State name is
an idempotent no-change result.

Transitions, animation-asset nodes, AnimGraph output wiring, compilation, and
saving remain explicit later operations. The focused test proves a missing
disposable AnimBlueprint is rejected before State graph mutation.

Canonical `Build-ToolLab.cmd` succeeded (`Result: Succeeded`, exit 0). Fixed
Host `RunCotSAutomation` operation `4716d48d-468a-42fc-a00a-35ad55d7234c`
returned exit 0; the editor log records 13 CotS tests and `TEST COMPLETE. EXIT
CODE: 0`. The Host lock was released under `supervisor-task-013`.

## Twelfth increment: guarded AnimBlueprint transition authoring

`UCotSMutationToolset::AddDisposableAnimBlueprintTransition` creates one
directional transition only between two distinct, exact named States in the
single initialized State Machine of a disposable AnimBlueprint. It validates a
finite crossfade in `[0,10]`, uses UE 5.8's public
`FEdGraphSchemaAction_NewStateNode` lifecycle for the transition-rule graph,
then calls the public `UAnimStateTransitionNode::CreateConnections` API. The
exact source, target, rule-graph path, crossfade, and post-write connection
status are returned; an existing matching directed transition is idempotently
reported without another mutation.

No transition-rule logic, animation-asset player, AnimGraph output wiring,
compilation, or saving is claimed. The focused test proves a missing
disposable AnimBlueprint is rejected before transition graph mutation.

Canonical `Build-ToolLab.cmd` succeeded (`Result: Succeeded`, exit 0). Fixed
Host `RunCotSAutomation` operation `1027b7ed-c40b-49da-8fa2-52b76aa83275`
returned exit 0; the editor log records 13 CotS tests and `TEST COMPLETE. EXIT
CODE: 0`. The Host lock was released under `supervisor-task-013`.

## Thirteenth increment: guarded State Sequence Player authoring

`UCotSMutationToolset::SetDisposableAnimBlueprintStateSequence` assigns one
exact-skeleton `UAnimSequence` to a named State in a disposable AnimBlueprint.
It uses UE 5.8's public `UAnimGraphNode_SequencePlayer` lifecycle, explicitly
sets the requested looping policy, and links the public `Pose` output to the
State Result's `Result` input using the same engine graph pattern. Existing
matching content is an idempotent no-change result; different State content is
refused rather than implicitly replaced. The structured result reports exact
State, sequence-player, and result-wiring information.

This does not wire the State Machine into the AnimGraph output, create a
transition-rule expression, compile, or save. The focused test proves a
missing disposable AnimBlueprint is rejected before State content mutation.

Canonical `Build-ToolLab.cmd` succeeded (`Result: Succeeded`, exit 0). Fixed
Host `RunCotSAutomation` operation `6cf663bf-1d0f-47a0-8b03-980e7b44d670`
returned exit 0; the editor log records 13 CotS tests and `TEST COMPLETE. EXIT
CODE: 0`. The Host lock was released under `supervisor-task-013`.

## Fourteenth increment: guarded AnimGraph Root wiring

`UCotSMutationToolset::WireDisposableAnimBlueprintStateMachineOutput` wires
the single disposable State Machine's public `Pose` output to the
factory-supplied AnimGraph Root's public `Result` input. It requires exactly
one `UAnimationGraph`, State Machine, and Root; it reports a no-change when
already wired and refuses an existing conflicting output producer. This
completes the graph topology needed for a later explicit compilation boundary.

The operation deliberately does not create transition-rule logic, compile, or
save. The focused test proves a missing disposable AnimBlueprint is rejected
before graph mutation.

Canonical `Build-ToolLab.cmd` succeeded (`Result: Succeeded`, exit 0). Fixed
Host `RunCotSAutomation` operation `c65da073-6080-43a8-90a9-39c754ec435b`
returned exit 0; the editor log records 13 CotS tests and `TEST COMPLETE. EXIT
CODE: 0`. The Host lock was released under `supervisor-task-013`.

## Fifteenth increment: guarded constant transition-rule authoring

`UCotSMutationToolset::SetDisposableAnimBlueprintTransitionRule` finds one
exact directed transition in the single State Machine of a disposable
AnimBlueprint and changes only its public `UAnimGraphNode_TransitionResult`
`bCanEnterTransition` property. It returns the exact rule-graph/result-node
paths and before/after values, refuses absent or ambiguous topology, and is
idempotent when the requested constant rule is already set. It deliberately
does not synthesize K2 expression graphs, compile, or save the asset.

The focused test proves a missing disposable AnimBlueprint is rejected before
transition-rule mutation. Canonical `Build-ToolLab.cmd` succeeded (`Result:
Succeeded`, exit 0). Fixed Host `RunCotSAutomation` operation
`2401e2bb-ae2f-40ca-8f77-55e71b9ea1c3` returned exit 0; the editor log records
13 CotS tests and `TEST COMPLETE. EXIT CODE: 0`. The Host lock was released
under `supervisor-task-013`.

## Sixteenth increment: complete mixed locomotion policy validation

`UCotSValidationToolset::ValidateLocomotionPolicyWithRootMotionSet` validates
one exact Skeleton, explicitly separated looping and one-shot clip sets, the
subset that must contain root motion, and required root/IK bones. It rejects
duplicates, missing clips, clips outside the declared policy, and mismatches
in skeleton identity, looping, or per-clip root-motion settings.

The full committed locomotion set passes the policy: the four `MF_Unarmed`
walk clips are looping and root-motion enabled; `MM_Idle`, `MM_Jump`,
`MM_Fall_Loop`, and `MM_Land` are non-looping and in-place. All eight resolve
to the imported Mannequin Skeleton, which contains `root`, `pelvis`,
`ik_foot_l`, and `ik_foot_r`.

Canonical `Build-ToolLab.cmd` succeeded (`Result: Succeeded`, exit 0). Fixed
Host `RunCotSAutomation` operation `10b094cd-a0e4-4208-804a-02f64432b212`
returned exit 0; the editor log records 13 CotS tests and `TEST COMPLETE. EXIT
CODE: 0`. The Host lock was released under `supervisor-task-013`.

## Seventeenth increment: verified Quinn preview-mesh content import

Recursively scanned `SKM_Quinn_Simple.uasset`'s package strings (same
offline, zero-risk binary-scan method used for the original locomotion
import) to determine its real dependency closure before copying anything:

- Direct references: `SK_Mannequin` (already imported), `MI_Quinn_01`,
  `MI_Quinn_02` (material instances), `PA_Mannequin` (PhysicsAsset),
  `CR_Mannequin_Body` (Control Rig).
- `MI_Quinn_01`/`MI_Quinn_02` recursively require `M_Mannequin` (parent
  material) and their own Quinn textures (`T_Quinn_01_{D,MRA,N}`,
  `T_Quinn_02_{D,MRA,N}`).
- `PA_Mannequin` and `CR_Mannequin_Body` both reference `SKM_Manny_Simple` —
  a *different* skeletal mesh, not one we hold — opening a separate,
  unverified dependency branch. `M_Mannequin` itself also has default
  texture-parameter values pointing at Manny textures (`T_Manny_01_*`,
  `T_UE_Logo_M`), used only as an unused fallback since the Quinn instances
  override every relevant parameter.

**Scope decision**: imported only the fully self-contained, verified subset
needed for a valid preview *mesh* — `SKM_Quinn_Simple`, `M_Mannequin`,
`MI_Quinn_01`, `MI_Quinn_02`, and the 6 Quinn textures (22 MB) — and
deliberately did **not** import `PA_Mannequin`/`CR_Mannequin_Body` or the
Manny default-parameter textures. A SkeletalMesh with an unassigned
PhysicsAsset/Control-Rig and a material with an unused missing default
texture parameter both load and render correctly in UE (missing physics/
control-rig means no simulation/rig preview; a missing default-only texture
parameter falls back to a checker/error texture only if nothing overrides
it, which the Quinn instances already do) — neither blocks the intended use
as a Skeleton preview mesh for Blend Space/AnimBP authoring. Chasing the
Manny sub-tree further would be scope creep beyond what a preview mesh
needs.

Copied (preserving the original `/Game/Characters/Mannequins/...` relative
path) under agent id `supervisor-task-013`: `AcquireMutationLock` (no editor
was running, so no close/reopen cycle was needed for the copy itself),
copied the 9 files, then `OpenToolLab`/`WaitForUnrealMcp` to force a fresh
Asset Registry scan, and `ReleaseMutationLock`.

**Verification performed**: `ToolLab/Saved/Logs/CotSToolLab.log` after the
scan shows no Quinn/Mannequin-related entries under an `Error|Missing|Broken`
grep, and `MapCheck: Map check complete: 0 Error(s), 0 Warning(s)`. This
Claude turn's own `unreal-mcp` MCP client had already failed to connect at
session start (ToolLab was closed then), so the live `AssetTools.exists`/
`get_dependencies` confirmation used for the original Mannequin import could
not be repeated in the same turn — that native re-verification, and actually
assigning this mesh as the Skeleton's active preview mesh (`USkeleton::SetPreviewMesh`
is a C++ function, not a directly `set_properties`-settable reflected field,
so it needs a small new guarded CotS tool rather than a generic property
set), are left for the next turn with a live connection.

## Eighteenth increment: live Quinn-preview-mesh re-verification and real Blend Space authoring

At the start of this Claude turn, ToolLab was already running (left open from
the previous turn), so `unreal-mcp` connected natively at session start —
resolving the deferred re-verification:

- `AssetTools.exists("/Game/Characters/Mannequins/Meshes/SKM_Quinn_Simple")`
  -> `true`; `get_asset_class` -> `"SkeletalMesh"`.
- `AssetTools.get_dependencies` lists `CR_Mannequin_Body`/`PA_Mannequin` as
  declared-but-absent (the deliberately skipped Manny sub-tree) alongside the
  present `SK_Mannequin`/`MI_Quinn_01`/`MI_Quinn_02` — the call itself
  succeeds with no error, confirming UE degrades missing soft references
  gracefully rather than failing to enumerate dependencies.
- `CotSInspectionToolset.GetAnimationAsset` **loads** the mesh
  (`LoadObject`, not just an asset-registry query) and succeeds cleanly,
  resolving `"skeleton": ".../SK_Mannequin.SK_Mannequin"` — proving the mesh
  is usable despite its unmet PhysicsAsset/Control-Rig references.

This also surfaced that no new preview-mesh-assignment tool was needed:
`CreateDisposableLocomotionBlendSpace`/`CreateDisposableAnimBlueprint`
(already implemented by a concurrent turn) both take an explicit
`previewMeshPath` parameter rather than depending on the Skeleton's own
`PreviewMesh` field, so the imported Quinn mesh could be passed directly.

With that unblocked, ran the first real (non-dry-run) Blend Space authoring
proof against genuine locomotion content, under `supervisor-task-013`:

1. `CreateDisposableLocomotionBlendSpace` with `skeletonPath=SK_Mannequin`,
   `previewMeshPath=SKM_Quinn_Simple`, target
   `/Game/CotSMutationLive/BS_LocomotionProof.BS_LocomotionProof` -> success,
   `speed_axis: "0..600"`, `direction_axis: "-180..180"`. (Note: the exact
   object path must include the redundant `.AssetName` suffix — a bare
   package path is rejected as `outside_disposable_scope`.)
2. `AddLocomotionBlendSpaceSample` x5, all succeeded: `MM_Idle` at (0, 0),
   `MF_Unarmed_Walk_Fwd` at (300, 0), `MF_Unarmed_Walk_Bwd` at (300, 180),
   `MF_Unarmed_Walk_Left` at (300, -90), `MF_Unarmed_Walk_Right` at (300, 90).
3. Independent re-inspection: `CotSInspectionToolset.GetAnimationAsset` on
   the new Blend Space returned `"class": "BlendSpace"`,
   `"skeleton": ".../SK_Mannequin.SK_Mannequin"`, `"sample_count": 5` —
   matching all five additions.
4. `SaveAsset` succeeded, then `DeleteDisposableAsset` cleaned it up (matching
   the "disposable" naming and this doc's established pattern of proof-then-
   cleanup rather than committing binary scratch assets); `AssetTools.exists`
   confirmed `false` afterward.

This is the first genuine (non-dry-run) exercise of the concurrently-built
Blend Space authoring tools against real, non-disposable project content,
directly closing the "create/configure Blend Spaces" target capability.

## Nineteenth increment: real compiled AnimBlueprint locomotion state machine

Using the same imported Quinn preview mesh, built and compiled a genuine
4-state locomotion `AnimBlueprint` end-to-end under `supervisor-task-013`,
kept (not deleted, unlike the Blend Space proof) since it is a substantive,
directly reusable locomotion-setup artifact rather than a disposable
one-shot capability exercise:

1. `CreateDisposableAnimBlueprint` -> `/Game/CotSMutationLive/ABP_LocomotionProof.ABP_LocomotionProof`,
   `skeletonPath=SK_Mannequin`, `previewMeshPath=SKM_Quinn_Simple`.
2. `AddDisposableAnimBlueprintStateMachine` -> one State Machine node in the
   AnimGraph, `state_count: 0`.
3. `AddDisposableAnimBlueprintState` x4: `Idle`, `JumpStart`, `Falling`,
   `Landing` — all `entry_wired: true`.
4. `SetDisposableAnimBlueprintStateSequence` x4, pairing each state with a
   real animation and correct looping flag: `Idle`->`MM_Idle` (looping),
   `JumpStart`->`MM_Jump` (one-shot), `Falling`->`MM_Fall_Loop` (looping),
   `Landing`->`MM_Land` (one-shot) — matching the same loop policy already
   validated by `ValidateLocomotionPolicyWithRootMotionSet`.
5. `AddDisposableAnimBlueprintTransition` x4, forming the cycle
   `Idle -> JumpStart -> Falling -> Landing -> Idle`, each `connected: true`.
6. `SetDisposableAnimBlueprintTransitionRule` x4, setting
   `bCanEnterTransition=true` on every transition (`before_can_enter_transition:
   false` -> `after: true` each time) — a minimal always-open-cycle rule set,
   since constant rules are this tool's documented scope (gameplay-driven
   conditions are a later concern, not required to prove the graph compiles
   and topology is sound).
7. `WireDisposableAnimBlueprintStateMachineOutput` -> `root_wired: true`.
8. `CompileBlueprint` -> `"compile_status": 5, "compiled_up_to_date": true`,
   no errors.
9. Independent re-inspection: `CotSInspectionToolset.GetBlueprint` confirms
   the same `compile_status: 5`/`compiled_up_to_date: true` from a separate
   read path, `parent_class: AnimInstance`, `graphs: ["EventGraph"]`.
10. `SaveAsset` succeeded.

This directly closes "create/configure Animation Blueprints/state machines"
against real content — the first fully compiled, real-content locomotion
AnimBlueprint produced by either agent this task.

**Correction from the twentieth increment below**: "compiles without errors"
is true but was not sufficient evidence that the state machine actually
*works*. A subsequent PIE run surfaced compiler warnings that this increment's
own inspection calls did not surface (`CompileBlueprint`'s and `GetBlueprint`'s
JSON both reported an empty `warnings` array despite real compiler warnings
being logged) — the transition rules as set do not actually function. Treat
this increment as "produces a compiling AnimBlueprint asset with the intended
topology," not "produces a working locomotion state machine."

## Twentieth increment: live PIE run reveals a real transition-rule defect

Attempted the literal "runs the test" clause: spawned an `ASkeletalMeshActor`,
assigned `skeletalMeshAsset=SKM_Quinn_Simple`, `animationMode=AnimationBlueprint`,
`animClass=ABP_LocomotionProof_C` (found via `ObjectTools.list_properties` —
UE5.8 renamed the mesh property to `skeletalMeshAsset`), and ran PIE.

**First attempt placed the actor in `/Temp/Untitled_1`** (the level open at
turn start) and it did not appear in `ListPIEActors` at all. Investigation
showed `/Temp/Untitled_1` is actually a large World Partition map (landscape,
sky, dozens of streaming-cell sublevels), not an empty scratch level — the
actor likely landed in a cell that didn't stream into the brief PIE session.
Switched to a purpose-built disposable map instead: `CreateDisposableMap`
(note: its `MapAssetPath` must be exactly under `/Game/CotSAutonomousProof/`,
not `/Game/CotSMutationLive/` — a second, different exact-scope restriction
from the Blend Space/AnimBlueprint one) -> `/Game/CotSAutonomousProof/Maps/M_LocomotionProof`,
loaded it, placed the actor there instead. `ListPIEActors` then correctly
showed `LocomotionProofActor` (class `SkeletalMeshActor`) in the running PIE
world, confirming the placement/assignment approach itself was correct.

**The real finding**: re-reading `ToolLab/Saved/Logs/CotSToolLab.log` around
the earlier `CompileBlueprint` call (from the prior increment, same session)
showed compiler warnings that were never surfaced through the MCP call's own
`warnings` field:

```
LogBlueprint: Warning: [AssetLog] .../ABP_LocomotionProof: [Compiler]
  Idle to JumpStart  will never be taken, please connect something to  Can Enter Transition
  (repeated for JumpStart->Falling, Falling->Landing, Landing->Idle)
```

Reading `SetDisposableAnimBlueprintTransitionRule`'s implementation
(`UnrealPlugin/.../CotSMutationToolset.cpp`) confirms why: it writes
`ResultNode->Node.bCanEnterTransition` directly on the compiled runtime
struct via reflection, but `UAnimGraphNode_TransitionResult`'s boolean input
is a real graph pin — Unreal's animation-transition-graph compiler generates
its bytecode from pin connections (and pin `DefaultValue` strings), not from
whatever a raw struct member holds after the fact, so an unconnected pin is
compiled as "never true" regardless of the struct write succeeding. The tool
call's own reported `after_can_enter_transition: true` is therefore true of
the in-memory struct field at the moment it was set, but not of what the
compiled/saved graph will actually evaluate at runtime.

This is exactly the class of thing "run the test" is meant to catch that a
"compiles without errors" claim can miss, and neither this task's nor the
concurrent agent's own focused unit tests exercised it — their own
documented test scope for this tool "proves a missing disposable
AnimBlueprint is rejected before transition-rule mutation," not that a
fully-wired transition actually fires. `ABP_LocomotionProof` is being kept
committed as an accurate, useful reference of this real (if currently
non-functional) topology, not as a working locomotion setup.

Cleaned up the diagnostic map/actor: `AssetTools.delete` on
`/Game/CotSAutonomousProof/Maps/M_LocomotionProof` after switching the
loaded level away from it (delete on the currently-loaded level is a no-op);
its `.umap` file remained on disk after that call reported `true` (an
async-save artifact, not a registry inconsistency worth deeper investigation
here), so it was removed directly via filesystem delete and confirmed absent
from `git status` before committing.

## Remaining work (not done here)

- **Fix `SetDisposableAnimBlueprintTransitionRule`** to set the transition
  result pin's actual default value (e.g. via the pin's
  `GetSchema()->TrySetDefaultValue`/`PC_Boolean` default-value string, or by
  wiring a boolean literal `K2Node`) rather than the raw runtime struct
  field, so `bCanEnterTransition=true` is honored by the compiler. Re-run
  the same PIE proof afterward to confirm the state machine actually cycles
  through all four states.
- Enable the MetaHuman plugin if/when actual retargeting-to-MetaHuman
  automation is implemented (not required merely to hold this UE5-skeleton
  locomotion content or to check compatibility against it).
- Configure a disposable IK Retargeter with a genuine distinct target and
  perform/inspect/clean up a guarded batch retarget proof.
- Run the disposable-test-area acceptance test end-to-end and report exact
  assets/results, once the transition-rule defect above is fixed.

Status remains `PARTIAL`, not `COMPLETE_VERIFIED` — this record covers the
content prerequisite plus most of the eight target capabilities; only the
IK-retarget proof and the live PIE run of the acceptance test remain.
