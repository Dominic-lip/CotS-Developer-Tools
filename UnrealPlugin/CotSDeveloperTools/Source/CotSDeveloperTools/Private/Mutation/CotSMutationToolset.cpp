#include "Mutation/CotSMutationToolset.h"

#include "AssetToolsModule.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Animation/AnimBlueprint.h"
#include "Animation/AnimInstance.h"
#include "Animation/AnimSequence.h"
#include "AnimationGraph.h"
#include "AnimGraphNode_StateMachine.h"
#include "AnimGraphNode_SequencePlayer.h"
#include "AnimGraphNode_StateResult.h"
#include "AnimGraphNode_Root.h"
#include "AnimGraphNode_TransitionResult.h"
#include "AnimStateEntryNode.h"
#include "AnimStateNode.h"
#include "AnimStateTransitionNode.h"
#include "AnimationTransitionGraph.h"
#include "AnimationStateMachineSchema.h"
#include "Animation/BlendSpace.h"
#include "Components/SceneComponent.h"
#include "Core/CotSEditorMutationScope.h"
#include "Core/CotSOperationResult.h"
#include "Curves/CurveFloat.h"
#include "Dom/JsonObject.h"
#include "Editor.h"
#include "EditorAssetLibrary.h"
#include "EdGraphUtilities.h"
#include "FileHelpers.h"
#include "Engine/Blueprint.h"
#include "Engine/SkeletalMesh.h"
#include "EngineUtils.h"
#include "EngineUtils.h"
#include "Factories/CurveFactory.h"
#include "Factories/BlendSpaceFactoryNew.h"
#include "Factories/AnimBlueprintFactory.h"
#include "GameFramework/Actor.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "Misc/PackageName.h"
#include "RetargetEditor/IKRetargetBatchOperation.h"
#include "RetargetEditor/IKRetargeterController.h"
#include "RetargetEditor/IKRetargetFactory.h"
#include "Retargeter/IKRetargeter.h"
#include "Rig/IKRigDefinition.h"
#include "RigEditor/IKRigController.h"
#include "RigEditor/IKRigDefinitionFactory.h"
#include "Subsystems/EditorActorSubsystem.h"
#include "UObject/SoftObjectPath.h"
#include "UObject/UnrealType.h"

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

