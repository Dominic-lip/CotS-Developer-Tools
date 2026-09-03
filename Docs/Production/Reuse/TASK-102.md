# TASK-102 Reuse Decision — Platform Identity, Authentication and Character Contract

## Sources inspected

- `C:\Dev\CotS` TASK-101 runtime/networking foundation. Its authoritative
  network probe confirms that connection ownership is transient and that a
  durable identity must remain outside replicated gameplay state.
- `C:\Dev\Shardlands\Source\Shardlands\Items\ShardlandsPlayableWorldTypes.h`
  and its call sites in persistent storage, housing, shops and workshops.
  The donor derives a fallback account key from `APlayerState` / actor names.
- `Dominic-lip/CotS-Website` and `Dominic-lip/CotS-Platform-API`: no local
  checkout exists under `C:\Dev`; their public repository lookup did not
  resolve through this adapter on 2026-09-03. No endpoint, token format, or
  schema is inferred from their absence.

## Decisions

| Material | Decision | Rationale |
| --- | --- | --- |
| Shardlands fallback `GetShardlandsAccountKey` | REIMPLEMENT | It is useful evidence that ownership must be checked on authority, but player names and actor names are not durable platform identities. |
| Shardlands ownership call sites | ADAPT | Preserve the rule that server-side gameplay uses an account/character ownership assertion; do not copy its feature-coupled systems. |
| Website / Platform API protocol | LEAVE pending peer access | The game owns a versioned, token-free integration seam only. The platform provider remains the authority for credential verification, issuance, revocation and persistent character records. |

## Result

TASK-102 introduces opaque account, character, authenticated-session and
server-discovery contract values. Access-token material is deliberately absent
from reflected/replicated game values. A later provider adapter must validate a
credential out of process, construct the session grant server-side, and use the
same ownership-selection predicate before spawning a character. TASK-103 owns
durable storage and migrations; TASK-102 does not add a local account database.
