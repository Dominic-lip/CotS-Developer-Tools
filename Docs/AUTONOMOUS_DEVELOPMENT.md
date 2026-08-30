# Autonomous ToolLab development

`Scripts\CotSHostMcp.py` is the local, agent-neutral lifecycle controller. Start it with `Scripts\Start-CotSHostMcp.cmd`; it binds exclusively to `http://127.0.0.1:8010/mcp`.

It exposes only these fixed MCP operations: `GetToolLabStatus`, lock acquire and release, `OpenToolLab`, `CloseToolLab`, `WaitForUnrealMcp`, `BuildToolLab`, and `RunCotSAutomation`. Every operation that can change ToolLab state requires an `agent_id` that owns the controller's single-writer lock. The controller records only its own launched editor PID in `.cots/host-state.local.json`.

`CloseToolLab` opens a UE 5.8 HTTP MCP session internally and invokes only `CotSDeveloperTools.CotSLifecycleToolset.RequestToolLabShutdown` through UE's `call_tool` search dispatcher. That editor-only tool rejects non-ToolLab contexts, active Slate modals, active PIE (after requesting a clean PIE stop), and persistent dirty packages; it then calls UE's normal non-forced `FPlatformMisc::RequestExit(false)`. The Host verifies the exact recorded PID and MCP endpoint disappear before reporting a graceful `unreal_mcp` close. WM_CLOSE is a constrained fallback only when the recorded process owns a suitable top-level window; the controller has no generic Unreal-MCP proxy or public force-kill operation.

If the lifecycle tool refuses its safety preconditions, `CloseToolLab` returns that structured refusal and does not try WM_CLOSE. This preserves dirty-package safety rather than converting a refusal into a close attempt.

The controller does not accept shell text, executable paths, arbitrary command arguments, filesystem paths, or target PIDs. Build and test commands are fixed to the canonical build script and the `CotS` automation invocation with the in-memory DDC workaround. Local lock/checkpoint state is intentionally ignored.

Typical agent sequence: acquire a stable agent ID, close ToolLab, build, run tests, open, wait for `http://127.0.0.1:8000/mcp`, use native Unreal MCP for inspection/mutation, close when finished, then release the lock. Under the persistent supervisor that identity is task-scoped and provider-neutral (for example `supervisor-task-012`), so Codex/Claude handoff does not strand a provider-specific owner. `TransferMutationLock` can atomically migrate an existing legacy `codex-task-*`/`claude-task-*` owner to that stable identity; it requires the current owner token and never releases the lock in between. Do not use this controller to evade the repository's broader single-mutating-agent policy.

## Persistent Codex supervisor (TASK-008B)

`Scripts\Launch-CotS-Agents.bat` starts `CotSAgentSupervisor.py` by default;
pass `manual` only for an intentionally interactive Codex CLI. The supervisor
owns Codex App Server, stores a durable thread/checkpoint in `.cots`, and sends
the required continuation prompt after each completed turn. It stops only for a
structured human gate, completion, failure, or usage-reset state.

It uses App Server's `auto_review` approval reviewer with granular approval
settings. Routine workspace work does not wait for a human approval; permission
expansion and MCP elicitation remain risk-reviewed. Autonomous Git completion
must use `Scripts\CotS-GitCompletion.py`, which allows status/diff checks and a
validated exact-file commit followed only by `git push origin main`. Reset,
clean, force-push, history rewrite, arbitrary process commands, and access
outside this repository remain outside the autonomous approval boundary.
If Git metadata is unavailable inside App Server's workspace sandbox, only the
exact fixed completion wrapper may request a supported escalation, and its
`auto_review` decision remains the sole approval path. The granular sandbox and
rule channels exist only to let that reviewer assess this wrapper request; they
do not authorize arbitrary commands.

## Live dashboard and Codex/Claude rotation (TASK-008C)

The supervisor console redraws a fixed-size status summary in place — active
agent, preferred agent, current task/phase, turn count, both providers'
availability, ToolLab/Unreal MCP/Host MCP state, the mutation lease owner, Git
branch/status/last commit, and a bounded recent-events list. It never prints
raw protocol JSON to the console. Detailed traffic goes to
`.cots/codex-protocol.log` and `.cots/claude-protocol.log`; summarized events
go to `.cots/supervisor-events.log`.