bool IsExactObjectPath(const FString& Path)
{
    if (!Path.StartsWith(TEXT("/")) || Path.Contains(TEXT(" ")) || !Path.Contains(TEXT("."))) { return false; }
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

bool IsDisposableRetargetTargetPath(const FString& Path)
{
    return Path.StartsWith(DisposableRoot, ESearchCase::CaseSensitive)
        && FPackageName::IsValidLongPackageName(Path, false)
        && !Path.Contains(TEXT("."));
}

bool IsDisposableAssetPath(const FString& Path)
{
    return IsExactGameObjectPath(Path) && Path.StartsWith(DisposableRoot, ESearchCase::CaseSensitive);
}

bool ConfigureLocomotionBlendSpace(UBlendSpace* BlendSpace)
{
    FStructProperty* ParametersProperty = FindFProperty<FStructProperty>(UBlendSpace::StaticClass(), TEXT("BlendParameters"));
    if (!ParametersProperty || ParametersProperty->Struct != FBlendParameter::StaticStruct() || ParametersProperty->ArrayDim != 3) { return false; }

    const FName AxisNames[] = { TEXT("Speed"), TEXT("Direction") };
    const float AxisMins[] = { 0.0f, -180.0f };
    const float AxisMaxs[] = { 600.0f, 180.0f };
    const int32 AxisGrids[] = { 6, 8 };
    BlendSpace->PreEditChange(ParametersProperty);
    for (int32 Index = 0; Index < 2; ++Index)
    {
        FBlendParameter* Parameter = ParametersProperty->ContainerPtrToValuePtr<FBlendParameter>(BlendSpace, Index);
        if (!Parameter) { return false; }
        Parameter->DisplayName = AxisNames[Index].ToString();
        Parameter->Min = AxisMins[Index];
        Parameter->Max = AxisMaxs[Index];
        Parameter->GridNum = AxisGrids[Index];
        Parameter->bSnapToGrid = false;
        Parameter->bWrapInput = false;
    }
    BlendSpace->PostEditChange();
    BlendSpace->ValidateSampleData();
    return true;
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

UObject* LoadExactEditorAsset(const FString& ObjectPath)
{
    if (!IsExactObjectPath(ObjectPath)) { return nullptr; }
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

FString UCotSMutationToolset::BatchRetargetAnimationAssets(const TArray<FString>& SourceAssetPaths, const FString& RetargeterPath, const FString& TargetPath, bool bDryRun)
{
    constexpr const TCHAR* Op = TEXT("CotS.Mutation.BatchRetargetAnimationAssets");
    if (SourceAssetPaths.IsEmpty()) { return FCotSOperationResult::Fail(Op, TEXT("source_assets_required"), TEXT("At least one exact animation asset path is required."), bDryRun).ToJson(); }
    if (!IsExactGameObjectPath(RetargeterPath)) { return InvalidPath(Op, RetargeterPath, bDryRun).ToJson(); }
    if (!IsDisposableRetargetTargetPath(TargetPath))
    {
        return FCotSOperationResult::Fail(Op, TEXT("invalid_disposable_target_path"), TEXT("TargetPath must be a package path under /Game/CotSMutationLive/ without an object suffix."), bDryRun).ToJson();
    }

    UIKRetargeter* Retargeter = Cast<UIKRetargeter>(LoadExactAsset(RetargeterPath));
    if (!Retargeter) { return FCotSOperationResult::Fail(Op, TEXT("retargeter_not_found"), TEXT("RetargeterPath must resolve to a UIKRetargeter asset."), bDryRun).ToJson(); }
    USkeletalMesh* SourceMesh = Retargeter->GetPreviewMesh(ERetargetSourceOrTarget::Source);
    USkeletalMesh* TargetMesh = Retargeter->GetPreviewMesh(ERetargetSourceOrTarget::Target);
    if (!SourceMesh || !TargetMesh || SourceMesh == TargetMesh)
    {
        return FCotSOperationResult::Fail(Op, TEXT("retargeter_not_configured"), TEXT("The retargeter must provide distinct source and target preview meshes."), bDryRun).ToJson();
    }

    FCotSOperationResult Result = Start(Op, bDryRun, RetargeterPath, TargetPath);
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("retargeter_path"), RetargeterPath);
    Result.Data->SetStringField(TEXT("target_path"), TargetPath);
    Result.Data->SetStringField(TEXT("source_mesh"), SourceMesh->GetPathName());
    Result.Data->SetStringField(TEXT("target_mesh"), TargetMesh->GetPathName());

    TSet<FString> SeenPaths;
    TArray<FAssetData> AssetsToRetarget;
    for (const FString& SourceAssetPath : SourceAssetPaths)
    {
        if (!IsExactGameObjectPath(SourceAssetPath)) { return InvalidPath(Op, SourceAssetPath, bDryRun).ToJson(); }
        if (SeenPaths.Contains(SourceAssetPath)) { return FCotSOperationResult::Fail(Op, TEXT("duplicate_source_asset"), TEXT("Each source animation asset path must be unique."), bDryRun).ToJson(); }
        SeenPaths.Add(SourceAssetPath);
        UAnimationAsset* Animation = Cast<UAnimationAsset>(LoadExactAsset(SourceAssetPath));
        if (!Animation) { return FCotSOperationResult::Fail(Op, TEXT("unsupported_source_asset"), TEXT("Every source path must resolve to a UAnimationAsset."), bDryRun).ToJson(); }
        if (Animation->GetSkeleton() != SourceMesh->GetSkeleton())
        {
            return FCotSOperationResult::Fail(Op, TEXT("source_skeleton_mismatch"), TEXT("Every source animation asset must use the source preview mesh's exact skeleton."), bDryRun).ToJson();
        }
        AssetsToRetarget.Add(FAssetData(Animation));
        Result.AddAffectedObject(SourceAssetPath);
    }
    Result.Data->SetNumberField(TEXT("source_asset_count"), AssetsToRetarget.Num());
    Result.Validation.Add(TEXT("retargeter_source_and_target_meshes_validated"));
    Result.Validation.Add(TEXT("source_assets_use_exact_source_skeleton"));
    Result.Validation.Add(TEXT("output_restricted_to_disposable_scope"));
    if (bDryRun) { return Finish(Result, true, false, TEXT("Native batch retarget is package-backed and not transaction-backed.")); }

    FIKRetargetBatchOperationInputs Inputs;
    Inputs.AssetsToRetarget = MoveTemp(AssetsToRetarget);
    Inputs.SourceMesh = SourceMesh;
    Inputs.TargetMesh = TargetMesh;
    Inputs.IKRetargetAsset = Retargeter;
    Inputs.TargetPath = TargetPath;
    Inputs.bUseSourcePath = false;
    Inputs.bOverwriteExistingFiles = false;
    const TArray<FAssetData> Outputs = UIKRetargetBatchOperation::RunBatchRetarget(Inputs);
    if (Outputs.IsEmpty()) { return FCotSOperationResult::Fail(Op, TEXT("retarget_failed"), TEXT("UE's native batch retarget operation did not create any output assets.")).ToJson(); }

    TArray<TSharedPtr<FJsonValue>> OutputPaths;
    for (const FAssetData& Output : Outputs)
    {
        const FString OutputPath = Output.GetObjectPathString();
        Result.AddAffectedObject(OutputPath);
        OutputPaths.Add(MakeShared<FJsonValueString>(OutputPath));
    }
    Result.Data->SetArrayField(TEXT("output_assets"), OutputPaths);
    Result.Validation.Add(TEXT("re-inspect every output asset and save only after review"));
    return Finish(Result, true, false, TEXT("Native batch retarget is package-backed and not transaction-backed."));
}

FString UCotSMutationToolset::CreateDisposableIKRig(const FString& ObjectPath, const FString& SkeletalMeshPath, bool bDryRun)
{
    constexpr const TCHAR* Op = TEXT("CotS.Mutation.CreateDisposableIKRig");
    if (!IsDisposableAssetPath(ObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("outside_disposable_scope"), TEXT("IK Rig creation is restricted to /Game/CotSMutationLive/ exact object paths."), bDryRun).ToJson(); }
    USkeletalMesh* Mesh = Cast<USkeletalMesh>(LoadExactEditorAsset(SkeletalMeshPath));
    if (!Mesh) { return FCotSOperationResult::Fail(Op, TEXT("skeletal_mesh_not_found"), TEXT("SkeletalMeshPath must resolve to an exact USkeletalMesh asset."), bDryRun).ToJson(); }

    FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath, SkeletalMeshPath);
    if (UObject* Existing = LoadExactAsset(ObjectPath))
    {
        UIKRigDefinition* ExistingRig = Cast<UIKRigDefinition>(Existing);
        UIKRigController* ExistingController = ExistingRig ? UIKRigController::GetController(ExistingRig) : nullptr;
        if (!ExistingController || ExistingController->GetSkeletalMesh() != Mesh)
        {
            return FCotSOperationResult::Fail(Op, TEXT("destination_collision"), TEXT("The destination is occupied by an IK Rig configured for a different mesh or by another asset class."), bDryRun).ToJson();
        }
        Result.Validation.Add(TEXT("already_exists_with_requested_mesh"));
        return Finish(Result, false, false, TEXT("IK Rig assets are package-backed and not transaction-backed."));
    }
    if (bDryRun) { Result.Validation.Add(TEXT("validated_disposable_destination_and_mesh")); return Finish(Result, true, false, TEXT("IK Rig assets are package-backed and not transaction-backed.")); }

    const FString ObjectName = FPackageName::ObjectPathToObjectName(ObjectPath);
    const FString PackagePath = FPackageName::ObjectPathToPackageName(ObjectPath).LeftChop(ObjectName.Len() + 1);
    UIKRigDefinition* Rig = UIKRigDefinitionFactory::CreateNewIKRigAsset(PackagePath, ObjectName);
    UIKRigController* Controller = Rig ? UIKRigController::GetController(Rig) : nullptr;
    if (!Controller || !Controller->SetSkeletalMesh(Mesh)) { return FCotSOperationResult::Fail(Op, TEXT("ik_rig_configuration_failed"), TEXT("UE could not initialize the new IK Rig with the requested Skeletal Mesh.")).ToJson(); }
    const bool bAutoDefinitionApplied = Controller->ApplyAutoGeneratedRetargetDefinition();
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("skeletal_mesh"), Mesh->GetPathName());
    Result.Data->SetBoolField(TEXT("auto_retarget_definition_applied"), bAutoDefinitionApplied);
    Result.Data->SetNumberField(TEXT("retarget_chain_count"), Controller->GetRetargetChains().Num());
    Result.Validation.Add(TEXT("created_with_ue_ik_rig_factory_and_controller"));
    Result.Validation.Add(TEXT("reinspect_with_CotS.Inspection.GetIKRetargeter_after_retargeter_creation"));
    return Finish(Result, true, false, TEXT("IK Rig assets are package-backed and not transaction-backed."));
}

