#include "Validation/CotSValidationToolset.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Core/CotSOperationResult.h"
#include "Dom/JsonObject.h"
#include "UObject/SoftObjectPath.h"
#include UE_INLINE_GENERATED_CPP_BY_NAME(CotSValidationToolset)

FString UCotSValidationToolset::ValidateAsset(const FString& ObjectPath)
{
    const FString Op = TEXT("CotS.Validation.ValidateAsset");
    FCotSOperationResult Result = FCotSOperationResult::Succeed(Op); Result.Data = MakeShared<FJsonObject>();
    FAssetData Asset;
    const EExists Exists = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get().TryGetAssetByObjectPath(FSoftObjectPath(ObjectPath), Asset);
    if (Exists != EExists::Exists) { if (UObject* Loaded = FindObject<UObject>(nullptr, *ObjectPath)) { Asset = FAssetData(Loaded); } }
    Result.Data->SetStringField(TEXT("object_path"), ObjectPath); Result.Data->SetBoolField(TEXT("exists"), Asset.IsValid());
    if (!Asset.IsValid()) { return FCotSOperationResult::Fail(Op, TEXT("asset_not_found"), TEXT("The exact asset object path does not resolve.")).ToJson(); }
    Result.AddAffectedObject(Asset.GetObjectPathString()); Result.Data->SetStringField(TEXT("class"), Asset.AssetClassPath.ToString()); Result.Validation.Add(TEXT("asset_registry_exact_path_resolved")); return Result.ToJson();
}

FString UCotSValidationToolset::ValidateFolder(const FString& FolderPath)
{
    const FString Op = TEXT("CotS.Validation.ValidateFolder");
    if (!FolderPath.StartsWith(TEXT("/Game"))) return FCotSOperationResult::Fail(Op, TEXT("invalid_folder_scope"), TEXT("Folder validation is restricted to /Game paths.")).ToJson();
    FCotSOperationResult Result = FCotSOperationResult::Succeed(Op); Result.Data = MakeShared<FJsonObject>(); TArray<FAssetData> Assets;
    FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get().GetAssetsByPath(FName(FolderPath), Assets, true);
    Assets.Sort([](const FAssetData& A, const FAssetData& B){ return A.GetObjectPathString() < B.GetObjectPathString(); });
    TArray<TSharedPtr<FJsonValue>> Paths; for (const FAssetData& Asset : Assets) { Paths.Add(MakeShared<FJsonValueString>(Asset.GetObjectPathString())); Result.AddAffectedObject(Asset.GetObjectPathString()); }
    Result.Data->SetStringField(TEXT("folder_path"), FolderPath); Result.Data->SetNumberField(TEXT("asset_count"), Assets.Num()); Result.Data->SetArrayField(TEXT("asset_paths"), Paths); return Result.ToJson();
}
