#include "Mutation/CotSMutationToolset.h"

#include "AssetToolsModule.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Components/SceneComponent.h"
#include "Core/CotSEditorMutationScope.h"
#include "Core/CotSOperationResult.h"
#include "Curves/CurveFloat.h"
#include "Dom/JsonObject.h"
#include "Editor.h"
#include "EditorAssetLibrary.h"
#include "FileHelpers.h"
#include "Engine/Blueprint.h"
#include "EngineUtils.h"
#include "EngineUtils.h"
#include "Factories/CurveFactory.h"
#include "GameFramework/Actor.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "Misc/PackageName.h"
#include "Subsystems/EditorActorSubsystem.h"
#include "UObject/SoftObjectPath.h"

#include UE_INLINE_GENERATED_CPP_BY_NAME(CotSMutationToolset)

namespace
{
constexpr TCHAR DisposableRoot[] = TEXT("/Game/CotSMutationLive/");
constexpr TCHAR ProofMapRoot[] = TEXT("/Game/CotSAutonomousProof/");
constexpr TCHAR DisposableActorPrefix[] = TEXT("CotSMutation_");

void SetDetails(FCotSOperationResult& Result, bool bChanged, bool bUndoable, const FString& Note = FString())
{
    if (!Result.Data.IsValid()) { Result.Data = MakeShared<FJsonObject>(); }
    Result.Data->SetBoolField(TEXT("changed"), bChanged);
    Result.Data->SetBoolField(TEXT("transaction_undo_available"), bUndoable);
    if (!Note.IsEmpty()) { Result.Data->SetStringField(TEXT("transaction_note"), Note); }
    if (!bChanged) { Result.Status = TEXT("no_change"); }
}

bool IsExactGameObjectPath(const FString& Path)
{
    if (!Path.StartsWith(TEXT("/Game/")) || Path.Contains(TEXT(" ")) || !Path.Contains(TEXT("."))) { return false; }
    const FString PackageName = FPackageName::ObjectPathToPackageName(Path);
    const FString ObjectName = FPackageName::ObjectPathToObjectName(Path);
    return FPackageName::IsValidLongPackageName(PackageName, false) && !ObjectName.IsEmpty()
        && Path.Equals(PackageName + TEXT(".") + ObjectName, ESearchCase::CaseSensitive);
}

bool IsDisposableMapPath(const FString& Path)
{
    return Path.StartsWith(ProofMapRoot, ESearchCase::CaseSensitive)
        && FPackageName::IsValidLongPackageName(Path, false)
        && !Path.Contains(TEXT("."));
}

FString Finish(FCotSOperationResult& Result, bool bChanged, bool bUndoable, const FString& Note = FString())
{
    SetDetails(Result, bChanged, bUndoable, Note);
    return Result.ToJson();
}

FCotSOperationResult InvalidPath(const FString& Operation, const FString& Path, bool bDryRun)
{
    return FCotSOperationResult::Fail(Operation, TEXT("invalid_exact_object_path"), FString::Printf(TEXT("'%s' must be an exact /Game object path in /Game/Foo/Asset.Asset form."), *Path), bDryRun);
}

UObject* LoadExactAsset(const FString& ObjectPath)
{
    if (!IsExactGameObjectPath(ObjectPath)) { return nullptr; }
    if (UObject* Loaded = FindObject<UObject>(nullptr, *ObjectPath)) { return IsValid(Loaded) ? Loaded : nullptr; }
    FAssetData Data;
    const EExists Exists = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get().TryGetAssetByObjectPath(FSoftObjectPath(ObjectPath), Data);
    return Exists == EExists::Exists ? Data.GetAsset() : nullptr;
}

FCotSOperationResult Start(const FString& Operation, bool bDryRun, const FString& FirstPath, const FString& SecondPath = FString())
{
    FCotSOperationResult Result = FCotSOperationResult::Succeed(Operation, bDryRun);
    Result.AddAffectedObject(FirstPath); Result.AddAffectedObject(SecondPath); return Result;
}

AActor* ResolveExactActor(const FString& ActorPath)
{
    if (ActorPath.IsEmpty() || !ActorPath.Contains(TEXT("."))) { return nullptr; }
    AActor* Actor = FindObject<AActor>(nullptr, *ActorPath);
    if (!Actor && GEditor) { Actor = FindObject<AActor>(GEditor->GetEditorWorldContext().World(), *ActorPath); }
    return Actor && Actor->GetPathName().Equals(ActorPath, ESearchCase::CaseSensitive) ? Actor : nullptr;
}

FCotSOperationResult MissingActor(const FString& Operation, const FString& ActorPath, bool bDryRun)
{
    return FCotSOperationResult::Fail(Operation, TEXT("actor_not_found"), FString::Printf(TEXT("No actor resolves at exact path '%s' in the editor world."), *ActorPath), bDryRun);
}

bool IsDisposableActor(const AActor* Actor) { return Actor && Actor->GetActorLabel().StartsWith(DisposableActorPrefix, ESearchCase::CaseSensitive); }
}