FString UCotSMutationToolset::CreateDisposableIKRetargeter(const FString& ObjectPath, const FString& SourceIKRigPath, const FString& TargetIKRigPath, bool bDryRun)
{
    constexpr const TCHAR* Op = TEXT("CotS.Mutation.CreateDisposableIKRetargeter");
    if (!IsDisposableAssetPath(ObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("outside_disposable_scope"), TEXT("IK Retargeter creation is restricted to /Game/CotSMutationLive/ exact object paths."), bDryRun).ToJson(); }
    UIKRigDefinition* SourceRig = Cast<UIKRigDefinition>(LoadExactEditorAsset(SourceIKRigPath));
    UIKRigDefinition* TargetRig = Cast<UIKRigDefinition>(LoadExactEditorAsset(TargetIKRigPath));
    UIKRigController* SourceController = SourceRig ? UIKRigController::GetController(SourceRig) : nullptr;
    UIKRigController* TargetController = TargetRig ? UIKRigController::GetController(TargetRig) : nullptr;
    USkeletalMesh* SourceMesh = SourceController ? SourceController->GetSkeletalMesh() : nullptr;
    USkeletalMesh* TargetMesh = TargetController ? TargetController->GetSkeletalMesh() : nullptr;
    if (!SourceRig || !TargetRig || !SourceMesh || !TargetMesh) { return FCotSOperationResult::Fail(Op, TEXT("ik_rig_not_configured"), TEXT("Both exact IK Rig paths must resolve and provide a Skeletal Mesh."), bDryRun).ToJson(); }
    if (SourceRig == TargetRig || SourceMesh == TargetMesh) { return FCotSOperationResult::Fail(Op, TEXT("source_target_not_distinct"), TEXT("Source and target IK Rigs must use distinct assets and distinct Skeletal Meshes."), bDryRun).ToJson(); }

    FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath, SourceIKRigPath);
    Result.AddAffectedObject(TargetIKRigPath);
    if (UObject* Existing = LoadExactAsset(ObjectPath))
    {
        UIKRetargeter* ExistingRetargeter = Cast<UIKRetargeter>(Existing);
        if (!ExistingRetargeter || ExistingRetargeter->GetIKRig(ERetargetSourceOrTarget::Source) != SourceRig || ExistingRetargeter->GetIKRig(ERetargetSourceOrTarget::Target) != TargetRig)
        {
            return FCotSOperationResult::Fail(Op, TEXT("destination_collision"), TEXT("The destination is occupied by a differently configured IK Retargeter or another asset class."), bDryRun).ToJson();
        }
        Result.Validation.Add(TEXT("already_exists_with_requested_distinct_rigs"));
        return Finish(Result, false, false, TEXT("IK Retargeter assets are package-backed and not transaction-backed."));
    }
    if (bDryRun) { Result.Validation.Add(TEXT("validated_disposable_destination_and_distinct_rigs")); return Finish(Result, true, false, TEXT("IK Retargeter assets are package-backed and not transaction-backed.")); }

    const FString ObjectName = FPackageName::ObjectPathToObjectName(ObjectPath);
    const FString PackagePath = FPackageName::ObjectPathToPackageName(ObjectPath).LeftChop(ObjectName.Len() + 1);
    UIKRetargeter* Retargeter = Cast<UIKRetargeter>(FAssetToolsModule::GetModule().Get().CreateAsset(ObjectName, PackagePath, UIKRetargeter::StaticClass(), NewObject<UIKRetargetFactory>()));
    UIKRetargeterController* Controller = Retargeter ? UIKRetargeterController::GetController(Retargeter) : nullptr;
    if (!Controller) { return FCotSOperationResult::Fail(Op, TEXT("retargeter_creation_failed"), TEXT("UE could not create a controller for the new IK Retargeter.")).ToJson(); }
    Controller->SetIKRig(ERetargetSourceOrTarget::Source, SourceRig);
    Controller->SetIKRig(ERetargetSourceOrTarget::Target, TargetRig);
    Controller->SetPreviewMesh(ERetargetSourceOrTarget::Source, SourceMesh);
    Controller->SetPreviewMesh(ERetargetSourceOrTarget::Target, TargetMesh);
    if (Retargeter->GetIKRig(ERetargetSourceOrTarget::Source) != SourceRig || Retargeter->GetIKRig(ERetargetSourceOrTarget::Target) != TargetRig)
    {
        return FCotSOperationResult::Fail(Op, TEXT("retargeter_configuration_failed"), TEXT("UE did not retain both requested IK Rig assignments.")).ToJson();
    }
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("source_mesh"), SourceMesh->GetPathName());
    Result.Data->SetStringField(TEXT("target_mesh"), TargetMesh->GetPathName());
    Result.Validation.Add(TEXT("created_with_ue_ik_retargeter_factory_and_controller"));
    Result.Validation.Add(TEXT("source_and_target_meshes_are_distinct"));
    Result.Validation.Add(TEXT("run_BatchRetargetAnimationAssets_then_reinspect_outputs"));
    return Finish(Result, true, false, TEXT("IK Retargeter assets are package-backed and not transaction-backed."));
}

FString UCotSMutationToolset::CreateDisposableLocomotionBlendSpace(const FString& ObjectPath, const FString& SkeletonPath, const FString& PreviewMeshPath, bool bDryRun)
{
    constexpr const TCHAR* Op = TEXT("CotS.Mutation.CreateDisposableLocomotionBlendSpace");
    if (!IsDisposableAssetPath(ObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("outside_disposable_scope"), TEXT("Blend Space creation is restricted to /Game/CotSMutationLive/ exact object paths."), bDryRun).ToJson(); }
    USkeleton* Skeleton = Cast<USkeleton>(LoadExactAsset(SkeletonPath));
    USkeletalMesh* PreviewMesh = PreviewMeshPath.IsEmpty() ? (Skeleton ? Skeleton->GetPreviewMesh(true) : nullptr) : Cast<USkeletalMesh>(LoadExactAsset(PreviewMeshPath));
    if (!Skeleton || !PreviewMesh || PreviewMesh->GetSkeleton() != Skeleton)
    {
        return FCotSOperationResult::Fail(Op, TEXT("invalid_skeleton_or_preview_mesh"), TEXT("SkeletonPath must resolve; PreviewMeshPath must resolve, or its empty value must let UE resolve the Skeleton's preview mesh; the mesh must use that exact skeleton."), bDryRun).ToJson();
    }
    FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath, SkeletonPath);
    Result.AddAffectedObject(PreviewMesh->GetPathName());
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("object_path"), ObjectPath);
    Result.Data->SetStringField(TEXT("skeleton"), SkeletonPath);
    Result.Data->SetStringField(TEXT("preview_mesh"), PreviewMesh->GetPathName());
    Result.Data->SetStringField(TEXT("speed_axis"), TEXT("0..600"));
    Result.Data->SetStringField(TEXT("direction_axis"), TEXT("-180..180"));
    if (UObject* Existing = LoadExactAsset(ObjectPath))
    {
        if (Existing->IsA<UBlendSpace>()) { Result.Validation.Add(TEXT("already_exists_with_requested_class")); return Finish(Result, false, false, TEXT("Blend Space creation is package-backed and not transaction-backed.")); }
        return FCotSOperationResult::Fail(Op, TEXT("destination_collision"), TEXT("The exact path is occupied by a different asset class."), bDryRun).ToJson();
    }
    if (bDryRun) { Result.Validation.Add(TEXT("validated_disposable_blend_space_target")); return Finish(Result, true, false, TEXT("Blend Space creation is package-backed and not transaction-backed.")); }

    const FString ObjectName = FPackageName::ObjectPathToObjectName(ObjectPath);
    const FString PackagePath = FPackageName::ObjectPathToPackageName(ObjectPath).LeftChop(ObjectName.Len() + 1);
    UBlendSpaceFactoryNew* Factory = NewObject<UBlendSpaceFactoryNew>();
    Factory->TargetSkeleton = Skeleton;
    Factory->PreviewSkeletalMesh = PreviewMesh;
    UBlendSpace* BlendSpace = Cast<UBlendSpace>(FAssetToolsModule::GetModule().Get().CreateAsset(ObjectName, PackagePath, UBlendSpace::StaticClass(), Factory));
    if (!BlendSpace || !BlendSpace->GetPathName().Equals(ObjectPath, ESearchCase::CaseSensitive)) { return FCotSOperationResult::Fail(Op, TEXT("create_failed"), TEXT("UE could not create the requested Blend Space.")).ToJson(); }
    BlendSpace->Modify();
    if (!ConfigureLocomotionBlendSpace(BlendSpace)) { return FCotSOperationResult::Fail(Op, TEXT("blend_parameter_configuration_failed"), TEXT("UE's BlendParameters property did not match the expected typed configuration contract.")).ToJson(); }
    BlendSpace->MarkPackageDirty();
    Result.Validation.Add(TEXT("re-inspect Blend Space axes and sample count before save"));
    return Finish(Result, true, false, TEXT("Blend Space creation is package-backed and not transaction-backed."));
}

