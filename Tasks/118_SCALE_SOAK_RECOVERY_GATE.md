# TASK-118 — Scale, Soak & Recovery Engineering Gate

## Authorization
This task is explicitly authorized to modify `C:\Dev\CotS` through the fixed campaign production lifecycle adapter. `C:\Dev\Shardlands` remains read-only.

## Objective
Turn the TASK-115 P0 scale/soak backlog into measured, repeatable multiplayer and persistence engineering evidence using TASK-117 observability.

## Required work
- extend the fixed two-participant harness into bounded configurable multi-client load;
- record CPU, memory, bandwidth, tick/latency and event/persistence throughput;
- run sustained soak windows with deterministic thresholds and machine-readable results;
- exercise server restart, persistence restart, reconnect, idempotency and recovery paths;
- add corruption/conflict injection only through disposable test data and fixed harnesses;
- identify and fix measurable bottlenecks inside task scope rather than masking them with looser thresholds.

## Acceptance
- reproducible multi-client load and soak evidence with explicit machine/environment parameters;
- no unbounded RAM/CPU runaway: local hardware safety guard remains authoritative;
- restart/reconnect/persistence recovery proofs pass;
- production editor/game/server builds and focused automation pass;
- evidence records thresholds, peak resource usage and any remaining scale limits before COMPLETE_VERIFIED.
