# TASK-008 — Safe Mutation Primitives

## Objective
Allow controlled, inspectable editor changes after the read-only foundation is proven.

## Target capabilities
Create/duplicate/move/rename assets; set supported properties; create/delete disposable actors; add/remove supported components; save assets/levels; compile Blueprints; manipulate DataAssets/DataTables where supported.

## Requirements
- exact target paths
- impact reporting
- idempotence where practical
- transactions/undo where supported
- dry-run/preview for bulk operations
- structured success/warning/error output

## Validation
All mutation tests occur in a disposable Tool Lab namespace and are followed by independent re-inspection.
