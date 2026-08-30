# TASK-012 Validation — Claude Independent Autonomous Unreal Proof

Task spec: `Tasks/012_AUTONOMOUS_PROOF.md`. Required test: "Using Tool Lab only,
the agent must create a disposable Blueprint actor with a visible component
and configurable property, place it in a test map, compile/save, run PIE,
verify the runtime value, stop PIE, collect logs and report all changed
assets," executed once each by Codex and Claude with no manual editor
construction. Codex's proof already exists
(`/Game/CotSAutonomousProof/BP_CodexProofActor`, `Maps/M_CodexProof`,
commits `5bb14ed`/`028b81d`). This records the independent Claude proof,
executed 2026-08-30 under agent id `supervisor-task-012`, using only native
Unreal MCP calls (`editor_toolset.*`) plus the fixed CotS composite tools
(`CotSDeveloperTools.CotSMutationToolset`, `CotSInspectionToolset`) — no
manual dragging, property edits, or actor placement.

## Sequence and evidence

1. **Create disposable map** —
   `CotSMutationToolset.CreateDisposableMap(mapAssetPath="/Game/CotSAutonomousProof/Maps/M_ClaudeProof")`
   -> `"success": true`, `world_path: "/Game/CotSAutonomousProof/Maps/M_ClaudeProof.M_ClaudeProof"`.
   Loaded via `SceneTools.load_level`; `get_current_level` confirmed
   `/Game/CotSAutonomousProof/Maps/M_ClaudeProof`.
2. **Create Blueprint** — `BlueprintTools.create(folder_path="/Game/CotSAutonomousProof", asset_name="BP_ClaudeProofActor", asset_type=/Script/Engine.Actor)`
   -> `/Game/CotSAutonomousProof/BP_ClaudeProofActor.BP_ClaudeProofActor`.
3. **Add configurable property** — `BlueprintTools.add_variable(name="RuntimeValue", type_name="float")`,
   then `set_variable_instance_editable(variable_name="RuntimeValue", instance_editable=true)`
   — an instance-editable float, matching the exact property name the CotS
   inspection PIE-reader (`GetPIEActorFloatProperty`) is designed to read.
4. **Add visible component** — `PrimitiveTools.add_sphere(actor=<Blueprint CDO
   Default__BP_ClaudeProofActor_C>, name="ProofSphere", radius=50)` ->
   returned `.../BP_ClaudeProofActor_C:ProofSphere_GEN_VARIABLE`, confirming
   a real SCS component variable on the class (not an instance-only add).
5. **Set class default and compile/save** — `ObjectTools.set_properties(CDO,
   {"RuntimeValue": 1.0})`; `BlueprintTools.compile_blueprint(...)` (no
   error); `AssetTools.save_assets(["/Game/CotSAutonomousProof/BP_ClaudeProofActor"])`
   -> `true`.
6. **Place instance in the test map** —
   `SceneTools.add_to_scene_from_class(actor_type=BP_ClaudeProofActor_C, name="ClaudeProofActor_Instance", xform={location:{x:0,y:0,z:100}})`
   -> `/Game/CotSAutonomousProof/Maps/M_ClaudeProof.M_ClaudeProof:PersistentLevel.BP_ClaudeProofActor_C_0`.
7. **Configure the instance property** — `ObjectTools.set_properties(instance,
   {"RuntimeValue": 777.5})`, independently re-read back via
   `ObjectTools.get_properties` -> `{"RuntimeValue":777.5}` (distinct from
   the class default `1.0`, proving the per-instance override — the
   "configurable property" — actually took effect, not just the class
   default). Map saved (`AssetTools.save_assets`); `AssetTools.is_dirty` ->
   `false` afterward.
8. **Run PIE** — `EditorAppToolset.StartPIE({bSimulate:false, playMode:"PlayMode_InViewPort", warmupSeconds:1})`.
   `CotSInspectionToolset.ListPIEActors` confirmed `ClaudeProofActor_Instance`
   (class `BP_ClaudeProofActor_C`) live in the running PIE world.
9. **Verify the runtime value** —
   `CotSInspectionToolset.GetPIEActorFloatProperty(actorSelector="ClaudeProofActor_Instance", propertyName="RuntimeValue")`
   -> `{"value": 777.5}`. The live runtime value matches the editor-time
   configured value exactly, verified through the actor's live PIE-world
   path (`UEDPIE_0_M_ClaudeProof...BP_ClaudeProofActor_C_0`), not the
   editor-time actor.
10. **Stop PIE** — `EditorAppToolset.StopPIE()`; `IsPIERunning` -> `false`
    immediately after, confirming a clean stop.
11. **Collect logs** — `EditorToolset.LogsToolset.GetLogEntries(category="", pattern="PIE", maxEntries=15)`
    returned the full PIE lifecycle: play-world creation
    (`Creating play world package: .../UEDPIE_0_M_ClaudeProof`), world
    bring-up, `PIE: Play in editor total start time 0.054 seconds`, and
    clean teardown (`BeginTearingDown`, `Shutting down PIE online
    subsystems`) after `StopPIE`.
12. **Report changed assets** — `AssetTools.exists` confirmed both
    `/Game/CotSAutonomousProof/BP_ClaudeProofActor` and
    `/Game/CotSAutonomousProof/Maps/M_ClaudeProof` persisted on disk after
    the session.

## Changed/affected assets

- `/Game/CotSAutonomousProof/BP_ClaudeProofActor` (new Blueprint: 1 visible
  `ProofSphere` StaticMeshComponent, 1 instance-editable `RuntimeValue` float
  variable, default `1.0`)
- `/Game/CotSAutonomousProof/Maps/M_ClaudeProof` (new disposable map,
  containing one placed `ClaudeProofActor_Instance` with `RuntimeValue`
  configured to `777.5`)

No production CotS or Shardlands scope was touched. These proof assets are
left in place (disposable but not deleted), matching Codex's equivalent
`BP_CodexProofActor`/`Maps/M_CodexProof` precedent from the same task.

## Acceptance

Every required step — Blueprint with visible component and configurable
property, placement in a disposable test map, compile/save, PIE run,
independently-verified live runtime value matching the configured override,
clean PIE stop, log collection, and a full changed-assets report — is
directly evidenced above from actual native Unreal MCP calls against the
live `CotSToolLab` editor, with no manual editor construction. Combined with
the existing Codex proof, both required independent per-agent runs now
exist.
