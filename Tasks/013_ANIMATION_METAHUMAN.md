# TASK-013 — Animation and MetaHuman Automation

## Objective
Build the first major CotS domain toolset: automate the class of locomotion/MetaHuman work that previously required long manual editor sessions.

## Target capabilities
Inspect skeleton compatibility; detect ambiguous/duplicate skeletons; inspect/configure retarget assets; batch retarget; create/configure Blend Spaces; create/configure Animation Blueprints/state machines; root-motion/IK policy checks; validate locomotion; run a locomotion test.

## Acceptance test
In a disposable test area, provide a MetaHuman-compatible target plus a small locomotion set (idle, four walk directions, jump/fall/land). The agent produces the locomotion setup, compiles it, runs the test and reports exact assets/results with minimal human intervention.

Do not copy broken/experimental Shardlands animation assets merely to satisfy the test; use Shardlands only as read-only reference unless migration is explicitly authorized later.
