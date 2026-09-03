# TASK-103 — Persistence and Canonical Data Foundation

## Contracts

`FCotSPersistentCharacterSnapshot` carries a stable TASK-102 character/account
identity, an item definition ID, schema version and optimistic revision. Actor,
connection and player-name identity are not persisted.

`ICotSCharacterPersistenceStore` defines save, load, deterministic export and
import. `FCotSInMemoryCharacterPersistenceStore` is the test/local adapter;
it validates canonical IDs, enforces revision comparison and records
idempotency keys. It is intentionally not a production database.

`FCotSPersistenceMigration` upgrades schema zero to the current schema one and
rejects unknown future versions. Future migrations must be explicit and
loss-aware.

## Canonical data

`Data/Canonical/CotSCoreDefinitions.json` is a versioned, validated production
catalog seeded from verified Shardlands IDs: `Item.Raw.FlaxBundle`,
`Item.Processed.FibreCordage`, and `Item.Component.RopeCoil`. The runtime loader
rejects malformed JSON, unsupported schemas, duplicate IDs and non-`Item.`
definitions before exposing the catalog.

The full donor catalog is not copied wholesale: its rows include mixed
implementation/review status and task-specific gameplay assumptions. Later
tasks may expand the production compiler and catalog only through a reviewed,
reproducible generation step.