FString UCotSMutationToolset::CreateDisposableAnimBlueprint(const FString& ObjectPath, const FString& SkeletonPath, const FString& PreviewMeshPath, bool bDryRun)
{
    constexpr const TCHAR* Op = TEXT("CotS.Mutation.CreateDisposableAnimBlueprint");
    if (!IsDisposableAssetPath(ObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("outside_disposable_scope"), TEXT("AnimBlueprint creation is restricted to /Game/CotSMutationLive/ exact object paths."), bDryRun).ToJson(); }
    USkeleton* Skeleton = Cast<USkeleton>(LoadExactAsset(SkeletonPath));
    USkeletalMesh* PreviewMesh = PreviewMeshPath.IsEmpty() ? (Skeleton ? Skeleton->GetPreviewMesh(true) : nullptr) : Cast<USkeletalMesh>(LoadExactAsset(PreviewMeshPath));
    if (!Skeleton || !PreviewMesh || PreviewMesh->GetSkeleton() != Skeleton)
    {
        return FCotSOperationResult::Fail(Op, TEXT("invalid_skeleton_or_preview_mesh"), TEXT("SkeletonPath must resolve; PreviewMeshPath must resolve, or its empty value must let UE resolve the Skeleton's preview mesh; the mesh must use that exact skeleton."), bDryRun).ToJson();
    }
    FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath, SkeletonPath);
    Result.AddAffectedObject(PreviewMesh->GetPathName());
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("object_path"), ObjectPath);
    Result.Data->SetStringField(TEXT("skeleton"), SkeletonPath);
    Result.Data->SetStringField(TEXT("preview_mesh"), PreviewMesh->GetPathName());
    Result.Data->SetStringField(TEXT("parent_class"), UAnimInstance::StaticClass()->GetPathName());
    Result.Data->SetStringField(TEXT("graph_topology"), TEXT("none_created"));
    if (UObject* Existing = LoadExactAsset(ObjectPath))
    {
        if (!Existing->IsA<UAnimBlueprint>()) { return FCotSOperationResult::Fail(Op, TEXT("destination_collision"), TEXT("The exact path is occupied by a different asset class."), bDryRun).ToJson(); }
        Result.Validation.Add(TEXT("already_exists_with_requested_class"));
        return Finish(Result, false, false, TEXT("AnimBlueprint asset creation is package-backed and graph topology is not created by this operation."));
    }
    if (bDryRun)
    {
        Result.Validation.Add(TEXT("validated_disposable_animblueprint_creation_target"));
        return Finish(Result, true, false, TEXT("AnimBlueprint asset creation is package-backed and graph topology is not created by this operation."));
    }
    const FString ObjectName = FPackageName::ObjectPathToObjectName(ObjectPath);
    const FString PackagePath = FPackageName::ObjectPathToPackageName(ObjectPath).LeftChop(ObjectName.Len() + 1);
    UAnimBlueprintFactory* Factory = NewObject<UAnimBlueprintFactory>();
    Factory->ParentClass = UAnimInstance::StaticClass();
    Factory->TargetSkeleton = Skeleton;
    Factory->PreviewSkeletalMesh = PreviewMesh;
    UAnimBlueprint* Blueprint = Cast<UAnimBlueprint>(FAssetToolsModule::GetModule().Get().CreateAsset(ObjectName, PackagePath, UAnimBlueprint::StaticClass(), Factory));
    if (!Blueprint || !Blueprint->GetPathName().Equals(ObjectPath, ESearchCase::CaseSensitive)) { return FCotSOperationResult::Fail(Op, TEXT("create_failed"), TEXT("UE could not create the requested AnimBlueprint.")).ToJson(); }
    Result.Validation.Add(TEXT("inspect with CotS.Inspection.GetAnimBlueprintStateMachines before graph authoring"));
    return Finish(Result, true, false, TEXT("AnimBlueprint asset creation is package-backed and graph topology is not created by this operation."));
}

FString UCotSMutationToolset::AddDisposableAnimBlueprintStateMachine(const FString& ObjectPath, bool bDryRun)
{
    constexpr const TCHAR* Op = TEXT("CotS.Mutation.AddDisposableAnimBlueprintStateMachine");
    if (!IsDisposableAssetPath(ObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("outside_disposable_scope"), TEXT("State Machine authoring is restricted to /Game/CotSMutationLive/ exact object paths."), bDryRun).ToJson(); }
    UAnimBlueprint* Blueprint = Cast<UAnimBlueprint>(LoadExactAsset(ObjectPath));
    if (!Blueprint) { return FCotSOperationResult::Fail(Op, TEXT("animblueprint_not_found"), TEXT("ObjectPath must resolve to a UAnimBlueprint asset."), bDryRun).ToJson(); }
    UAnimationGraph* AnimGraph = nullptr;
    for (UEdGraph* Graph : Blueprint->FunctionGraphs)
    {
        if (UAnimationGraph* Candidate = Cast<UAnimationGraph>(Graph)) { AnimGraph = Candidate; break; }
    }
    if (!AnimGraph) { return FCotSOperationResult::Fail(Op, TEXT("animation_graph_not_found"), TEXT("The AnimBlueprint has no editable UAnimationGraph."), bDryRun).ToJson(); }
    FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath);
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("animation_graph"), AnimGraph->GetPathName());
    TArray<UAnimGraphNode_Base*> ExistingMachines;
    AnimGraph->GetGraphNodesOfClass(UAnimGraphNode_StateMachine::StaticClass(), ExistingMachines, true);
    if (ExistingMachines.Num() > 0)
    {
        const UAnimGraphNode_StateMachine* ExistingMachine = Cast<UAnimGraphNode_StateMachine>(ExistingMachines[0]);
        Result.Data->SetStringField(TEXT("state_machine_graph"), ExistingMachine && ExistingMachine->EditorStateMachineGraph ? ExistingMachine->EditorStateMachineGraph->GetPathName() : FString());
        Result.Validation.Add(TEXT("already_contains_state_machine"));
        return Finish(Result, false, false, TEXT("State Machine authoring is graph-backed and not transaction-backed."));
    }
    if (bDryRun)
    {
        Result.Validation.Add(TEXT("validated_single_default_state_machine_creation"));
        return Finish(Result, true, false, TEXT("State Machine authoring is graph-backed and not transaction-backed."));
    }
    Blueprint->Modify();
    AnimGraph->Modify();
    FGraphNodeCreator<UAnimGraphNode_StateMachine> NodeCreator(*AnimGraph);
    UAnimGraphNode_StateMachine* MachineNode = NodeCreator.CreateNode(false);
    NodeCreator.Finalize();
    if (!MachineNode || !MachineNode->EditorStateMachineGraph) { return FCotSOperationResult::Fail(Op, TEXT("state_machine_create_failed"), TEXT("UE could not initialize the State Machine graph.")).ToJson(); }
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    Result.Data->SetStringField(TEXT("state_machine_graph"), MachineNode->EditorStateMachineGraph->GetPathName());
    Result.Data->SetNumberField(TEXT("state_count"), 0);
    Result.Validation.Add(TEXT("inspect with CotS.Inspection.GetAnimBlueprintStateMachines before adding states or transitions"));
    return Finish(Result, true, false, TEXT("State Machine authoring is graph-backed and not transaction-backed."));
}

