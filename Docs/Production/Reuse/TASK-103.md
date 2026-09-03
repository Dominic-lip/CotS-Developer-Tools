# TASK-103 Reuse Decision — Persistence and Canonical Data

## Sources inspected

- `C:\Dev\Shardlands\sharddata.py`, `Data/Source`, `Data/Generated`, and
  `Data/Registry/build_manifest.json`: a deterministic standard-library
  CSV-to-JSON compiler with typed primary/cross-reference validation. The
  observed registry reports 1,712 items and zero warnings.
- `C:\Dev\Shardlands\Docs\Architecture\Persistence.md`: durable identity,
  authoritative writers, idempotency, revision conflict, migration and restore
  rules.
- Production TASK-102 identity contracts: `FCotSAccountId` and
  `FCotSCharacterIdentity` are the durable identity input to this task.
- Website/Platform API availability is unchanged from TASK-102: no local
  checkout or reachable public repository was available. No backend schema or
  credential protocol is inferred.

## Decisions

| Material | Decision | Rationale |
| --- | --- | --- |
| Shardlands canonical compiler/registry | ADAPT | Preserve versioned JSON, deterministic ordering and typed IDs. Start with an audited three-ID production catalog rather than blindly importing the 3 MB, mixed-status donor item registry. |
| Shardlands persistence architecture | REFERENCE_ONLY | Preserve server-writer, transactional, idempotency, revision and migration rules; rebuild the production API free of donor gameplay coupling. |
| TASK-102 identity contracts | REUSE_DIRECTLY | Stable account and character IDs already satisfy the persistent-owner boundary. |

## Result

TASK-103 provides a clean storage interface and deterministic in-memory adapter,
not a local database. A later Platform API/database adapter implements the same
interface and must retain the canonical-ID, schema-version, idempotency and
optimistic-revision rules. Expanded authored data remains a generated-data
migration, with an explicit status/content review before importing donor rows.
