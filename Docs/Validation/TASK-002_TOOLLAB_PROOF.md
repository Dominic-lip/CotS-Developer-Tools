# TASK-002 Tool Lab proof

Date: 2026-08-30. This evidence was performed by the active Codex supervisor
adapter against the fixed local CotS Host MCP operations; no Shardlands or CotS
production files were written.

## Build and editor lifecycle

1. `AcquireMutationLock` acquired `supervisor-task-002` (operation
   `752ab15f-d14b-4eeb-b160-224e1f76f92e`).
2. Fixed Host `BuildToolLab` completed with exit code 0 (operation
   `412123a9-c60f-4944-a320-a591a98e49ce`). Its canonical
   `Scripts\\Build-ToolLab.cmd` output identified
   `CotSToolLabEditor Win64 Development`, project
   `C:\\Dev\\CotSDeveloperTools\\ToolLab\\CotSToolLab.uproject`, UE 5.8, and
   ended `Result: Succeeded` / `[OK] CotS Tool Lab editor target built
   successfully.`
3. Fixed Host `OpenToolLab` started editor PID 44104 (operation
   `977d89e3-1b01-41e1-b41e-d162935c3089`), and `WaitForUnrealMcp` confirmed
   `http://127.0.0.1:8000/mcp` ready (operation
   `7aa676d7-2777-4b88-ab94-0f6f80ad5849`).

The only build warning was Unreal's advisory that the installed Visual Studio
14.51.36252 compiler is newer than its preferred 14.50.35717; UBT reported a
successful build with no actions required.

## Initial read-only CotS inspection

The historical `CotS.Tools.*` console spellings are now represented by the
native typed CotS toolsets. Calls were made through UE's `call_tool` dispatcher
and returned successful operation-result envelopes with no errors or warnings:

| Required read | Current typed call | Result |
| --- | --- | --- |
| Status | `CotSFoundationToolset.GetStatus` | Plugin `CotSDeveloperTools` 0.2.0; UE `5.8.1-56057345+++UE5+Release-5.8`. |
| Project/plugin status | `CotSInspectionToolset.GetProjectStatus` | Project `CotSToolLab`; `cots_plugin_enabled: true`; `cots_module_loaded: true`; PIE not running. |
| Asset listing under `/Game` | `CotSInspectionToolset.SearchAssets(nameQuery: "", pathQuery: "/Game", classPath: "")` | Returned `/Game/CotSAutonomousProof/BP_CodexProofActor.BP_CodexProofActor` and `/Game/CotSAutonomousProof/Maps/M_CodexProof.M_CodexProof`. |
| Valid exact asset inspection | `CotSInspectionToolset.GetAsset("/Game/CotSAutonomousProof/BP_CodexProofActor.BP_CodexProofActor")` | `exists: true`, class `/Script/Engine.Blueprint`. |
| Invalid exact asset inspection | `CotSInspectionToolset.GetAsset("/Game/__TASK002_Missing.Asset")` | Successful read operation with `exists: false`. |

`GetPlugins("CotSDeveloperTools")` independently reported the project plugin
enabled and its `CotSDeveloperTools` module loaded. Together with the ready
native endpoint, this is the startup proof; no plugin-load error occurred.

## Clean shutdown

Fixed Host `CloseToolLab` shut down the exact recorded PID through the editor
lifecycle tool (`FPlatformMisc::RequestExit(false)`), operation
`4148e7e9-a9f5-4e6b-8cfa-890c2ab12f80`. The Host verified the PID and native
MCP endpoint disappeared. `ReleaseMutationLock` then released
`supervisor-task-002` (operation `577c5192-abff-4f83-8750-9068f4652d4d`);
final Host status reported editor closed, MCP not ready, and no mutation-lock
owner.
