# TASK-101 Reuse Decision — Runtime, Networking and Dedicated Server

## Sources inspected

- `C:\Dev\CotS` baseline at `8e744c7da1fafb1f8321cadb0ccc481e38b75f4d`.
- Read-only local `C:\Dev\Shardlands` at
  `64f5ca409fab5ccb62d09edde013cdc4fa67649c`, with newer uncommitted local
  work; no donor file was modified.
- `Shardlands.uproject`, `Source/Shardlands/Shardlands.Build.cs`,
  `Config/DefaultEngine.ini`, `Aether/ShardlandsAetherPawn.*`, and
  `Combat/ShardlandsCombatComponent.cpp`.
- `Dominic-lip/CotS-Platform-API` has no local checkout and was not reachable
  through this adapter. TASK-101 therefore keeps external identity/persistence
  contracts abstract; TASK-102/103 must inspect that peer before defining one.

## Decisions

| Donor material | Decision | Rationale |
| --- | --- | --- |
| `Shardlands` runtime/module layout and template redirects | REIMPLEMENT | It is a valuable compatibility reference, but the default maps/GameMode and public include paths retain first-person/variant prototype coupling. |
| Server RPC pattern in Aether and Combat | ADAPT | Retain the principle: client requests are validated and state changes occur only on authority; replicated presentation derives from authoritative state. Do not copy feature-specific combat/Aether code. |
| Dedicated-server visual guards (`NM_DedicatedServer`) | ADAPT | Preserve the separation of authoritative simulation from cosmetic client work in CotS runtime services. |
| Shardlands inventory/world/combat systems | LEAVE for later task-scoped review | They depend on persistence, authority, UI, and canonical data contracts not yet established by TASK-101. |

## Result

TASK-101 establishes new CotS runtime seams and tests around these principles.
No Shardlands implementation is copied; future tasks must cite this decision
and deepen only their subsystem-specific review.
