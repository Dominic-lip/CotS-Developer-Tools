# TASK-004 — Native UE 5.8 MCP Capability Audit

## Objective
Determine exactly what Epic's native UE 5.8 MCP implementation already provides before CotS duplicates any editor capability.

## Allowed scope
Tool Lab and documentation/report output. Harmless disposable test assets may be created only in the Tool Lab.

## Forbidden scope
No Shardlands or CotS writes.

## Requirements
Test and classify at least:
- project/editor/viewport/selection inspection
- asset search and metadata
- asset dependencies/referencers
- actor creation/manipulation
- asset creation/rename/move/delete
- property read/write
- Blueprint creation/edit/compile
- Animation Blueprint/state machine access
- animation/skeleton/Blend Space/retarget assets
- materials
- DataTables/DataAssets
- level/map operations
- Python/script execution bridge if available
- console command execution if available
- PIE start/stop/runtime inspection
- Automation Framework invocation
- log/output retrieval
- screenshots/viewport capture
- async/long-running operations

For each capability record: `Native`, `Partial`, `Missing`, or `Unreliable`; tested client(s); exact native tool; limits; and whether a CotS high-level tool is warranted.

## Validation
Repeat critical read operations with both Codex and Claude. Perform mutations only on disposable Tool Lab assets and clean them up safely.

## Acceptance criteria
Produce `Docs/MCP_CAPABILITY_MATRIX.md` grounded in actual UE 5.8 tests. The matrix becomes the authority for subsequent tool implementation.
