# TASK-015 — Production Bootstrap Evidence

## Implemented baseline

On 2026-09-02, the fixed `Scripts/CotSProductionLifecycle.py` bridge created
the empty `C:\Dev\CotS` tree with its UE 5.8 project descriptor, Config
conventions, runtime module, game/editor/server targets, project-local agent
rules, and `.gitignore`. The operation reported twelve created files and no
conflicts, then initialized the local production repository.

The bounded production manifest `TASK-015-build-settings-v7.json` reconciled
all three targets to `BuildSettingsVersion.V7`, which UE 5.8 requires for the
shared editor build environment. The production root commit `fb6c12c`
(`Bootstrap TASK-015 UE 5.8 production baseline`) contains the twelve
bootstrap files; follow-up commit `821bfe6` captures UE-generated
`Config/DefaultInput.ini`. Fixed status then reported a clean production
worktree at `821bfe679468827b57545c5e9cb86c2590ba19ee`.

## Validation performed

- `python Scripts/CotSProductionLifecycle.py status` reported the fixed
  `C:\Dev\CotS\CotS.uproject`, initialized repository, UE 5.8 availability,
  and no production editor before launch.
- The canonical `build --target editor` operation returned exit code 0 and UBT
  `Result: Succeeded` after the V7 correction.
- The canonical `build --target game` operation recorded `build_target: game`
  and `build_exit_code: 0` in the fixed lifecycle state.
- The declared `CotSServer` target was invoked once through the fixed bridge.
  UBT reported that server targets are not supported by this installed engine
  distribution, so no retry was made; the source target remains the required
  deterministic server plan rather than a falsely claimed server build.
- The fixed `open` operation launched the production editor (tracked PID
  `24700`).

## Native-MCP reconciliation and remaining gate

The production descriptor now enables `ModelContextProtocol` and
`AllToolsets`; its project user settings specify `/mcp` and
`bAutoStartServer=True`. The fixed `wait-mcp --timeout 90` operation then
proved a ready endpoint at `http://127.0.0.1:8000/mcp`, and native toolset
diagnostics confirmed the registered Scene, Asset, EditorApp, Programmatic,
and Slate Inspector toolsets. Production commit `f90da9c` records those exact
configuration files; fixed status afterwards reported a clean worktree.

No direct native tool creates a level asset: Scene tools only load or operate
on existing levels, and Asset tools only save existing assets. The registered
Slate Inspector exposed the File menu's `New Level...` command, but invoking
that UI command through the fixed bridge timed out and blocked subsequent MCP
requests while the editor remained live. The fixed `close` operation then
closed the tracked editor cleanly. No `/Game/Maps/CotS_Entry` asset was
created, and no fixed smoke pass was recorded.

TASK-015 therefore remains `PARTIAL`. It needs a fixed, non-blocking
production `create-entry-map` operation (or a native direct level-creation
tool), then one create/save, editor/MCP inspection, and fixed smoke proof.