FString UCotSMutationToolset::AddDisposableAnimBlueprintState(const FString& ObjectPath, const FString& StateName, bool bDryRun)
{
    constexpr const TCHAR* Op = TEXT("CotS.Mutation.AddDisposableAnimBlueprintState");
    if (!IsDisposableAssetPath(ObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("outside_disposable_scope"), TEXT("State authoring is restricted to /Game/CotSMutationLive/ exact object paths."), bDryRun).ToJson(); }
    if (StateName.IsEmpty() || !FName::IsValidXName(StateName, INVALID_OBJECTNAME_CHARACTERS)) { return FCotSOperationResult::Fail(Op, TEXT("invalid_state_name"), TEXT("StateName must be a non-empty valid Unreal object name."), bDryRun).ToJson(); }
    UAnimBlueprint* Blueprint = Cast<UAnimBlueprint>(LoadExactAsset(ObjectPath));
    if (!Blueprint) { return FCotSOperationResult::Fail(Op, TEXT("animblueprint_not_found"), TEXT("ObjectPath must resolve to a UAnimBlueprint asset."), bDryRun).ToJson(); }
    UAnimationGraph* AnimGraph = nullptr;
    for (UEdGraph* Graph : Blueprint->FunctionGraphs) { if (UAnimationGraph* Candidate = Cast<UAnimationGraph>(Graph)) { AnimGraph = Candidate; break; } }
    if (!AnimGraph) { return FCotSOperationResult::Fail(Op, TEXT("animation_graph_not_found"), TEXT("The AnimBlueprint has no editable UAnimationGraph."), bDryRun).ToJson(); }
    TArray<UAnimGraphNode_Base*> Machines;
    AnimGraph->GetGraphNodesOfClass(UAnimGraphNode_StateMachine::StaticClass(), Machines, true);
    UAnimGraphNode_StateMachine* Machine = Machines.Num() == 1 ? Cast<UAnimGraphNode_StateMachine>(Machines[0]) : nullptr;
    if (!Machine || !Machine->EditorStateMachineGraph || !Machine->EditorStateMachineGraph->EntryNode) { return FCotSOperationResult::Fail(Op, TEXT("state_machine_not_found"), TEXT("The AnimBlueprint must contain exactly one initialized State Machine."), bDryRun).ToJson(); }
    UAnimationStateMachineGraph* StateMachineGraph = Machine->EditorStateMachineGraph;
    TArray<UAnimStateNode*> ExistingStates;
    StateMachineGraph->GetNodesOfClass(ExistingStates);
    for (UAnimStateNode* ExistingState : ExistingStates)
    {
        if (ExistingState && ExistingState->GetStateName().Equals(StateName, ESearchCase::CaseSensitive))
        {
            FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath);
            Result.Data = MakeShared<FJsonObject>();
            Result.Data->SetStringField(TEXT("state_machine_graph"), StateMachineGraph->GetPathName());
            Result.Data->SetStringField(TEXT("state_graph"), ExistingState->BoundGraph ? ExistingState->BoundGraph->GetPathName() : FString());
            Result.Validation.Add(TEXT("already_contains_requested_state"));
            return Finish(Result, false, false, TEXT("State authoring is graph-backed and not transaction-backed."));
        }
    }
    FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath);
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("state_machine_graph"), StateMachineGraph->GetPathName());
    Result.Data->SetStringField(TEXT("requested_state_name"), StateName);
    if (bDryRun) { Result.Validation.Add(TEXT("validated_named_entry_wired_state_creation")); return Finish(Result, true, false, TEXT("State authoring is graph-backed and not transaction-backed.")); }
    Blueprint->Modify();
    StateMachineGraph->Modify();
    UAnimStateNode* StateNode = FEdGraphSchemaAction_NewStateNode::SpawnNodeFromTemplate<UAnimStateNode>(StateMachineGraph, NewObject<UAnimStateNode>(), FVector2f(240.0f, 0.0f), false);
    if (!StateNode || !StateNode->BoundGraph) { return FCotSOperationResult::Fail(Op, TEXT("state_create_failed"), TEXT("UE could not initialize the State graph.")).ToJson(); }
    FEdGraphUtilities::RenameGraphToNameOrCloseToName(StateNode->BoundGraph, StateName);
    StateNode->AutowireNewNode(StateMachineGraph->EntryNode->GetOutputPin());
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    Result.Data->SetStringField(TEXT("state_graph"), StateNode->BoundGraph->GetPathName());
    Result.Data->SetBoolField(TEXT("entry_wired"), StateMachineGraph->EntryNode->GetOutputNode() == StateNode);
    Result.Validation.Add(TEXT("inspect with CotS.Inspection.GetAnimBlueprintStateMachines before adding transitions"));
    return Finish(Result, true, false, TEXT("State authoring is graph-backed and not transaction-backed."));
}

