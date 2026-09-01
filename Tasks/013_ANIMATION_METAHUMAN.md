# TASK-013 — Animation and MetaHuman Automation

## Objective
Build the first major CotS domain toolset: automate the class of locomotion/MetaHuman work that previously required long manual editor sessions.

## Target capabilities
Inspect skeleton compatibility; detect ambiguous/duplicate skeletons; inspect/configure retarget assets; batch retarget; create/configure Blend Spaces; create/configure Animation Blueprints/state machines; root-motion/IK policy checks; validate locomotion; run a locomotion test.

## Acceptance test
In a disposable test area, provide a MetaHuman-compatible target plus a small locomotion set (idle, four walk directions, jump/fall/land). The agent produces the locomotion setup, compiles it, runs the test and reports exact assets/results with minimal human intervention.

Do not copy broken/experimental Shardlands animation assets merely to satisfy the test; use Shardlands only as read-only reference unless migration is explicitly authorized later.

## Acceptance scope resolution
The durable validation record in `Docs/Validation/TASK-013_LOCOMOTION_CONTENT_PREREQUISITE.md` demonstrates the literal acceptance test end-to-end: the agent produced the disposable locomotion setup, compiled it without warnings, ran PIE, and independently observed the runtime state machine cycling through `Falling -> JumpStart -> Landing`, with exact asset/results recorded and no manual editor interaction.

The later MetaHuman investigation established that the only remaining item from the broader target-capability wish list is **authoring a new IK Rig for a genuinely distinct source skeleton**. The installed MetaHuman retarget content is a MetaHuman-to-MetaHuman self-retargeter, and neither native Unreal MCP nor the current CotS plugin exposes IK Rig authoring. Implementing that capability requires a new C++ tool around `UIKRigController` / `UIKRigDefinition`; it is not missing acceptance evidence for the locomotion setup already produced.

Therefore TASK-013 is considered complete at its written acceptance boundary. New IK Rig authoring is explicitly moved to the non-gating `Docs/TOOLING_BACKLOG.md` and must be implemented when a production animation task actually needs it. This scope resolution does **not** claim that IK Rig authoring already exists.
