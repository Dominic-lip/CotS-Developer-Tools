# TASK-112 — Combat & Adversarial Runtime Security

## Objective
Productionize server-authoritative combat while treating every client request and replicated gameplay boundary as adversarial input.

## Existing-work check
Inspect existing Shardlands authoritative melee/equipment/combat components and later player-state work before rewriting combat fundamentals.

## Requirements
- Authoritative attack intent, timing, hit validation, damage/incapacitation and equipment integration.
- Clear separation of cosmetic prediction/animation from server truth.
- Range/rate/state/target/RPC validation and replay/double-submit resistance where applicable.
- Basic combat extensibility for future weapon/ability types without prematurely implementing all content.
- Threat-model review of networking, inventory/equipment, interaction and persistence surfaces built so far.
- Automated adversarial tests and multiplayer combat proof.

## Acceptance criteria
Two clients can complete a representative combat/incapacitation flow with server-validated results, common forged/invalid requests fail, and security findings are either fixed or explicitly backlogged with severity/evidence.
