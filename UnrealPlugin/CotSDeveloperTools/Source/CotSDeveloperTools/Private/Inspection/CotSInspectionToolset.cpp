#include "Inspection/CotSInspectionToolset.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Core/CotSOperationResult.h"
#include "Dom/JsonObject.h"
#include "Editor.h"
#include "Engine/Blueprint.h"
#include "Engine/SCS_Node.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/SimpleConstructionScript.h"
#include "Animation/AnimBlueprint.h"
#include "Animation/AnimSequence.h"
#include "Animation/AnimationAsset.h"
#include "Animation/BlendSpace.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/App.h"
#include "Misc/EngineVersion.h"
#include "Modules/ModuleManager.h"
#include "UObject/SoftObjectPath.h"

#include UE_INLINE_GENERATED_CPP_BY_NAME(CotSInspectionToolset)

namespace
{
using namespace UE::AssetRegistry;

TArray<TSharedPtr<FJsonValue>> Strings(const TArray<FString>& Values)
{
    TArray<TSharedPtr<FJsonValue>> Json;
    for (const FString& Value : Values) { Json.Add(MakeShared<FJsonValueString>(Value)); }
    return Json;
}

FString PathOf(const UObject* Object)
{
    return Object ? Object->GetPathName() : FString();
}

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

void SortAssets(TArray<FAssetData>& Assets)
{
    Assets.Sort([](const FAssetData& A, const FAssetData& B) { return A.GetObjectPathString() < B.GetObjectPathString(); });
}

void SetAssets(TSharedPtr<FJsonObject>& Data, const TCHAR* Field, TArray<FAssetData> Assets)
{
    SortAssets(Assets);
    TArray<TSharedPtr<FJsonValue>> Json;
    for (const FAssetData& Asset : Assets) { Json.Add(MakeShared<FJsonValueObject>(AssetJson(Asset))); }
    Data->SetArrayField(Field, Json);
}

FCotSOperationResult InvalidPath(const TCHAR* Operation, const FString& ObjectPath)
{
    return FCotSOperationResult::Fail(Operation, TEXT("asset_not_found"), FString::Printf(TEXT("No asset exists at exact object path '%s'."), *ObjectPath));
}

bool GetAssetData(const FString& ObjectPath, FAssetData& OutAsset)
{
    if (FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get().TryGetAssetByObjectPath(FSoftObjectPath(ObjectPath), OutAsset) == EExists::Exists)
    {
        return true;
    }

    // Test and newly-created editor assets can be in memory before their package has a disk registry entry.
    if (UObject* LoadedObject = FindObject<UObject>(nullptr, *ObjectPath))
    {
        OutAsset = FAssetData(LoadedObject);
        return OutAsset.IsValid();
    }
    return false;
}

FString DependencyKind(const FAssetDependency& Dependency)
{
    if (Dependency.Category != EDependencyCategory::Package) { return TEXT("non_package"); }
    return EnumHasAnyFlags(Dependency.Properties, EDependencyProperty::Hard) ? TEXT("hard") : TEXT("soft");
}
}

FString UCotSInspectionToolset::GetProjectStatus()
{
    FCotSOperationResult Result = FCotSOperationResult::Succeed(TEXT("CotS.Inspection.GetProjectStatus"));
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("project_name"), FApp::GetProjectName());
    Result.Data->SetStringField(TEXT("project_path"), FPaths::GetProjectFilePath());
    Result.Data->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Result.Data->SetBoolField(TEXT("pie_running"), GEditor && GEditor->PlayWorld != nullptr);
    Result.Data->SetStringField(TEXT("current_map"), GEditor && GEditor->GetEditorWorldContext().World() ? GEditor->GetEditorWorldContext().World()->GetOutermost()->GetName() : TEXT(""));
    Result.Data->SetBoolField(TEXT("cots_plugin_enabled"), IPluginManager::Get().FindPlugin(TEXT("CotSDeveloperTools")).IsValid());
    Result.Data->SetBoolField(TEXT("cots_module_loaded"), FModuleManager::Get().IsModuleLoaded(TEXT("CotSDeveloperTools")));
    return Result.ToJson();
}

