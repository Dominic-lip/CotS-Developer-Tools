# CotS 24x7 Autonomous Development Runtime

## Purpose

The 24x7 runtime turns the CotS Factory/Supervisor stack into a continuously available local service while treating cloud-model quota as an expensive engineering resource rather than a heartbeat mechanism.

The core policy is:

- **local work stays local**: health checks, logs, quota reads, hardware checks, restart decisions, backoff, support bundles and telemetry use no Codex/Claude model turns;
- **provider output is untrusted data**: malformed `SUPERVISOR_CONTEXT` telemetry is normalized locally and cannot crash the supervisor;
- **alive and productive are different states**: a healthy process that burns provider turns without durable engineering evidence is not considered productive;
- **four unproductive provider turns trip a governor**: the cloud provider is stopped, local diagnosis runs, and a cooldown is entered;
- **no-progress crashes do not hot-loop**: repeated fast failures trigger increasing local cooldowns before another provider can be used;
- **the GUI is not life support**: the Control Center can be closed while the watchdog continues;
- **Windows is the final supervisor**: a Scheduled Task restarts the watchdog itself if the watchdog process dies;
- **remote access is private by default**: telemetry binds to localhost and can be proxied through Tailscale Serve. Control actions require a bearer token;
- **runtime self-modification is canaried**: autonomous changes to the control plane are locally compiled/tested; failed canaries restore pre-generation copies without `git reset` or `git clean`.

## Process hierarchy

```text
Windows Scheduled Task / Launch-CotS.bat
└─ CotSWatchdogCampaign.py
   └─ CotSWatchdog24x7Final.py
      └─ CotSWatchdog24x7Enhanced.py
         ├─ localhost telemetry/control :8765
         ├─ cross-process-safe ProviderUsageLedger
         ├─ read-only Codex rate-limit probe
         ├─ ProductivityGovernor
         ├─ HardwareMonitor
         ├─ LocalAI (optional Ollama on 127.0.0.1)
         ├─ RollbackGuard + canary
         ├─ OperationalMetrics + MilestoneNotifier
         └─ CotSFactoryControllerCampaign.py
            ├─ CotSFactoryController24x7.py
            │  └─ CotSHostMcp.py
            └─ CotSAgentSupervisorCampaign.py
               └─ CotSAgentSupervisor24x7.py
                  ├─ Codex app-server
                  └─ Claude CLI
```

`CotSControlCenter.py` is the canonical Control Center and explicitly falls back to the campaign watchdog. It opens the mature enhanced UI through a non-blocking read-mostly usage-ledger adapter. Closing it does not stop the watchdog. The watchdog remains the preferred usage-ledger writer so the GUI cannot double-consume provider protocol offsets.

## Provider usage and quota

`CotSUsageLedger.py` tails provider protocol logs locally for turn counts, failures, token-usage events and explicit quota errors. `CotSUsageLedgerSafe.py` serializes writers across the watchdog and GUI.

In addition it performs a **read-only** Codex App Server call approximately every minute:

```text
initialize
account/rateLimits/read
```

It does not start a Codex thread or model turn. When Codex reports rate-limit windows, the Control Center displays:

- percentage used;
- percentage remaining;
- window duration (for example 5-hour or weekly);
- exact reset timestamp and countdown;
- successful/failed turns;
- explicit usage-limit events;
- 24-hour quota-use graph.

When Codex does not report a particular bucket, the UI says **Not reported** rather than inventing a percentage. Explicit `usageLimitExceeded` messages are still parsed locally for reset time.

`.cots/telemetry/provider-usage-samples.jsonl` holds the local graph samples.

## Productivity governor

`CotSProductivityGovernor.py` evaluates each completed provider turn against durable local evidence:

- Git commit changed;
- working tree changed;
- targeted/full test evidence increased;
- acceptance/validation evidence increased;
- successful gate changed;
- task advanced.

If four provider turns complete without any such evidence, the watchdog:

1. gracefully stops the provider/factory boundary;
2. records a `GOVERNOR_PAUSE` event;
3. runs local deterministic/Ollama diagnosis;
4. waits locally (default 15 minutes) without cloud usage;
5. resumes with a fresh productivity streak.

The dashboard reports useful/observed turns, commits per turn, tests per turn, governor trips and current no-value streak.

## Local AI on the GPU

`CotSLocalAI.py` is optional and talks **only** to Ollama at `127.0.0.1:11434`. There is deliberately no cloud fallback.

Preferred small local models include Qwen coder and Llama-class models. When available, local AI can:

- classify failures;
- cluster duplicate incidents;
- select a recovery runbook;
- recommend whether waking a cloud coding agent is worthwhile;
- write a daily activity summary.

If Ollama is unavailable, deterministic rule-based classification remains active.

For the optional local setup helper:

```powershell
powershell -ExecutionPolicy Bypass -File .\Scripts\Setup-CotSLocalAI.ps1
```

If Ollama is not installed and you explicitly want the helper to install it through `winget`:

```powershell
powershell -ExecutionPolicy Bypass -File .\Scripts\Setup-CotSLocalAI.ps1 -InstallOllama
```

The default model is `qwen2.5-coder:14b`; set `COTS_LOCAL_AI_MODEL` to choose a different installed Ollama model. Model downloads can be several GB and are never performed silently by the watchdog.

## Hardware safety telemetry

