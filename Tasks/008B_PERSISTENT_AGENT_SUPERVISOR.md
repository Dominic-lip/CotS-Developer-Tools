# TASK-008B — Persistent Agent Supervisor

`Scripts/CotSAgentSupervisor.py` owns a Codex App Server process, persists its
durable thread ID and state in `.cots/agent-supervisor.local.json`, and sends a
continuation turn after every `turn/completed` notification unless Codex emits a
structured human gate or completion marker. It never starts interactive `codex`;
`Scripts/Launch-CotS-Agents.bat` launches the supervisor by default and retains
`manual` for an intentionally interactive session.

Before reading or updating its checkpoint, the supervisor obtains an OS-held,
local-only lease. A second live instance fails with `supervisor_lease_held`;
the operating system releases the lease if the owning process crashes. A failed
thread resume starts a fresh thread with the full bootstrap instructions rather
than treating stale checkpoint turn history as a continuation.

## Approval boundary

The supervisor uses the current Codex App Server granular approval policy with
`approvalsReviewer: auto_review`. Normal workspace work stays in
`workspace-write`; permission expansion and MCP elicitation are risk-reviewed
by Codex rather than pausing for an ordinary human approval. A direct fallback
approval request is denied by the supervisor, never silently accepted.

The granular `sandbox_approval` and `rules` channels are enabled solely so the
auto-reviewer can evaluate the fixed Git wrapper's metadata-write escalation;
they do not make arbitrary shell commands approved.

Routine Git work is constrained to `Scripts/CotS-GitCompletion.py`: read-only
status/diff checks, or a single validated task completion that stages exact
repository-relative files, runs cached `diff --check`, commits one single-line
message, and pushes only `origin main`. It has no commands for reset, clean,
force push, checkout, branch changes, history rewriting, or arbitrary paths.

The autonomous instructions permit normal edits only inside this repository,
canonical ToolLab build/test and fixed Host/Unreal MCP operations, and disposable
ToolLab fixtures. They prohibit writes to Shardlands, production CotS mutation
before bootstrap authorization, arbitrary shell/process control, credentials,
and non-disposable destructive work.

## Checkpoint states

`STARTING`, `PREFLIGHT`, `RUNNING_TURN`, `CONTINUING`,
`WAITING_FOR_USAGE_RESET`, `HUMAN_GATE`, `COMPLETE`, and `FAILED` are persisted.
The state file enables resumption after a terminal closure, reboot, crash, or
usage reset. The supervisor remains a single mutating-agent owner.

`Tasks/008C_SUPERVISOR_DASHBOARD.md` supersedes two things described above: it
adds a live console dashboard, and it adds a Claude adapter that shares this
lease/checkpoint contract. It also changes `WAITING_FOR_USAGE_RESET` from a
process-exit state into a polling-and-retry state — the supervisor now rotates
to the other configured provider, or waits and rechecks, rather than exiting
whenever a usage limit is reached.
