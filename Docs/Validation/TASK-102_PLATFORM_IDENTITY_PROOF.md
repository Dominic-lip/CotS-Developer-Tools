# TASK-102 — Platform Identity, Authentication and Character Contract Proof

## Scope and peer reconciliation

On 2026-09-03 the task inspected the TASK-101 production authority boundary,
the read-only Shardlands account-key implementation and its server-authority
call sites. There is no local `CotS-Website` or `CotS-Platform-API` checkout
under `C:\Dev`; their public repository lookup did not resolve through the
active adapter. The resulting contract therefore does not fabricate a provider
endpoint, issuer, credential format, or database schema. The complete reuse
decision is in `Docs/Production/Reuse/TASK-102.md`.

## Implemented boundary

Production commit `aa6c0e9` adds `FCotSAccountId`,
`FCotSCharacterIdentity`, `FCotSSessionGrant`,
`FCotSCharacterSelectionRequest`, `FCotSServerDiscoveryRecord`, and the pure
server-side `FCotSPlatformIdentityContract::CanSelectCharacter` predicate.

- The provider, not Unreal gameplay, verifies credentials and constructs an
  active grant; the grant carries no bearer, access, or refresh token.
- Selection requires server UTC expiry validation, exact session binding,
  matching character ID, and account ownership.
- Discovery data accepts only HTTPS/WSS endpoints and excludes credentials.
- Connection/player/actor identifiers are explicitly not persistent identity.

## Production validation

1. The canonical fixed production lifecycle build operation completed UE 5.8
   `CotSEditor Win64 Development` with `Result: Succeeded`; UHT processed the
   added reflected contract and UBT compiled `CotSPlatformIdentityTests.cpp`.
2. The fixed argument-free
   `platform-identity-automation` lifecycle operation completed with exit code
   0 and audited the production log for exactly
   `CotS.Platform.Identity.CharacterSelectionContract` success plus
   `TEST COMPLETE. EXIT CODE: 0`.
3. The live Unreal test covers allowed owner selection, foreign-account
   rejection, expired-session rejection, secure discovery acceptance, and
   insecure discovery rejection.

The production completion operation committed the exact two source files. Its
push step reported that the production repository has no `origin` remote; the
local production commit remains durable evidence and no network retry was
attempted.