FString UCotSMutationToolset::CreateCurveFloat(const FString& ObjectPath, bool bDryRun)
{
    const FString Op = TEXT("CotS.Mutation.CreateCurveFloat");
    if (!IsExactGameObjectPath(ObjectPath)) { return InvalidPath(Op, ObjectPath, bDryRun).ToJson(); }
    FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath);
    if (UObject* Existing = LoadExactAsset(ObjectPath))
    {
        if (Existing->IsA<UCurveFloat>()) { Result.Validation.Add(TEXT("already_exists_with_requested_class")); return Finish(Result, false, false, TEXT("Asset creation is package-backed and not transaction-backed.")); }
        return FCotSOperationResult::Fail(Op, TEXT("destination_collision"), TEXT("The exact path is occupied by a different asset class."), bDryRun).ToJson();
    }
    if (bDryRun) { Result.Validation.Add(TEXT("validated_creation_target")); return Finish(Result, true, false, TEXT("Asset creation is package-backed and not transaction-backed.")); }
    const FString ObjectName = FPackageName::ObjectPathToObjectName(ObjectPath);
    const FString PackagePath = FPackageName::ObjectPathToPackageName(ObjectPath).LeftChop(ObjectName.Len() + 1);
    UObject* Created = FAssetToolsModule::GetModule().Get().CreateAsset(ObjectName, PackagePath, UCurveFloat::StaticClass(), NewObject<UCurveFloatFactory>());
    if (!Created || !Created->GetPathName().Equals(ObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("create_failed"), TEXT("UE could not create the requested CurveFloat asset.")).ToJson(); }
    Result.Validation.Add(TEXT("independently inspect with CotS.Inspection.GetAsset"));
    return Finish(Result, true, false, TEXT("Asset creation is package-backed and not transaction-backed."));
}

FString UCotSMutationToolset::MoveAsset(const FString& SourceObjectPath, const FString& DestinationObjectPath, bool bDryRun)
{
    const FString Op = TEXT("CotS.Mutation.MoveAsset");
    if (!IsExactGameObjectPath(SourceObjectPath)) { return InvalidPath(Op, SourceObjectPath, bDryRun).ToJson(); }
    if (!IsExactGameObjectPath(DestinationObjectPath)) { return InvalidPath(Op, DestinationObjectPath, bDryRun).ToJson(); }
    FCotSOperationResult Result = Start(Op, bDryRun, SourceObjectPath, DestinationObjectPath);
    if (SourceObjectPath == DestinationObjectPath) { return Finish(Result, false, false, TEXT("Asset rename/move is package-backed and not transaction-backed.")); }
    if (!LoadExactAsset(SourceObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("asset_not_found"), TEXT("Source exact object path does not resolve."), bDryRun).ToJson(); }
    if (LoadExactAsset(DestinationObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("destination_collision"), TEXT("Destination exact object path already resolves."), bDryRun).ToJson(); }
    if (bDryRun) { Result.Validation.Add(TEXT("source_exists_destination_free")); return Finish(Result, true, false, TEXT("Asset rename/move is package-backed and not transaction-backed.")); }
    if (!UEditorAssetLibrary::RenameAsset(SourceObjectPath, DestinationObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("move_failed"), TEXT("UE failed to rename/move the asset.")).ToJson(); }
    Result.Validation.Add(TEXT("re-inspect destination and confirm source absence"));
    return Finish(Result, true, false, TEXT("Asset rename/move is package-backed and not transaction-backed."));
}

