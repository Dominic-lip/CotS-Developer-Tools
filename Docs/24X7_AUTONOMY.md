# CotS 24x7 Autonomous Development Runtime

## Purpose

This runtime turns the existing CotS Factory/Supervisor stack into a continuously available local service while protecting provider quota from rapid crash loops.

The core policy is:

- **local work stays local**: health checks, logs, restart decisions, backoff, process ownership, support bundles and telemetry use no Codex/Claude turns;
- **provider output is untrusted data**: malformed `SUPERVISOR_CONTEXT` telemetry is normalized locally and cannot crash the supervisor;
- **no-progress crashes do not hot-loop**: repeated fast failures trigger an exponentially increasing local cooldown before another provider can be used;
- **the GUI is not life support**: the Control Center can be closed while the watchdog continues;
- **Windows is the final supervisor**: a Scheduled Task restarts the watchdog itself if the watchdog process dies;
- **remote access is private by default**: telemetry binds to localhost and can be proxied through Tailscale Serve. Control actions require a bearer token.

## Process hierarchy

```text
Windows Scheduled Task
└─ CotSWatchdog24x7.py
   ├─ local HTTP telemetry/control :8765
   └─ CotSFactoryController24x7.py
      ├─ CotSHostMcp.py
      └─ CotSAgentSupervisor24x7.py
         ├─ Codex app-server
         └─ Claude CLI
```

`CotSControlCenter24x7.py` is only a client/observer. Closing it does not stop the watchdog.

## Fix for the September 1 crash

The observed failures were caused by provider-generated checkpoint telemetry having the wrong JSON types, e.g. a list where `targeted_tests_run` must be an integer, or an integer where `read_fingerprints` must be a list.

`CotSAgentSupervisor24x7.py` inserts a strict schema boundary before that data reaches the existing supervisor. Numeric fields are converted safely, list fields are accepted only as lists, malformed values fall back to previous good values or neutral defaults, and a `TELEMETRY_SANITIZED` local event is written.

This repair consumes no provider turn.

## Quota protection

The watchdog records a progress signature before each Factory generation:

- Git HEAD
- task
- phase
- provider turn count
- last successful gate

If a generation dies quickly without changing any of those values, the `no_progress_streak` increases. Restart delays grow through `5s -> 15s -> 60s -> 120s -> 5m -> 15m -> 30m`.

No provider call is made during the cooldown.

The provider-consuming `CotSAgentFixIt` path is deliberately conservative: it is attempted only after repeated local recovery failed, no more than once per hour, and only when a provider is not already marked exhausted.

## Local daily logs

`.cots/telemetry/YYYY-MM-DD.log` contains human-readable state transitions, watchdog decisions, crashes, recoveries and supervisor events.

`.cots/telemetry/YYYY-MM-DD.jsonl` contains the same events in structured form.

These are generated entirely from local process/checkpoint/log data. They do not use Codex or Claude. The Control Center's **Daily Logs** tab opens these files directly.

## Support bundle

Use **Create Support Bundle** in the Control Center or:

```powershell
python Scripts\CotSSupportBundle.py
```

The ZIP contains recent local telemetry, incidents, watchdog/factory/supervisor state and Git status. It deliberately excludes the remote-control token and raw provider protocol logs.

## Install for continuous operation

From an elevated PowerShell in the repository:

```powershell
powershell -ExecutionPolicy Bypass -File .\Scripts\Install-CotS24x7.ps1 -DisableSleepOnAC
```

This registers `CotS Autonomous Factory 24x7` at user logon, with automatic restart after process failure and no execution-time limit.

The Unreal automation stack requires an interactive signed-in Windows session. For unattended operation leave the machine signed in. The optional `-DisableSleepOnAC` prevents Windows sleeping/hibernating on mains power. The monitor may still turn off normally.

## Manual launch

```text
Scripts\Launch-CotS-24x7.bat
```

This starts the watchdog and opens the new Control Center.

## Remote telemetry

The HTTP service listens on `http://127.0.0.1:8765/`.

Routes:

- `GET /health`
- `GET /snapshot`
- `GET /logs`
- `GET /logs/YYYY-MM-DD`
- `POST /control/restart`
- `POST /control/stop`
- `POST /control/resume`

Control requests require `Authorization: Bearer <token>`. The token is generated locally at `.cots/telemetry-token.local.txt`. Do not commit or publish it.

### Tailscale

After Tailscale is installed and signed in, use the Control Center's **Enable Tailscale Serve** button or:

```powershell
powershell -ExecutionPolicy Bypass -File .\Scripts\Enable-CotS-Remote.ps1
```

Keep the CotS control endpoint inside the private tailnet; do not expose it directly to the public Internet.

## Genuine human gates

"24/7 autonomous" means software/process/provider failures should recover without someone clicking a button. It cannot legitimately bypass external requirements such as MFA, reauthentication, billing/subscription action, CAPTCHA, missing secrets or an explicitly destructive decision.

When one of those is detected, the watchdog remains alive, keeps telemetry available, and waits for a remote/local resume rather than dying.

## Validation

Run:

```powershell
python -m unittest Scripts.tests.test_cots_24x7 -v
```

The regression suite includes the exact malformed telemetry shapes that caused the September 1 supervisor crashes.
