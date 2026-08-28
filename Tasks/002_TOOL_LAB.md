# TASK-002 — Disposable Unreal 5.8 Tool Lab

## Objective
Establish a minimal disposable UE 5.8 C++ project used exclusively to develop and test CotS tooling.

## Allowed scope
`C:\Dev\CotSDeveloperTools\ToolLab`, `UnrealPlugin`, scripts and docs.

## Forbidden scope
No Shardlands or CotS writes.

## Requirements
- Run `Scripts/Bootstrap-ToolLab.ps1` to link the plugin into `ToolLab/Plugins`.
- Generate UE project files.
- Build the `CotSToolLabEditor` target for Win64 Development Editor.
- Launch the editor.
- Verify the plugin loads.
- Run `CotS.Tools.Status`, `CotS.Tools.ListAssets /Game`, and a valid/invalid `CotS.Tools.InspectAsset` call.
- Fix all compile/API issues against the actual UE 5.8 installation rather than asking the human to edit source manually.

## Validation
A clean editor build and startup with no plugin load error. Console status command prints the correct Tool Lab project and UE version.

## Acceptance criteria
The Tool Lab reliably opens and the initial read-only CotS console commands execute.