FString UCotSMutationToolset::DuplicateAsset(const FString& SourceObjectPath, const FString& DestinationObjectPath, bool bDryRun)
{
    const FString Op = TEXT("CotS.Mutation.DuplicateAsset");
    if (!IsExactGameObjectPath(SourceObjectPath)) { return InvalidPath(Op, SourceObjectPath, bDryRun).ToJson(); }
    if (!IsExactGameObjectPath(DestinationObjectPath)) { return InvalidPath(Op, DestinationObjectPath, bDryRun).ToJson(); }
    FCotSOperationResult Result = Start(Op, bDryRun, SourceObjectPath, DestinationObjectPath);
    if (!LoadExactAsset(SourceObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("asset_not_found"), TEXT("Source exact object path does not resolve."), bDryRun).ToJson(); }
    if (LoadExactAsset(DestinationObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("destination_collision"), TEXT("Duplicate destination already exists; duplicate is intentionally non-idempotent."), bDryRun).ToJson(); }
    if (bDryRun) { Result.Validation.Add(TEXT("source_exists_destination_free")); return Finish(Result, true, false, TEXT("Asset duplication is package-backed and not transaction-backed.")); }
    if (!UEditorAssetLibrary::DuplicateAsset(SourceObjectPath, DestinationObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("duplicate_failed"), TEXT("UE failed to duplicate the asset.")).ToJson(); }
    Result.Validation.Add(TEXT("re-inspect both exact object paths"));
    return Finish(Result, true, false, TEXT("Asset duplication is package-backed and not transaction-backed."));
}

FString UCotSMutationToolset::DeleteDisposableAsset(const FString& ObjectPath, bool bDryRun)
{
    const FString Op = TEXT("CotS.Mutation.DeleteDisposableAsset");
    if (!IsExactGameObjectPath(ObjectPath)) { return InvalidPath(Op, ObjectPath, bDryRun).ToJson(); }
    if (!ObjectPath.StartsWith(DisposableRoot, ESearchCase::CaseSensitive)) { return FCotSOperationResult::Fail(Op, TEXT("outside_disposable_scope"), TEXT("Deletion is restricted to /Game/CotSMutationLive/."), bDryRun).ToJson(); }
    FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath);
    if (!LoadExactAsset(ObjectPath)) { Result.Validation.Add(TEXT("already_absent")); return Finish(Result, false, false, TEXT("Force-delete can clear Undo history; it is not transaction-backed.")); }
    if (bDryRun) { Result.Validation.Add(TEXT("validated_disposable_delete")); return Finish(Result, true, false, TEXT("Force-delete can clear Undo history; it is not transaction-backed.")); }
    if (!UEditorAssetLibrary::DeleteAsset(ObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("delete_failed"), TEXT("UE failed to delete the disposable asset.")).ToJson(); }
    Result.Validation.Add(TEXT("re-inspect exact path and confirm absence")); return Finish(Result, true, false, TEXT("Force-delete can clear Undo history; it is not transaction-backed."));
}

FString UCotSMutationToolset::SaveAsset(const FString& ObjectPath, bool bDryRun)
{
    const FString Op = TEXT("CotS.Mutation.SaveAsset"); if (!IsExactGameObjectPath(ObjectPath)) { return InvalidPath(Op, ObjectPath, bDryRun).ToJson(); }
    FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath); if (!LoadExactAsset(ObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("asset_not_found"), TEXT("Exact object path does not resolve."), bDryRun).ToJson(); }
    if (bDryRun) { Result.Validation.Add(TEXT("asset_exists")); return Finish(Result, true, false, TEXT("Saving packages is not an undoable editor transaction.")); }
    if (!UEditorAssetLibrary::SaveAsset(ObjectPath, false)) { return FCotSOperationResult::Fail(Op, TEXT("save_failed"), TEXT("UE failed to save the asset package.")).ToJson(); }
    return Finish(Result, true, false, TEXT("Saving packages is not an undoable editor transaction."));
}