FString UCotSInspectionToolset::SearchAssets(const FString& NameQuery, const FString& PathQuery, const FString& ClassPath)
{
    FCotSOperationResult Result = FCotSOperationResult::Succeed(TEXT("CotS.Inspection.SearchAssets"));
    Result.Data = MakeShared<FJsonObject>();
    TArray<FAssetData> AllAssets;
    FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get().GetAllAssets(AllAssets);
    TArray<FAssetData> Matches;
    for (const FAssetData& Asset : AllAssets)
    {
        const bool bNameMatches = NameQuery.IsEmpty() || Asset.AssetName.ToString().Contains(NameQuery, ESearchCase::IgnoreCase);
        const bool bPathMatches = PathQuery.IsEmpty() || Asset.PackagePath.ToString().StartsWith(PathQuery, ESearchCase::IgnoreCase);
        const bool bClassMatches = ClassPath.IsEmpty() || Asset.AssetClassPath.ToString().Equals(ClassPath, ESearchCase::IgnoreCase);
        if (bNameMatches && bPathMatches && bClassMatches) { Matches.Add(Asset); Result.AddAffectedObject(Asset.GetObjectPathString()); }
    }
    SetAssets(Result.Data, TEXT("assets"), MoveTemp(Matches));
    return Result.ToJson();
}

FString UCotSInspectionToolset::GetAsset(const FString& ObjectPath)
{
    FAssetData Asset;
    if (!GetAssetData(ObjectPath, Asset))
    {
        FCotSOperationResult Missing = FCotSOperationResult::Succeed(TEXT("CotS.Inspection.GetAsset"));
        Missing.Data = MakeShared<FJsonObject>();
        Missing.Data->SetStringField(TEXT("object_path"), ObjectPath);
        Missing.Data->SetBoolField(TEXT("exists"), false);
        return Missing.ToJson();
    }
    FCotSOperationResult Result = FCotSOperationResult::Succeed(TEXT("CotS.Inspection.GetAsset"));
    Result.AddAffectedObject(Asset.GetObjectPathString());
    Result.Data = AssetJson(Asset);
    Result.Data->SetBoolField(TEXT("exists"), true);
    TSharedRef<FJsonObject> Metadata = MakeShared<FJsonObject>();
    Asset.TagsAndValues.ForEach([&Metadata](const TPair<FName, FAssetTagValueRef>& Pair) { Metadata->SetStringField(Pair.Key.ToString(), Pair.Value.AsString()); });
    Result.Data->SetObjectField(TEXT("metadata"), Metadata);
    return Result.ToJson();
}

FString UCotSInspectionToolset::GetReferences(const FString& ObjectPath, bool bReferencers)
{
    FAssetData Asset;
    if (!GetAssetData(ObjectPath, Asset)) { return InvalidPath(TEXT("CotS.Inspection.GetReferences"), ObjectPath).ToJson(); }
    FCotSOperationResult Result = FCotSOperationResult::Succeed(TEXT("CotS.Inspection.GetReferences"));
    Result.AddAffectedObject(Asset.GetObjectPathString());
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetBoolField(TEXT("referencers"), bReferencers);
    TArray<FAssetDependency> Dependencies;
    IAssetRegistry& Registry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get();
    const bool bQuerySucceeded = bReferencers ? Registry.GetReferencers(FAssetIdentifier(Asset.PackageName), Dependencies) : Registry.GetDependencies(FAssetIdentifier(Asset.PackageName), Dependencies);
    if (!bQuerySucceeded) { Result.AddWarning(TEXT("Asset Registry returned no dependency graph entry; normalized to an empty collection.")); }
    Dependencies.Sort([](const FAssetDependency& A, const FAssetDependency& B) { return A.AssetId.ToString() < B.AssetId.ToString(); });
    TArray<TSharedPtr<FJsonValue>> Json;
    for (const FAssetDependency& Dependency : Dependencies)
    {
        TSharedRef<FJsonObject> Item = MakeShared<FJsonObject>();
        Item->SetStringField(TEXT("package_path"), Dependency.AssetId.PackageName.ToString());
        Item->SetStringField(TEXT("reference_kind"), DependencyKind(Dependency));
        Item->SetBoolField(TEXT("hard"), EnumHasAnyFlags(Dependency.Properties, EDependencyProperty::Hard));
        Item->SetBoolField(TEXT("soft"), Dependency.Category == EDependencyCategory::Package && !EnumHasAnyFlags(Dependency.Properties, EDependencyProperty::Hard));
        Item->SetNumberField(TEXT("category_flags"), static_cast<uint8>(Dependency.Category));
        Item->SetNumberField(TEXT("property_flags"), static_cast<uint8>(Dependency.Properties));
        Json.Add(MakeShared<FJsonValueObject>(Item));
    }
    Result.Data->SetArrayField(bReferencers ? TEXT("referencers") : TEXT("dependencies"), Json);
    return Result.ToJson();
}

