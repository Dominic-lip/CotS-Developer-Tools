# TASK-005 Validation — Plugin Foundation Revalidation

Task spec: `Tasks/005_PLUGIN_FOUNDATION.md`. Per
`Docs/FOUNDATION_COMPLETION_LEDGER.md`, the plugin implementation (`d80f82f`:
result core, domain interfaces, foundation test) already existed; the
outstanding gap was a committed canonical build/startup/module-load/test
result, not new implementation. This records that revalidation only.

## Canonical build

`mcp__cots-host__BuildToolLab` (the fixed `Scripts\Build-ToolLab.cmd`, run
against the actual local UE 5.8.1 installation):

```
Target:  CotSToolLabEditor Win64 Development
...
Result: Succeeded
Total execution time: 1.41 seconds
[OK] CotS Tool Lab editor target built successfully.
```

`exit_code: 0`. No API drift fixes were needed against the installed UE 5.8.1
— the existing plugin source still compiles clean.

## Editor startup and module load

`mcp__cots-host__RunCotSAutomation` (the fixed CotS Automation suite: an
unattended `-NullRHI` editor launch running `Automation RunTests CotS;Quit`)
launched a real `CotSToolLabEditor` process. Editor startup and module load
are proven directly by the run rather than by a separate interactive-editor
step:

- `ToolLab/Saved/Logs/CotSToolLab.log` shows the editor booting, loading the
  `CotSDeveloperTools` module, and the Automation Controller both discovering
  and executing 12 `CotS.*` tests against live toolset classes.
- Each `*.ToolRegistration` test (`CotS.Foundation.ToolRegistration`,
  `CotS.Inspection.ToolRegistration`, `CotS.Execution.ToolRegistration`,
  `CotS.Mutation.ToolRegistration`, `CotS.Validation.ToolRegistration`,
  `CotS.Lifecycle.PreflightAndRegistration`) directly asserts
  `UToolsetRegistry::IsToolsetClassRegistered(...)` for its domain toolset
  class, which can only pass if the plugin module loaded and the Foundation,
  Inspection, Execution, Mutation, Validation, and Lifecycle domain toolsets
  all registered successfully in a live editor process — i.e. this is
  stronger, more direct evidence of "editor startup + module load" than a
  separate manual open would have been.

## Automated plugin tests (exceeds "one automated plugin test")

Full `CotS.*` automation run result, `ToolLab/Saved/Logs/CotSToolLab.log`:

```
**** TEST COMPLETE. EXIT CODE: 0 ****
```

All 12 tests reported `Test Completed. Result={Success}`, zero failures:

1. `CotS.Execution.RefusesUnsupportedRequests` — console/query smoke test
   (rejects `cmd.exe`, PowerShell, Python, cvar-injection, and empty
   requests).
2. `CotS.Execution.ToolRegistration`
3. `CotS.Execution.ValidHarmlessQuery` — console smoke test (harmless
   `project.context` query, twice, with distinct operation IDs).
4. `CotS.Foundation.OperationResult`
5. `CotS.Foundation.ToolRegistration`
6. `CotS.Inspection.ExactPathsAndEmptyReferences`
7. `CotS.Inspection.ToolRegistration`
8. `CotS.Lifecycle.PreflightAndRegistration`
9. `CotS.Mutation.ActorWorkflow`
10. `CotS.Mutation.AssetWorkflowAndGuardrails`
11. `CotS.Mutation.ToolRegistration`
12. `CotS.Validation.ToolRegistration`

No production CotS or Shardlands scope was touched; all disposable fixtures
created by the mutation/asset tests (under `/Game/CotSMutationLive`,
`/Game/CotSLifecycleFixture`, `/Game/CotSInspectionFixtures`) are created and
deleted by the tests themselves as part of their own assertions.

## Infrastructure note (not a TASK-005 acceptance blocker)

During this revalidation the Host MCP process (`Scripts/CotSHostMcp.py`)
became unreachable twice, and on the second occurrence the owning
`CotSAgentSupervisor.py` and `CotSFactoryController.py` processes also exited
— while this turn's own `claude -p` process continued unaffected. The first
Host MCP loss coincided with `ToolLab/Saved/Logs/CotSToolLab-backup-*-13.29.13.log`
showing the automation editor process receiving `ConsoleCtrl RequestExit`
0.14s after launch, immediately after a `BuildToolLab` run. This looks like a
shared-console signal-propagation issue (none of `CotSHostMcp.py`'s,
`CotSAgentSupervisor.py`'s, or `CotSFactoryController.py`'s subprocess
launches isolate a new process group/console), not a TASK-005 plugin defect.
Recovery was a manual `python Scripts/CotSHostMcp.py` restart; the retried
`RunCotSAutomation` then completed cleanly end-to-end as recorded above. This
is left as a follow-up infrastructure concern rather than fixed here, since
it is outside TASK-005's plugin-foundation scope and a fix needs deliberate,
isolated repro rather than an in-place guess during task work.

## Acceptance

Clean build, editor startup, module load, and automated plugin tests (12,
exceeding the required one) are all directly evidenced above from actual UE
5.8.1 runs, not source inspection alone.
