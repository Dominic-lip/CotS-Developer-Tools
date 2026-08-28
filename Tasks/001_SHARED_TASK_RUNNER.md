# TASK-001 — Shared Codex/Claude Task Runner

## Objective
Prove one Markdown task specification can be launched through either Codex or Claude Code without changing the task itself.

## Allowed scope
`C:\Dev\CotSDeveloperTools\Scripts`, docs and test output only.

## Forbidden scope
No Unreal asset changes. No writes to Shardlands or CotS.

## Requirements
- Validate `Scripts/Run-CotSTask.ps1` against the locally installed Codex CLI version.
- Validate it against Claude Code once installed/authenticated.
- Preserve interactive mode as the default for human permission visibility.
- Keep non-interactive mode available but do not bypass either client's safety/approval mechanisms.
- Fix CLI syntax based on locally installed help output rather than assumptions.

## Validation
Run the runner in `-DryRun` mode for each agent. Then run a harmless task that only reads this repository and reports its README title.

## Acceptance criteria
Both clients can consume the same task file and operate from the intended working directory.
