# TASK-010 Validation — Deterministic Tool Lab Test Launch/Observe/Pass-Fail

Task spec: `Tasks/010_AUTOMATED_TESTING.md`. Acceptance criteria: "A
deterministic Tool Lab test launches, observes runtime state, terminates
cleanly and returns a pass/fail result without human editor manipulation."
Per `Docs/FOUNDATION_COMPLETION_LEDGER.md`, native PIE/Automation coverage
and runtime readers already existed (`e4763c2`, `5bb14ed`, `028b81d`) and
TASK-012 gave one Codex runtime proof, but no standalone deterministic
pass/fail artifact had been committed. This reuses the freshest already-run
automation pass rather than launching Unreal again, per the "do not re-run
durable evidence unless relevant source or its acceptance contract changed"
rule — the fixed `RunCotSAutomation` command and plugin test sources are
unchanged since that run.

## Evidence (reused, unchanged source): `Docs/Validation/TASK-008A_LIFECYCLE_PROOF.md`, step 5

`mcp__cots-host__RunCotSAutomation` invokes the fixed, deterministic command:

```
UnrealEditor-Cmd.exe CotSToolLab.uproject -unattended -nop4 -nosplash -NullRHI -NoSound
  -DDC-ForceMemoryCache -ExecCmds="Automation RunTests CotS;Quit"
  -TestExit="Automation Test Queue Empty"
```

This directly satisfies each acceptance clause:

- **Launches**: a real `UnrealEditorCmd` process starts the project, fully
  unattended (`-unattended -nop4 -nosplash`), with no editor window requiring
  a human (`-NullRHI -NoSound`).
- **Observes runtime state**: the Automation Controller executes each
  registered `CotS.*` test against live engine/plugin state — asset registry
  reads/writes, actor spawn/transform/component lifecycle, curve property
  mutation, PIE-preflight checks — not static source inspection.
- **Terminates cleanly**: `-TestExit="Automation Test Queue Empty"` plus
  `;Quit` drives a deterministic, self-terminating exit once the test queue
  drains; the log shows `LogAutomationCommandLine: Shutting down. GIsCriticalError=0`.
- **Returns a pass/fail result**: `LogAutomationCommandLine: Display: ****
  TEST COMPLETE. EXIT CODE: 0 ****`, with per-test
  `Test Completed. Result={Success}` for all 12 tests; a genuine test
  failure would flip both the per-test result and the process exit code, so
  this is a real pass/fail signal, not a fixed success stub.
- **Without human editor manipulation**: the entire run is driven by the
  fixed Host MCP `RunCotSAutomation` operation; no manual editor interaction
  occurred.

This run was captured post the process-group isolation fix (`13bdc10`), and
`Docs/Validation/TASK-008A_LIFECYCLE_PROOF.md`'s infrastructure note already
records that Host MCP remained reachable and the run completed cleanly with
no early `ConsoleCtrl RequestExit`, corroborating determinism under the fixed
infrastructure.

## Acceptance

The deterministic launch/observe/terminate/pass-fail cycle required by
TASK-010 is directly evidenced by an actual UE 5.8.1 run captured in
`Docs/Validation/TASK-008A_LIFECYCLE_PROOF.md`; the native PIE start/stop and
runtime-actor/property readers referenced in the ledger
(`e4763c2`/`5bb14ed`/`028b81d`) remain in place as retained capability and
are exercised independently by `CotS.Inspection.ExactPathsAndEmptyReferences`'s
PIE-preflight check within the same run.
