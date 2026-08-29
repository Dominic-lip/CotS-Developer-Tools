# Toolchain Roadmap

## M0 — Constitution and shared task system
- Establish workspace boundaries and safety rules.
- Use one task format for Codex and Claude.
- Provide a shared task runner and prerequisite diagnostics.

## M1 — Disposable UE 5.8 Tool Lab
- Minimal C++ project.
- CotSDeveloperTools plugin linked into the project.
- Clean editor build/startup.
- No production assets.

## M2 — Native MCP connectivity
Both Codex and Claude must independently prove they can identify the open project, current map/selection and enumerate available toolsets.

## M3 — Native MCP capability audit
Systematically test what Epic already provides. Record native/partial/missing/unreliable capabilities. Do not duplicate working native tools.

## M4 — Inspection foundation
Target capabilities:
- Unreal/editor/project status
- asset search and exact object paths
- asset/class/property inspection
- dependencies and referencers
- Blueprint inspection
- skeleton/animation inspection
- plugin/module inventory
- duplicate detection

## M5 — Safe mutation foundation
Create/move/rename assets, set properties, create actors/components, save, compile and validate. Add impact reporting and dry-run behavior where practical.

## M6 — Build/test/diagnostics
Agents must be able to compile their own work, run Automation/PIE tests, collect logs and distinguish warnings from failures.

## M6.5 — Autonomous lifecycle controller (TASK-008A)
- Loopback-only, agent-neutral Host MCP controls the disposable ToolLab lifecycle.
- Fixed open/close/readiness/build/test operations preserve one mutating agent at a time.
- No arbitrary host command, process, PID, or filesystem capability is exposed.

## M7 — Autonomous proof
The same specification is executed once by Codex and once by Claude: create a small test actor, compile/save, run it in PIE, inspect runtime state, stop PIE and report all changes without human editor clicking.

## M8 — Animation and MetaHuman toolset
Automate the workflow that previously required manual retarget/Blend Space/AnimBP work. Acceptance test: given a MetaHuman and a small locomotion set, produce and validate a working locomotion pipeline with minimal human intervention.

## M9 — Shardlands donor tooling
Inventory and compare legacy systems without modifying them. Generate explicit migrate/rebuild/leave decisions and dependency manifests.

## M10 — CotS production bootstrap
Only after the factory is proven: generate the clean production UE project, build targets, plugin linkage, validation gates and baseline commit.

## Guiding metric
The important metric is not number of tools. It is the amount of reliable Unreal work an agent can complete and verify without human editor manipulation.
