# Native UE 5.8 MCP Capability Matrix

Audit date: 2026-08-29  
Project/editor under test: `CotSToolLab`, UE 5.8.1, native listener `http://127.0.0.1:8000/mcp`  
Disposable scope: `/Game/CotSDevAudit` only

## Test basis

Codex connected directly to Epic's native Streamable HTTP MCP endpoint, negotiated
protocol `2025-11-25`, called `list_toolsets`/`describe_toolset`, and invoked native
tools through the registered `call_tool` dispatcher. No filesystem or manual-editor
substitute was used for any capability result below.

The listener exposed 40+ toolsets, including the native editor, logs, automation,
asset, actor, Blueprint, scene, material, data, skeletal-mesh, Control Rig, Slate,
and programmatic orchestration toolsets.

Claude Code 2.1.251 was present but had no configured MCP servers. `claude mcp add
--transport http unreal-native-audit http://127.0.0.1:8000/mcp` reported that it had
written the project-local setting, but both `claude mcp get` and `claude mcp list`
immediately reported no configured server. The required independent Claude critical-read
repeat therefore remained unverified at that time; this was a client/configuration
reliability issue, not evidence that the UE endpoint was unavailable.

**Update, 2026-08-30 (TASK-003/TASK-004 follow-up):** the checked-in `.mcp.json`
and `ToolLab/.mcp.json` project configuration (rather than a local `claude mcp
add`) made the `unreal-mcp` server persistent, and Claude independently
completed both required proofs against the same running `CotSToolLab` editor
this audit used:

- `Docs/Validation/TASK-003_MCP_CONNECTIVITY.md` — the full TASK-003
  connection/read proof (toolset enumeration, engine version `5.8.1-56057345+++UE5+Release-5.8`,
  project `CotSToolLab`, current level `/Temp/Untitled_1`, no actor selected).
