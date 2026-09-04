# CotS Production Control Plane

## Operator path

`Scripts\Launch-CotS.bat` is the only normal operator entry point. It starts
the active campaign watchdog and opens the Control Center. Closing the window
does not stop the watchdog.

```text
Launch-CotS.bat
├─ CotSWatchdogCampaign.py                 canonical persistent runtime
│  └─ CotSWatchdog24x7Final.py             current reliability dependency
│     └─ CotSWatchdog24x7Enhanced.py       quota, hardware, recovery services
│        ├─ CotSWatchdog24x7.py            telemetry/control implementation
│        ├─ CotSProductionHostBridge.py    loopback fixed lifecycle bridge
│        │  └─ CotSProductionLifecycleCampaign.py (private direct re-entry)
│        │     └─ fixed reviewed operations against C:\Dev\CotS
│        └─ CotSFactoryControllerCampaign.py
│           └─ CotSFactoryController24x7.py
│              └─ CotSFactoryController.py
│                 ├─ CotSHostMcp.py        ToolLab-only host controller
│                 └─ CotSAgentSupervisorCampaign.py
│                    └─ CotSAgentSupervisor24x7.py
│                       └─ CotSAgentSupervisor.py
│                          ├─ Codex routing
│                          └─ Claude routing
│                             └─ CotSProductionLifecycleCampaign.py
│                                └─ loopback host bridge
└─ CotSControlCenter.py                    canonical operator UI
   └─ CotSControlCenter24x7Final.py        current UI implementation
```

Production mutation is authorized only for the reviewed campaign scheduler universe:
`TASK-015`, `TASK-100..115`, and `TASK-117..121`. The campaign adapter rejects
`TASK-122`; `TASK-117` remains the earliest incomplete task. The fixed
`CotSProductionLifecycleCampaign.py` adapter normally proxies through the
watchdog-owned bridge. It can execute the base adapter directly only when the
bridge supplies its private re-entry environment flag. The bridge binds only to
`127.0.0.1:8011`, requires its private token, accepts no executable, cwd, or
shell command, and always launches that exact adapter. The base lifecycle still
performs the reviewed operation, task, manifest, path, Git, and Unreal checks.
`C:\Dev\Shardlands` is never a production target.

## Classification and staged consolidation

| Component | Classification | Reason |
| --- | --- | --- |
| `Launch-CotS.bat`, `CotSControlCenter.py`, `CotSWatchdogCampaign.py` | CANONICAL | Active operator surface and TASK-117..121 scheduler. |
| Campaign factory/supervisor/lifecycle adapters | CURRENT_DEPENDENCY | They supply campaign task authorization, completion semantics, and fixed lifecycle routing. |
| `*24x7*`, `*Enhanced*`, `*Final*` Python modules | CURRENT_DEPENDENCY | Mature reliability/UI behaviour is still composed by campaign modules. They must not be removed until that behaviour is moved behind explicit configuration. |
| `Launch-CotS-24x7.bat`, `Launch-CotS-Campaign-Control-Center.bat` | COMPATIBILITY_ONLY | Tiny, labelled redirects to the canonical launcher. |
| `Launch-CotS-Agents.bat`, `CotSFactoryBootstrap.py`, base factory/supervisor | COMPATIBILITY_ONLY | Retained for documented manual/bootstrap workflows and legacy-fixture tests; they fail closed against the live campaign task universe and are not the production campaign operator path. |
| `CotSControlCenter24x7.py`, `CotSControlCenter24x7Stable.py` | COMPATIBILITY_ONLY | Historical UI entry points; no canonical path targets them. |

The old version names are implementation dependencies, not operator vocabulary.
The next safe collapse is to replace module-global monkey patches in the
campaign wrappers with an explicit `ControlPlaneConfig` consumed by the mature
watchdog, factory, supervisor and lifecycle implementations. That is not
performed here because those globals are presently covered by regression
contracts and changing them without a dedicated migration would risk provider,
hardware, loop-guard and recovery behaviour.

## Host-bridge verification status

`CotSProductionHostBridge.py` is the watchdog-owned production bridge. It is
genuinely wired: normal provider lifecycle calls proxy to it; only its private
re-entry launches the reviewed lifecycle adapter under the normal host identity.
Provider sandboxes do not require direct NTFS access to `C:\Dev\CotS`. The
campaign instructions explicitly reject ACL changes, global Git configuration,
alternate host commands, and direct-write workarounds when access fails.
