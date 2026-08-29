# CotS Developer Tools — Agent Operating Rules

## Mission
Build an agent-neutral Unreal Engine production toolchain for Chronicles of the Sigilarium. Codex, Claude Code, and future MCP-compatible agents must be able to use the same capabilities.

## Workspace boundaries
The expected local workspace is:

- `C:\Dev\Shardlands` — legacy donor/reference project. Treat as READ-ONLY unless a task explicitly authorizes a write.
- `C:\Dev\CotSDeveloperTools` — this repository. Tooling work belongs here.
- `C:\Dev\CotS` — clean production game. Do not create or modify production implementation until the relevant bootstrap task explicitly authorizes it.
- `C:\Dev\Tasks` — optional external task specifications.

Never delete, reset, clean, reorganize, rename, or wholesale-migrate Shardlands. Never use destructive Git commands (`reset --hard`, forced checkout, history rewrite, force push, broad clean) without explicit human authorization.

## Agent concurrency safety
- Only one mutating AI agent may operate against a given Unreal project, asset set, filesystem workspace, or Git worktree at a time.
- Codex and Claude may both be connected for read-only compatibility checks, but do not let them concurrently create, edit, rename, delete, save, compile, run PIE mutations, or commit against the same working state.
- Normal operation is one active agent and the other on standby. Hand over by stopping the first agent, recording current state/results, then starting the second against the same task specification.
- Parallel mutation is allowed only when work is deliberately isolated into separate repositories/worktrees/projects with non-overlapping scope.

## Working method
For substantial tasks use this sequence:

1. Inspect the current state.
2. State a short implementation plan.
3. Identify intended files/assets and risks.
4. Execute the smallest coherent change.
5. Compile/validate/test using the strongest available mechanism.
6. Re-inspect the resulting state.
7. Report exactly what changed, tests run, failures/warnings, and remaining work.

Do not claim success when a build/test was not actually run. Distinguish `implemented`, `compiled`, `tested`, and `verified in Unreal`.

## Unreal build execution safety
- UnrealBuildTool writes and rotates diagnostics under `%LOCALAPPDATA%\UnrealBuildTool`. Some AI-agent sandboxes cannot write there even when they can edit the repository.
- Use `Scripts\Build-ToolLab.cmd` as the canonical Tool Lab build entry point. It performs a write preflight before launching UBT.
- If the build script reports `[BLOCKED]`, do not retry raw `dotnet`, `UnrealBuildTool`, or `Build.bat` from the same sandbox; doing so can cause the misleading Windows `dotnet.exe` CLR error `0xE0434352`.
- Instead request an explicitly unsandboxed/approved command execution when the client supports it, or ask the human operator to run `Scripts\Build-ToolLab.cmd` from a normal user PowerShell.
- A build is considered verified only when the canonical script returns exit code 0 and UBT reports `Result: Succeeded`.

## Unreal / MCP rules
- Target Unreal Engine 5.8 unless a task says otherwise.
- Prefer Epic's native Unreal MCP capabilities when they are sufficient.
- Do not duplicate native MCP functions until `Tasks/004_NATIVE_MCP_CAPABILITY_AUDIT.md` has demonstrated a real gap or reliability problem.
- Do not guess private/experimental UE 5.8 C++ MCP APIs. Inspect the installed engine source/headers and local plugin implementation first.
- High-level CotS tools should sit above generic/native primitives and remain usable by both Codex and Claude.
- Return exact object paths and classes whenever possible; do not rely only on display names.
- Mutating tools should be idempotent where practical and report all affected assets/objects.
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
The current phase is **toolchain foundation**. Do not begin production CotS game implementation. Build and prove the factory first.
