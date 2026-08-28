# TASK-007 — Controlled Development Execution Bridge

## Objective
Provide a development-only escape hatch for novel Unreal editor operations that do not yet justify dedicated CotS tools.

## Requirements
Prefer a native UE MCP Python/console/script facility if TASK-004 proves one exists. Otherwise implement the narrowest safe bridge supported by UE 5.8.

The bridge must:
- be editor/development only;
- log requested operation and completion/failure;
- make affected assets discoverable where practical;
- not silently bypass Unreal transactions/validation;
- refuse obvious process/system-shell escalation from inside Unreal unless explicitly designed and authorized;
- be treated as a prototyping mechanism, not the permanent API for repeated workflows.

## Acceptance criteria
An agent can execute one harmless novel editor inspection in Tool Lab, validate the result, and report the audit trail.
