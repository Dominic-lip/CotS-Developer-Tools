# Validation and diagnostics

TASK-009 keeps native UE 5.8 MCP as the primary route for Blueprint compilation, Output Log retrieval, and Automation execution. `CotSValidationToolset` adds stable machine-readable exact asset and `/Game` folder validation.

Live proof: a missing disposable CurveFloat returned `asset_not_found`; after typed creation the same exact path validated successfully; typed deletion restored the expected failure. Newly created in-memory assets are validated through an object fallback before their registry entry is persisted.

UE 5.8's `UEditorEngine::Map_Check` is private. CotS does not bypass that access boundary via console execution; map check remains native/UI-driven until Epic exposes a supported callable MCP surface.
