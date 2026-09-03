# TASK-101 Runtime and Networking Contract

## Direction of dependencies

`CotSRuntime` owns actor-neutral authority rules, connection/session lifecycle,
replicated gameplay state, and multiplayer test fixtures. Gameplay domains
depend on it; it depends only on Unreal Engine networking primitives and
small shared value types. Presentation, UI, animation, input, platform
identity, persistence adapters, simulation, combat and inventory must not
create reverse dependencies into each other through runtime internals.

`CotSGame` owns game mode, player controller, player state and pawn assembly.
It composes runtime services but cannot become a persistence or platform API
client. `CotSClient` and `CotSServer` targets package the same authority model;
server builds exclude cosmetic-only code paths.

## Authority and replication rules

- Clients submit intent only. Every server RPC validates ownership, actor
  lifetime, connection/session state, range/rate/invariant constraints, and
  required authority before changing state.
- Server-owned state is the only source of replicated truth. Replicated data
  exposes the minimum view required by the recipient; private ownership and
  later persistence identities are not broadcast by default.
- Prediction is opt-in and domain-specific. A client may render reversible
  local feedback, but reconciliation follows server results and no predicted
  value is treated as authoritative.
- Disconnect destroys transient connection ownership but not durable identity;
  persistence/account reconstruction remains an interface for TASK-102/103.

## Initial automated proof

The harness will use UE automation to prove listen/dedicated-compatible
connect, server spawn, replicated authority state, disconnect, and reconnect.
It must test both accepted requests and an invalid non-owning request without
requiring a website, platform service, or durable database.

## Build and lifecycle

Use only the fixed production lifecycle bridge for production builds and
lifecycle. TASK-015 already proved editor and game builds plus smoke. The
installed UE distribution currently refuses a server target; TASK-101 retains
the target declaration and records this environmental limitation until a
server-capable engine is supplied.

## Current implementation evidence

Production commit `89cacc6` adds `ACotSNetworkProbeActor`: a replicated,
non-movement actor whose server RPC advances `AuthorityEpoch` only when the
claimed epoch matches authoritative state. It is intentionally a narrow seam,
not an identity or persistence model. The canonical fixed editor build returned
UBT `Result: Succeeded`, compiling the probe and
`CotS.Runtime.NetworkProbe.AuthorityContract`. In a live production native-MCP
editor session, Automation discovery found that exact test and its one-test run
returned `Success` with no errors or warnings.

This proves the initial replicated authority contract compiles and is
registered/testable. It does not yet prove two-client connection, spawn,
replication, disconnect, and reconnect, and it cannot satisfy the dedicated
server build acceptance while the installed engine refuses server targets. A
fixed `build --target server` rerun after `89cacc6` returned exit code 6 before
project compilation: `Server targets are not currently supported from this
engine distribution.` No retry is appropriate without a server-capable UE
installation.

Production commit `1495abb` adds the UE 5.8
`IMPLEMENT_NETWORKED_AUTOMATION_TEST` seam
`CotS.Runtime.NetworkProbe.TwoParticipantLifecycle`. It declares host and
client participants, opens the authoritative entry map on the host, and waits
for the client participant through the engine's network-automation command
primitives. The canonical editor build compiled this source successfully.
The production native-MCP editor controller discovers only editor-context
tests; UE's networked macro deliberately removes `EditorContext` and requires
two workers, so this test is not discoverable or runnable through that
single-editor controller. A fixed, auditable multi-worker automation operation
is still required to execute and record the connect/replicate/disconnect/
reconnect proof.

The fixed `networked-automation` lifecycle operation now starts exactly two
game workers and one UE command-line automation controller with the audited
test name above; it accepts no executable, project, test, address, or command
arguments. Its first run returned exit code 255 before worker discovery because
the installed engine's all-platform SDK validation requires `MainVersion`
metadata for LinuxArm64 and VisionOS. The operation records owned worker state
and reports failure unless both workers have exited. This is an installed-engine
validation topology gate, not evidence that the network lifecycle test ran.


## Final TASK-101 acceptance evidence

TASK-101 reached `COMPLETE_VERIFIED` against production head `d9557ef`.

The final production implementation includes:

- `ACotSNetworkProbeActor`, a replicated server-authoritative validation fixture.
- A real two-participant Unreal network automation lifecycle.
- Shared automation-session routing through the fixed lifecycle harness.
- A client connection to a listen server with reciprocal connection evidence.
- Server-authoritative actor spawn and server-to-client replication.
- Client-owned server RPC routing.
- Server-side sequencing validation and authoritative state mutation.
- Replication of the resulting authoritative state back to the client.
- Rejection of a deliberately stale client request without state mutation.
- Client disconnect with server-observed departure.
- Preservation of authoritative state while the client is absent.
- Client reconnect with state re-replication.

Final source-engine acceptance sweep:

- `CotSEditor Win64 Development` ? `Result: Succeeded`.
- `CotS Win64 Development` ? `Result: Succeeded`; output `C:\Dev\CotS\Binaries\Win64\CotS.exe`.
- `CotSServer Win64 Development` ? `Result: Succeeded`; output `C:\Dev\CotS\Binaries\Win64\CotSServer.exe`.
- `CotS.Runtime.NetworkProbe.TwoParticipantLifecycle` ? exit `0`.

The earlier Launcher-engine server-target and all-platform SDK limitations are superseded by the verified UE 5.8.1 source-engine toolchain.
