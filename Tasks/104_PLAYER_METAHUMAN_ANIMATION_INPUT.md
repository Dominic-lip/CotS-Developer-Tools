# TASK-104 — Embodied Player, MetaHuman, Animation & Input

## Objective
Build the production first/third-person player embodiment and locomotion stack on top of the networking/data foundations.

## Existing-work check
Deep-inspect relevant `C:\Dev\Shardlands` Shard-115 player/MetaHuman work, locomotion assets, interaction hooks and the completed CotS animation/MetaHuman tooling. Do not recreate known-good retarget work without reason.

## Requirements
- Production player pawn/character architecture with authoritative state and correct local/remote presentation.
- MetaHuman body/camera visibility rules suitable for first-person local and third-person remote views.
- Production input/actions for movement, look, jump, crouch/sprint and extensible action routing.
- Locomotion/airborne/crouch animation pipeline with exact assets/paths and automated validation where supported.
- Multiplayer tests proving movement/animation state replication and no local-camera body regressions.
- Record donor decisions in `Docs/Production/Reuse/TASK-104.md`.

## Acceptance criteria
Two clients can spawn, move and observe each other's embodied/animated characters correctly in the production project, builds/tests pass, and the pipeline no longer depends on manual graph construction for routine changes.
