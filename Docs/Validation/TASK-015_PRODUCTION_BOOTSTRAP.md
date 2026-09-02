# TASK-015 — Production Bootstrap Evidence

## Implemented baseline

On 2026-09-02, the fixed `Scripts/CotSProductionLifecycle.py` bridge created
the empty `C:\Dev\CotS` tree with its UE 5.8 project descriptor, Config
conventions, runtime module, game/editor/server targets, project-local agent
rules, and `.gitignore`. The operation reported twelve created files and no
conflicts, then initialized the local production repository.

The bounded production manifest `TASK-015-build-settings-v7.json` reconciled
all three targets to `BuildSettingsVersion.V7`, which UE 5.8 requires for the
shared editor build environment. The production root commit is `fb6c12c`
(`Bootstrap TASK-015 UE 5.8 production baseline`) and contains exactly the
twelve bootstrap files.

## Validation performed

- `python Scripts/CotSProductionLifecycle.py status` reported the fixed
  `C:\Dev\CotS\CotS.uproject`, initialized repository, UE 5.8 availability,
  and no production editor before launch.
- The canonical `build --target editor` operation returned exit code 0 and UBT
  `Result: Succeeded` after the V7 correction.
- The canonical `build --target game` operation recorded `build_target: game`
  and `build_exit_code: 0` in the fixed lifecycle state.
- The fixed `open` operation launched the production editor (tracked PID
  `24700`).

## Remaining acceptance gate

No production test-map asset was created. After opening the editor, fixed
lifecycle status continued to report `mcp_ready: false`; this App Server
adapter exposes no native Unreal MCP operation for the production endpoint.
A later fixed `close` operation returned:

`no top-level production editor window is available for graceful close`

The live PID therefore cannot be closed or inspected further through the
approved bridge. TASK-015 remains `PARTIAL` until the production adapter
exposes a ready, closeable native Unreal MCP lifecycle (or a fixed audited
test-map bootstrap operation), at which point a minimal `/Game/Maps/CotS_Entry`
asset must be created/saved and the fixed smoke/editor launch path recorded.