FString UCotSMutationToolset::SetCurveEventFlag(const FString& ObjectPath, bool bIsEventCurve, bool bDryRun)
{
    const FString Op = TEXT("CotS.Mutation.SetCurveEventFlag"); if (!IsExactGameObjectPath(ObjectPath)) { return InvalidPath(Op, ObjectPath, bDryRun).ToJson(); }
    UCurveFloat* Curve = Cast<UCurveFloat>(LoadExactAsset(ObjectPath)); if (!Curve) { return FCotSOperationResult::Fail(Op, TEXT("unsupported_property_target"), TEXT("Only UCurveFloat.bIsEventCurve is supported by this typed property operation."), bDryRun).ToJson(); }
    FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath); SetDetails(Result, Curve->bIsEventCurve != bIsEventCurve, true); Result.Data->SetBoolField(TEXT("before"), Curve->bIsEventCurve); Result.Data->SetBoolField(TEXT("after"), bIsEventCurve);
    if (Curve->bIsEventCurve == bIsEventCurve || bDryRun) { if (bDryRun) { Result.Validation.Add(TEXT("typed_boolean_value_validated")); } return Result.ToJson(); }
    FCotSEditorMutationScope Scope(FText::FromString(TEXT("CotS Set Curve Event Flag")), Curve, false); Curve->Modify(); Curve->bIsEventCurve = bIsEventCurve; Curve->MarkPackageDirty(); Result.Validation.Add(TEXT("re-inspect asset after save")); return Result.ToJson();
}

FString UCotSMutationToolset::CompileBlueprint(const FString& ObjectPath, bool bDryRun)
{
    const FString Op = TEXT("CotS.Mutation.CompileBlueprint"); if (!IsExactGameObjectPath(ObjectPath)) { return InvalidPath(Op, ObjectPath, bDryRun).ToJson(); }
    UBlueprint* Blueprint = Cast<UBlueprint>(LoadExactAsset(ObjectPath)); if (!Blueprint) { return FCotSOperationResult::Fail(Op, TEXT("unsupported_blueprint_target"), TEXT("Exact path does not resolve to UBlueprint."), bDryRun).ToJson(); }
    FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath); if (bDryRun) { Result.Validation.Add(TEXT("blueprint_target_validated")); return Finish(Result, false, false, TEXT("Blueprint compilation is not represented as a user undo transaction.")); }
    FKismetEditorUtilities::CompileBlueprint(Blueprint); Result.Data = MakeShared<FJsonObject>(); Result.Data->SetNumberField(TEXT("compile_status"), static_cast<uint8>(Blueprint->Status)); Result.Data->SetBoolField(TEXT("compiled_up_to_date"), Blueprint->IsUpToDate()); Result.Data->SetBoolField(TEXT("transaction_undo_available"), false); Result.Validation.Add(TEXT("re-inspect with CotS.Inspection.GetBlueprint")); return Result.ToJson();
}

FString UCotSMutationToolset::CreateDisposableMap(const FString& MapAssetPath, bool bDryRun)
{
    const FString Op = TEXT("CotS.Mutation.CreateDisposableMap");
    if (!IsDisposableMapPath(MapAssetPath))
    {
        return FCotSOperationResult::Fail(Op, TEXT("invalid_disposable_map_path"), TEXT("MapAssetPath must be a /Game/CotSAutonomousProof/ package path without an object suffix."), bDryRun).ToJson();
    }
    FCotSOperationResult Result = Start(Op, bDryRun, MapAssetPath);
    if (FPackageName::DoesPackageExist(MapAssetPath))
    {
        return FCotSOperationResult::Fail(Op, TEXT("destination_collision"), TEXT("A map package already exists at the requested path."), bDryRun).ToJson();
    }
    if (bDryRun) { Result.Validation.Add(TEXT("validated_disposable_map_target")); return Finish(Result, true, false, TEXT("Map creation and saving are package-backed and not transaction-backed.")); }
    UWorld* World = UEditorLoadingAndSavingUtils::NewBlankMap(false);
    if (!World || !UEditorLoadingAndSavingUtils::SaveMap(World, MapAssetPath))
    {
        return FCotSOperationResult::Fail(Op, TEXT("map_create_failed"), TEXT("UE could not create and save the disposable map.")).ToJson();
    }
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("map_path"), MapAssetPath);
    Result.Data->SetStringField(TEXT("world_path"), World->GetPathName());
    Result.Validation.Add(TEXT("load the exact map path before placing proof actors"));
    return Finish(Result, true, false, TEXT("Map creation and saving are package-backed and not transaction-backed."));
}

