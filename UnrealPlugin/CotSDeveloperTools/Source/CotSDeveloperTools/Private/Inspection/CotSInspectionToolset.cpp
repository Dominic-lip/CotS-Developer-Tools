#include "Inspection/CotSInspectionToolset.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Core/CotSOperationResult.h"
#include "Dom/JsonObject.h"
#include "Editor.h"
#include "Engine/Blueprint.h"
#include "EngineUtils.h"
#include "Engine/SCS_Node.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/SimpleConstructionScript.h"
#include "Animation/AnimBlueprint.h"
#include "Animation/AnimSequence.h"
#include "Animation/AnimationAsset.h"
#include "Animation/BlendSpace.h"
#include "Animation/Skeleton.h"
#include "Components/ActorComponent.h"
#include "Curves/CurveFloat.h"
#include "GameFramework/Actor.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/App.h"
#include "Misc/EngineVersion.h"
#include "Modules/ModuleManager.h"
#include "UObject/SoftObjectPath.h"
#include "UObject/UnrealType.h"

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

bool IsIdentifier(const FString& Value)
{
    if (Value.IsEmpty()) { return false; }
    for (const TCHAR Character : Value)
    {
        if (!FChar::IsAlnum(Character) && Character != TEXT('_')) { return false; }
    }
    return true;
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

FString UCotSInspectionToolset::GetCurveFloat(const FString& ObjectPath)
{
    UCurveFloat* Curve = LoadObject<UCurveFloat>(nullptr, *ObjectPath);
    if (!Curve) { return InvalidPath(TEXT("CotS.Inspection.GetCurveFloat"), ObjectPath).ToJson(); }
    FCotSOperationResult Result = FCotSOperationResult::Succeed(TEXT("CotS.Inspection.GetCurveFloat"));
    Result.AddAffectedObject(Curve->GetPathName()); Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("object_path"), Curve->GetPathName());
    Result.Data->SetBoolField(TEXT("is_event_curve"), Curve->bIsEventCurve);
    return Result.ToJson();
}

FString UCotSInspectionToolset::GetActor(const FString& ActorPath)
{
    AActor* Actor = FindObject<AActor>(nullptr, *ActorPath);
    if (!IsValid(Actor) || !Actor->GetPathName().Equals(ActorPath, ESearchCase::CaseSensitive))
    {
        FCotSOperationResult Missing = FCotSOperationResult::Succeed(TEXT("CotS.Inspection.GetActor"));
        Missing.Data = MakeShared<FJsonObject>(); Missing.Data->SetStringField(TEXT("actor_path"), ActorPath); Missing.Data->SetBoolField(TEXT("exists"), false); return Missing.ToJson();
    }
    FCotSOperationResult Result = FCotSOperationResult::Succeed(TEXT("CotS.Inspection.GetActor"));
    Result.AddAffectedObject(ActorPath); Result.Data = MakeShared<FJsonObject>(); Result.Data->SetBoolField(TEXT("exists"), true);
    Result.Data->SetStringField(TEXT("actor_path"), ActorPath); Result.Data->SetStringField(TEXT("label"), Actor->GetActorLabel()); Result.Data->SetStringField(TEXT("location"), Actor->GetActorLocation().ToString());
    TArray<TSharedPtr<FJsonValue>> Components;
    for (UActorComponent* Component : Actor->GetComponents()) { if (Component) { Components.Add(MakeShared<FJsonValueString>(Component->GetPathName())); } }
    Result.Data->SetArrayField(TEXT("components"), Components); return Result.ToJson();
}

FString UCotSInspectionToolset::ListPIEActors()
{
    constexpr const TCHAR* Operation = TEXT("CotS.Inspection.ListPIEActors");
    if (!GEditor || !GEditor->PlayWorld)
    {
        return FCotSOperationResult::Fail(Operation, TEXT("pie_not_running"), TEXT("No active Play-In-Editor world is available.")).ToJson();
    }
    TArray<AActor*> Actors;
    for (TActorIterator<AActor> It(GEditor->PlayWorld); It; ++It) { Actors.Add(*It); }
    Actors.Sort([](const AActor& Left, const AActor& Right) { return Left.GetPathName() < Right.GetPathName(); });

    FCotSOperationResult Result = FCotSOperationResult::Succeed(Operation);
    Result.Data = MakeShared<FJsonObject>();
    TArray<TSharedPtr<FJsonValue>> Items;
    for (const AActor* Actor : Actors)
    {
        TSharedRef<FJsonObject> Item = MakeShared<FJsonObject>();
        Item->SetStringField(TEXT("actor_path"), Actor->GetPathName());
        Item->SetStringField(TEXT("label"), Actor->GetActorLabel());
        Item->SetStringField(TEXT("class"), Actor->GetClass()->GetPathName());
        Items.Add(MakeShared<FJsonValueObject>(Item));
    }
    Result.Data->SetArrayField(TEXT("actors"), Items);
    return Result.ToJson();
}

