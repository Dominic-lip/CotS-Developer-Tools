# TASK-008A Validation — Full Host MCP Lifecycle Proof

Task spec: `Tasks/008A_AUTONOMOUS_DEVELOPMENT_ORCHESTRATOR.md`. Required
proof: "Acquire the lock, open ToolLab, close it automatically, build, test,
reopen, wait for Unreal MCP, perform a harmless inspection, close, reopen,
and verify that the lifecycle remains ready. Release the lock after the
proof." Executed as a single Claude session on 2026-08-30 under agent id
`supervisor-task-008a`, exercising only the fixed Host MCP operations.

## Sequence and evidence

1. **AcquireMutationLock** — `{"owner": "supervisor-task-008a", "acquired": true}`.
2. **OpenToolLab** — `editor_pid: 46704`, `mcp_url: http://127.0.0.1:8000/mcp`.
3. **CloseToolLab (automatic)** — graceful via the native
   `CotSDeveloperTools.CotSLifecycleToolset.RequestToolLabShutdown` tool:
   `"shutdown_method": "unreal_mcp"`, `"graceful": true`,
   `"unreal_mcp_gone": true`, exact PID `46704` verified exited.
4. **BuildToolLab** — canonical `Scripts\Build-ToolLab.cmd`: `exit_code: 0`,
   `Result: Succeeded`.
5. **RunCotSAutomation** — fixed `CotS.*` automation suite: `exit_code: 0`;
   `ToolLab/Saved/Logs/CotSToolLab.log` shows 12/12
   `Test Completed. Result={Success}` and
   `**** TEST COMPLETE. EXIT CODE: 0 ****`, with no early
   `ConsoleCtrl RequestExit` termination (see infrastructure note below).
6. **OpenToolLab (reopen)** — `editor_pid: 20176`.
7. **WaitForUnrealMcp** — `{"ready": true, "mcp_url": "http://127.0.0.1:8000/mcp"}`.
8. **Harmless inspection** — a direct MCP session (`initialize` ->
   `notifications/initialized` -> `tools/call call_tool`) against
   `http://127.0.0.1:8000/mcp` invoked
   `CotSDeveloperTools.CotSFoundationToolset.GetStatus`, returning
   `"success": true`, `unreal_version: 5.8.1-56057345+++UE5+Release-5.8`,
   `plugin: CotSDeveloperTools`. Read-only; no mutation.
9. **CloseToolLab** — graceful again via the same native lifecycle tool,
   exact PID `20176` verified exited.
10. **OpenToolLab (reopen)** — `editor_pid: 34460`.
11. **WaitForUnrealMcp** — `{"ready": true}`.
12. **GetToolLabStatus (verify)** —
    `{"editor_running": true, "editor_pid": 34460, "mcp_ready": true, "mutation_lock_owner": "supervisor-task-008a"}`
    — lifecycle confirmed ready.
13. **ReleaseMutationLock** — `{"owner": "supervisor-task-008a", "released": true}`.

No production CotS or Shardlands scope was touched; the only mutation this
proof performed was the automation suite's own self-contained disposable
fixtures (already covered by TASK-005/006/008 evidence), and the ToolLab
editor open/close/build/test cycle itself.

## Infrastructure note

This proof directly exercised the `BuildToolLab` -> `RunCotSAutomation` path
immediately after the process-group isolation fix (see commit
`13bdc10`, "Isolate Host MCP build/editor children into their own process
group..."). Unlike the two prior occurrences during TASK-005 validation,
Host MCP remained reachable and responsive throughout this entire run (step
5's `GetToolLabStatus` immediately after `RunCotSAutomation` succeeded
without a connection error), and the editor log shows a clean
`**** TEST COMPLETE. EXIT CODE: 0 ****` rather than an early `ConsoleCtrl
RequestExit`. This is corroborating evidence the fix holds, not a
substitute for it.

## Acceptance

Every step of the specified lock/open/close/build/test/reopen/read/close/
reopen/verify/release sequence is directly evidenced above from actual Host
MCP and native Unreal MCP calls, not source inspection alone.
