#include "Execution/CotSExecutionToolset.h"

#include "Core/CotSOperationResult.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonObject.h"
#include "Editor.h"
#include "Engine/Engine.h"
#include "HAL/IConsoleManager.h"
#include "Misc/App.h"
#include "Misc/EngineVersion.h"

#include UE_INLINE_GENERATED_CPP_BY_NAME(CotSExecutionToolset)

namespace
{
    constexpr TCHAR OperationName[] = TEXT("CotS.Execution.ExecuteReadOnlyQuery");

    bool IsSafeConsoleVariableName(const FString& Name)
    {
        if (Name.IsEmpty() || Name.Len() > 128 || !FChar::IsAlpha(Name[0]))
        {
            return false;
        }

        for (const TCHAR Character : Name)
        {
            if (!FChar::IsAlnum(Character) && Character != TEXT('.') && Character != TEXT('_'))
            {
                return false;
            }
        }
        return true;
    }

    FString CurrentMapPath()
    {
        if (GEditor)
        {
            if (UWorld* World = GEditor->GetEditorWorldContext().World())
            {
                return World->GetOutermost()->GetName();
            }
        }
        return FString();
    }

    FString SafeQueryForLog(const FString& Query)
    {
        return Query.Left(128).ReplaceCharWithEscapedChar();
    }

    void MarkFailed(FCotSOperationResult& Result, const FString& ErrorCode, const FString& ErrorMessage)
    {
        Result.bSuccess = false;
        Result.Status = TEXT("failure");
        Result.AddError(ErrorCode, ErrorMessage);
    }

    FString Complete(FCotSOperationResult& Result, const FString& Query, const bool bSucceeded)
    {
        if (bSucceeded)
        {
            UE_LOG(LogCotSDeveloperTools, Display, TEXT("CotS execution request %s completed: query='%s'."), *Result.OperationId, *SafeQueryForLog(Query));
        }
        else
        {
            UE_LOG(LogCotSDeveloperTools, Warning, TEXT("CotS execution request %s failed: query='%s'."), *Result.OperationId, *SafeQueryForLog(Query));
        }
        return Result.ToJson();
    }
}

FString UCotSExecutionToolset::ExecuteReadOnlyQuery(const FString& Query, const bool bDryRun)
{
    const double StartedAt = FPlatformTime::Seconds();
    FCotSOperationResult Result = FCotSOperationResult::Succeed(OperationName, bDryRun);
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("query"), Query);
    Result.Data->SetStringField(TEXT("execution_surface"), TEXT("capability_constrained_read_only_query"));

#if !WITH_EDITOR
    MarkFailed(Result, TEXT("editor_only"), TEXT("CotS execution queries are available only in an Unreal Editor build."));
    Result.DurationMs = FMath::RoundToInt64((FPlatformTime::Seconds() - StartedAt) * 1000.0);
    return Complete(Result, Query, false);
#else
    if (!GIsEditor || IsRunningCommandlet())
    {
        MarkFailed(Result, TEXT("editor_context_required"), TEXT("CotS execution queries require an interactive Unreal Editor context."));
        Result.DurationMs = FMath::RoundToInt64((FPlatformTime::Seconds() - StartedAt) * 1000.0);
        return Complete(Result, Query, false);
    }

    if (Query.TrimStartAndEnd().IsEmpty())
    {
        MarkFailed(Result, TEXT("empty_request"), TEXT("Query must name one supported read-only capability."));
        Result.DurationMs = FMath::RoundToInt64((FPlatformTime::Seconds() - StartedAt) * 1000.0);
        return Complete(Result, Query, false);
    }

    UE_LOG(LogCotSDeveloperTools, Display, TEXT("CotS execution request %s started: query='%s'."), *Result.OperationId, *SafeQueryForLog(Query));

    if (Query == TEXT("project.context"))
    {
        Result.Data->SetStringField(TEXT("project_name"), FApp::GetProjectName());
        Result.Data->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
        Result.Data->SetStringField(TEXT("current_map"), CurrentMapPath());
    }
    else if (Query == TEXT("project.name"))
    {
        Result.Data->SetStringField(TEXT("value"), FApp::GetProjectName());
    }
    else if (Query == TEXT("engine.version"))
    {
        Result.Data->SetStringField(TEXT("value"), FEngineVersion::Current().ToString());
    }
    else if (Query == TEXT("map.current"))
    {
        Result.Data->SetStringField(TEXT("value"), CurrentMapPath());
    }
    else if (Query.StartsWith(TEXT("cvar.")))
    {
        const FString ConsoleVariableName = Query.RightChop(5);
        if (!IsSafeConsoleVariableName(ConsoleVariableName))
        {
            MarkFailed(Result, TEXT("forbidden_request"), TEXT("Only an exact read-only cvar.<letters-digits-dot-underscore> query is permitted."));
        }
        else if (IConsoleVariable* ConsoleVariable = IConsoleManager::Get().FindConsoleVariable(*ConsoleVariableName))
        {
            Result.Data->SetStringField(TEXT("console_variable"), ConsoleVariableName);
            Result.Data->SetStringField(TEXT("value"), ConsoleVariable->GetString());
        }
        else
        {
            MarkFailed(Result, TEXT("query_execution_failed"), FString::Printf(TEXT("Console variable '%s' was not found."), *ConsoleVariableName));
        }
    }
    else
    {
        MarkFailed(Result, TEXT("forbidden_request"), TEXT("Submitted code, console commands, UObject invocation, process launch, filesystem, and network operations are not execution capabilities of this bridge."));
    }

    Result.DurationMs = FMath::RoundToInt64((FPlatformTime::Seconds() - StartedAt) * 1000.0);
    return Complete(Result, Query, Result.bSuccess);
#endif
}
