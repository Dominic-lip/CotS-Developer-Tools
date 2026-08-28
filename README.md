# CotS Developer Tools

Internal development tooling for **Chronicles of the Sigilarium (CotS)**.

This repository is the reusable Unreal Engine production toolchain used by AI coding agents such as Codex and Claude. It is deliberately separate from both the legacy `Shardlands` donor project and the clean `CotS` production game repository.

## Workspace layout

```text
C:\Dev\
├── Shardlands\          # legacy/reference donor project
├── CotSDeveloperTools\  # this repository
├── CotS\                # clean production game
└── Tasks\               # optional external task specifications
```

## Core rule

If a deterministic Unreal Editor operation must be repeated manually, treat that as a tooling defect and automate it.

## Initial milestones

1. Shared Codex/Claude task system.
2. Disposable UE 5.8 Tool Lab.
3. Native Unreal MCP connectivity for both agents.
4. Audit Epic's native MCP capabilities before duplicating them.
5. CotSDeveloperTools Unreal plugin foundation.
6. Inspection, mutation, validation and test primitives.
7. First fully autonomous Unreal proof task.
8. Animation/MetaHuman automation.
9. Shardlands migration tooling.
10. Production CotS project bootstrap.

See `Docs/ROADMAP.md` and `Tasks/` for the executable plan.
