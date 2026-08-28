# TASK-011 — Source Control and Change Guardrails

## Objective
Make agent-driven Unreal work easy to review and hard to damage accidentally.

## Requirements
Provide shared preflight/report scripts for repository path, branch, dirty status, changed files and intended scope. After operations, report source changes, Unreal assets affected and validation results.

Never automatically use destructive Git cleanup/reset/history-rewrite operations. Never assume Git rollback is permission for a risky bulk mutation.

## Acceptance criteria
A sample Tool Lab mutation produces a before/after change report suitable for human review.
