# TASK-104 Reuse Decision — Embodied Player, MetaHuman, Animation and Input

## Sources inspected

- `ShardlandsCharacterAppearanceComponent`: replicated, server-authored stable
  recipe with a renderer-independent presentation notification.
- `ShardlandsEmbodiedCharacterComponent`: local camera alignment and owner-only
  presentation hiding, explicitly separate from gameplay authority.
- `ShardlandsMetaHumanPresentationComponent`: optional experimental renderer
  adapter over MetaHuman Collection/Instance APIs.
- TASK-013's verified UE 5.8 Mannequin-to-distinct-MetaHuman retarget proof.

## Decisions

| Material | Decision | Rationale |
| --- | --- | --- |
| Appearance recipe replication | ADAPT | Preserve server-authored, replicated stable recipe semantics in CotS. |
| Embodiment/camera behaviour | ADAPT | Preserve local-presentation-only principles, not donor character/component coupling. |
| MetaHuman Collection/Instance adapter | REFERENCE_ONLY | Keep production presentation optional until a reviewed MetaHuman asset/runtime pipeline exists. |
| Donor animation assets and template input configuration | REBUILD CLEANLY | TASK-013 tooling and CotS architecture control skeleton, retarget and input policy. |

## Result

TASK-104 will introduce a minimal authoritative CotS player embodiment seam and
Enhanced Input locomotion boundary. It will not copy donor Blueprint, MetaHuman
asset, child-actor, first-person mesh, or legacy input setup.
