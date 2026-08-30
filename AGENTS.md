# CotS Developer Tools — Agent Operating Rules

## Mission
Build and operate an agent-neutral Unreal Engine production factory for Chronicles of the Sigilarium. Codex, Claude Code, and future MCP-compatible agents must be able to use the same capabilities, then use those capabilities to build the production MMO in the dependency order defined by `Docs/PRODUCTION_ROADMAP.md`.

## Workspace boundaries
The expected local workspace is:

- `C:\Dev\Shardlands` — legacy donor/reference project. Treat as READ-ONLY unless a task explicitly authorizes a write.
- `C:\Dev\CotSDeveloperTools` — this repository. Shared tooling, task specifications, migration/reuse evidence and autonomous orchestration belong here.
- `C:\Dev\CotS` — clean production game. Production tasks `TASK-100+` may modify it only within their explicit scope.
- `C:\Dev\Tasks` — optional external task specifications.

Known additional read/reference sources include the GitHub repositories `Dominic-lip/Shardlands`, `Dominic-lip/CotS-Website`, `Dominic-lip/CotS-Platform-API`, and `Dominic-lip/CotS-Game`. A production task may inspect these when relevant. Do not mutate another repository merely because it contains reusable work; cross-repository writes require explicit task scope.

Never delete, reset, clean, reorganize, rename, or wholesale-migrate Shardlands. Never use destructive Git commands (`reset --hard`, forced checkout, history rewrite, force push, broad clean) without explicit human authorization.

## Existing-work-first production rule
Every production task must follow `Docs/EXISTING_WORK_REUSE_POLICY.md` before implementing a subsystem. This is a just-in-time check, not a requirement to exhaustively re-audit all legacy work up front.

For the subsystem currently being built:
1. Search the existing-work index and previous reuse decisions.
2. Inspect only relevant Shardlands/local donor code, assets, data and history, plus website/platform/backend work where the subsystem crosses those boundaries.
3. Prefer verified reuse/adaptation over reimplementation when it reduces risk or duplicated effort.
4. Record why significant donor code is reused, adapted, rebuilt or left behind.
5. Never copy a large body of code/assets blindly; reconcile dependencies, authority, persistence, data identities and current UE 5.8 architecture first.

Local `C:\Dev\Shardlands` may contain newer or unpushed work than remote GitHub. Read its actual filesystem/Git state when relevant, but keep it read-only.

## Agent concurrency safety
- Only one mutating AI agent may operate against a given Unreal project, asset set, filesystem workspace, or Git worktree at a time.
- Codex and Claude may both be connected for read-only compatibility checks, but do not let them concurrently create, edit, rename, delete, save, compile, run PIE mutations, or commit against the same working state.
- Normal operation is one active agent and the other on standby. Hand over through the supervisor/checkpoint contract.
- Parallel mutation is allowed only when work is deliberately isolated into separate repositories/worktrees/projects with non-overlapping scope.

## Working method
For substantial tasks use this sequence:

1. Inspect and reconcile the current state.
2. For production work, perform the task-scoped existing-work check.
3. State a short implementation plan.
4. Identify intended files/assets and risks.
5. Execute the smallest coherent change.
6. Compile/validate/test using the strongest available mechanism.
7. Re-inspect the resulting state.
8. Report exactly what changed, donor/reuse decisions, tests run, failures/warnings, and remaining work.

Do not claim success when a build/test was not actually run. Distinguish `implemented`, `compiled`, `tested`, and `verified in Unreal`.

## Unreal build execution safety
- UnrealBuildTool writes and rotates diagnostics under `%LOCALAPPDATA%\UnrealBuildTool`. Some AI-agent sandboxes cannot write there even when they can edit the repository.
- Use the canonical task-appropriate build entry point. `Scripts\Build-ToolLab.cmd` remains the Tool Lab build path; production tasks should establish and then use an equally deterministic CotS build path.
- If a build script reports a sandbox/write block, do not retry raw `dotnet`, `UnrealBuildTool`, or `Build.bat` from the same restricted context.
- A build is verified only when the canonical script returns exit code 0 and UBT reports success.

## Autonomous lifecycle
- `Scripts\CotSHostMcp.py` is the agent-neutral host controller for the disposable ToolLab and shared orchestration capabilities. It is not an arbitrary shell/process endpoint.
- Respect the persistent single-writer lock and provider-neutral task identity.
- Production lifecycle automation must retain the same principle: fixed, auditable operations rather than unrestricted host execution.

## Unreal / MCP rules
- Target Unreal Engine 5.8 unless a task says otherwise.
- Prefer Epic's native Unreal MCP capabilities when sufficient.
- Do not duplicate native MCP functions unless a demonstrated reliability/capability gap exists.
- Do not guess private/experimental UE 5.8 C++ MCP APIs. Inspect installed engine source/headers and local plugin implementation first.
- High-level CotS tools should sit above generic/native primitives and remain usable by both Codex and Claude.
- Return exact object paths/classes whenever possible; do not rely only on display names.
- Mutating tools should be idempotent where practical and report affected assets/objects.
- Destructive/bulk operations require a dry-run or impact preview where practical.

## Tool design principles
- Capability before content.
- Inspection before mutation.
- Validation after mutation.
- Deterministic repeated editor work should become a tool.
- Prefer reusable domain operations over brittle click automation.
- Keep editor tooling out of packaged game runtime unless runtime support is explicitly necessary.
- Keep structured results machine-readable even when also logging human-readable summaries.

## Current phase
The toolchain foundation (`TASK-000` through `TASK-016`) is complete. The current phase is **CotS production development**, beginning with `TASK-100` and following `Docs/PRODUCTION_ROADMAP.md`. Production tasks may write `C:\Dev\CotS` only within their stated scope. Shardlands remains donor/reference and read-only.
