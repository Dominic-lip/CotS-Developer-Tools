# Autonomous Efficiency Policy

## Principle

Maximize verified engineering progress per provider turn. Efficiency removes repeated context, inspection and proof; it never removes acceptance criteria, single-mutator safety, Git/MCP safeguards, existing-work-first investigation or required validation.

## Coherent work and context

Agents normally work in substantial coherent chunks: reconcile facts that may have changed, understand the relevant slice, implement, run targeted validation, inspect the result and save a compact checkpoint. A routine task should usually take 1--4 meaningful provider turns; larger subsystems may need 4--10. These are targets, not quotas.

The supervisor checkpoint carries a bounded machine-readable task context: objective, remaining acceptance, decisions, changed/relevant files, tests and validation already run, blocker/next action, donor decisions, HEAD/lease and read fingerprints. Incoming providers use it first and inspect source only to verify it or reconcile a changed delta. Conversational history is not a handoff artifact.

Read fingerprints identify path, revision/mtime/hash where useful, purpose and summary. An unchanged file may be trusted through its summary when sufficient; changed source always invalidates that shortcut. The existing-work index and previous donor classifications are likewise reused until relevant donor source or production architecture changes.

## Validation and evidence

Iteration uses the smallest relevant build/test/validation set. Completion, shared foundations, infrastructure-wide changes and explicit acceptance gates run their genuinely required full suite. Checkpoints distinguish targeted and full-suite runs with the reason for a full suite.

Committed completion state and ledger evidence are authoritative. It is not repeated merely because a provider rotates; it is invalidated only by a relevant implementation or acceptance-contract change.

## Providers, failure and repair

One provider implements normal work. The standby provider is used only for an explicit independent requirement, capacity rotation, deliberate alternate repair, or genuine unavailability. Rotation passes the compact checkpoint and keeps the single mutating-agent boundary intact.

Failures are fingerprinted by operation, error, relevant paths, task and phase. A substantially identical failure twice stops blind retrying and moves to diagnosis/recovery. Repair turns receive the exact incident, compact checkpoint, changed-file summary, prior-attempt count and bounded relevant log tail; they inspect outward from that evidence.

## Telemetry

The Factory dashboard reports task/provider turns, rotations, current turn elapsed time, targeted/full suites, repeated failures, current-turn reads, unchanged rereads and compact-context size. Provider usage/reset data appears only when actually reported by provider protocols; token counts are never invented.