`ClaudeAgent` drives `claude -p --output-format json`, resumed by
`--resume <session_id>`, with `--allowedTools` fixed to
`Read Edit Write Grep Glob` plus the same two shell invocations Codex is
allowed (`Scripts\CotS-GitCompletion.py`, `Scripts\Build-ToolLab.cmd`) — it
cannot run any other shell command. `--permission-mode bypassPermissions` is
safe here specifically because that tool allowlist, not a human approval
prompt, is the actual safety boundary; a non-interactive `-p` session has no
one to answer an approval prompt anyway.

When the active provider reports a usage/rate limit, the supervisor stops
submitting it further turns, records the reset time when known, saves the
checkpoint, and rotates to the other configured provider if one is usable.
Only when neither provider is currently usable does it enter
`WAITING_FOR_AGENT_CAPACITY` (or, with a single configured provider,
`WAITING_FOR_USAGE_RESET`) and poll on a bounded interval — it does not exit
the process for this. Exit is reserved for `HUMAN_GATE`, `COMPLETE`, `FAILED`,
or an operator's Ctrl+C. Rotation always fully closes the previous provider's
process before the next one starts a turn; two mutating agents are never live
at once.

An elapsed `reset_at` is a probe cue, not assumed capacity. At safe completed-turn boundaries the supervisor marks that provider `ELIGIBLE_FOR_PROBE`, makes one bounded harmless real-turn probe, and records `PROBING_AVAILABILITY` then either `READY` (clearing stale reset/error data) or a newly observed exhausted/stalled response. When a productive non-preferred turn ends and recovered Codex is ready, it checkpoints, deactivates the current provider, and returns to Codex automatically. Agents that need a specific provider use `SUPERVISOR_OUTCOME: HANDOFF` plus `SUPERVISOR_TARGET_AGENT` and `SUPERVISOR_HANDOFF_REASON`; the supervisor waits/rechecks that target instead of converting capacity into a human decision. Provider-bound `HUMAN_GATE` messages are similarly converted to recovery, while genuine human choices and authentication gates remain terminal human gates.

`Scripts\Launch-CotS-Agents.bat` opens one visible window (`cmd /k`, not
minimized) so an operator can read supervisor state without inspecting
PowerShell output or the checkpoint JSON directly. Ctrl+C requests a
controlled shutdown: the in-flight turn is allowed to finish, the checkpoint
is saved, the owned Codex/Claude subprocess is closed, and this process's own
supervisor instance lease is released. It never forces a release of the
ToolLab mutation lock it does not itself own; that remains the acting agent's
own responsibility to reconcile on its next turn.

### Usage-limit detection, failed-turn classification, and the hot-loop breaker

Codex usage exhaustion is classified from the real Codex 0.151.0 App Server
protocol (`.cots/codex-protocol.log`): a standalone `error` notification and/or
a `turn/completed` with `status: "failed"`, both carrying
`codexErrorInfo: "usageLimitExceeded"`. `account/rateLimits/updated`'s
`rateLimitReachedType` is consulted for forward compatibility but is not
required — it is `null` even mid-exhaustion on some accounts, so it is never
the sole detection path. Claude Code's `-p --output-format json` usage-limit
detection uses the confirmed real `api_error_status` field (429/529), with
text-pattern matching over stdout/stderr as a fallback.

A failed turn is never assumed to be `CONTINUING` merely because it produced
no assistant text: it is classified as usage exhaustion (rotate), a known
transient/transport failure (bounded retry with backoff), or an unknown
failure (`FAILED`, terminal). Separately, a hot-loop circuit breaker tracks
consecutive suspicious turns per provider (near-instant, no assistant text,
no recorded tool/item activity); three in a row trips `STALLED_PROVIDER`,
which is gated and rotated exactly like `USAGE_EXHAUSTED` but with a short
fixed backoff instead of a provider-reported reset time.

Task/phase are reconciled from the strongest available evidence rather than
staying `(unknown)` indefinitely: a `SUPERVISOR_TASK`/`SUPERVISOR_PHASE`
marker already parsed from a turn is authoritative; otherwise the Host
mutation-lease owner's `<agent>-task-<n>` naming convention is used as a
fallback (e.g. `codex-task-012` -> `TASK-012`); otherwise the dashboard shows
the explicit `RECONCILING` state rather than inventing a value.