FString UCotSInspectionToolset::GetBlueprint(const FString& ObjectPath)
{
    UBlueprint* Blueprint = LoadObject<UBlueprint>(nullptr, *ObjectPath);
    if (!Blueprint) { return InvalidPath(TEXT("CotS.Inspection.GetBlueprint"), ObjectPath).ToJson(); }
    FCotSOperationResult Result = FCotSOperationResult::Succeed(TEXT("CotS.Inspection.GetBlueprint"));
    Result.AddAffectedObject(PathOf(Blueprint));
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("object_path"), PathOf(Blueprint));
    Result.Data->SetStringField(TEXT("parent_class"), PathOf(Blueprint->ParentClass));
    Result.Data->SetNumberField(TEXT("compile_status"), static_cast<uint8>(Blueprint->Status));
    Result.Data->SetBoolField(TEXT("compiled_up_to_date"), Blueprint->IsUpToDate());
    TArray<FString> Components, Variables, Functions, Graphs;
    for (const UActorComponent* Component : Blueprint->ComponentTemplates) { Components.Add(Component ? FString::Printf(TEXT("%s:%s"), *Component->GetName(), *Component->GetClass()->GetPathName()) : TEXT("")); }
    for (const FBPVariableDescription& Variable : Blueprint->NewVariables) { Variables.Add(FString::Printf(TEXT("%s:%s"), *Variable.VarName.ToString(), *Variable.VarType.PinCategory.ToString())); }
    for (const UEdGraph* Graph : Blueprint->FunctionGraphs) { if (Graph) { Functions.Add(Graph->GetName()); } }
    for (const UEdGraph* Graph : Blueprint->UbergraphPages) { if (Graph) { Graphs.Add(Graph->GetName()); } }
    Components.Sort(); Variables.Sort(); Functions.Sort(); Graphs.Sort();
    Result.Data->SetArrayField(TEXT("components"), Strings(Components));
    Result.Data->SetArrayField(TEXT("variables"), Strings(Variables));
    Result.Data->SetArrayField(TEXT("functions"), Strings(Functions));
    Result.Data->SetArrayField(TEXT("graphs"), Strings(Graphs));
    return Result.ToJson();
}

FString UCotSInspectionToolset::GetAnimationAsset(const FString& ObjectPath)
{
    UObject* Object = LoadObject<UObject>(nullptr, *ObjectPath);
    if (!Object) { return InvalidPath(TEXT("CotS.Inspection.GetAnimationAsset"), ObjectPath).ToJson(); }
    FCotSOperationResult Result = FCotSOperationResult::Succeed(TEXT("CotS.Inspection.GetAnimationAsset"));
    Result.AddAffectedObject(PathOf(Object));
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("object_path"), PathOf(Object));
    Result.Data->SetStringField(TEXT("class"), Object->GetClass()->GetPathName());
    if (const USkeletalMesh* Mesh = Cast<USkeletalMesh>(Object)) { Result.Data->SetStringField(TEXT("skeleton"), PathOf(Mesh->GetSkeleton())); }
    else if (const UAnimationAsset* Animation = Cast<UAnimationAsset>(Object)) { Result.Data->SetStringField(TEXT("skeleton"), PathOf(Animation->GetSkeleton())); }
    else if (const UAnimBlueprint* AnimationBlueprint = Cast<UAnimBlueprint>(Object)) { Result.Data->SetStringField(TEXT("skeleton"), PathOf(AnimationBlueprint->TargetSkeleton)); Result.Data->SetStringField(TEXT("preview_mesh"), PathOf(AnimationBlueprint->GetPreviewMesh())); }
    else if (Object->IsA<USkeleton>()) { Result.Data->SetStringField(TEXT("skeleton"), PathOf(Object)); }
    else { return FCotSOperationResult::Fail(TEXT("CotS.Inspection.GetAnimationAsset"), TEXT("unsupported_animation_asset"), TEXT("The object is not a Skeleton, SkeletalMesh, AnimationSequence, AnimBlueprint, or BlendSpace.")).ToJson(); }
    if (const UAnimSequence* Sequence = Cast<UAnimSequence>(Object)) { Result.Data->SetNumberField(TEXT("play_length_seconds"), Sequence->GetPlayLength()); Result.Data->SetNumberField(TEXT("sampled_keys"), Sequence->GetNumberOfSampledKeys()); }
    if (const UBlendSpace* BlendSpace = Cast<UBlendSpace>(Object)) { Result.Data->SetNumberField(TEXT("sample_count"), BlendSpace->GetNumberOfBlendSamples()); }
    return Result.ToJson();
}

