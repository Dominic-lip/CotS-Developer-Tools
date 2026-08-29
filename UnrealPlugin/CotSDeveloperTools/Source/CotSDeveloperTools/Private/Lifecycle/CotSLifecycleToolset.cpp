#include "Lifecycle/CotSLifecycleToolset.h"

#include "Core/CotSOperationResult.h"
#include "Editor.h"
#include "Dom/JsonObject.h"
#include "FileHelpers.h"
#include "Framework/Application/SlateApplication.h"
#include "Misc/App.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Misc/ScopeExit.h"
#include "HAL/PlatformMisc.h"
#include "UObject/Package.h"

namespace
{
    constexpr TCHAR ToolLabProjectFile[] = TEXT("CotSToolLab.uproject");

    bool IsToolLabProject()
    {
        return FPaths::GetCleanFilename(FPaths::GetProjectFilePath()).Equals(ToolLabProjectFile, ESearchCase::CaseSensitive)
            && FString(FApp::GetProjectName()).Equals(TEXT("CotSToolLab"), ESearchCase::CaseSensitive);
    }

    FCotSOperationResult ValidateShutdownPreconditions()
    {
        const FString Operation = TEXT("CotS.Lifecycle.RequestToolLabShutdown");
        if (!GIsEditor || !GEditor)
        {
            return FCotSOperationResult::Fail(Operation, TEXT("editor_context_required"), TEXT("Shutdown is available only from a running Unreal Editor."));
        }
        if (!IsToolLabProject())
        {
            return FCotSOperationResult::Fail(Operation, TEXT("tool_lab_project_required"), TEXT("Shutdown is restricted to the CotSToolLab editor project."));
        }
        if (FSlateApplication::IsInitialized() && FSlateApplication::Get().GetActiveModalWindow().IsValid())
        {
            return FCotSOperationResult::Fail(Operation, TEXT("modal_operation_active"), TEXT("A Slate modal operation is active; resolve it before requesting shutdown."));
        }
        if (GEditor->IsPlaySessionInProgress())
        {
            GEditor->RequestEndPlayMap();
            return FCotSOperationResult::Fail(Operation, TEXT("pie_shutdown_requested"), TEXT("PIE shutdown was requested; retry after the play session ends."));
        }
        const TArray<FString> DirtyPackages = UCotSLifecycleToolset::GetPersistentDirtyPackagePaths();
        if (!DirtyPackages.IsEmpty())
        {
            FCotSOperationResult Result = FCotSOperationResult::Fail(Operation, TEXT("dirty_packages_present"), TEXT("Persistent dirty packages must be saved or cleaned before shutdown."));
            Result.Data = MakeShared<FJsonObject>();
            TArray<TSharedPtr<FJsonValue>> Values;
            for (const FString& Path : DirtyPackages) { Values.Add(MakeShared<FJsonValueString>(Path)); Result.AddAffectedObject(Path); }
            Result.Data->SetArrayField(TEXT("dirty_package_paths"), Values);
            return Result;
        }
        return FCotSOperationResult::Succeed(Operation);
    }
}

bool UCotSLifecycleToolset::IsPersistentPackageForShutdown(const UPackage* Package)
{
    if (!Package || Package == GetTransientPackage()) { return false; }
    const FString Name = Package->GetName();
    return FPackageName::IsValidLongPackageName(Name, false)
        && !Name.StartsWith(TEXT("/Temp/"), ESearchCase::CaseSensitive)
        && !Name.Equals(TEXT("/Engine/Transient"), ESearchCase::CaseSensitive);
}

TArray<FString> UCotSLifecycleToolset::GetPersistentDirtyPackagePaths()
{
    TArray<UPackage*> DirtyPackages;
    FEditorFileUtils::GetDirtyWorldPackages(DirtyPackages);
    FEditorFileUtils::GetDirtyContentPackages(DirtyPackages);
    TArray<FString> Paths;
    for (UPackage* Package : DirtyPackages)
    {
        if (IsPersistentPackageForShutdown(Package)) { Paths.AddUnique(Package->GetName()); }
    }
    Paths.Sort();
    return Paths;
}

FString UCotSLifecycleToolset::RequestToolLabShutdown()
{
    FCotSOperationResult Result = ValidateShutdownPreconditions();
    if (!Result.bSuccess) { return Result.ToJson(); }
    Result.Status = TEXT("shutdown_requested");
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetBoolField(TEXT("accepted"), true);
    Result.Data->SetStringField(TEXT("exit_api"), TEXT("FPlatformMisc::RequestExit(false)"));
    Result.Validation.Add(TEXT("host_must_verify_the_exact_editor_pid_exits"));
    UE_LOG(LogCotSDeveloperTools, Display, TEXT("CotS lifecycle shutdown requested: %s"), *Result.OperationId);
    const FString Acknowledgement = Result.ToJson();
    FPlatformMisc::RequestExit(false, TEXT("CotSLifecycleToolset.RequestToolLabShutdown"));
    return Acknowledgement;
}
