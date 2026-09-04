# TASK-120 Local Voice Privacy Proof

Production commit `c46a188` adds a deterministic, provider-unavailable
local-voice boundary. Focused Unreal automation passed local-area acceptance,
out-of-range and foreign-session rejection, mute/block propagation, consent
rejection, reconnect behavior, retention-deletion hooks, and privileged-only
audit visibility. The unavailable response is deterministic and does not
prevent the surrounding game session from continuing.

Canonical UE 5.8 editor, game and server builds all succeeded. The boundary
has no credential or media-payload input, and its observability events contain
only event categories plus opaque character identifiers.

The remaining acceptance is real-provider activation. It requires a provider
account/credential and may require billing or irreversible configuration; no
such authority was provided, so TASK-120 remains `PARTIAL` rather than being
advanced past its explicit human gate.
