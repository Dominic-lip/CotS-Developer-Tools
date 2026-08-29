# TASK-004 — Native UE 5.8 MCP Capability Audit

## Objective
Determine exactly what Epic's native UE 5.8 MCP implementation already provides before CotS duplicates any editor capability. Produce a capability matrix grounded in actual UE 5.8 calls, not schema inspection alone.

## Current baseline
- Tool Lab builds successfully on UE 5.8.
- `ModelContextProtocol` and `AllToolsets` are enabled in `CotSToolLab.uproject`.
- MCP uses `/mcp`, port `8000`, auto-start enabled, Tool Search enabled.
- 52 native toolsets are discoverable through the three MCP meta-tools.
- Codex and Claude have both proven read-only MCP connectivity.
- Normal operation is one active mutating agent at a time.

## Allowed scope
- `C:\Dev\CotSDeveloperTools`
- `C:\Dev\CotSDeveloperTools\ToolLab`
- Disposable Unreal test content under `/Game/CotSDevAudit` only.
- Documentation/report output under `Docs/`.

## Forbidden scope
- No writes to `C:\Dev\Shardlands`.
- No writes to `C:\Dev\CotS`.
- Do not begin TASK-005.
- Do not mutate assets outside `/Game/CotSDevAudit`.
- Do not run destructive Git operations.
- Do not run a full C++ Tool Lab build while the Tool Lab editor is open. Native editor/MCP testing does not require that build.

## Safety rules
1. Inspect before mutation.
2. Use exact Unreal object paths.
3. Keep every disposable asset beneath `/Game/CotSDevAudit`.
4. Prefer idempotent operations and unique audit asset names.
5. After each mutation, re-read the affected object and verify the requested state.
6. If a native tool behaves unexpectedly, record it as `Unreliable` rather than repeatedly forcing it.
7. At the end, delete only the disposable audit content created by this task and verify cleanup.
8. Do not let a second agent mutate the same Tool Lab concurrently.

## Phase A — Inventory and read-only inspection
Enumerate all native toolsets and record exact tool names. Verify representative read operations for:
- project/editor identity
- viewport and selection
- asset search and metadata
- dependencies and referencers
- actor/world/level inspection
- Blueprint inspection
- skeleton/animation inspection
- plugin/module awareness
- logs/output retrieval
- Automation Framework discovery/status

Schema discovery alone is not sufficient when a callable read operation exists.

## Phase B — Disposable world/actor mutation
Using `/Game/CotSDevAudit` and the current disposable Tool Lab world where possible, test:
- actor creation
- actor rename
- transform/property mutation
- component add/remove if native support exists
- selection/query after mutation
- actor deletion
- level/map create/save/open operations if native support exists

Record whether each operation is `Native`, `Partial`, `Missing`, or `Unreliable`.

## Phase C — Disposable asset mutation
Create only disposable audit assets and test native support for:
- generic asset creation
- rename/move/delete
- property read/write
- save
- dependency/referencer re-query
- DataAsset/DataTable/StringTable workflows where available
- material creation/editing where available
- Gameplay Tags / GAS data where available
- PCG and Niagara smoke operations where available

Do not create large content or expensive generated data.

## Phase D — Blueprint capability test
Create one minimal disposable Blueprint in `/Game/CotSDevAudit` and test as far as native tools permit:
- Blueprint creation
- variable/property creation
- component creation
- graph/node construction
- compile
- compile-error inspection
- save
- reopen/reinspect
- delete during cleanup

Record separately whether Blueprint *inspection*, *construction*, *graph editing*, and *compilation* are supported; do not collapse them into one result.

## Phase E — Animation/character capability test
Without importing external production assets, test and classify native support for:
- animation asset inspection
- skeleton inspection
- Animation Blueprint inspection/editing
- state-machine inspection/editing
- Blend Space creation/editing
- IK Rig / IK Retargeter inspection/editing
- Control Rig support
- Sequencer animation/control-rig support
- MetaHuman-specific discovery or assembly support

If the native surface only supports Sequencer/Control Rig but not locomotion/retargeting, record that distinction explicitly.

## Phase F — Runtime/testing/diagnostics
Test native support for:
- PIE start/stop
- runtime actor inspection
- input/simulation if available
- Automation test discovery
- Automation test execution/status/results/cancel
- output log querying
- map validation/checks
- viewport/screenshot capture
- async/long-running task handling

Do not run destructive or long stress tests.

## Phase G — Cleanup and evidence
- Delete only `/Game/CotSDevAudit` content created by this task.
- Verify no disposable actors/assets remain.
- Verify Git status and distinguish expected documentation changes from local/generated Unreal files.
- Do not commit binary audit assets; the intended durable deliverable is the documentation matrix.

## Capability classification
For every tested capability record one of:
- `Native` — works directly and reliably using Epic's native MCP surface.
- `Partial` — useful support exists but important sub-operations are absent or require awkward composition.
- `Missing` — no suitable native MCP operation is exposed.
- `Unreliable` — a suitable operation exists but failed or behaved inconsistently in actual testing.

For each entry record:
- capability
- classification
- exact native toolset/tool(s)
- tested client(s)
- exact test performed
- result/evidence
- limitations
- whether a CotS high-level wrapper/tool is warranted
- priority: `Foundation`, `High`, `Medium`, or `Low`

## Cross-agent validation
Do not duplicate the entire mutation audit with both agents. After the primary agent completes the matrix, use the standby agent only for a small read-only compatibility sample of critical native calls unless a client-specific problem is suspected.

## Deliverable
Create/update:

`Docs/MCP_CAPABILITY_MATRIX.md`

It must contain:
1. Executive summary.
2. Native toolset inventory.
3. Capability matrix.
4. Important reliability findings.
5. CotS-relevant gaps.
6. Recommended first custom CotSDeveloperTools capabilities, ordered by dependency and leverage.
7. Explicit recommendation on what should remain native vs what should become a CotS high-level tool.

## Validation
- Critical operations are based on actual MCP calls against UE 5.8.
- Disposable mutations are verified after write.
- Audit content is cleaned up.
- No Shardlands or CotS writes occurred.
- Final Git status is reported.

## Acceptance criteria
`Docs/MCP_CAPABILITY_MATRIX.md` becomes the authority for TASK-005 and subsequent tool implementation. The task is complete only when the matrix distinguishes native primitives from the CotS-specific orchestration/validation layer we still need to build.