FString UCotSMutationToolset::CreateDisposableActor(const FString& ActorLabel, double X, double Y, double Z, bool bDryRun)
{
    const FString Op = TEXT("CotS.Mutation.CreateDisposableActor");
    if (!ActorLabel.StartsWith(DisposableActorPrefix) || ActorLabel.Contains(TEXT("."))) { return FCotSOperationResult::Fail(Op, TEXT("invalid_disposable_actor_label"), TEXT("Actor label must begin CotSMutation_ and contain no dot."), bDryRun).ToJson(); }
    if (!GEditor || !GEditor->GetEditorWorldContext().World()) { return FCotSOperationResult::Fail(Op, TEXT("editor_world_unavailable"), TEXT("No editor world is available."), bDryRun).ToJson(); }
    FCotSOperationResult Result = FCotSOperationResult::Succeed(Op, bDryRun);
    for (TActorIterator<AActor> It(GEditor->GetEditorWorldContext().World()); It; ++It)
    {
        if (It->GetActorLabel() == ActorLabel)
        {
            const FString ExistingActorPath = It->GetPathName();
            Result.AddAffectedObject(ExistingActorPath);
            Result.Data = MakeShared<FJsonObject>();
            Result.Data->SetStringField(TEXT("actor_path"), ExistingActorPath);
            Result.Validation.Add(TEXT("already_exists_with_requested_label"));
            return Finish(Result, false, true);
        }
    }
    if (bDryRun)
    {
        Result.Data = MakeShared<FJsonObject>();
        // Actor object paths are assigned by UE during spawn, so do not fabricate one for a preview.
        Result.Data->SetStringField(TEXT("preview_actor_label"), ActorLabel);
        Result.Data->SetStringField(TEXT("preview_world_path"), GEditor->GetEditorWorldContext().World()->GetPathName());
        Result.Validation.Add(TEXT("editor_world_available"));
        return Finish(Result, true, true);
    }
    FCotSEditorMutationScope Scope(FText::FromString(TEXT("CotS Create Disposable Actor")), nullptr, false);
    AActor* Actor = GEditor->GetEditorSubsystem<UEditorActorSubsystem>()->SpawnActorFromClass(AActor::StaticClass(), FVector(X, Y, Z));
    if (!Actor) { return FCotSOperationResult::Fail(Op, TEXT("actor_create_failed"), TEXT("UE could not create the disposable actor.")).ToJson(); }
    Actor->Modify(); Actor->SetActorLabel(ActorLabel);
    const FString CreatedActorPath = Actor->GetPathName();
    Result.AddAffectedObject(CreatedActorPath);
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("actor_path"), CreatedActorPath);
    Result.Validation.Add(TEXT("re-inspect actor by exact returned path"));
    return Finish(Result, true, true);
}

FString UCotSMutationToolset::SetActorLocation(const FString& ActorPath, double X, double Y, double Z, bool bDryRun)
{
    const FString Op = TEXT("CotS.Mutation.SetActorLocation"); AActor* Actor = ResolveExactActor(ActorPath); if (!Actor) { return MissingActor(Op, ActorPath, bDryRun).ToJson(); }
    if (!FMath::IsFinite(X) || !FMath::IsFinite(Y) || !FMath::IsFinite(Z)) { return FCotSOperationResult::Fail(Op, TEXT("invalid_property_value"), TEXT("Actor location coordinates must be finite numeric values."), bDryRun).ToJson(); }
    FCotSOperationResult Result = Start(Op, bDryRun, ActorPath); const FVector NewLocation(X, Y, Z); Result.Data = MakeShared<FJsonObject>(); Result.Data->SetStringField(TEXT("actor_path"), ActorPath); Result.Data->SetStringField(TEXT("before"), Actor->GetActorLocation().ToString()); Result.Data->SetStringField(TEXT("after"), NewLocation.ToString()); Result.Data->SetBoolField(TEXT("transaction_undo_available"), true);
    if (Actor->GetActorLocation().Equals(NewLocation)) { Result.Status = TEXT("no_change"); return Result.ToJson(); }
    if (bDryRun) { return Result.ToJson(); }
    FCotSEditorMutationScope Scope(FText::FromString(TEXT("CotS Set Actor Location")), Actor, false); Actor->Modify(); Actor->SetActorLocation(NewLocation); return Result.ToJson();
}