FString UCotSInspectionToolset::GetPIEActorFloatProperty(const FString& ActorSelector, const FString& PropertyName)
{
    constexpr const TCHAR* Operation = TEXT("CotS.Inspection.GetPIEActorFloatProperty");
    if (!IsIdentifier(PropertyName))
    {
        return FCotSOperationResult::Fail(Operation, TEXT("invalid_property_name"), TEXT("PropertyName must contain only letters, digits, or underscores.")).ToJson();
    }
    if (!GEditor || !GEditor->PlayWorld)
    {
        return FCotSOperationResult::Fail(Operation, TEXT("pie_not_running"), TEXT("No active Play-In-Editor world is available.")).ToJson();
    }

    AActor* Match = nullptr;
    for (TActorIterator<AActor> It(GEditor->PlayWorld); It; ++It)
    {
        if (It->GetPathName() != ActorSelector && It->GetActorLabel() != ActorSelector && It->GetClass()->GetPathName() != ActorSelector && It->GetClass()->GetName() != ActorSelector) { continue; }
        if (Match)
        {
            return FCotSOperationResult::Fail(Operation, TEXT("ambiguous_actor_selector"), TEXT("More than one PIE actor matches the requested path, label, class path, or class name.")).ToJson();
        }
        Match = *It;
    }
    if (!Match)
    {
        return FCotSOperationResult::Fail(Operation, TEXT("actor_not_found"), TEXT("No PIE actor matches the requested path, label, class path, or class name.")).ToJson();
    }

    const FProperty* Property = FindFProperty<FProperty>(Match->GetClass(), FName(*PropertyName));
    if (!Property)
    {
        return FCotSOperationResult::Fail(Operation, TEXT("float_property_not_found"), TEXT("The requested property does not exist or is not a float or double real value.")).ToJson();
    }

    double Value = 0.0;
    if (const FFloatProperty* FloatProperty = CastField<FFloatProperty>(Property))
    {
        Value = FloatProperty->GetPropertyValue_InContainer(Match);
    }
    else if (const FDoubleProperty* DoubleProperty = CastField<FDoubleProperty>(Property))
    {
        Value = DoubleProperty->GetPropertyValue_InContainer(Match);
    }
    else
    {
        return FCotSOperationResult::Fail(Operation, TEXT("float_property_not_found"), TEXT("The requested property does not exist or is not a float or double real value.")).ToJson();
    }

    FCotSOperationResult Result = FCotSOperationResult::Succeed(Operation);
    Result.AddAffectedObject(Match->GetPathName());
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("actor_path"), Match->GetPathName());
    Result.Data->SetStringField(TEXT("actor_selector"), ActorSelector);
    Result.Data->SetStringField(TEXT("property_name"), PropertyName);
    Result.Data->SetNumberField(TEXT("value"), Value);
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
    if (const UAnimSequence* Sequence = Cast<UAnimSequence>(Object))
    {
        // Locomotion-validation-relevant metadata: idle/walk clips should
        // loop, jump start/land typically should not, and root motion
        // consistency matters once these feed a locomotion AnimBP.
        Result.Data->SetNumberField(TEXT("play_length_seconds"), Sequence->GetPlayLength());
        Result.Data->SetNumberField(TEXT("sampled_keys"), Sequence->GetNumberOfSampledKeys());
        Result.Data->SetBoolField(TEXT("is_looping"), Sequence->bLoop);
        Result.Data->SetBoolField(TEXT("has_root_motion"), Sequence->HasRootMotion());
    }
    if (const UBlendSpace* BlendSpace = Cast<UBlendSpace>(Object)) { Result.Data->SetNumberField(TEXT("sample_count"), BlendSpace->GetNumberOfBlendSamples()); }
    return Result.ToJson();
}

FString UCotSInspectionToolset::GetSkeletonCompatibility(const FString& ObjectPath, const FString& CandidateSkeletonPath)
{
    UObject* Object = LoadObject<UObject>(nullptr, *ObjectPath);
    if (!Object) { return InvalidPath(TEXT("CotS.Inspection.GetSkeletonCompatibility"), ObjectPath).ToJson(); }

    const USkeleton* Skeleton = nullptr;
    if (const USkeletalMesh* Mesh = Cast<USkeletalMesh>(Object)) { Skeleton = Mesh->GetSkeleton(); }
    else if (const UAnimationAsset* Animation = Cast<UAnimationAsset>(Object)) { Skeleton = Animation->GetSkeleton(); }
    else if (const UAnimBlueprint* AnimationBlueprint = Cast<UAnimBlueprint>(Object)) { Skeleton = AnimationBlueprint->TargetSkeleton; }
    else if (const USkeleton* DirectSkeleton = Cast<USkeleton>(Object)) { Skeleton = DirectSkeleton; }

    if (!Skeleton) { return FCotSOperationResult::Fail(TEXT("CotS.Inspection.GetSkeletonCompatibility"), TEXT("unsupported_animation_asset"), TEXT("The object is not a Skeleton, SkeletalMesh, AnimationAsset, or AnimBlueprint, or it has no assigned skeleton.")).ToJson(); }

    FCotSOperationResult Result = FCotSOperationResult::Succeed(TEXT("CotS.Inspection.GetSkeletonCompatibility"));
    Result.AddAffectedObject(PathOf(Skeleton));
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("skeleton"), PathOf(Skeleton));

    TArray<FAssetData> CompatibleAssets;
    Skeleton->GetCompatibleSkeletonAssets(CompatibleAssets);
    SetAssets(Result.Data, TEXT("declared_compatible_skeletons"), CompatibleAssets);

    if (!CandidateSkeletonPath.IsEmpty())
    {
        FAssetData CandidateAssetData;
        if (!GetAssetData(CandidateSkeletonPath, CandidateAssetData)) { return InvalidPath(TEXT("CotS.Inspection.GetSkeletonCompatibility"), CandidateSkeletonPath).ToJson(); }
        Result.Data->SetStringField(TEXT("candidate_skeleton"), CandidateSkeletonPath);
        Result.Data->SetBoolField(TEXT("is_compatible"), Skeleton->IsCompatibleForEditor(CandidateAssetData));
    }
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