FString UCotSInspectionToolset::GetPlugins(const FString& NameFilter)
{
    FCotSOperationResult Result = FCotSOperationResult::Succeed(TEXT("CotS.Inspection.GetPlugins"));
    Result.Data = MakeShared<FJsonObject>();
    TArray<TSharedRef<IPlugin>> Plugins = IPluginManager::Get().GetDiscoveredPlugins();
    Plugins.Sort([](const TSharedRef<IPlugin>& A, const TSharedRef<IPlugin>& B) { return A->GetName() < B->GetName(); });
    TArray<TSharedPtr<FJsonValue>> Json;
    for (const TSharedRef<IPlugin>& Plugin : Plugins)
    {
        if (!NameFilter.IsEmpty() && !Plugin->GetName().Contains(NameFilter, ESearchCase::IgnoreCase)) { continue; }
        TSharedRef<FJsonObject> Item = MakeShared<FJsonObject>();
        Item->SetStringField(TEXT("name"), Plugin->GetName()); Item->SetBoolField(TEXT("enabled"), Plugin->IsEnabled());
        Item->SetStringField(TEXT("version"), Plugin->GetDescriptor().VersionName); Item->SetStringField(TEXT("type"), Plugin->GetType() == EPluginType::Project ? TEXT("project") : TEXT("engine"));
        TArray<TSharedPtr<FJsonValue>> Modules;
        for (const FModuleDescriptor& Module : Plugin->GetDescriptor().Modules) { TSharedRef<FJsonObject> M = MakeShared<FJsonObject>(); M->SetStringField(TEXT("name"), Module.Name.ToString()); M->SetNumberField(TEXT("type"), static_cast<uint8>(Module.Type)); M->SetBoolField(TEXT("loaded"), FModuleManager::Get().IsModuleLoaded(Module.Name)); Modules.Add(MakeShared<FJsonValueObject>(M)); }
        Item->SetArrayField(TEXT("modules"), Modules); Json.Add(MakeShared<FJsonValueObject>(Item));
    }
    Result.Data->SetArrayField(TEXT("plugins"), Json);
    return Result.ToJson();
}

FString UCotSInspectionToolset::FindDuplicateNames(const FString& ShortName)
{
    FCotSOperationResult Result = FCotSOperationResult::Succeed(TEXT("CotS.Inspection.FindDuplicateNames"));
    Result.Data = MakeShared<FJsonObject>();
    TArray<FAssetData> Assets;
    FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get().GetAllAssets(Assets);
    TMap<FString, TArray<FAssetData>> Groups;
    for (const FAssetData& Asset : Assets) { if (ShortName.IsEmpty() || Asset.AssetName.ToString().Equals(ShortName, ESearchCase::IgnoreCase)) { Groups.FindOrAdd(Asset.AssetName.ToString()).Add(Asset); } }
    TArray<FString> Names; Groups.GetKeys(Names); Names.Sort();
    TArray<TSharedPtr<FJsonValue>> Duplicates;
    for (const FString& Name : Names) { TArray<FAssetData>& Group = Groups[Name]; if (Group.Num() > 1) { TSharedRef<FJsonObject> Item = MakeShared<FJsonObject>(); TSharedPtr<FJsonObject> ItemPtr = Item; Item->SetStringField(TEXT("asset_name"), Name); SetAssets(ItemPtr, TEXT("assets"), Group); Duplicates.Add(MakeShared<FJsonValueObject>(Item)); for (const FAssetData& Asset : Group) { Result.AddAffectedObject(Asset.GetObjectPathString()); } } }
    Result.Data->SetArrayField(TEXT("duplicates"), Duplicates);
    return Result.ToJson();
}
