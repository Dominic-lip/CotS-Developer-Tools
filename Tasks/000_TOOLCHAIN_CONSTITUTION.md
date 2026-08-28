# TASK-000 — Toolchain Constitution

## Objective
Confirm and enforce the development architecture, safety boundaries and agent-neutral rules before deeper tooling work begins.

## Context
Previous Shardlands development accumulated useful systems but also significant prototype/editor debt. The new production approach is capability-first: build the factory before building the game.

## Allowed scope
`C:\Dev\CotSDeveloperTools` only.

## Forbidden scope
No writes to `C:\Dev\Shardlands` or `C:\Dev\CotS`.

## Requirements
- Review `AGENTS.md`, architecture and roadmap.
- Verify repository structure is internally consistent.
- Identify any rule that would accidentally tie the toolchain to Codex or Claude specifically.
- Identify missing safety rules for Unreal asset mutation, Git or bulk operations.
- Improve documentation where necessary.

## Validation
- `git status`
- inspect all root policy/docs files
- ensure no task requires production game implementation yet

## Acceptance criteria
Workspace boundaries, shared task format, agent neutrality and no-destructive-operation rules are explicit and non-contradictory.

## Deliverables
Any documentation corrections plus a concise constitution review report.
