#include "Inspection/CotSAssetQueryToolset.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Core/CotSOperationResult.h"
#include "Dom/JsonObject.h"
#include "Misc/PackageName.h"
#include "Modules/ModuleManager.h"
#include "UObject/TopLevelAssetPath.h"

#include UE_INLINE_GENERATED_CPP_BY_NAME(CotSAssetQueryToolset)

namespace
{
TSharedRef<FJsonObject> AssetJson(const FAssetData& Asset)
{
    TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
    Json->SetStringField(TEXT("object_path"), Asset.GetObjectPathString());
    Json->SetStringField(TEXT("package_path"), Asset.PackagePath.ToString());
    Json->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Json->SetStringField(TEXT("asset_name"), Asset.AssetName.ToString());
    Json->SetStringField(TEXT("class"), Asset.AssetClassPath.ToString());
    return Json;
}
}

FString UCotSAssetQueryToolset::SearchAssetsFiltered(
    const FString& NameQuery,
    const FString& PackagePath,
    const FString& ClassPath,
    bool bRecursivePaths,
    bool bRecursiveClasses,
    int32 MaxResults)
{
    constexpr const TCHAR* Operation = TEXT("CotS.AssetQuery.SearchAssetsFiltered");
    if (MaxResults < 1 || MaxResults > 5000)
    {
        return FCotSOperationResult::Fail(
            Operation,
            TEXT("invalid_max_results"),
            TEXT("MaxResults must be between 1 and 5000.")).ToJson();
    }

    FARFilter Filter;
    Filter.bRecursivePaths = bRecursivePaths;
    Filter.bRecursiveClasses = bRecursiveClasses;

    if (!PackagePath.IsEmpty())
    {
        if (!FPackageName::IsValidLongPackageName(PackagePath, false))
        {
            return FCotSOperationResult::Fail(
                Operation,
                TEXT("invalid_package_path"),
                TEXT("PackagePath must be an exact long package path such as /Game/CotS.")).ToJson();
        }
        Filter.PackagePaths.Add(FName(*PackagePath));
    }

    if (!ClassPath.IsEmpty())
    {
        FTopLevelAssetPath ParsedClassPath;
        if (!ParsedClassPath.TrySetPath(ClassPath))
        {
            return FCotSOperationResult::Fail(
                Operation,
                TEXT("invalid_class_path"),
                TEXT("ClassPath must be a valid top-level Unreal class path.")).ToJson();
        }
        Filter.ClassPaths.Add(ParsedClassPath);
    }

    IAssetRegistry& Registry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get();
    TArray<FAssetData> Candidates;
    if (Filter.IsEmpty())
    {
        // An unconstrained production-wide scan is intentionally refused. The
        // legacy SearchAssets remains available for small ToolLab diagnostics.
        return FCotSOperationResult::Fail(
            Operation,
            TEXT("filter_required"),
            TEXT("Provide PackagePath and/or ClassPath for production-scale searches.")).ToJson();
    }
    Registry.GetAssets(Filter, Candidates);

    Candidates.Sort([](const FAssetData& Left, const FAssetData& Right)
    {
        return Left.GetObjectPathString() < Right.GetObjectPathString();
    });

    FCotSOperationResult Result = FCotSOperationResult::Succeed(Operation);
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetNumberField(TEXT("candidate_count"), Candidates.Num());
    Result.Data->SetNumberField(TEXT("max_results"), MaxResults);
    Result.Data->SetStringField(TEXT("package_path"), PackagePath);
    Result.Data->SetStringField(TEXT("class_path"), ClassPath);

    TArray<TSharedPtr<FJsonValue>> Assets;
    int32 MatchCount = 0;
    bool bTruncated = false;
    for (const FAssetData& Asset : Candidates)
    {
        if (!NameQuery.IsEmpty() && !Asset.AssetName.ToString().Contains(NameQuery, ESearchCase::IgnoreCase))
        {
            continue;
        }
        ++MatchCount;
        if (Assets.Num() >= MaxResults)
        {
            bTruncated = true;
            continue;
        }
        Assets.Add(MakeShared<FJsonValueObject>(AssetJson(Asset)));
        Result.AddAffectedObject(Asset.GetObjectPathString());
    }
    Result.Data->SetArrayField(TEXT("assets"), Assets);
    Result.Data->SetNumberField(TEXT("match_count"), MatchCount);
    Result.Data->SetBoolField(TEXT("truncated"), bTruncated);
    return Result.ToJson();
}
