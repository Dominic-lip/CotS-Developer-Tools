# TASK-102 — Platform Identity, Authentication and Character Contract

## Authority boundary

The Platform API is authoritative for credentials, account lifecycle, session
issue/revocation, character records and server-directory publication. CotS
receives only an already-verified `FCotSSessionGrant` at its server boundary.
The grant contains an opaque session identifier, an opaque account identifier,
state and expiry; it intentionally contains no bearer/access/refresh token.

Clients may request a character identifier and a session identifier. The game
server must select only when the session is active at the server's current UTC
time, the request names that exact session, and the selected character belongs
to that grant's account. Connection IDs, player names, actors and RPC ownership
are transport details, never persistent account identity.

## Contract values

- `FCotSAccountId` — opaque, stable provider subject; never synthesized from a
  player name or actor name.
- `FCotSCharacterIdentity` — stable character GUID plus owning account ID and
  a non-authoritative archetype label. Persistent payload belongs to TASK-103.
- `FCotSSessionGrant` — server-side verified session assertion with explicit
  active/expired/revoked state and UTC expiry.
- `FCotSCharacterSelectionRequest` — untrusted client intent. It is accepted
  only by `FCotSPlatformIdentityContract::CanSelectCharacter`.
- `FCotSServerDiscoveryRecord` — public, versioned directory metadata. It
  permits only TLS WebSocket/HTTPS endpoints and contains no credentials.

## Deferred provider integration

When the Website/Platform API source or a reviewed live contract becomes
available, add an adapter at this seam and reconcile field names, issuer/
audience validation, expiry/skew, revocation, character-list pagination and
directory signature/health rules. That work must not weaken the ownership or
token-handling rules above.
