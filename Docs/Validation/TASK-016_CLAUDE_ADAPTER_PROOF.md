# TASK-016 Validation — Claude Independent Host/Unreal MCP + Lock-Contention Proof

Task spec: `Tasks/016_DUAL_AGENT_MCP_PARITY.md`.
Ledger context: `Docs/FOUNDATION_COMPLETION_LEDGER.md` records symmetric
endpoint wiring and Host protocol fixes as done (`4748427`, `585dfee`,
`04b3819`, plus this task's `5d1c8c0` Host MCP 405 transport fix) but no
durable two-adapter live session/lock-contention proof.

## Prerequisite fix landed this turn

`Scripts/CotSHostMcp.py` answered an unimplemented HTTP method (`GET`/`DELETE`
on `/mcp`) with a bare `501`, which Codex's `rmcp` Streamable HTTP client
treats as a fatal transport error and tears down the whole server connection
instead of skipping the optional capability. Fixed to the spec-correct `405`
with `Allow: POST`, covered by `Scripts/tests/test_cots_host_mcp.py` (3/3
passing). Committed as `5d1c8c0`. This was blocking Codex's own Host MCP
reachability, so it is a precondition for the dual-adapter proof below, not a
side task.

## Claude — CotS Host MCP proof

Date: 2026-09-02. This turn is the active Claude adapter, so per
`AGENTS.md`/`Docs/AUTONOMOUS_DEVELOPMENT.md` provider-self-validation, the
Claude-side proof is performed directly in this session using the
provider-neutral task identity `supervisor-task-016`:

1. `GetToolLabStatus` (no lock required) — confirmed baseline
   `{"editor_running": false, "mcp_ready": false, "mutation_lock_owner": null}`.
2. `AcquireMutationLock(agent_id="supervisor-task-016")` — `{"acquired": true}`.
3. `OpenToolLab` — `editor_pid: 52020`, `mcp_url: http://127.0.0.1:8000/mcp`.
4. `WaitForUnrealMcp` — `{"ready": true, "mcp_url": "http://127.0.0.1:8000/mcp"}`.
5. Read-only inspection call: `GetToolLabStatus` while holding the lock —
   `{"editor_running": true, "editor_pid": 52020, "mcp_ready": true,
   "mutation_lock_owner": "supervisor-task-016"}`.

## Lock-contention / read-only-unaffected proof (Host MCP side)

With `supervisor-task-016` still holding the lock, a distinct standby identity
was exercised against the same running Host MCP:

- `AcquireMutationLock(agent_id="standby-check-task-016")` ->
  `{"success": false, "error": "mutation_lock_held", "data": {"owner": "supervisor-task-016"}}`
  — the standby agent's mutation attempt is refused while the lease is held.
- `GetToolLabStatus(agent_id="standby-check-task-016")` ->
  succeeded normally (`editor_running: true`, `mcp_ready: true`) — read-only
  connectivity for the non-owning caller is unaffected by the held lock.

This directly demonstrates the acceptance criterion's Host MCP half: "the
single-mutating-agent lease still rejects concurrent mutation from the standby
agent" while "read-only MCP connectivity remains unaffected."

The lock was then released (`ReleaseMutationLock` -> `{"released": true}`) so
this turn end does not strand the lease. ToolLab was deliberately **left
running** (`editor_pid 52020`, `mcp_ready: true`, `mutation_lock_owner: null`)
rather than closed.

## Native Unreal MCP — session-start ordering gap (same class as TASK-003)

This Claude process's `unreal-mcp` HTTP MCP client attempted its one
connection at session start, before this turn had opened ToolLab, and was
refused (`ConnectionRefused`) — confirmed by the system reminder recorded at
turn start and consistent with the pre-open `GetToolLabStatus` read in step 1
above (`mcp_ready: false` at that time). Per the precedent already recorded in
`Docs/Validation/TASK-003_MCP_CONNECTIVITY.md`, a Claude Code HTTP MCP client
does not retry a server that was unreachable when the client process started,
even after the endpoint becomes reachable mid-session; `ToolSearch` for
`unreal-mcp` tools mid-session confirmed no tools became available after
`WaitForUnrealMcp` reported ready.

This is the same validation-topology/ordering gap already characterized for
TASK-003, not a broken endpoint, a broken client configuration, or a HUMAN_GATE:
the endpoint (`http://127.0.0.1:8000/mcp`) is real, ready, and was confirmed
ready by `WaitForUnrealMcp` inside this same turn. Per
`Docs/AUTONOMOUS_DEVELOPMENT.md` provider self-validation guidance, the fix is
a fresh Claude turn started while ToolLab/Unreal MCP is already up, not a
recursive/standalone launch and not a human decision.

## Disposition

Completed this turn: Host MCP acquire/release, Host MCP read-only inspection,
and the full Host-side lock-contention/read-only-unaffected proof for Claude.
Remaining for TASK-016's Claude proof: native Unreal MCP connection
confirmation, native/CotS toolset enumeration, one native read-only inspection
call, and the Unreal-MCP-side half of the lock-contention check (mirroring
`Docs/Validation/TASK-003_MCP_CONNECTIVITY.md`'s completed pattern) — all
achievable in the very next Claude turn now that ToolLab was left running
with `mcp_ready: true`. Codex's independent proof (Host + native Unreal MCP,
toolset enumeration, lock contention as observed from Codex's side) remains to
be recorded in this same file or a companion `TASK-016_CODEX_ADAPTER_PROOF.md`
before the ledger can move TASK-016 to `COMPLETE_VERIFIED`.

## Codex — independent Host and native Unreal MCP proof

Date: 2026-09-02. With ToolLab deliberately left open by the Claude turn,
the active Codex App Server adapter connected to both configured endpoints in
one session without reconfiguration:

1. `GetToolLabStatus` through CotS Host MCP returned
   `editor_running: true`, `editor_pid: 52020`, `mcp_ready: true`, and no
   lock owner.
2. Native `list_toolsets` enumerated the native registry plus all CotS
   toolsets, including `CotSFoundationToolset`, `CotSInspectionToolset`,
   `CotSMutationToolset`, and `CotSLifecycleToolset`.
3. Native `describe_toolset(CotSFoundationToolset)` followed by the read-only
   `GetStatus` call returned `plugin: CotSDeveloperTools`, version `0.2.0`,
   and UE `5.8.1-56057345+++UE5+Release-5.8`.
4. Codex acquired Host lock `codex-task-016-owner`; a distinct
   `codex-task-016-standby` acquire request was refused with
   `mutation_lock_held` and reported the owner. Codex then released the owner
   lock successfully.

This is Codex's complete independent connectivity/toolset/read-only/Host-lock
proof. ToolLab remains running and MCP-ready with no owner for Claude's fresh
native-MCP turn.
