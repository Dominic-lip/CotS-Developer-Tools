# TASK-008C — Visible Supervisor Dashboard and Codex/Claude Rotation

## Objective

`Scripts\CotSAgentSupervisor.py` must never present as a blank console. It
renders a live, redraw-in-place status dashboard, and it must survive either
Codex or Claude exhausting its usage allowance without any human action.

## Scope

- A dashboard thread that redraws a fixed-size summary in place (cursor-home
  plus clear-to-end-of-screen; never a scrolling flood of raw protocol JSON).
- A generic agent-adapter shape (`CodexAgent`, `ClaudeAgent`) so the
  orchestration loop is agent-neutral, matching `Docs/AGENT_COMPATIBILITY.md`.
  `ClaudeAgent` drives `claude -p --output-format json`, structurally scoped
  with `--allowedTools` to `Read Edit Write Grep Glob` plus the two fixed
  wrapper invocations (`Scripts\CotS-GitCompletion.py`,
  `Scripts\Build-ToolLab.cmd`) — the same routine-edit/fixed-wrapper boundary
  TASK-008B already gives Codex — and resumes by `--resume <session_id>`.
- Usage-limit detection for both providers. On detection: stop submitting
  further turns to that provider, record its reset time when known, save the
  checkpoint, and — if the other provider is available — rotate to it and
  continue automatically. If neither is available, enter
  `WAITING_FOR_AGENT_CAPACITY` (or, single-agent mode, the legacy
  `WAITING_FOR_USAGE_RESET`) and poll on a bounded interval until one becomes
  usable again, rather than exiting the process. Exit remains reserved for
  `HUMAN_GATE`, `COMPLETE`, `FAILED`, or an operator's Ctrl+C.
- Dashboard states: `STARTING`, `PREFLIGHT`, `RUNNING_CODEX`,
  `RUNNING_CLAUDE`, `ROTATING_AGENT`, `WAITING_FOR_AGENT_CAPACITY`,
  `WAITING_FOR_USAGE_RESET`, `HUMAN_GATE`, `FAILED`, `COMPLETE`, `STOPPING`.
  A provider's own status field additionally distinguishes `USAGE_EXHAUSTED`
  from `STALLED_PROVIDER` (the hot-loop circuit breaker: three consecutive
  suspicious/no-op turns), both gated by a reset time before that provider is
  picked again.
- Separate human-facing summary from machine detail: `.cots/supervisor-events.log`
  (summarized, bounded-severity events), `.cots/codex-protocol.log` (raw App
  Server JSON, as before), `.cots/claude-protocol.log` (raw `claude -p`
  invocations and JSON results).
- `Scripts\Launch-CotS-Agents.bat` opens one visible, non-minimized window
  (`cmd /k` so the final dashboard frame stays on screen after the process
  ends) and prints the required minimize/close notice before starting.
- Ctrl+C requests a controlled shutdown: let the in-flight turn finish, save
  the checkpoint, close the owned Codex/Claude subprocess, release this
  process's own supervisor instance lease, and exit. It never forces a
  release of the ToolLab mutation lock it does not itself own — the acting
  agent's own next reconciliation remains the sole owner of that lock's
  lifecycle, per `AGENTS.md`.

## Explicit non-goals

- No change to the one-mutating-agent policy: rotating agents means the
  previous provider's process is fully closed before the next one starts a
  turn, never overlapped.
- No forced release of a mutation lock this script does not own, and no new
  privileged host operation to do so.
- No raw MCP/App-Server JSON printed to the console; that stays in the
  protocol log files.

## Acceptance proof

1. Start the supervisor once; the dashboard shows `RUNNING_CODEX` (or
   `RUNNING_CLAUDE`), the active agent, current task/phase, and turn count.
2. Trigger (live, or via the `--simulate-codex-usage-limit-after` /
   `--simulate-claude-usage-limit-after` test hooks) a usage-limit condition
   on the active provider. The dashboard visibly transitions usage-exhausted
   -> rotating -> the other provider active, and that provider completes a
   further turn without human input.
3. Demonstrate the reverse rotation once the first provider is usable again.
4. Throughout, only one mutating agent subprocess exists at a time, the
   console never floods with raw protocol traffic, and an operator can read
   supervisor state, current task, and last commit from the window alone.