`CotSHardwareTelemetry.py` records local CPU/RAM/disk/GPU/Unreal/network state. NVIDIA telemetry is read from `nvidia-smi`; Windows memory and Unreal process memory are read locally from the OS.

The factory is paused before unsafe conditions can cascade, including:

- less than 10 GB disk free;
- critically low available RAM;
- GPU temperature above the configured safety threshold;
- critically low VRAM while Unreal is running.

Hardware recovery is checked locally; the factory automatically resumes after the condition clears.

## Automatic runtime rollback

`CotSRollbackGuard.py` snapshots the managed autonomous control-plane files before a factory generation. If autonomous work changes those files, a post-generation canary runs local Python compilation and both 24x7 regression suites.

If the canary fails, the exact pre-generation copies are restored. This is intentionally **not** implemented with `git reset`, `git clean`, history rewriting or a force checkout, so unrelated user work remains untouched.

## Milestone notifications

Local Windows notifications are deliberately sparse. They are emitted for events such as:

- task advanced/completed;
- genuine human gate;
- provider quota exhausted;
- maximum 30-minute cooldown;
- one hour without progress.

Routine turns and healthy restarts do not produce notifications.

## Alive versus productive

The top of the enhanced Control Center reports both independently.

A typical 24-hour line is conceptually:

```text
24h uptime 99.7% · 11 useful turns · 8 commits · 37 tests · 1 recovery · 0 human interventions
```

`CotSOperationalMetrics.py` stores lightweight 30-second local samples for 48 hours and calculates the rolling 24-hour report without using an AI provider. Telemetry continues updating during deliberate cooldowns and genuine human-gate waits.

## Quota/crash protection

The outer watchdog still records a generation progress signature and applies local crash-loop backoff:

```text
5s -> 15s -> 60s -> 120s -> 5m -> 15m -> 30m
```

No provider call is made during cooldown. Provider-consuming FixIt remains conservative: only after repeated local recovery fails, no more than once per hour, and only when a provider is not already marked exhausted.

## Local daily logs

`.cots/telemetry/YYYY-MM-DD.log` contains human-readable state transitions, watchdog decisions, crashes, recoveries and supervisor events.

`.cots/telemetry/YYYY-MM-DD.jsonl` contains the same events in structured form.

The enhanced Control Center has a **Daily Logs** tab for browsing these files and a **Local AI** tab for optional local summaries. Raw checkpoint/provider dictionaries belong in **Diagnostics**, not on the Overview screen.

## Chaos testing

`CotSChaosRunner.py` runs safe deterministic simulations covering malformed provider output, fake quota exhaustion, process death semantics, productivity trips, hardware gates, rollback primitives and recovery state. It does not disable the real network or kill unrelated live processes.

```powershell
python Scripts\CotSChaosRunner.py
```

or use **Chaos / Recovery -> Run Safe Chaos Suite** in the Control Center.

`CotSLiveChaosMaintenance.py` is the explicitly destructive maintenance harness. It does nothing unless `--live` is supplied, targets only exact PIDs recorded as CotS-owned, and verifies recovery after each fault. The watchdog-kill test additionally refuses to run unless the Windows recovery scheduled task is installed.

```powershell
python Scripts\CotSLiveChaosMaintenance.py --live --components provider,supervisor,host,factory,watchdog
```

Optional provider-network chaos is Windows/admin-only and blocks only safely identifiable native `codex.exe`/`claude.exe` executables. It arms an independent timed firewall-rule cleanup before applying the block and refuses broad Node/Python network blocking:

```powershell
python Scripts\CotSLiveChaosMaintenance.py --live --components provider,supervisor,host,factory --include-provider-network
```

## Support bundle

Use **Support Bundle** in the Control Center or:

```powershell
python Scripts\CotSSupportBundle.py
```

The ZIP includes recent local telemetry, incidents, watchdog/factory/supervisor state, quota ledger, productivity governor, hardware state, rollback/chaos state and Git status. It excludes the remote-control token and raw provider protocol logs.

## Install for continuous operation

From an elevated PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\Scripts\Install-CotS24x7.ps1 -DisableSleepOnAC
```

This registers `CotS Autonomous Factory 24x7` at user logon with automatic process restart and no execution-time limit. The Unreal automation stack requires an interactive signed-in Windows session.

## Manual launch

```text
Scripts\Launch-CotS.bat
```

This starts the production campaign watchdog and opens the canonical Control Center. Historical launcher names redirect here.

## Remote telemetry

The HTTP service listens on `http://127.0.0.1:8765/` and exposes local health/snapshot/logs plus bearer-token-protected safe stop/restart/resume controls.

After Tailscale is installed and signed in, use **Remote / Tunnel -> Enable Tailscale Serve**. Keep the service inside the private tailnet. For shell access, use Windows OpenSSH over Tailscale rather than opening public port 22.

## Genuine human gates

24/7 autonomous recovery cannot bypass MFA, reauthentication, billing/subscription action, CAPTCHA, missing secrets or an explicitly destructive decision. For those cases the watchdog remains alive and keeps telemetry available while awaiting local/remote intervention.

## Validation

Run:

```powershell
python -m unittest Scripts.tests.test_cots_24x7 Scripts.tests.test_cots_24x7_enhanced -v
```

The suites include the exact malformed telemetry shapes that caused the September 1 supervisor crashes plus enhanced quota, governor, hardware, metrics and rollback primitives.
