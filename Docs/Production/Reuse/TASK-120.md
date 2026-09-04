# TASK-120 Reuse Decision

TASK-114's `FCotSSocialCommunicationAuthority` is adapted as the sole
authoritative local-area, session and mute/block policy. Production commit
`c46a188` adds a version-one server-side provider boundary over that contract.
It accepts no provider credential, media payload or token and sends only
privacy-category audit events through TASK-117 observability.

No installed provider account, credential, billing authority or irreversible
provider configuration was available. A real-provider transport/schema is
therefore deliberately not invented; that activation remains the isolated
human gate specified by TASK-120.
