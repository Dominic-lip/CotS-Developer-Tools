# TASK-104 — Embodied Player, MetaHuman, Animation and Input

## Production contract

`FCotSAppearanceRecipe` is stable, renderer-independent character appearance
data. It has no mesh, skeletal asset, Blueprint, child-actor or MetaHuman
instance reference. The recipe is deliberately suitable for an authoritative
owner to replicate while allowing a client presentation adapter to change.

`FCotSEmbodimentContract` supplies only deterministic local camera placement.
Invalid or incomplete appearance data uses the neutral 165 cm fallback. It does
not control collision, character movement or other gameplay authority.

`FCotSLocomotionInputContract` is the Enhanced Input boundary. It accepts a
local `FInputActionValue`, produces a unit-bounded planar locomotion intent,
and bounds look input before it reaches presentation or a future pawn adapter.
It contains no client-authoritative world mutation.

## Presentation and animation boundary

TASK-013's UE 5.8 Mannequin-to-distinct-MetaHuman retarget validation remains
the animation-content prerequisite. This task intentionally creates no
MetaHuman, animation, Input Mapping Context or Input Action asset: the
production contract is renderer and asset independent. A later reviewed
MetaHuman adapter may consume `FCotSAppearanceRecipe` locally, but must not
become the source of ownership, collision or movement authority.
