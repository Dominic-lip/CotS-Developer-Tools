# TASK-118 Reuse Decision — Scale, Soak & Recovery

TASK-101's networked automation was adapted as a fixed four-worker harness;
TASK-103's deterministic persistence adapter was adapted for disposable
export/corruption/import recovery. No donor soak implementation was found.
The harness does not add gameplay authority: the server advances replicated
epochs and all clients observe them; persistence fixtures use disposable IDs.
