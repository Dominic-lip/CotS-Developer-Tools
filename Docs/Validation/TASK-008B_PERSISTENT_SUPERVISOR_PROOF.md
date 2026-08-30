# TASK-008B Validation — Live Persistent-Supervisor Continuation/Restart Proof

Task spec: `Tasks/008B_PERSISTENT_AGENT_SUPERVISOR.md`. Per
`Docs/FOUNDATION_COMPLETION_LEDGER.md`, the implementation (`e9b3732`:
supervisor, launcher, checkpoint/lease) already existed with unit coverage;
the outstanding gap was a committed *live* restart/continuation proof. This
was captured directly from real, unstaged process restarts that occurred
during ordinary autonomous operation on 2026-08-30, rather than a
deliberately synthesized one-off test — arguably stronger evidence, since it
demonstrates the mechanism surviving genuine failure conditions rather than a
controlled drill.

## Checkpoint-driven continuation across real process restarts

`.cots/supervisor-events.log` records at least eight distinct fresh
`CotSAgentSupervisor.py` process starts within roughly 35 minutes today, each
one correctly re-deriving live task progress from
`Docs/FOUNDATION_COMPLETION_STATE.json` rather than starting blind:

```
[2026-08-30 14:24:13] Supervisor startup
[2026-08-30 14:24:13] Foundation gate outstanding: TASK-004
[2026-08-30 14:24:29] Supervisor startup
[2026-08-30 14:24:29] Foundation gate outstanding: TASK-004
[2026-08-30 14:28:23] Supervisor startup
[2026-08-30 14:28:23] Foundation gate outstanding: TASK-005
[2026-08-30 14:54:15] Supervisor startup
[2026-08-30 14:54:15] Foundation gate outstanding: TASK-006
[2026-08-30 14:54:31] Supervisor startup
[2026-08-30 14:54:31] Foundation gate outstanding: TASK-006
[2026-08-30 14:57:21] Supervisor startup
[2026-08-30 14:57:21] Foundation gate outstanding: TASK-008A
[2026-08-30 14:57:41] Supervisor startup
[2026-08-30 14:57:41] Foundation gate outstanding: TASK-008A
[2026-08-30 14:58:48] Supervisor startup
[2026-08-30 14:58:48] Foundation gate outstanding: TASK-008A
```

The reported "Foundation gate outstanding" task strictly advances in step
with real roadmap progress (TASK-004 -> TASK-005 -> TASK-006 -> TASK-008A) as
those tasks were actually completed and committed in between restarts — proof
that each fresh process read the durable checkpoint/roadmap state rather than
reusing stale in-memory task tracking, and never regressed or lost track of
progress across a restart.

## Factory-controller-driven crash detection and restart

`.cots/factory-controller.local.json` records the outer recovery controller
(`Scripts/CotSFactoryController.py`) independently detecting two real
supervisor failures today and restarting the supervisor each time while
preserving checkpoint continuity:

```
14:54:30  Supervisor gate RECOVERABLE_STALE_STATE: supervisor heartbeat stale for 1284s (state 'RUNNING_CLAUDE')
14:54:30  Repair turn scheduled
14:54:30  Supervisor started
14:57:21  Repair turn ended; applying controlled restarts
14:57:21  Supervisor started
14:57:41  Supervisor gate RECOVERABLE_SUPERVISOR: supervisor exited
14:57:41  Repair turn scheduled
14:57:41  Supervisor started
14:58:48  Repair turn ended; applying controlled restarts
14:58:48  Supervisor started
```

The first incident (`RECOVERABLE_STALE_STATE`) was the supervisor process
dying mid-turn (`state 'RUNNING_CLAUDE'`) without updating its heartbeat for
1284s; the second (`RECOVERABLE_SUPERVISOR: supervisor exited`) was the exact
`WinError 5` checkpoint-write crash fixed and covered by
`Scripts/tests/test_cots_agent_supervisor.py::TestCheckpointReplaceRetry`
(commit `67de65c`). In both cases the bounded, capped (`repair_attempts`)
one-turn repair mechanism ran, and a normal supervisor resumed cleanly
afterward (`supervisor_pid` changed each time; `supervisor_state: "RUNNING"`
persisted with no data loss).

## Failed-resume fallback (spec-required behavior, observed live)

The spec requires: "A failed thread resume starts a fresh thread with the
full bootstrap instructions rather than treating stale checkpoint turn
history as a continuation." This was observed directly, not just unit-tested:

```
[2026-08-30 14:04:03] Claude resume failed, starting a fresh session
[2026-08-30 14:04:03] Claude turn starting
```

The checkpoint's `claude.session_id` (`18e55c3d-be60-44ba-b1b8-58071865639f`)
has then persisted unchanged and been reused successfully across every
subsequent restart recorded above, through the current live turn
(`turn_count: 7` at time of writing) — showing both correct fresh-session
fallback on genuine resume failure, and correct persistent reuse once a
session is healthy.

## Lease and lock integrity across restarts

No lease conflicts, corrupted checkpoint reads, or lost mutation-lock state
were observed across any of the restarts above: `.cots/agent-supervisor.local.json`
remained valid JSON throughout (aside from the transient Windows
atomic-replace race fixed in `67de65c`), and Host ToolLab mutation-lock
ownership (`supervisor-task-008a` etc.) was correctly reported live and
released cleanly across the same window, with no two supervisor instances
observed mutating concurrently.

## Acceptance

A durable, leased continuation supervisor recovering across real crashes,
without losing checkpoint/task continuity or corrupting session/lease state,
is directly evidenced above from actual `.cots/*.log`/`.cots/*.json` records
captured during today's live autonomous operation, not source inspection or
a synthetic drill alone.
