# TASK-118 Scale, Soak & Recovery Proof

Production commit `ccba97a` adds a fixed four-participant recovery test and a
disposable persistence/event-throughput recovery test. The audited campaign
route ran four UE workers for 47.563 seconds: peak combined working set was
6,632,112,128 bytes, aggregate worker CPU was 190.734 seconds (401.01%), and
the 12 GiB hard memory guard did not trigger. All workers were cleaned up.

The network proof replicated 64 authoritative epochs to three clients,
disconnected one client, preserved server state, then reconnected it. The
persistence proof wrote 32 disposable snapshots with idempotent retries,
rejected corrupted schema data, restored the valid export, and accepted 64
authoritative operation events (`TASK118_METRIC`, 0.112 ms local contract
window). Logical replicated payload is 256 bytes; this is a bounded local
engineering gate, not an internet-scale bandwidth claim.

UE 5.8 editor, game, and server targets all returned `Result: Succeeded`.
Remaining limit: this gate is capped at four local workers and a 12 GiB guard;
TASK-119+ must not infer wider production capacity from it.
