# TASK-014 — Shardlands donor / migration audit

## Scope and evidence

This is a read-only inventory of `C:\Dev\Shardlands` on 2026-08-31. No
Shardlands or CotS file was written. The donor is a UE 5.8 project with two
runtime modules (`Shardlands`, `ShardlandsMetaHuman`), StateTree and
GameplayStateTree plugins, MetaHuman Character/Crowd plugins, and three
variant maps (`FirstPerson/Lvl_FirstPerson`, `Variant_Horror/Lvl_Horror`, and
`Variant_Shooter/Lvl_Shooter`). The main module explicitly uses
`bUseUnity=false`, Enhanced Input, UMG, AI, StateTree, and GameplayStateTree.

The inventory is intentionally at subsystem level: it identifies reusable
contracts and dependencies without treating generated binaries, test maps, or
whole folders as a migration unit.

| Area | Evidence | Classification | Dependencies / migration boundary | Confidence |
| --- | --- | --- | --- | --- |
| Project/module/config baseline | `Shardlands.uproject`; `Source/Shardlands*.Build.cs`; `Config/*.ini` | REBUILD CLEANLY | UE 5.8, DX12/SM6 renderer settings, Enhanced Input, UMG, StateTree; current config retains first-person template redirects/default maps. | High |
| Core character/player/camera/game mode | `Source/Shardlands/ShardlandsCharacter*`, `ShardlandsPlayerController*`, `ShardlandsGameMode*`, `ShardlandsCameraManager*` | MIGRATE AFTER CLEANUP | Depends on template-origin game-mode/input defaults and Item/Interaction/Combat components; extract authority contracts, not classes wholesale. | High |
| Character appearance and population | `Character/ShardlandsCharacterAppearance*`, `ShardlandsCharacterCreatorModel*`, population presets; replicated appearance component | MIGRATE AFTER CLEANUP | Stable renderer-independent recipe is a useful seam; preserve replicated identity/recipe, replace project paths and presentation hooks. | High |
| MetaHuman presentation | `Source/ShardlandsMetaHuman/*`; `MetaHumanCharacterPalette` dependency | MIGRATE AFTER CLEANUP | Isolated optional runtime module, explicit option-map Data Asset, collection/instance APIs; legacy pipeline is marked `MetaHumanCreatorOnly` / “Legacy - Do Not Use”. | High |
| Animation / locomotion assets | `Content/Characters`, `Content/MetaHumans`; mannequin/MetaHuman content | REBUILD CLEANLY | Asset and retarget setup must be re-authored against CotS skeleton policy and TASK-013 tooling; do not bulk-copy experimental assets. | Medium |
| Inventory, equipment, containers, item identity | `Items/ShardlandsInventoryComponent*`, `ShardlandsEquipment*`, `ShardlandsPortableContainerTypes*`, `ShardlandsItemTypes*` | MIGRATE AFTER CLEANUP | Strong server-authoritative, replicated ownership/grid/container contracts; coupled to world actors, UI and many specialist state subsystems. | High |
| Crafting, metallurgy, workmanship and lineage | `Items/Shardlands*StateSubsystem*`, `*Quality*`, `*Provenance*`, `World/*Bench*`, `Interaction/*Workmanship*` | MIGRATE AFTER CLEANUP | Retain domain rules/data identities after extracting from development fixture actors and UI/presentation coupling. | High |
| Interaction and physical carry | `Interaction/ShardlandsInteractionComponent*`, `ShardlandsInteractable*`, carried-workpiece/cargo helpers | MIGRATE AFTER CLEANUP | Server RPC boundary, inventory, world stations, UMG and development commands are interleaved; split production intent/authority from dev routing. | High |
| Combat and ranged prototype | `Combat/*`, `Variant_Shooter/*` | REBUILD CLEANLY | Shooter variant, projectile and StateTree sample behavior are useful reference only; target combat authority and MMO networking are not established here. | High |
| World simulation/ecology | `World/ShardlandsEcologySubsystem*`, resource/deposit actors, environment/clock/transition subsystems | MIGRATE AFTER CLEANUP | Valuable renewable-resource and authority concepts; depends on prototype world actors, test-plane helpers and generated data. | Medium |
| World-authoring / development tools | `World/*Development*`, `*TestPlane*`, `*QATestbed*`, `UI/ShardlandsDevelopmentMenu*` | LEAVE IN SHARDLANDS | Explicit dev/test fixture and teleport/refill/spawn machinery; retain only as reference for new CotS tooling acceptance tests. | High |
| Canonical data compiler and generated registry | `sharddata.py`, `Data/Source/*.csv`, `Data/Generated/*.json`, `Data/Registry/build_manifest.json` | MIGRATE DIRECTLY | Python stdlib CSV/JSON compiler validates typed IDs/references. Manifest records 1,712 items, 65 actions, 53 processes, 36 recipes and 36 resource nodes. Move schema/compiler as a separately versioned CotS data boundary, then regenerate outputs. | High |
| UI | `UI/*Widget*`, inventory/equipment/context/workmanship widgets | MIGRATE AFTER CLEANUP | Depends heavily on Item/Interaction RPC snapshots and first-person/dev menu flows; preserve presentation requirements, rebuild view models/layouts. | High |
| Maps, experiments and duplicates | `Content/FirstPerson`, `Variant_Horror`, `Variant_Shooter`, `__ExternalActors__`, `__ExternalObjects__`, `Source/Variant_*` | LEAVE IN SHARDLANDS | Template-derived first-person baseline and deliberately divergent horror/shooter experiments; use only for reference or narrow behavior tests. | High |
| Aether realm prototype | `Aether/ShardlandsAether*` | LEAVE IN SHARDLANDS | Isolated prototype with no verified CotS production dependency yet. | Medium |

## Dependency observations

- The canonical data pipeline is the cleanest direct donor: `sharddata.py`
  declares source tables, primary keys, typed cross-reference checks, and a
  generated manifest with no warnings. It should be migrated before gameplay
  systems that consume its identities.
- Inventory/interaction/workmanship/world actors form one tightly coupled
  vertical slice. Reuse their server-authoritative rules only after defining
  production persistence, replication, and UI boundaries.
- Appearance is deliberately split: the main module owns a replicated stable
  recipe, while the MetaHuman module owns optional renderer integration. That
  seam is worth preserving; the legacy collection pipeline is not.
- Current default maps, template redirects, variant folders and development
  fixture APIs are donor evidence, not production bootstrap material.

## Recommended production order

1. Adapt the data compiler and canonical schemas, preserving source IDs and
   regeneration rather than copying generated JSON as hand-maintained data.
2. Rebuild a narrow authority/persistence core, then adapt inventory and
   interaction contracts against it.
3. Adapt appearance identity/presentation seam after the production character
   architecture exists; integrate MetaHuman assets through the new pipeline.
4. Rebuild combat, UI, maps and world presentation from requirements; consult
   variants/test planes only as behavioral references.

This audit does not authorize a migration. Each production task must still
perform its just-in-time existing-work review and record its own reuse choice.
