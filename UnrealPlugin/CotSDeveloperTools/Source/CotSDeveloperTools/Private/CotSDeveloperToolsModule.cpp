#include "CotSDeveloperToolsModule.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "HAL/IConsoleManager.h"
#include "Misc/EngineVersion.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"

DEFINE_LOG_CATEGORY(LogCotSDeveloperTools);

void FCotSDeveloperToolsModule::StartupModule()
{
    StatusCommand = IConsoleManager::Get().RegisterConsoleCommand(
        TEXT("CotS.Tools.Status"),
        TEXT("Print CotS Developer Tools, project and Unreal Engine status."),
        FConsoleCommandDelegate::CreateRaw(this, &FCotSDeveloperToolsModule::HandleStatusCommand),
        ECVF_Default);

    ListAssetsCommand = IConsoleManager::Get().RegisterConsoleCommand(
        TEXT("CotS.Tools.ListAssets"),
        TEXT("List assets under a package path. Usage: CotS.Tools.ListAssets /Game [MaxResults]"),
        FConsoleCommandWithArgsDelegate::CreateRaw(this, &FCotSDeveloperToolsModule::HandleListAssetsCommand),
        ECVF_Default);

    InspectAssetCommand = IConsoleManager::Get().RegisterConsoleCommand(
        TEXT("CotS.Tools.InspectAsset"),
        TEXT("Inspect an exact Unreal object path. Usage: CotS.Tools.InspectAsset /Game/Path/Asset.Asset"),
        FConsoleCommandWithArgsDelegate::CreateRaw(this, &FCotSDeveloperToolsModule::HandleInspectAssetCommand),
        ECVF_Default);

    UE_LOG(LogCotSDeveloperTools, Display, TEXT("CotS Developer Tools 0.1.0 loaded."));
}

void FCotSDeveloperToolsModule::ShutdownModule()
{
    if (StatusCommand)
    {
        IConsoleManager::Get().UnregisterConsoleObject(StatusCommand);
        StatusCommand = nullptr;
    }
    if (ListAssetsCommand)
    {
        IConsoleManager::Get().UnregisterConsoleObject(ListAssetsCommand);
        ListAssetsCommand = nullptr;
    }
    if (InspectAssetCommand)
    {
        IConsoleManager::Get().UnregisterConsoleObject(InspectAssetCommand);
        InspectAssetCommand = nullptr;
    }
}

void FCotSDeveloperToolsModule::HandleStatusCommand()
{
    UE_LOG(LogCotSDeveloperTools, Display, TEXT("Status | Project=%s | ProjectDir=%s | Engine=%s"),
        FApp::GetProjectName(),
        *FPaths::ConvertRelativePathToFull(FPaths::ProjectDir()),
        *FEngineVersion::Current().ToString());
}

void FCotSDeveloperToolsModule::HandleListAssetsCommand(const TArray<FString>& Args)
{
    const FString PackagePath = Args.Num() > 0 ? Args[0] : TEXT("/Game");
    const int32 MaxResults = Args.Num() > 1 ? FMath::Max(1, FCString::Atoi(*Args[1])) : 100;

    FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    FARFilter Filter;
    Filter.PackagePaths.Add(FName(*PackagePath));
    Filter.bRecursivePaths = true;

    TArray<FAssetData> Assets;
    AssetRegistryModule.Get().GetAssets(Filter, Assets);
    Assets.Sort([](const FAssetData& A, const FAssetData& B)
    {
        return A.GetObjectPathString() < B.GetObjectPathString();
    });

    UE_LOG(LogCotSDeveloperTools, Display, TEXT("ListAssets | Path=%s | Found=%d | Showing=%d"),
        *PackagePath, Assets.Num(), FMath::Min(MaxResults, Assets.Num()));

    for (int32 Index = 0; Index < Assets.Num() && Index < MaxResults; ++Index)
    {
        const FAssetData& Asset = Assets[Index];
        UE_LOG(LogCotSDeveloperTools, Display, TEXT("ASSET | %s | Class=%s | Package=%s"),
            *Asset.GetObjectPathString(),
            *Asset.AssetClassPath.ToString(),
            *Asset.PackageName.ToString());
    }
}

void FCotSDeveloperToolsModule::HandleInspectAssetCommand(const TArray<FString>& Args)
{
    if (Args.IsEmpty())
    {
        UE_LOG(LogCotSDeveloperTools, Error, TEXT("InspectAsset requires an exact object path."));
        return;
    }

    const FString ObjectPath = Args[0];
    UObject* Asset = StaticLoadObject(UObject::StaticClass(), nullptr, *ObjectPath);
    if (!Asset)
    {
        UE_LOG(LogCotSDeveloperTools, Error, TEXT("InspectAsset | NotFound=%s"), *ObjectPath);
        return;
    }

    UE_LOG(LogCotSDeveloperTools, Display, TEXT("InspectAsset | Object=%s | Class=%s | Package=%s | Flags=0x%08x"),
        *Asset->GetPathName(),
        *Asset->GetClass()->GetPathName(),
        *Asset->GetOutermost()->GetName(),
        static_cast<uint32>(Asset->GetFlags()));
}

IMPLEMENT_MODULE(FCotSDeveloperToolsModule, CotSDeveloperTools)