FString UCotSMutationToolset::AddDisposableAnimBlueprintTransition(const FString& ObjectPath, const FString& SourceStateName, const FString& TargetStateName, double CrossfadeSeconds, bool bDryRun)
{
    constexpr const TCHAR* Op = TEXT("CotS.Mutation.AddDisposableAnimBlueprintTransition");
    if (!IsDisposableAssetPath(ObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("outside_disposable_scope"), TEXT("Transition authoring is restricted to /Game/CotSMutationLive/ exact object paths."), bDryRun).ToJson(); }
    if (SourceStateName.IsEmpty() || TargetStateName.IsEmpty() || SourceStateName == TargetStateName || !FMath::IsFinite(CrossfadeSeconds) || CrossfadeSeconds < 0.0 || CrossfadeSeconds > 10.0)
    {
        return FCotSOperationResult::Fail(Op, TEXT("invalid_transition_request"), TEXT("Source/Target State names must be distinct and CrossfadeSeconds must be finite in [0,10]."), bDryRun).ToJson();
    }
    UAnimBlueprint* Blueprint = Cast<UAnimBlueprint>(LoadExactAsset(ObjectPath));
    if (!Blueprint) { return FCotSOperationResult::Fail(Op, TEXT("animblueprint_not_found"), TEXT("ObjectPath must resolve to a UAnimBlueprint asset."), bDryRun).ToJson(); }
    UAnimationGraph* AnimGraph = nullptr;
    for (UEdGraph* Graph : Blueprint->FunctionGraphs) { if (UAnimationGraph* Candidate = Cast<UAnimationGraph>(Graph)) { AnimGraph = Candidate; break; } }
    if (!AnimGraph) { return FCotSOperationResult::Fail(Op, TEXT("animation_graph_not_found"), TEXT("The AnimBlueprint has no editable UAnimationGraph."), bDryRun).ToJson(); }
    TArray<UAnimGraphNode_Base*> Machines;
    AnimGraph->GetGraphNodesOfClass(UAnimGraphNode_StateMachine::StaticClass(), Machines, true);
    UAnimGraphNode_StateMachine* Machine = Machines.Num() == 1 ? Cast<UAnimGraphNode_StateMachine>(Machines[0]) : nullptr;
    if (!Machine || !Machine->EditorStateMachineGraph) { return FCotSOperationResult::Fail(Op, TEXT("state_machine_not_found"), TEXT("The AnimBlueprint must contain exactly one initialized State Machine."), bDryRun).ToJson(); }
    UAnimationStateMachineGraph* StateMachineGraph = Machine->EditorStateMachineGraph;
    TArray<UAnimStateNode*> States;
    StateMachineGraph->GetNodesOfClass(States);
    UAnimStateNode* SourceState = nullptr;
    UAnimStateNode* TargetState = nullptr;
    for (UAnimStateNode* State : States)
    {
        if (!State) { continue; }
        if (State->GetStateName().Equals(SourceStateName, ESearchCase::CaseSensitive)) { SourceState = State; }
        if (State->GetStateName().Equals(TargetStateName, ESearchCase::CaseSensitive)) { TargetState = State; }
    }
    if (!SourceState || !TargetState) { return FCotSOperationResult::Fail(Op, TEXT("state_not_found"), TEXT("Both requested State names must resolve in the single State Machine."), bDryRun).ToJson(); }
    TArray<UAnimStateTransitionNode*> ExistingTransitions;
    StateMachineGraph->GetNodesOfClass(ExistingTransitions);
    for (UAnimStateTransitionNode* Transition : ExistingTransitions)
    {
        if (Transition && Transition->GetPreviousState() == SourceState && Transition->GetNextState() == TargetState)
        {
            FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath);
            Result.Data = MakeShared<FJsonObject>();
            Result.Data->SetStringField(TEXT("source_state"), SourceStateName);
            Result.Data->SetStringField(TEXT("target_state"), TargetStateName);
            Result.Data->SetStringField(TEXT("transition_graph"), Transition->BoundGraph ? Transition->BoundGraph->GetPathName() : FString());
            Result.Validation.Add(TEXT("already_contains_requested_transition"));
            return Finish(Result, false, false, TEXT("Transition authoring is graph-backed and not transaction-backed."));
        }
    }
    FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath);
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("source_state"), SourceStateName);
    Result.Data->SetStringField(TEXT("target_state"), TargetStateName);
    Result.Data->SetNumberField(TEXT("crossfade_seconds"), CrossfadeSeconds);
    if (bDryRun) { Result.Validation.Add(TEXT("validated_directional_transition_creation")); return Finish(Result, true, false, TEXT("Transition authoring is graph-backed and not transaction-backed.")); }
    Blueprint->Modify();
    StateMachineGraph->Modify();
    UAnimStateTransitionNode* Transition = FEdGraphSchemaAction_NewStateNode::SpawnNodeFromTemplate<UAnimStateTransitionNode>(StateMachineGraph, NewObject<UAnimStateTransitionNode>(), FVector2f(480.0f, 0.0f), false);
    if (!Transition || !Transition->BoundGraph) { return FCotSOperationResult::Fail(Op, TEXT("transition_create_failed"), TEXT("UE could not initialize the transition-rule graph.")).ToJson(); }
    Transition->CrossfadeDuration = static_cast<float>(CrossfadeSeconds);
    Transition->CreateConnections(SourceState, TargetState);
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    Result.Data->SetStringField(TEXT("transition_graph"), Transition->BoundGraph->GetPathName());
    Result.Data->SetBoolField(TEXT("connected"), Transition->GetPreviousState() == SourceState && Transition->GetNextState() == TargetState);
    Result.Validation.Add(TEXT("inspect with CotS.Inspection.GetAnimBlueprintStateMachines before adding rule logic"));
    return Finish(Result, true, false, TEXT("Transition authoring is graph-backed and not transaction-backed."));
}

FString UCotSMutationToolset::SetDisposableAnimBlueprintStateSequence(const FString& ObjectPath, const FString& StateName, const FString& AnimationPath, bool bLooping, bool bDryRun)
{
    constexpr const TCHAR* Op = TEXT("CotS.Mutation.SetDisposableAnimBlueprintStateSequence");
    if (!IsDisposableAssetPath(ObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("outside_disposable_scope"), TEXT("State content authoring is restricted to /Game/CotSMutationLive/ exact object paths."), bDryRun).ToJson(); }
    UAnimBlueprint* Blueprint = Cast<UAnimBlueprint>(LoadExactAsset(ObjectPath));
    UAnimSequence* Animation = Cast<UAnimSequence>(LoadExactAsset(AnimationPath));
    if (!Blueprint || !Animation || !Blueprint->TargetSkeleton || Animation->GetSkeleton() != Blueprint->TargetSkeleton)
    {
        return FCotSOperationResult::Fail(Op, TEXT("invalid_animblueprint_or_sequence"), TEXT("ObjectPath must resolve to a target-Skeleton AnimBlueprint and AnimationPath to an exact-skeleton UAnimSequence."), bDryRun).ToJson();
    }
    UAnimStateNode* State = nullptr;
    for (UEdGraph* Graph : Blueprint->FunctionGraphs)
    {
        TArray<UAnimGraphNode_Base*> Machines;
        if (UAnimationGraph* AnimGraph = Cast<UAnimationGraph>(Graph)) { AnimGraph->GetGraphNodesOfClass(UAnimGraphNode_StateMachine::StaticClass(), Machines, true); }
        for (UAnimGraphNode_Base* Node : Machines)
        {
            if (UAnimGraphNode_StateMachine* Machine = Cast<UAnimGraphNode_StateMachine>(Node))
            {
                TArray<UAnimStateNode*> States;
                if (Machine->EditorStateMachineGraph) { Machine->EditorStateMachineGraph->GetNodesOfClass(States); }
                for (UAnimStateNode* Candidate : States) { if (Candidate && Candidate->GetStateName().Equals(StateName, ESearchCase::CaseSensitive)) { State = Candidate; break; } }
            }
            if (State) { break; }
        }
        if (State) { break; }
    }
    if (!State || !State->BoundGraph) { return FCotSOperationResult::Fail(Op, TEXT("state_not_found"), TEXT("StateName must resolve to a State with an initialized animation graph."), bDryRun).ToJson(); }
    UAnimGraphNode_StateResult* ResultNode = State->GetResultNodeInsideState();
    if (!ResultNode) { return FCotSOperationResult::Fail(Op, TEXT("state_result_not_found"), TEXT("The State graph has no result node."), bDryRun).ToJson(); }
    TArray<UAnimGraphNode_SequencePlayer*> ExistingPlayers;
    State->BoundGraph->GetNodesOfClass(ExistingPlayers);
    if (ExistingPlayers.Num() > 0)
    {
        if (ExistingPlayers.Num() == 1 && ExistingPlayers[0]->GetAnimationAsset() == Animation && ExistingPlayers[0]->Node.IsLooping() == bLooping)
        {
            FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath, AnimationPath);
            Result.Validation.Add(TEXT("already_contains_requested_sequence_player"));
            return Finish(Result, false, false, TEXT("State content authoring is graph-backed and not transaction-backed."));
        }
        return FCotSOperationResult::Fail(Op, TEXT("state_content_already_exists"), TEXT("The State already contains a different sequence player; replace/remove is intentionally explicit."), bDryRun).ToJson();
    }
    FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath, AnimationPath);
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("state_graph"), State->BoundGraph->GetPathName());
    Result.Data->SetStringField(TEXT("animation"), AnimationPath);
    Result.Data->SetBoolField(TEXT("looping"), bLooping);
    if (bDryRun) { Result.Validation.Add(TEXT("validated_exact_skeleton_sequence_player_creation")); return Finish(Result, true, false, TEXT("State content authoring is graph-backed and not transaction-backed.")); }
    Blueprint->Modify();
    State->BoundGraph->Modify();
    FGraphNodeCreator<UAnimGraphNode_SequencePlayer> PlayerCreator(*State->BoundGraph);
    UAnimGraphNode_SequencePlayer* Player = PlayerCreator.CreateNode(false);
    Player->SetAnimationAsset(Animation);
    Player->Node.SetLoopAnimation(bLooping);
    PlayerCreator.Finalize();
    UEdGraphPin* PoseOutput = Player->FindPinChecked(TEXT("Pose"), EGPD_Output);
    UEdGraphPin* ResultInput = ResultNode->FindPinChecked(TEXT("Result"), EGPD_Input);
    PoseOutput->MakeLinkTo(ResultInput);
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    Result.Data->SetStringField(TEXT("sequence_player"), Player->GetPathName());
    Result.Data->SetBoolField(TEXT("result_wired"), PoseOutput->LinkedTo.Contains(ResultInput));
    Result.Validation.Add(TEXT("inspect State Machine before AnimGraph output wiring or compilation"));
    return Finish(Result, true, false, TEXT("State content authoring is graph-backed and not transaction-backed."));
}

