# TASK-117 Operations, Event Observability & Regional Diagnostics Proof

Production commit `c5a9619` adds the server-only
`UCotSOperationsObservabilitySubsystem` and the focused
`CotS.Operations.EventObservability.AuthorityAuditFailureInjection` Unreal
automation test.

## Implementation boundary

- An envelope contains a stable event ID, authoritative server Unix time,
  schema version, trace ID, event type, and opaque hierarchy-compatible region
  ID. It intentionally carries no replicated diagnostics interface.
- The event store accepts publication and persistence restore only through the
  server-authoritative path. It deduplicates stable IDs, migrates schema zero,
  rejects unknown schemas before mutation, and exports/restores accepted
  envelopes without creating gameplay state or a second authority ledger.
- Privileged diagnostics alone include counts and the audit trail. Rejected
  publication and injected dispatch failures increment alertable counters;
  injected failures do not accept or corrupt the authoritative event state.

## Fixed lifecycle validation

All production operations used `Scripts/CotSProductionLifecycleCampaign.py`.
The final source revision passed the following canonical UE 5.8 routes:

- `build --target editor` — `Result: Succeeded` (7.58 seconds).
- `build --target game` — `Result: Succeeded` (20.50 seconds).
- `build --target server` — `Result: Succeeded` (18.17 seconds).
- `operations-automation --timeout 300` — exit code 0 with the exact Unreal
  result `CotS.Operations.EventObservability.AuthorityAuditFailureInjection`
  and `TEST COMPLETE. EXIT CODE: 0`.

The test proves server-authority rejection, stable-event deduplication,
versioned export/restore, migration from schema zero, rejection without state
corruption, privileged diagnostic gating, and observable failure injection.

The fixed `git-complete` route committed exactly the three production source
files; production was clean before the commit and no donor or peer repository
was modified.