- Standby critical-read compatibility sample for this task (per "Cross-agent
  validation" below), all read-only, no mutation, no repeat of the full audit:
  - `EditorAppToolset.GetCameraTransform` → returned the live viewport camera
    transform, confirming viewport inspection matches Codex's row.
  - `AutomationTestToolset.DiscoverTests` → `{"status": "ready"}`, matching
    Codex's result for this row.
  - `AssetTools.find_assets(folder_path="/Game", name="")` → returned
    `/Game/CotSAutonomousProof/BP_CodexProofActor` and
    `/Game/CotSAutonomousProof/Maps/M_CodexProof` (the existing TASK-012 Codex
    proof assets), confirming asset search sees real project content from a
    second client.
  - `LogsToolset.GetLogEntries(category="", pattern="", maxEntries=5)` →
    returned live `LogModelContextProtocol` entries for Claude's own preceding
    tool calls, confirming log retrieval. (Note: the tool's `category`
    parameter defaults to the literal string `"LogsToolset"`, which is not a
    registered log category and raises `Log category 'LogsToolset' not
    found.` — callers must pass `category: ""` explicitly for an unfiltered
    read; this is a minor default-value defect worth fixing if a CotS wrapper
    is ever built around this tool.)

No asset, actor, or level was created, changed, or deleted by this sample.

| Capability | Result | Tested client(s) and exact native tool(s) | Verified result / limits | CotS high-level tool? |
|---|---|---|---|---|
| Project/editor/viewport/selection inspection | Native | Codex: `SceneTools.get_current_level`, `EditorAppToolset.GetCameraTransform`, `GetSelectedActors` | Returned `/Temp/Untitled_1`, camera transform, and selection; selection mutation/readback also succeeded. Claude repeat pending. | No for primitive queries; add a compact project-context aggregate later. |
| Asset search and metadata | Partial | Codex: `AssetTools.find_assets`, `update_metadata_tags`, `get_metadata_tags`, `exists` | Metadata `Audit=TASK-004` wrote and read back. `find_assets` returned an empty list despite the just-created matching Blueprint and tag. | Yes: dependable asset-search wrapper. |
| Asset dependencies / referencers | Unreliable | Codex: `AssetTools.get_dependencies`, `get_referencers` | Both calls failed with `'NoneType' object is not iterable` for the disposable Blueprint, rather than returning an empty collection. | Yes. Normalize empty results and errors. |
| Actor creation and manipulation | Native | Codex: `SceneTools.add_to_scene_from_class`, `ActorTools.set_label`, `set_actor_transform`, `get_label`, `get_actor_transform`, `remove_from_scene`, `find_actors` | Created `AuditActor`; label and transform read back exactly; removal succeeded and `find_actors` returned `[]`. | No for primitives; add semantic spawning only if useful. |
| Asset creation / rename-or-move / delete | Native | Codex: `AssetTools.create_folder`, `BlueprintTools.create`, `AssetTools.move`, `delete`, `exists` | Created, moved, verified, and deleted the disposable content folder. Native API calls it `move`; no separate rename was exposed. | No for basic lifecycle. |
| Property read / write | Native | Codex: `ActorTools.set_actor_transform`, `get_actor_transform`; registry also exposes `ObjectTools.list_properties`, `get_properties`, `set_properties` | Transform write read back as `(400,500,600)`. Generic object property surface is registered; use its discovery-first workflow. | No, except domain validation. |
| Blueprint creation / edit / compile | Native | Codex: `BlueprintTools.create`, `compile_blueprint`; registry exposes variables, graphs, nodes/pins and graph DSL read/write | `BP_AuditActor` created and compiled successfully. | No for low-level editing; yes for safe domain templates. |
| Animation Blueprint / state-machine access | Missing | Native registry enumeration | No Animation Blueprint or state-machine toolset registered. | Yes. |
| Animation / skeleton / Blend Space / retarget assets | Partial | Registry: `SkeletalMeshTools` (skeleton, bones, sockets, materials) and `ControlRigTools` | Native skeletal and Control Rig coverage exists; no dedicated AnimSequence, Skeleton-asset authoring, Blend Space, or IK retargeter toolsets were registered. | Yes, beginning with inspection/import workflows. |
| Materials | Native | Codex: `MaterialTools.create_material`, `get_expressions`, `create_parameter_collection`; registry exposes expressions/connections/recompile | `M_Audit` and `MPC_Audit` created; new material expression query returned `[]`. | No for atomic graph work; yes for material conventions. |
| DataTables / DataAssets | Native | Codex: `DataTableTools.create`, `DataAssetTools.create`; registry exposes table rows/schema mutations | `DT_Audit` using `TableRowBase` and `DA_Audit` using `PrimaryDataAsset` were created successfully. | No for atomic access; yes for schema-aware project operations. |
| Level / map operations | Partial | Codex: `SceneTools.get_current_level`, `add_to_scene_from_class`, `remove_from_scene`, `find_actors`; registry exposes `load_level`, folder operations and save | Current temporary level and actor lifecycle tested. No disposable saved map was created, so map save/load has not yet been mutation-verified. | Yes: transactional map operations and save guardrails. |
| Python / script execution bridge | Partial | Codex: `ProgrammaticToolset.get_execution_environment`; TASK-007 UE source audit | A sandboxed Python orchestration bridge is available, with only `json`, `math`, `datetime`, `copy`, `re`, `time` plus `execute_tool`; it explicitly is **not** general Unreal Python execution. UE's `IPythonScriptPlugin::ExecPythonCommandEx` has result/log capture but no reliable submitted-code sandbox. | TASK-007 adds `CotSExecutionToolset` as a capability-constrained, read-only editor-query bridge; see `Docs/EXECUTION_BRIDGE.md`. |
| Console command execution | Missing | Codex: `EditorAppToolset.SearchCVars`; full editor-toolset enumeration | CVar search works, but no native console-command execution tool is registered. | Yes. |
| PIE start / stop / runtime inspection | Native | Codex: `EditorAppToolset.IsPIERunning`, `StartPIE`, `StopPIE` | Simulate-in-editor started, returned `true`, stopped, and returned `false`. Runtime inspection is limited to specialised runtime toolsets (e.g. GAS/Niagara), not a general actor inspector. | Yes: generic safe runtime inspection. |
| Automation Framework | Native | Codex: `AutomationTestToolset.DiscoverTests`, `ListTests` | Discovery returned `ready`; list returned 3 of 8,772 tests. Async run/status/result/stop tools are registered but no test run was started. | No for invocation; possibly results normalization. |
| Log / output retrieval | Native | Codex: `LogsToolset.GetLogEntries` | Returned recent native log entries. Tool schema requires camelCase `maxEntries` and a `pattern` argument even though empty pattern is valid. | No; helper may hide contract quirks. |
| Screenshots / viewport capture | Partial | Codex: `EditorAppToolset.CaptureViewport` | PNG capture succeeded (2,558,069-character response). Supposedly optional `captureTransform` and `annotations` must both be supplied in full or the call errors. | Yes: sane defaults and image persistence/metadata. |
| Async / long-running operations | Native | Codex: `AutomationTestToolset.DiscoverTests` | Native call completed asynchronously with `{"status":"ready"}`; `RunTests`, status, results, and stop are registered. | No for basic polling; yes for task-level orchestration. |
| Slate/editor UI automation | Native | Registry: `SlateInspectorToolset` | Snapshot, screenshot, click, type, select, observer and window controls are registered. Not used to substitute any test above. | No; reserve for gaps in semantic tools. |

## Disposable mutation record and cleanup

Created under `/Game/CotSDevAudit`:

- folder `/Game/CotSDevAudit`
- `BP_AuditActor`, then moved to `BP_AuditActorMoved`
- `M_Audit`
- `MPC_Audit`
- `DA_Audit`
- `DT_Audit`
- transient level actor `AuditActor` in `/Temp/Untitled_1`

Cleanup was native-only and verified:

- `SceneTools.remove_from_scene(AuditActor)` returned `true`; subsequent
  `SceneTools.find_actors(name='AuditActor', tag='', collision_channels=[])` returned `[]`.
- `AssetTools.delete('/Game/CotSDevAudit')` returned `true`; subsequent
  `AssetTools.exists('/Game/CotSDevAudit')` returned `false`.

No assets were created or changed under `/Game/CotS` or in `C:\Dev\Shardlands`.

## Remaining native gaps and first CotS toolsets

Prioritize these CotSDeveloperTools toolsets after the planned foundation work:

1. **ExecutionBridgeToolset** — a tightly allowlisted Python/console bridge, because
   native programmatic scripts cannot execute arbitrary Unreal Python and no console
   command executor is registered.
2. **AssetInspectionToolset** — reliable semantic asset search plus dependency and
   referencer normalization, because native search and empty-result queries are not
   dependable in this audit.
3. **AnimationAuthoringToolset** — Animation Blueprint/state-machine, Blend Space,
   retargeter, and animation-asset inspection/editing absent from native registration.
4. **LevelTransactionToolset** — guarded map save/load and undo-aware batch scene
   changes, building on the otherwise capable native actor tools.
5. **ViewportCaptureToolset** — wrapper applying valid native capture defaults and
   returning durable capture metadata.

Do not duplicate native primitive actor, asset lifecycle, Blueprint compile, material,
DataTable/DataAsset, PIE, Automation Framework, or log retrieval operations.

## TASK-008 mutation decision

Native MCP remains the preferred direct route for ordinary AssetTools lifecycle, ActorTools transforms/lifecycle, Blueprint compile, and DataAsset/DataTable schema operations. `CotSMutationToolset` adds only the guardrail gap: exact-path validation, previewable move/duplicate/delete intent, a disposable test scope, typed allowlisted property mutation, transaction/undo truthfulness, idempotent component handling, and uniform `FCotSOperationResult` audit data. It does not expose arbitrary reflection, component-class construction, shell, Python, or data-pipeline mutation.