FString UCotSMutationToolset::SetDisposableAnimBlueprintTransitionRule(const FString& ObjectPath, const FString& SourceStateName, const FString& TargetStateName, bool bCanEnterTransition, bool bDryRun)
{
    constexpr const TCHAR* Op = TEXT("CotS.Mutation.SetDisposableAnimBlueprintTransitionRule");
    if (!IsDisposableAssetPath(ObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("outside_disposable_scope"), TEXT("Transition-rule authoring is restricted to /Game/CotSMutationLive/ exact object paths."), bDryRun).ToJson(); }
    if (SourceStateName.IsEmpty() || TargetStateName.IsEmpty() || SourceStateName == TargetStateName)
    {
        return FCotSOperationResult::Fail(Op, TEXT("invalid_transition_request"), TEXT("Source and Target State names must be distinct and non-empty."), bDryRun).ToJson();
    }
    UAnimBlueprint* Blueprint = Cast<UAnimBlueprint>(LoadExactAsset(ObjectPath));
    if (!Blueprint) { return FCotSOperationResult::Fail(Op, TEXT("animblueprint_not_found"), TEXT("ObjectPath must resolve to a UAnimBlueprint asset."), bDryRun).ToJson(); }
    UAnimationGraph* AnimGraph = nullptr;
    for (UEdGraph* Graph : Blueprint->FunctionGraphs) { if (UAnimationGraph* Candidate = Cast<UAnimationGraph>(Graph)) { AnimGraph = Candidate; break; } }
    if (!AnimGraph) { return FCotSOperationResult::Fail(Op, TEXT("animation_graph_not_found"), TEXT("The AnimBlueprint has no editable UAnimationGraph."), bDryRun).ToJson(); }
    TArray<UAnimGraphNode_Base*> Machines;
    AnimGraph->GetGraphNodesOfClass(UAnimGraphNode_StateMachine::StaticClass(), Machines, true);
    UAnimGraphNode_StateMachine* Machine = Machines.Num() == 1 ? Cast<UAnimGraphNode_StateMachine>(Machines[0]) : nullptr;
    if (!Machine || !Machine->EditorStateMachineGraph) { return FCotSOperationResult::Fail(Op, TEXT("state_machine_not_found"), TEXT("The AnimBlueprint must contain exactly one initialized State Machine."), bDryRun).ToJson(); }
    UAnimStateTransitionNode* RequestedTransition = nullptr;
    TArray<UAnimStateTransitionNode*> Transitions;
    Machine->EditorStateMachineGraph->GetNodesOfClass(Transitions);
    for (UAnimStateTransitionNode* Transition : Transitions)
    {
        if (Transition && Transition->GetPreviousState() && Transition->GetNextState()
            && Transition->GetPreviousState()->GetStateName().Equals(SourceStateName, ESearchCase::CaseSensitive)
            && Transition->GetNextState()->GetStateName().Equals(TargetStateName, ESearchCase::CaseSensitive))
        {
            RequestedTransition = Transition;
            break;
        }
    }
    if (!RequestedTransition) { return FCotSOperationResult::Fail(Op, TEXT("transition_not_found"), TEXT("The requested exact directed transition must exist in the single State Machine."), bDryRun).ToJson(); }
    UAnimationTransitionGraph* RuleGraph = Cast<UAnimationTransitionGraph>(RequestedTransition->BoundGraph);
    UAnimGraphNode_TransitionResult* ResultNode = RuleGraph ? RuleGraph->GetResultNode() : nullptr;
    if (!ResultNode) { return FCotSOperationResult::Fail(Op, TEXT("transition_result_not_found"), TEXT("The requested transition has no initialized public Transition Result node."), bDryRun).ToJson(); }
    // bCanEnterTransition is a PinShownByDefault struct property: the anim
    // transition-graph compiler generates its bytecode from the pin (its
    // connection, or its DefaultValue string) and never reads the runtime
    // FAnimNode_TransitionResult struct directly, so writing only the struct
    // field compiles without error but the transition can never be taken --
    // the pin's own default value must be set for the rule to actually work.
    UEdGraphPin* CanEnterTransitionPin = ResultNode->FindPin(TEXT("bCanEnterTransition"));
    if (!CanEnterTransitionPin) { return FCotSOperationResult::Fail(Op, TEXT("transition_result_pin_not_found"), TEXT("The Transition Result node has no bCanEnterTransition input pin.")).ToJson(); }
    if (CanEnterTransitionPin->LinkedTo.Num() > 0)
    {
        return FCotSOperationResult::Fail(Op, TEXT("transition_rule_already_wired"), TEXT("The bCanEnterTransition pin already has a connected expression graph; this tool only authors an unconnected constant rule.")).ToJson();
    }
    FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath);
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("source_state"), SourceStateName);
    Result.Data->SetStringField(TEXT("target_state"), TargetStateName);
    Result.Data->SetStringField(TEXT("transition_graph"), RuleGraph->GetPathName());
    Result.Data->SetStringField(TEXT("result_node"), ResultNode->GetPathName());
    const bool bBeforeCanEnterTransition = CanEnterTransitionPin->DefaultValue.ToBool();
    Result.Data->SetBoolField(TEXT("before_can_enter_transition"), bBeforeCanEnterTransition);
    Result.Data->SetBoolField(TEXT("after_can_enter_transition"), bCanEnterTransition);
    if (bBeforeCanEnterTransition == bCanEnterTransition)
    {
        Result.Validation.Add(TEXT("already_contains_requested_constant_rule"));
        return Finish(Result, false, false, TEXT("Transition-rule authoring is graph-backed and not transaction-backed."));
    }
    if (bDryRun)
    {
        Result.Validation.Add(TEXT("validated_typed_constant_transition_rule"));
        return Finish(Result, true, false, TEXT("Transition-rule authoring is graph-backed and not transaction-backed."));
    }
    Blueprint->Modify();
    RuleGraph->Modify();
    ResultNode->Modify();
    CanEnterTransitionPin->DefaultValue = bCanEnterTransition ? TEXT("true") : TEXT("false");
    ResultNode->Node.bCanEnterTransition = bCanEnterTransition;
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    Result.Validation.Add(TEXT("compile with CotS.Mutation.CompileBlueprint before saving"));
    return Finish(Result, true, false, TEXT("Transition-rule authoring is graph-backed and not transaction-backed."));
}

