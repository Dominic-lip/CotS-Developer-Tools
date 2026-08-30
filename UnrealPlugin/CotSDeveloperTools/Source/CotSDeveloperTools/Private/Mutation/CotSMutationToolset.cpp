#include "Mutation/CotSMutationToolset.h"

#include "AssetToolsModule.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Animation/AnimBlueprint.h"
#include "Animation/AnimInstance.h"
#include "Animation/AnimSequence.h"
#include "AnimationGraph.h"
#include "AnimGraphNode_StateMachine.h"
#include "Animation/BlendSpace.h"
#include "Components/SceneComponent.h"
#include "Core/CotSEditorMutationScope.h"
#include "Core/CotSOperationResult.h"
#include "Curves/CurveFloat.h"
#include "Dom/JsonObject.h"
#include "Editor.h"
#include "EditorAssetLibrary.h"
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
#include "Retargeter/IKRetargeter.h"
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
