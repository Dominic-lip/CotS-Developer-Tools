# Controlled Development Execution Bridge

## Status and intended use

`CotSDeveloperTools.CotSExecutionToolset` is a development-only editor bridge for
small, novel **read-only** observations that native Unreal MCP does not provide.
It is deliberately capability-constrained; it is not a general script runner.

Repeated workflows must become typed CotS APIs. For example,
`CotS.Animation.CreateBlendSpace(...)` is the permanent shape for animation
authoring, not a submitted script string.

## UE 5.8.1 audit

The installed UE 5.8.1 source was inspected before implementation.

| Mechanism | UE 5.8.1 finding | Decision |
|---|---|---|
| Native MCP programmatic orchestration | The audited `ProgrammaticToolset.get_execution_environment` exposes only `json`, `math`, `datetime`, `copy`, `re`, `time`, and `execute_tool`; it is not Unreal Python. | Cannot perform novel Unreal editor calls itself. |
| Python Editor Script Plugin | `IPythonScriptPlugin::ExecPythonCommandEx(FPythonCommandEx&)` accepts literal code or a file. `FPythonCommandEx` exposes `CommandResult` and captured `FPythonLogOutputEntry` records. | Not exposed: caller-supplied code has ordinary embedded-Python authority. |
| Python restrictive mode | `Engine.Python.IsPythonInRestrictiveMode` is explicitly work-in-progress. The source restricts startup-script file paths and avoids pip installation, but does not provide a runtime sandbox for submitted Python. | Not a security boundary; insufficient for this bridge. |
| Console execution | `UEngine::Exec` / `UUnrealEdEngine::Exec` and `IConsoleCommandExecutor` exist in engine/editor source, but no native MCP console executor is registered. | Not exposed: command strings are broad, mutable, and not safely capability-scoped. |
| UObject invocation | `UObject::ProcessEvent`, `CallFunctionByNameWithArguments`, and `ProcessConsoleExec` are available. | Not exposed: reflective invocation would bypass typed validation and transaction conventions. |
| Toolset Registry | `UToolsetRegistry::RegisterToolsetClass`, `IsToolsetClassRegistered`, `GetToolsetJsonSchema`, and async `ExecuteTool` are present. `UToolsetDefinition` uses static `UFUNCTION(meta=(AICallable))` methods. | Used for MCP registration and testable schema integration. |
| Transactions | `FScopedTransaction` and the existing `FCotSEditorMutationScope` remain the mutation convention. | This bridge performs no mutation and opens no transaction. |
| Result/error/log capture | Python has `FPythonCommandEx` capture; console calls take an `FOutputDevice`; CotS results use `FCotSOperationResult`. | The bridge emits the shared JSON result and explicit start/completion/failure logs. |

## Exposed capability

`ExecuteReadOnlyQuery(query, dry_run)` only accepts these exact query forms:

- `project.context`
- `project.name`
- `engine.version`
- `map.current`
- `cvar.<letters-digits-dot-underscore>`

It reads context through `FApp::GetProjectName`, `FEngineVersion::Current`, the
interactive editor world context, and `IConsoleManager::FindConsoleVariable` / `GetString`.
It never calls `UEngine::Exec`, `UObject::ProcessEvent`, the Python plugin, or an
external executable.

## Threat and safety model

The bridge is compiled in an Editor-only module and also rejects non-editor or
commandlet contexts. Submitted text is a small allowlist grammar, not executable
source. Consequently shell launch, process spawning, filesystem access, network
access, Python imports, console commands, and arbitrary UObject calls have no
capability path to reach them. The cvar branch accepts only a validated cvar name
and reads its value; it cannot set a cvar.

This is stronger than a blacklist because unsupported text is never interpreted.
It is not a security boundary against an operator who can modify/rebuild the plugin
or otherwise control the editor process. It must therefore remain development-only
and should not be enabled in an untrusted multi-tenant editor environment.

## Audit trail and result contract

Every request allocates an `FCotSOperationResult` operation ID. A request-start log
and a completion/failure log include that ID and the bounded, validated query. The
JSON envelope provides `success`, `status`, `operation_id`, errors/error details,
duration, and result data. Read-only queries report no affected object paths; future
typed mutations must use `FCotSEditorMutationScope`, `Modify()`, validation, and
exact object paths.