FString UCotSMutationToolset::AddSceneComponent(const FString& ActorPath, const FString& ComponentName, bool bDryRun)
{
    const FString Op = TEXT("CotS.Mutation.AddSceneComponent"); AActor* Actor = ResolveExactActor(ActorPath); if (!Actor) { return MissingActor(Op, ActorPath, bDryRun).ToJson(); }
    if (!ComponentName.StartsWith(DisposableActorPrefix) || ComponentName.Contains(TEXT("."))) { return FCotSOperationResult::Fail(Op, TEXT("invalid_component_name"), TEXT("Component names must begin CotSMutation_ and contain no dot."), bDryRun).ToJson(); }
    FCotSOperationResult Result = Start(Op, bDryRun, ActorPath);
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("actor_path"), ActorPath);
    for (UActorComponent* Component : Actor->GetComponents())
    {
        if (Component && Component->GetName() == ComponentName)
        {
            const FString ExistingComponentPath = Component->GetPathName();
            Result.AddAffectedObject(ExistingComponentPath);
            Result.Data->SetStringField(TEXT("component_path"), ExistingComponentPath);
            return Finish(Result, false, true);
        }
    }
    if (bDryRun) { Result.Data->SetStringField(TEXT("preview_component_name"), ComponentName); return Finish(Result, true, true); }
    FCotSEditorMutationScope Scope(FText::FromString(TEXT("CotS Add Scene Component")), Actor, false); Actor->Modify(); USceneComponent* Component = NewObject<USceneComponent>(Actor, *ComponentName, RF_Transactional); Actor->AddInstanceComponent(Component); Component->OnComponentCreated(); Component->RegisterComponent(); const FString CreatedComponentPath = Component->GetPathName(); Result.AddAffectedObject(CreatedComponentPath); Result.Data->SetStringField(TEXT("component_path"), CreatedComponentPath); return Finish(Result, true, true);
}

FString UCotSMutationToolset::RemoveSceneComponent(const FString& ActorPath, const FString& ComponentName, bool bDryRun)
{
    const FString Op = TEXT("CotS.Mutation.RemoveSceneComponent"); AActor* Actor = ResolveExactActor(ActorPath); if (!Actor) { return MissingActor(Op, ActorPath, bDryRun).ToJson(); }
    FCotSOperationResult Result = Start(Op, bDryRun, ActorPath); Result.Data = MakeShared<FJsonObject>(); Result.Data->SetStringField(TEXT("actor_path"), ActorPath); USceneComponent* Target = nullptr;
    for (UActorComponent* Component : Actor->GetComponents()) { if (Component && Component->GetName() == ComponentName) { Target = Cast<USceneComponent>(Component); break; } }
    if (!Target) { Result.Validation.Add(TEXT("already_absent")); return Finish(Result, false, true); }
    const FString ComponentPath = Target->GetPathName(); Result.AddAffectedObject(ComponentPath); Result.Data->SetStringField(TEXT("component_path"), ComponentPath); if (bDryRun) { return Finish(Result, true, true); }
    FCotSEditorMutationScope Scope(FText::FromString(TEXT("CotS Remove Scene Component")), Actor, false); Actor->Modify(); Target->Modify(); Target->DestroyComponent(); return Finish(Result, true, true);
}

FString UCotSMutationToolset::DeleteDisposableActor(const FString& ActorPath, bool bDryRun)
{
    const FString Op = TEXT("CotS.Mutation.DeleteDisposableActor"); AActor* Actor = ResolveExactActor(ActorPath);
    if (!Actor) { FCotSOperationResult Result = Start(Op, bDryRun, ActorPath); Result.Validation.Add(TEXT("already_absent")); return Finish(Result, false, true); }
    if (!IsDisposableActor(Actor)) { return FCotSOperationResult::Fail(Op, TEXT("outside_disposable_scope"), TEXT("Actor deletion is restricted to actors labelled CotSMutation_."), bDryRun).ToJson(); }
    FCotSOperationResult Result = Start(Op, bDryRun, ActorPath); Result.Data = MakeShared<FJsonObject>(); Result.Data->SetStringField(TEXT("actor_path"), ActorPath); if (bDryRun) { return Finish(Result, true, true); }
    FCotSEditorMutationScope Scope(FText::FromString(TEXT("CotS Delete Disposable Actor")), Actor, false); Actor->Modify();
    if (!GEditor->GetEditorSubsystem<UEditorActorSubsystem>()->DestroyActor(Actor)) { return FCotSOperationResult::Fail(Op, TEXT("actor_delete_failed"), TEXT("UE failed to delete the actor.")).ToJson(); }
    Result.Validation.Add(TEXT("re-inspect exact actor path and confirm absence")); return Finish(Result, true, true);
}
