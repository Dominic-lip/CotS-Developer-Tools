# TASK-117 Operations validation checkpoint — 2026-09-04

## Fixed-adapter evidence

The required production lifecycle route was used exclusively:

1. `python Scripts/CotSProductionLifecycleCampaign.py status` reported that
   `C:\Dev\CotS` exists and that no production editor is running.
2. `python Scripts/CotSProductionLifecycleCampaign.py apply-manifest
   task-117-operations.json` returned `WinError 5: Access is denied` for
   `C:\Dev\CotS\Source\CotS\Public\Operations` before any manifest target
   was created.
3. The canonical campaign editor build returned exit code `999` with
   `RunUBT ERROR: UnrealBuildTool failed to check dependencies` and
   `ERROR: Failed to build UnrealBuildTool`.

The production status probe also returned Git's exact dubious-ownership refusal:
the production worktree is owned by `MOTU/domin`, while the App Server sandbox
process runs as `MOTU/CodexSandboxOffline`. No global Git configuration was
changed because it is outside the fixed authorized lifecycle path.

## Result

TASK-117 acceptance is not verified. The source manifest, focused
`operations-automation` lifecycle route, donor decisions, and exact failed
adapter observations are durable in DeveloperTools. Do not rerun the unchanged
manifest or build until the production lifecycle adapter can write to the
existing `C:\Dev\CotS` tree and its UBT dependency check succeeds.