FString UCotSMutationToolset::WireDisposableAnimBlueprintStateMachineOutput(const FString& ObjectPath, bool bDryRun)
{
    constexpr const TCHAR* Op = TEXT("CotS.Mutation.WireDisposableAnimBlueprintStateMachineOutput");
    if (!IsDisposableAssetPath(ObjectPath)) { return FCotSOperationResult::Fail(Op, TEXT("outside_disposable_scope"), TEXT("AnimGraph output wiring is restricted to /Game/CotSMutationLive/ exact object paths."), bDryRun).ToJson(); }
    UAnimBlueprint* Blueprint = Cast<UAnimBlueprint>(LoadExactAsset(ObjectPath));
    if (!Blueprint) { return FCotSOperationResult::Fail(Op, TEXT("animblueprint_not_found"), TEXT("ObjectPath must resolve to a UAnimBlueprint asset."), bDryRun).ToJson(); }
    UAnimationGraph* AnimGraph = nullptr;
    for (UEdGraph* Graph : Blueprint->FunctionGraphs) { if (UAnimationGraph* Candidate = Cast<UAnimationGraph>(Graph)) { AnimGraph = Candidate; break; } }
    if (!AnimGraph) { return FCotSOperationResult::Fail(Op, TEXT("animation_graph_not_found"), TEXT("The AnimBlueprint has no editable UAnimationGraph."), bDryRun).ToJson(); }
    TArray<UAnimGraphNode_Base*> Machines;
    AnimGraph->GetGraphNodesOfClass(UAnimGraphNode_StateMachine::StaticClass(), Machines, true);
    TArray<UAnimGraphNode_Root*> Roots;
    AnimGraph->GetNodesOfClass(Roots);
    UAnimGraphNode_StateMachine* Machine = Machines.Num() == 1 ? Cast<UAnimGraphNode_StateMachine>(Machines[0]) : nullptr;
    UAnimGraphNode_Root* Root = Roots.Num() == 1 ? Roots[0] : nullptr;
    if (!Machine || !Root) { return FCotSOperationResult::Fail(Op, TEXT("animgraph_topology_not_ready"), TEXT("The AnimBlueprint must contain exactly one State Machine and one AnimGraph Root."), bDryRun).ToJson(); }
    UEdGraphPin* MachineOutput = Machine->FindPin(TEXT("Pose"), EGPD_Output);
    UEdGraphPin* RootInput = Root->FindPin(TEXT("Result"), EGPD_Input);
    if (!MachineOutput || !RootInput) { return FCotSOperationResult::Fail(Op, TEXT("pose_pins_not_found"), TEXT("The State Machine or AnimGraph Root lacks its expected public Pose/Result pin."), bDryRun).ToJson(); }
    FCotSOperationResult Result = Start(Op, bDryRun, ObjectPath);
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("animation_graph"), AnimGraph->GetPathName());
    Result.Data->SetStringField(TEXT("root_node"), Root->GetPathName());
    if (RootInput->LinkedTo.Contains(MachineOutput)) { Result.Validation.Add(TEXT("already_wired_to_state_machine")); return Finish(Result, false, false, TEXT("AnimGraph output wiring is graph-backed and not transaction-backed.")); }
    if (RootInput->LinkedTo.Num() > 0) { return FCotSOperationResult::Fail(Op, TEXT("animgraph_output_already_wired"), TEXT("The AnimGraph Root is already wired to a different pose producer."), bDryRun).ToJson(); }
    if (bDryRun) { Result.Validation.Add(TEXT("validated_single_state_machine_to_root_wiring")); return Finish(Result, true, false, TEXT("AnimGraph output wiring is graph-backed and not transaction-backed.")); }
    Blueprint->Modify();
    AnimGraph->Modify();
    MachineOutput->MakeLinkTo(RootInput);
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    Result.Data->SetBoolField(TEXT("root_wired"), RootInput->LinkedTo.Contains(MachineOutput));
    Result.Validation.Add(TEXT("compile with CotS.Mutation.CompileBlueprint before saving"));
    return Finish(Result, true, false, TEXT("AnimGraph output wiring is graph-backed and not transaction-backed."));
}

FString UCotSMutationToolset::AddLocomotionBlendSpaceSample(const FString& BlendSpacePath, const FString& AnimationPath, double Speed, double Direction, bool bDryRun)
{
    constexpr const TCHAR* Op = TEXT("CotS.Mutation.AddLocomotionBlendSpaceSample");
    UBlendSpace* BlendSpace = Cast<UBlendSpace>(LoadExactAsset(BlendSpacePath));
    UAnimSequence* Animation = Cast<UAnimSequence>(LoadExactAsset(AnimationPath));
    if (!BlendSpace || !IsDisposableAssetPath(BlendSpacePath)) { return FCotSOperationResult::Fail(Op, TEXT("invalid_disposable_blend_space"), TEXT("BlendSpacePath must resolve to a Blend Space under /Game/CotSMutationLive/."), bDryRun).ToJson(); }
    if (!Animation || Animation->GetSkeleton() != BlendSpace->GetSkeleton()) { return FCotSOperationResult::Fail(Op, TEXT("animation_skeleton_mismatch"), TEXT("AnimationPath must resolve to a UAnimSequence using the Blend Space's exact skeleton."), bDryRun).ToJson(); }
    if (!FMath::IsFinite(Speed) || !FMath::IsFinite(Direction)) { return FCotSOperationResult::Fail(Op, TEXT("invalid_sample_coordinate"), TEXT("Speed and Direction must be finite numeric values."), bDryRun).ToJson(); }
    const FBlendParameter& SpeedAxis = BlendSpace->GetBlendParameter(0);
    const FBlendParameter& DirectionAxis = BlendSpace->GetBlendParameter(1);
    if (Speed < SpeedAxis.Min || Speed > SpeedAxis.Max || Direction < DirectionAxis.Min || Direction > DirectionAxis.Max)
    {
        return FCotSOperationResult::Fail(Op, TEXT("sample_outside_locomotion_axes"), TEXT("Sample coordinates must be within the configured Speed (0..600) and Direction (-180..180) axes."), bDryRun).ToJson();
    }
    const FVector SampleValue(Speed, Direction, 0.0);
    FCotSOperationResult Result = Start(Op, bDryRun, BlendSpacePath, AnimationPath);
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("sample_value"), SampleValue.ToString());
    for (const FBlendSample& Existing : BlendSpace->GetBlendSamples())
    {
        if (Existing.Animation == Animation && Existing.SampleValue.Equals(SampleValue)) { Result.Validation.Add(TEXT("already_exists_with_requested_sample")); return Finish(Result, false, true); }
    }
    if (bDryRun) { Result.Validation.Add(TEXT("validated_animation_and_locomotion_axes")); return Finish(Result, true, true); }
    FCotSEditorMutationScope Scope(FText::FromString(TEXT("CotS Add Locomotion Blend Space Sample")), BlendSpace, false);
    BlendSpace->Modify();
    if (BlendSpace->AddSample(Animation, SampleValue) < 0) { return FCotSOperationResult::Fail(Op, TEXT("add_sample_failed"), TEXT("UE rejected the requested Blend Space sample.")).ToJson(); }
    BlendSpace->MarkPackageDirty();
    Result.Validation.Add(TEXT("re-inspect sample count and save after review"));
    return Finish(Result, true, true);
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
