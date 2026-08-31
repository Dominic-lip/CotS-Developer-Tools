#include "Core/CotSOperationResult.h"
#include "Animation/AnimBlueprint.h"
#include "AnimationGraph.h"
#include "AnimGraphNode_StateMachine.h"
#include "AnimGraphNode_TransitionResult.h"
#include "AnimStateTransitionNode.h"
#include "AnimationTransitionGraph.h"
#include "Execution/CotSExecutionToolset.h"
#include "Foundation/CotSFoundationToolset.h"
#include "Inspection/CotSInspectionToolset.h"
#include "Lifecycle/CotSLifecycleToolset.h"
#include "Mutation/CotSMutationToolset.h"
#include "Validation/CotSValidationToolset.h"
#include "Retargeter/IKRetargeter.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Curves/CurveFloat.h"
#include "Misc/AutomationTest.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "ToolsetRegistry/UToolsetRegistry.h"
#include "UObject/Package.h"

#include <limits>

#if WITH_DEV_AUTOMATION_TESTS && WITH_EDITOR

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCotSOperationResultTest, "CotS.Foundation.OperationResult", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FCotSOperationResultTest::RunTest(const FString& Parameters)
{
    FCotSOperationResult Result = FCotSOperationResult::Succeed(TEXT("CotS.Foundation.Test"), true);
    Result.AddAffectedObject(TEXT("/Game/Test.Asset"));
    Result.AddWarning(TEXT("Preview only"));

    TSharedPtr<FJsonObject> Json;
    TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Result.ToJson());
    TestTrue(TEXT("Result serializes to JSON"), FJsonSerializer::Deserialize(Reader, Json));
    TestTrue(TEXT("Result reports success"), Json.IsValid() && Json->GetBoolField(TEXT("success")));
    TestEqual(TEXT("Result preserves operation"), Json->GetStringField(TEXT("operation")), FString(TEXT("CotS.Foundation.Test")));
    TestEqual(TEXT("Result has schema version"), Json->GetStringField(TEXT("schema_version")), FString(CotSOperationResultSchemaVersion));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCotSFoundationRegistrationTest, "CotS.Foundation.ToolRegistration", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FCotSFoundationRegistrationTest::RunTest(const FString& Parameters)
{
    TestTrue(TEXT("Toolset Registry is available"), UToolsetRegistry::IsAvailable());
    TestTrue(TEXT("Foundation toolset is registered"), UToolsetRegistry::IsToolsetClassRegistered(UCotSFoundationToolset::StaticClass()));
    const FString Schema = UToolsetRegistry::GetToolsetJsonSchema(UCotSFoundationToolset::StaticClass());
    TestTrue(TEXT("Foundation schema exposes GetStatus"), Schema.Contains(TEXT("GetStatus")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCotSInspectionRegistrationTest, "CotS.Inspection.ToolRegistration", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FCotSInspectionRegistrationTest::RunTest(const FString& Parameters)
{
    TestTrue(TEXT("Inspection toolset is registered"), UToolsetRegistry::IsToolsetClassRegistered(UCotSInspectionToolset::StaticClass()));
    TestTrue(TEXT("Inspection schema exposes SearchAssets"), UToolsetRegistry::GetToolsetJsonSchema(UCotSInspectionToolset::StaticClass()).Contains(TEXT("SearchAssets")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCotSExecutionRegistrationTest, "CotS.Execution.ToolRegistration", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FCotSExecutionRegistrationTest::RunTest(const FString& Parameters)
{
    TestTrue(TEXT("Execution toolset is registered"), UToolsetRegistry::IsToolsetClassRegistered(UCotSExecutionToolset::StaticClass()));
    TestTrue(TEXT("Execution schema exposes ExecuteReadOnlyQuery"), UToolsetRegistry::GetToolsetJsonSchema(UCotSExecutionToolset::StaticClass()).Contains(TEXT("ExecuteReadOnlyQuery")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCotSExecutionValidQueryTest, "CotS.Execution.ValidHarmlessQuery", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FCotSExecutionValidQueryTest::RunTest(const FString& Parameters)
{
    const FString FirstResponse = UCotSExecutionToolset::ExecuteReadOnlyQuery(TEXT("project.context"));
    const FString SecondResponse = UCotSExecutionToolset::ExecuteReadOnlyQuery(TEXT("project.context"));
    TSharedPtr<FJsonObject> FirstJson;
    TSharedPtr<FJsonObject> SecondJson;
    TestTrue(TEXT("First harmless query returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(FirstResponse), FirstJson));
    TestTrue(TEXT("Repeated harmless query returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(SecondResponse), SecondJson));
    TestTrue(TEXT("Harmless query succeeds"), FirstJson.IsValid() && FirstJson->GetBoolField(TEXT("success")));
    TestEqual(TEXT("Harmless query reports its operation"), FirstJson->GetStringField(TEXT("operation")), FString(TEXT("CotS.Execution.ExecuteReadOnlyQuery")));
    TestTrue(TEXT("Harmless query generates an operation id"), !FirstJson->GetStringField(TEXT("operation_id")).IsEmpty());
    TestTrue(TEXT("Repeat invocation gets a distinct operation id"), FirstJson->GetStringField(TEXT("operation_id")) != SecondJson->GetStringField(TEXT("operation_id")));
    TestTrue(TEXT("Harmless query returns project name"), FirstJson->GetObjectField(TEXT("data"))->HasField(TEXT("project_name")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCotSExecutionFailureTest, "CotS.Execution.RefusesUnsupportedRequests", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FCotSExecutionFailureTest::RunTest(const FString& Parameters)
{
    const TArray<FString> ForbiddenRequests = {
        TEXT("cmd.exe /c whoami"),
        TEXT("powershell -Command Get-Process"),
        TEXT("import subprocess; subprocess.run(['cmd.exe'])"),
        TEXT("raise RuntimeError('not executed')"),
        TEXT("cvar.r.ScreenPercentage; quit")
    };

    for (const FString& Request : ForbiddenRequests)
    {
        TSharedPtr<FJsonObject> Json;
        TestTrue(FString::Printf(TEXT("Forbidden request '%s' returns JSON"), *Request), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSExecutionToolset::ExecuteReadOnlyQuery(Request)), Json));
        TestFalse(FString::Printf(TEXT("Forbidden request '%s' is refused"), *Request), Json.IsValid() && Json->GetBoolField(TEXT("success")));
        TestEqual(FString::Printf(TEXT("Forbidden request '%s' has forbidden error code"), *Request), Json->GetArrayField(TEXT("error_details"))[0]->AsObject()->GetStringField(TEXT("code")), FString(TEXT("forbidden_request")));
    }

    TSharedPtr<FJsonObject> EmptyJson;
    TestTrue(TEXT("Empty request returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSExecutionToolset::ExecuteReadOnlyQuery(TEXT(""))), EmptyJson));
    TestFalse(TEXT("Empty request fails"), EmptyJson.IsValid() && EmptyJson->GetBoolField(TEXT("success")));
    TestEqual(TEXT("Empty request has a stable error code"), EmptyJson->GetArrayField(TEXT("error_details"))[0]->AsObject()->GetStringField(TEXT("code")), FString(TEXT("empty_request")));

    TSharedPtr<FJsonObject> MissingCvarJson;
    TestTrue(TEXT("Missing cvar returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSExecutionToolset::ExecuteReadOnlyQuery(TEXT("cvar.CotS.NonexistentTask007Cvar"))), MissingCvarJson));
    TestFalse(TEXT("Missing cvar fails cleanly"), MissingCvarJson.IsValid() && MissingCvarJson->GetBoolField(TEXT("success")));
    TestEqual(TEXT("Missing cvar uses execution failure code"), MissingCvarJson->GetArrayField(TEXT("error_details"))[0]->AsObject()->GetStringField(TEXT("code")), FString(TEXT("query_execution_failed")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCotSInspectionExactPathTest, "CotS.Inspection.ExactPathsAndEmptyReferences", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FCotSInspectionExactPathTest::RunTest(const FString& Parameters)
{
    IAssetRegistry& Registry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get();
    UPackage* PackageA = CreatePackage(TEXT("/Game/CotSInspectionFixtures/FolderA/SharedInspectionAsset"));
    UPackage* PackageB = CreatePackage(TEXT("/Game/CotSInspectionFixtures/FolderB/SharedInspectionAsset"));
    UCurveFloat* AssetA = NewObject<UCurveFloat>(PackageA, TEXT("SharedInspectionAsset"), RF_Public | RF_Standalone);
    UCurveFloat* AssetB = NewObject<UCurveFloat>(PackageB, TEXT("SharedInspectionAsset"), RF_Public | RF_Standalone);
    FAssetRegistryModule::AssetCreated(AssetA);
    FAssetRegistryModule::AssetCreated(AssetB);

    TSharedPtr<FJsonObject> SearchJson;
    TSharedRef<TJsonReader<>> SearchReader = TJsonReaderFactory<>::Create(UCotSInspectionToolset::SearchAssets(TEXT("SharedInspectionAsset"), TEXT("/Game/CotSInspectionFixtures"), TEXT("/Script/Engine.CurveFloat")));
    TestTrue(TEXT("Ambiguous-name search returns JSON"), FJsonSerializer::Deserialize(SearchReader, SearchJson));
    const TArray<TSharedPtr<FJsonValue>>* Assets = nullptr;
    TestTrue(TEXT("Ambiguous-name search returns an assets collection"), SearchJson.IsValid() && SearchJson->GetObjectField(TEXT("data"))->TryGetArrayField(TEXT("assets"), Assets));
    TestTrue(TEXT("Ambiguous-name search returns both exact paths"), Assets && Assets->Num() == 2);

    TSharedPtr<FJsonObject> DuplicatesJson;
    TSharedRef<TJsonReader<>> DuplicatesReader = TJsonReaderFactory<>::Create(UCotSInspectionToolset::FindDuplicateNames(TEXT("SharedInspectionAsset")));
    TestTrue(TEXT("Duplicate-name query returns JSON"), FJsonSerializer::Deserialize(DuplicatesReader, DuplicatesJson));
    const TArray<TSharedPtr<FJsonValue>>* Duplicates = nullptr;
    TestTrue(TEXT("Duplicate-name query returns the two exact paths"), DuplicatesJson.IsValid() && DuplicatesJson->GetObjectField(TEXT("data"))->TryGetArrayField(TEXT("duplicates"), Duplicates) && Duplicates && Duplicates->Num() == 1);

    TSharedPtr<FJsonObject> ReferencesJson;
    TSharedRef<TJsonReader<>> ReferencesReader = TJsonReaderFactory<>::Create(UCotSInspectionToolset::GetReferences(AssetA->GetPathName(), false));
    TestTrue(TEXT("Zero-dependency query returns JSON"), FJsonSerializer::Deserialize(ReferencesReader, ReferencesJson));
    TestTrue(TEXT("Zero-dependency query succeeds"), ReferencesJson.IsValid() && ReferencesJson->GetBoolField(TEXT("success")));
    const TArray<TSharedPtr<FJsonValue>>* Dependencies = nullptr;
    TestTrue(TEXT("Zero-dependency query has an empty collection"), ReferencesJson->GetObjectField(TEXT("data"))->TryGetArrayField(TEXT("dependencies"), Dependencies) && Dependencies && Dependencies->IsEmpty());

    TSharedPtr<FJsonObject> ReferencersJson;
    TSharedRef<TJsonReader<>> ReferencersReader = TJsonReaderFactory<>::Create(UCotSInspectionToolset::GetReferences(AssetA->GetPathName(), true));
    TestTrue(TEXT("Zero-referencer query returns JSON"), FJsonSerializer::Deserialize(ReferencersReader, ReferencersJson));
    const TArray<TSharedPtr<FJsonValue>>* Referencers = nullptr;
    TestTrue(TEXT("Zero-referencer query succeeds with an empty collection"), ReferencersJson.IsValid() && ReferencersJson->GetBoolField(TEXT("success")) && ReferencersJson->GetObjectField(TEXT("data"))->TryGetArrayField(TEXT("referencers"), Referencers) && Referencers && Referencers->IsEmpty());

    TSharedPtr<FJsonObject> PieJson;
    TestTrue(TEXT("PIE inspection preflight returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSInspectionToolset::GetPIEActorFloatProperty(TEXT("NoActor"), TEXT("RuntimeValue"))), PieJson));
    TestFalse(TEXT("PIE inspection refuses outside PIE"), PieJson.IsValid() && PieJson->GetBoolField(TEXT("success")));
    const FString InspectionSchema = UToolsetRegistry::GetToolsetJsonSchema(UCotSInspectionToolset::StaticClass());
    TestTrue(TEXT("Inspection schema exposes typed PIE inventory and float readers"), InspectionSchema.Contains(TEXT("ListPIEActors")) && InspectionSchema.Contains(TEXT("GetPIEActorFloatProperty")));

    FAssetRegistryModule::AssetDeleted(AssetA);
    FAssetRegistryModule::AssetDeleted(AssetB);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCotSInspectionSkeletonCompatibilityTest, "CotS.Inspection.SkeletonCompatibility", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FCotSInspectionSkeletonCompatibilityTest::RunTest(const FString& Parameters)
{
    // Exercises the TASK-013 locomotion content prerequisite (imported Epic
    // template Mannequin skeleton + Unarmed idle animation), not disposable
    // test fixtures -- both assets are committed, permanent project content.
    const FString SkeletonPath = TEXT("/Game/Characters/Mannequins/Meshes/SK_Mannequin.SK_Mannequin");
    const FString IdlePath = TEXT("/Game/Characters/Mannequins/Anims/Unarmed/MM_Idle.MM_Idle");

    TSharedPtr<FJsonObject> SkeletonJson;
    TestTrue(TEXT("Direct skeleton compatibility query returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSInspectionToolset::GetSkeletonCompatibility(SkeletonPath, SkeletonPath)), SkeletonJson));
    TestTrue(TEXT("Direct skeleton compatibility query succeeds"), SkeletonJson.IsValid() && SkeletonJson->GetBoolField(TEXT("success")));
    TestTrue(TEXT("A skeleton is reported compatible with itself"), SkeletonJson->GetObjectField(TEXT("data"))->GetBoolField(TEXT("is_compatible")));

    TSharedPtr<FJsonObject> AnimJson;
    TestTrue(TEXT("Animation-asset skeleton resolution returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSInspectionToolset::GetSkeletonCompatibility(IdlePath, FString())), AnimJson));
    TestTrue(TEXT("Animation-asset skeleton resolution succeeds"), AnimJson.IsValid() && AnimJson->GetBoolField(TEXT("success")));
    TestEqual(TEXT("Idle animation resolves to the imported Mannequin skeleton"), AnimJson->GetObjectField(TEXT("data"))->GetStringField(TEXT("skeleton")), SkeletonPath);

    TSharedPtr<FJsonObject> AnimationMetadataJson;
    TestTrue(TEXT("Animation metadata inspection returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSInspectionToolset::GetAnimationAsset(IdlePath)), AnimationMetadataJson));
    TestTrue(TEXT("Animation metadata inspection succeeds"), AnimationMetadataJson.IsValid() && AnimationMetadataJson->GetBoolField(TEXT("success")));
    TestFalse(TEXT("Idle animation reports its non-looping setting"), AnimationMetadataJson->GetObjectField(TEXT("data"))->GetBoolField(TEXT("is_looping")));
    TestFalse(TEXT("Idle animation reports no root motion"), AnimationMetadataJson->GetObjectField(TEXT("data"))->GetBoolField(TEXT("has_root_motion")));

    const TArray<FString> LocomotionClipPaths = {
        IdlePath,
        TEXT("/Game/Characters/Mannequins/Anims/Unarmed/Walk/MF_Unarmed_Walk_Fwd.MF_Unarmed_Walk_Fwd"),
        TEXT("/Game/Characters/Mannequins/Anims/Unarmed/Walk/MF_Unarmed_Walk_Bwd.MF_Unarmed_Walk_Bwd"),
        TEXT("/Game/Characters/Mannequins/Anims/Unarmed/Walk/MF_Unarmed_Walk_Left.MF_Unarmed_Walk_Left"),
        TEXT("/Game/Characters/Mannequins/Anims/Unarmed/Walk/MF_Unarmed_Walk_Right.MF_Unarmed_Walk_Right"),
        TEXT("/Game/Characters/Mannequins/Anims/Unarmed/Jump/MM_Jump.MM_Jump"),
        TEXT("/Game/Characters/Mannequins/Anims/Unarmed/Jump/MM_Fall_Loop.MM_Fall_Loop"),
        TEXT("/Game/Characters/Mannequins/Anims/Unarmed/Jump/MM_Land.MM_Land")
    };
    for (const FString& ClipPath : LocomotionClipPaths)
    {
        TSharedPtr<FJsonObject> ClipMetadataJson;
        TestTrue(FString::Printf(TEXT("Locomotion clip metadata returns JSON: %s"), *ClipPath), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSInspectionToolset::GetAnimationAsset(ClipPath)), ClipMetadataJson));
        TestTrue(FString::Printf(TEXT("Locomotion clip metadata succeeds: %s"), *ClipPath), ClipMetadataJson.IsValid() && ClipMetadataJson->GetBoolField(TEXT("success")));
        if (ClipMetadataJson.IsValid() && ClipMetadataJson->GetBoolField(TEXT("success")))
        {
            const TSharedPtr<FJsonObject> ClipData = ClipMetadataJson->GetObjectField(TEXT("data"));
            AddInfo(FString::Printf(TEXT("TASK-013 metadata %s looping=%s root_motion=%s"), *ClipPath, ClipData->GetBoolField(TEXT("is_looping")) ? TEXT("true") : TEXT("false"), ClipData->GetBoolField(TEXT("has_root_motion")) ? TEXT("true") : TEXT("false")));
        }
    }

    TSharedPtr<FJsonObject> MissingJson;
    TestTrue(TEXT("Nonexistent object path returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSInspectionToolset::GetSkeletonCompatibility(TEXT("/Game/Characters/Mannequins/Meshes/Missing.Missing"), FString())), MissingJson));
    TestFalse(TEXT("Nonexistent object path fails cleanly"), MissingJson.IsValid() && MissingJson->GetBoolField(TEXT("success")));

    UIKRetargeter* RetargeterFixture = NewObject<UIKRetargeter>(GetTransientPackage(), TEXT("CotSRetargeterInspectionFixture"));
    TSharedPtr<FJsonObject> RetargeterJson;
    TestTrue(TEXT("Transient IK Retargeter inspection returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSInspectionToolset::GetIKRetargeter(RetargeterFixture->GetPathName())), RetargeterJson));
    TestTrue(TEXT("Transient IK Retargeter inspection succeeds"), RetargeterJson.IsValid() && RetargeterJson->GetBoolField(TEXT("success")));
    const TSharedPtr<FJsonObject> RetargeterData = RetargeterJson->GetObjectField(TEXT("data"));
    TestFalse(TEXT("New Retargeter has no source rig"), RetargeterData->GetBoolField(TEXT("has_source_ik_rig")));
    TestFalse(TEXT("New Retargeter has no target rig"), RetargeterData->GetBoolField(TEXT("has_target_ik_rig")));

    UAnimBlueprint* AnimBlueprintFixture = NewObject<UAnimBlueprint>(GetTransientPackage(), TEXT("CotSAnimBlueprintInspectionFixture"));
    TSharedPtr<FJsonObject> AnimBlueprintJson;
    TestTrue(TEXT("Transient AnimBlueprint state-machine inspection returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSInspectionToolset::GetAnimBlueprintStateMachines(AnimBlueprintFixture->GetPathName())), AnimBlueprintJson));
    TestTrue(TEXT("Transient AnimBlueprint state-machine inspection succeeds"), AnimBlueprintJson.IsValid() && AnimBlueprintJson->GetBoolField(TEXT("success")));
    TestEqual(TEXT("New AnimBlueprint contains no state machines"), AnimBlueprintJson->GetObjectField(TEXT("data"))->GetArrayField(TEXT("state_machines")).Num(), 0);

    TSharedPtr<FJsonObject> BatchGuardJson;
    TestTrue(TEXT("Empty retarget batch returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSMutationToolset::BatchRetargetAnimationAssets({}, TEXT("/Game/Missing.Missing"), TEXT("/Game/CotSMutationLive/Retargeted"), true)), BatchGuardJson));
    TestFalse(TEXT("Empty retarget batch is rejected before mutation"), BatchGuardJson.IsValid() && BatchGuardJson->GetBoolField(TEXT("success")));

    // Since TASK-013 imported a real compatible preview mesh (SKM_Quinn_Simple)
    // for this Skeleton, USkeleton::GetPreviewMesh(bFindIfNotSet=true) now
    // finds and caches it (Skeleton.cpp: GetPreviewMesh -> FindCompatibleMesh
    // -> SetPreviewMesh), so an empty PreviewMeshPath no longer fails to
    // resolve -- it now proves the "let UE resolve the Skeleton's preview
    // mesh" fallback documented on these tools actually works.
    TSharedPtr<FJsonObject> BlendSpaceDryRunJson;
    TestTrue(TEXT("Disposable locomotion Blend Space dry-run returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSMutationToolset::CreateDisposableLocomotionBlendSpace(TEXT("/Game/CotSMutationLive/BS_AutomationPreview.BS_AutomationPreview"), SkeletonPath, FString(), true)), BlendSpaceDryRunJson));
    TestTrue(TEXT("Disposable locomotion Blend Space dry-run resolves the Skeleton's auto-discovered preview mesh"), BlendSpaceDryRunJson.IsValid() && BlendSpaceDryRunJson->GetBoolField(TEXT("success")));

    TSharedPtr<FJsonObject> AnimBlueprintDryRunJson;
    TestTrue(TEXT("Disposable AnimBlueprint dry-run returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSMutationToolset::CreateDisposableAnimBlueprint(TEXT("/Game/CotSMutationLive/ABP_AutomationPreview.ABP_AutomationPreview"), SkeletonPath, FString(), true)), AnimBlueprintDryRunJson));
    TestTrue(TEXT("Disposable AnimBlueprint dry-run resolves the Skeleton's auto-discovered preview mesh"), AnimBlueprintDryRunJson.IsValid() && AnimBlueprintDryRunJson->GetBoolField(TEXT("success")));

    TSharedPtr<FJsonObject> StateMachineGuardJson;
    TestTrue(TEXT("Disposable State Machine dry-run returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSMutationToolset::AddDisposableAnimBlueprintStateMachine(TEXT("/Game/CotSMutationLive/ABP_Missing.ABP_Missing"), true)), StateMachineGuardJson));
    TestFalse(TEXT("Disposable State Machine dry-run rejects a missing AnimBlueprint"), StateMachineGuardJson.IsValid() && StateMachineGuardJson->GetBoolField(TEXT("success")));

    TSharedPtr<FJsonObject> StateGuardJson;
    TestTrue(TEXT("Disposable State dry-run returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSMutationToolset::AddDisposableAnimBlueprintState(TEXT("/Game/CotSMutationLive/ABP_Missing.ABP_Missing"), TEXT("Idle"), true)), StateGuardJson));
    TestFalse(TEXT("Disposable State dry-run rejects a missing AnimBlueprint"), StateGuardJson.IsValid() && StateGuardJson->GetBoolField(TEXT("success")));

    TSharedPtr<FJsonObject> TransitionGuardJson;
    TestTrue(TEXT("Disposable transition dry-run returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSMutationToolset::AddDisposableAnimBlueprintTransition(TEXT("/Game/CotSMutationLive/ABP_Missing.ABP_Missing"), TEXT("Idle"), TEXT("Walk"), 0.2, true)), TransitionGuardJson));
    TestFalse(TEXT("Disposable transition dry-run rejects a missing AnimBlueprint"), TransitionGuardJson.IsValid() && TransitionGuardJson->GetBoolField(TEXT("success")));

    TSharedPtr<FJsonObject> SequenceGuardJson;
    TestTrue(TEXT("Disposable State sequence dry-run returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSMutationToolset::SetDisposableAnimBlueprintStateSequence(TEXT("/Game/CotSMutationLive/ABP_Missing.ABP_Missing"), TEXT("Idle"), IdlePath, false, true)), SequenceGuardJson));
    TestFalse(TEXT("Disposable State sequence dry-run rejects a missing AnimBlueprint"), SequenceGuardJson.IsValid() && SequenceGuardJson->GetBoolField(TEXT("success")));

    TSharedPtr<FJsonObject> TransitionRuleGuardJson;
    TestTrue(TEXT("Disposable transition-rule dry-run returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSMutationToolset::SetDisposableAnimBlueprintTransitionRule(TEXT("/Game/CotSMutationLive/ABP_Missing.ABP_Missing"), TEXT("Idle"), TEXT("Walk"), true, true)), TransitionRuleGuardJson));
    TestFalse(TEXT("Disposable transition-rule dry-run rejects a missing AnimBlueprint"), TransitionRuleGuardJson.IsValid() && TransitionRuleGuardJson->GetBoolField(TEXT("success")));

    TSharedPtr<FJsonObject> OutputWireGuardJson;
    TestTrue(TEXT("Disposable AnimGraph output dry-run returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSMutationToolset::WireDisposableAnimBlueprintStateMachineOutput(TEXT("/Game/CotSMutationLive/ABP_Missing.ABP_Missing"), true)), OutputWireGuardJson));
    TestFalse(TEXT("Disposable AnimGraph output dry-run rejects a missing AnimBlueprint"), OutputWireGuardJson.IsValid() && OutputWireGuardJson->GetBoolField(TEXT("success")));

    TSharedPtr<FJsonObject> LocomotionPolicyJson;
    TestTrue(TEXT("Locomotion policy validation returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSValidationToolset::ValidateLocomotionPolicy(SkeletonPath, {}, { IdlePath }, { TEXT("root"), TEXT("pelvis"), TEXT("ik_foot_l"), TEXT("ik_foot_r") }, false)), LocomotionPolicyJson));
    TestTrue(TEXT("Imported idle passes the non-looping, in-place, required-IK-bones policy"), LocomotionPolicyJson.IsValid() && LocomotionPolicyJson->GetBoolField(TEXT("success")));

    const TArray<FString> LoopingLocomotionClips = { LocomotionClipPaths[1], LocomotionClipPaths[2], LocomotionClipPaths[3], LocomotionClipPaths[4] };
    const TArray<FString> OneShotLocomotionClips = { LocomotionClipPaths[0], LocomotionClipPaths[5], LocomotionClipPaths[6], LocomotionClipPaths[7] };
    TSharedPtr<FJsonObject> CompleteLocomotionPolicyJson;
    TestTrue(TEXT("Complete mixed locomotion policy validation returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UCotSValidationToolset::ValidateLocomotionPolicyWithRootMotionSet(SkeletonPath, LoopingLocomotionClips, OneShotLocomotionClips, LoopingLocomotionClips, { TEXT("root"), TEXT("pelvis"), TEXT("ik_foot_l"), TEXT("ik_foot_r") })), CompleteLocomotionPolicyJson));
    TestTrue(TEXT("Complete locomotion set passes per-clip looping/root-motion and required-IK-bones policy"), CompleteLocomotionPolicyJson.IsValid() && CompleteLocomotionPolicyJson->GetBoolField(TEXT("success")));

    // Regression test for a real bug found via a live PIE run (see
    // Docs/Validation/TASK-013_LOCOMOTION_CONTENT_PREREQUISITE.md, twentieth
    // increment): SetDisposableAnimBlueprintTransitionRule used to write only
    // FAnimNode_TransitionResult::bCanEnterTransition, a runtime struct field
    // the transition-graph compiler ignores for its PinShownByDefault input;
    // the transition then compiled without error but could never be taken.
    // This exercises the full real (non-dry-run) pipeline the manual PIE
    // proof used and asserts the underlying graph pin itself, not just the
    // tool's own self-reported JSON, actually changes.
    const FString QuinnPreviewMeshPath = TEXT("/Game/Characters/Mannequins/Meshes/SKM_Quinn_Simple.SKM_Quinn_Simple");
    const FString TransitionRuleFixturePath = TEXT("/Game/CotSMutationLive/ABP_TransitionRuleFix.ABP_TransitionRuleFix");
    UCotSMutationToolset::DeleteDisposableAsset(TransitionRuleFixturePath, false);
    auto ParseMutation = [this](const FString& Text, TSharedPtr<FJsonObject>& Json, const TCHAR* Label) { return TestTrue(Label, FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Json)); };
    TSharedPtr<FJsonObject> FixtureJson;
    ParseMutation(UCotSMutationToolset::CreateDisposableAnimBlueprint(TransitionRuleFixturePath, SkeletonPath, QuinnPreviewMeshPath, false), FixtureJson, TEXT("Transition-rule fixture AnimBlueprint creation returns JSON"));
    TestTrue(TEXT("Transition-rule fixture AnimBlueprint creation succeeds"), FixtureJson.IsValid() && FixtureJson->GetBoolField(TEXT("success")));
    ParseMutation(UCotSMutationToolset::AddDisposableAnimBlueprintStateMachine(TransitionRuleFixturePath, false), FixtureJson, TEXT("Transition-rule fixture State Machine creation returns JSON"));
    TestTrue(TEXT("Transition-rule fixture State Machine creation succeeds"), FixtureJson.IsValid() && FixtureJson->GetBoolField(TEXT("success")));
    ParseMutation(UCotSMutationToolset::AddDisposableAnimBlueprintState(TransitionRuleFixturePath, TEXT("A"), false), FixtureJson, TEXT("Transition-rule fixture State A creation returns JSON"));
    TestTrue(TEXT("Transition-rule fixture State A creation succeeds"), FixtureJson.IsValid() && FixtureJson->GetBoolField(TEXT("success")));
    ParseMutation(UCotSMutationToolset::AddDisposableAnimBlueprintState(TransitionRuleFixturePath, TEXT("B"), false), FixtureJson, TEXT("Transition-rule fixture State B creation returns JSON"));
    TestTrue(TEXT("Transition-rule fixture State B creation succeeds"), FixtureJson.IsValid() && FixtureJson->GetBoolField(TEXT("success")));
    ParseMutation(UCotSMutationToolset::AddDisposableAnimBlueprintTransition(TransitionRuleFixturePath, TEXT("A"), TEXT("B"), 0.2, false), FixtureJson, TEXT("Transition-rule fixture transition creation returns JSON"));
    TestTrue(TEXT("Transition-rule fixture transition creation succeeds"), FixtureJson.IsValid() && FixtureJson->GetBoolField(TEXT("success")));
    ParseMutation(UCotSMutationToolset::SetDisposableAnimBlueprintTransitionRule(TransitionRuleFixturePath, TEXT("A"), TEXT("B"), true, false), FixtureJson, TEXT("Transition-rule fixture rule authoring returns JSON"));
    TestTrue(TEXT("Transition-rule fixture rule authoring succeeds"), FixtureJson.IsValid() && FixtureJson->GetBoolField(TEXT("success")));
    TestFalse(TEXT("Transition-rule reported false before the fix"), FixtureJson.IsValid() && FixtureJson->GetObjectField(TEXT("data"))->GetBoolField(TEXT("before_can_enter_transition")));
    TestTrue(TEXT("Transition-rule reports true after authoring"), FixtureJson.IsValid() && FixtureJson->GetObjectField(TEXT("data"))->GetBoolField(TEXT("after_can_enter_transition")));

    UAnimBlueprint* FixtureBlueprint = Cast<UAnimBlueprint>(StaticLoadObject(UAnimBlueprint::StaticClass(), nullptr, *TransitionRuleFixturePath));
    UAnimationGraph* FixtureAnimGraph = nullptr;
    for (UEdGraph* Graph : FixtureBlueprint->FunctionGraphs) { if (UAnimationGraph* Candidate = Cast<UAnimationGraph>(Graph)) { FixtureAnimGraph = Candidate; break; } }
    TArray<UAnimGraphNode_Base*> FixtureMachines;
    FixtureAnimGraph->GetGraphNodesOfClass(UAnimGraphNode_StateMachine::StaticClass(), FixtureMachines, true);
    UAnimGraphNode_StateMachine* FixtureMachine = Cast<UAnimGraphNode_StateMachine>(FixtureMachines[0]);
    TArray<UAnimStateTransitionNode*> FixtureTransitions;
    FixtureMachine->EditorStateMachineGraph->GetNodesOfClass(FixtureTransitions);
    UAnimGraphNode_TransitionResult* FixtureResultNode = Cast<UAnimationTransitionGraph>(FixtureTransitions[0]->BoundGraph)->GetResultNode();
    UEdGraphPin* FixtureCanEnterPin = FixtureResultNode->FindPin(TEXT("bCanEnterTransition"));
    TestNotNull(TEXT("Transition Result node exposes a bCanEnterTransition pin"), FixtureCanEnterPin);
    TestEqual(TEXT("The pin itself (not just the runtime struct) carries the authored default value"), FixtureCanEnterPin->DefaultValue, FString(TEXT("true")));

    TSharedPtr<FJsonObject> IdempotentRuleJson;
    ParseMutation(UCotSMutationToolset::SetDisposableAnimBlueprintTransitionRule(TransitionRuleFixturePath, TEXT("A"), TEXT("B"), true, false), IdempotentRuleJson, TEXT("Repeated transition-rule authoring returns JSON"));
    TestEqual(TEXT("Repeating the same rule is a deterministic no-op reading the pin, not the stale struct"), IdempotentRuleJson->GetStringField(TEXT("status")), FString(TEXT("no_change")));

    UCotSMutationToolset::DeleteDisposableAsset(TransitionRuleFixturePath, false);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCotSMutationRegistrationTest, "CotS.Mutation.ToolRegistration", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FCotSMutationRegistrationTest::RunTest(const FString& Parameters)
{
    TestTrue(TEXT("Mutation toolset is registered"), UToolsetRegistry::IsToolsetClassRegistered(UCotSMutationToolset::StaticClass()));
    const FString Schema = UToolsetRegistry::GetToolsetJsonSchema(UCotSMutationToolset::StaticClass());
    TestTrue(TEXT("Mutation schema exposes preview-capable asset move and disposable map creation"), Schema.Contains(TEXT("MoveAsset")) && Schema.Contains(TEXT("CreateDisposableMap")) && Schema.Contains(TEXT("bDryRun")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCotSLifecyclePreflightTest, "CotS.Lifecycle.PreflightAndRegistration", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FCotSLifecyclePreflightTest::RunTest(const FString& Parameters)
{
    TestTrue(TEXT("Lifecycle toolset is registered"), UToolsetRegistry::IsToolsetClassRegistered(UCotSLifecycleToolset::StaticClass()));
    const FString Schema = UToolsetRegistry::GetToolsetJsonSchema(UCotSLifecycleToolset::StaticClass());
    TestTrue(TEXT("Lifecycle schema exposes only the fixed shutdown operation"), Schema.Contains(TEXT("RequestToolLabShutdown")));
    TestFalse(TEXT("Transient package is not persistent shutdown state"), UCotSLifecycleToolset::IsPersistentPackageForShutdown(GetTransientPackage()));

    UPackage* Fixture = CreatePackage(TEXT("/Game/CotSLifecycleFixture"));
    Fixture->SetDirtyFlag(true);
    const TArray<FString> DirtyPackages = UCotSLifecycleToolset::GetPersistentDirtyPackagePaths();
    TestTrue(TEXT("Persistent dirty package is reported for shutdown refusal"), DirtyPackages.Contains(TEXT("/Game/CotSLifecycleFixture")));
    Fixture->SetDirtyFlag(false);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCotSValidationRegistrationTest, "CotS.Validation.ToolRegistration", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FCotSValidationRegistrationTest::RunTest(const FString& Parameters)
{
    TestTrue(TEXT("Validation toolset is registered"), UToolsetRegistry::IsToolsetClassRegistered(UCotSValidationToolset::StaticClass()));
    const FString Schema = UToolsetRegistry::GetToolsetJsonSchema(UCotSValidationToolset::StaticClass());
    TestTrue(TEXT("Validation schema exposes exact asset and folder validation"), Schema.Contains(TEXT("ValidateAsset")) && Schema.Contains(TEXT("ValidateFolder")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCotSMutationAssetWorkflowTest, "CotS.Mutation.AssetWorkflowAndGuardrails", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FCotSMutationAssetWorkflowTest::RunTest(const FString& Parameters)
{
    const FString Source = TEXT("/Game/CotSMutationLive/Curve_Source.Curve_Source");
    const FString Moved = TEXT("/Game/CotSMutationLive/Curve_Moved.Curve_Moved");
    const FString Copy = TEXT("/Game/CotSMutationLive/Curve_Copy.Curve_Copy");
    UCotSMutationToolset::DeleteDisposableAsset(Source, false);
    UCotSMutationToolset::DeleteDisposableAsset(Moved, false);
    UCotSMutationToolset::DeleteDisposableAsset(Copy, false);
    auto Parse = [this](const FString& Text, TSharedPtr<FJsonObject>& Json, const TCHAR* Label) { return TestTrue(Label, FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Json)); };
    TSharedPtr<FJsonObject> Json;
    Parse(UCotSMutationToolset::CreateCurveFloat(Source, false), Json, TEXT("Create returns structured result"));
    TestTrue(TEXT("Create succeeds"), Json.IsValid() && Json->GetBoolField(TEXT("success")) && !Json->GetStringField(TEXT("operation_id")).IsEmpty());
    Parse(UCotSInspectionToolset::GetAsset(Source), Json, TEXT("Independent pre-move inspection returns JSON"));
    TestTrue(TEXT("Independent inspection finds source"), Json->GetObjectField(TEXT("data"))->GetBoolField(TEXT("exists")));
    Parse(UCotSMutationToolset::MoveAsset(Source, Moved, true), Json, TEXT("Move preview returns JSON"));
    TestTrue(TEXT("Dry-run does not mutate"), Json->GetBoolField(TEXT("dry_run")) && Json->GetBoolField(TEXT("success")));
    Parse(UCotSInspectionToolset::GetAsset(Source), Json, TEXT("Post-preview inspection returns JSON"));
    TestTrue(TEXT("Source remains after dry-run"), Json->GetObjectField(TEXT("data"))->GetBoolField(TEXT("exists")));
    Parse(UCotSMutationToolset::MoveAsset(Source, Moved, false), Json, TEXT("Move returns JSON")); TestTrue(TEXT("Move succeeds"), Json->GetBoolField(TEXT("success")));
    Parse(UCotSInspectionToolset::GetAsset(Moved), Json, TEXT("Destination re-inspection returns JSON")); TestTrue(TEXT("Destination exists"), Json->GetObjectField(TEXT("data"))->GetBoolField(TEXT("exists")));
    Parse(UCotSInspectionToolset::GetAsset(Source), Json, TEXT("Source absence inspection returns JSON")); TestFalse(TEXT("Old source is absent"), Json->GetObjectField(TEXT("data"))->GetBoolField(TEXT("exists")));
    Parse(UCotSMutationToolset::SetCurveEventFlag(Moved, true, false), Json, TEXT("Typed property mutation returns JSON")); TestTrue(TEXT("Property mutation succeeds"), Json->GetBoolField(TEXT("success")) && Json->GetObjectField(TEXT("data"))->GetBoolField(TEXT("transaction_undo_available")));
    Parse(UCotSInspectionToolset::GetCurveFloat(Moved), Json, TEXT("Property re-inspection returns JSON")); TestTrue(TEXT("Exact property value re-inspected"), Json->GetObjectField(TEXT("data"))->GetBoolField(TEXT("is_event_curve")));
    Parse(UCotSMutationToolset::SetCurveEventFlag(Moved, true, false), Json, TEXT("Property no-op returns JSON")); TestEqual(TEXT("Property no-op deterministic"), Json->GetStringField(TEXT("status")), FString(TEXT("no_change")));
    Parse(UCotSMutationToolset::DuplicateAsset(Moved, Copy, false), Json, TEXT("Duplicate returns JSON")); TestTrue(TEXT("Duplicate succeeds"), Json->GetBoolField(TEXT("success")));
    Parse(UCotSInspectionToolset::GetAsset(Copy), Json, TEXT("Duplicate re-inspection returns JSON")); TestTrue(TEXT("Duplicate exists"), Json->GetObjectField(TEXT("data"))->GetBoolField(TEXT("exists")));
    Parse(UCotSMutationToolset::MoveAsset(Moved, Copy, true), Json, TEXT("Collision preview returns JSON")); TestFalse(TEXT("Destination collision rejected"), Json->GetBoolField(TEXT("success")));
    Parse(UCotSMutationToolset::MoveAsset(TEXT("Curve_Moved"), Copy, true), Json, TEXT("Ambiguous short name rejected as JSON")); TestFalse(TEXT("Ambiguous short asset name rejected"), Json->GetBoolField(TEXT("success")));
    Parse(UCotSMutationToolset::SetCurveEventFlag(Copy, false, false), Json, TEXT("Supported-property test result returns JSON"));
    Parse(UCotSMutationToolset::SetCurveEventFlag(TEXT("/Game/CotSMutationLive/Missing.Missing"), true, false), Json, TEXT("Nonexistent property target returns JSON")); TestFalse(TEXT("Nonexistent exact target deterministic"), Json->GetBoolField(TEXT("success")));
    Parse(UCotSMutationToolset::SaveAsset(Moved, false), Json, TEXT("Save returns JSON")); TestTrue(TEXT("Save succeeds"), Json->GetBoolField(TEXT("success")));
    Parse(UCotSMutationToolset::DeleteDisposableAsset(Moved, false), Json, TEXT("Moved cleanup returns JSON")); Parse(UCotSMutationToolset::DeleteDisposableAsset(Copy, false), Json, TEXT("Copy cleanup returns JSON"));
    Parse(UCotSInspectionToolset::GetAsset(Moved), Json, TEXT("Final moved cleanup inspection returns JSON")); TestFalse(TEXT("Moved asset cleaned up"), Json->GetObjectField(TEXT("data"))->GetBoolField(TEXT("exists")));
    Parse(UCotSInspectionToolset::GetAsset(Copy), Json, TEXT("Final copy cleanup inspection returns JSON")); TestFalse(TEXT("Copy asset cleaned up"), Json->GetObjectField(TEXT("data"))->GetBoolField(TEXT("exists")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCotSMutationActorWorkflowTest, "CotS.Mutation.ActorWorkflow", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FCotSMutationActorWorkflowTest::RunTest(const FString& Parameters)
{
    const FString Label = TEXT("CotSMutation_Task008Actor");
    const FString DryRunLabel = TEXT("CotSMutation_Task008ActorDryRun");
    const FString ComponentName = TEXT("CotSMutation_TestComponent");
    auto Parse = [this](const FString& Text, TSharedPtr<FJsonObject>& Json, const TCHAR* LabelText) { return TestTrue(LabelText, FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Json)); };
    TSharedPtr<FJsonObject> Json;
    Parse(UCotSMutationToolset::CreateDisposableActor(DryRunLabel, 1, 2, 3, true), Json, TEXT("Actor create dry-run returns JSON"));
    TestTrue(TEXT("Actor create dry-run is marked and succeeds"), Json->GetBoolField(TEXT("success")) && Json->GetBoolField(TEXT("dry_run")));
    const TSharedPtr<FJsonObject> DryRunData = Json->GetObjectField(TEXT("data"));
    TestTrue(TEXT("Actor create dry-run exposes intended label, not a fabricated actor path"), DryRunData->GetStringField(TEXT("preview_actor_label")) == DryRunLabel && !DryRunData->HasField(TEXT("actor_path")));
    Parse(UCotSMutationToolset::CreateDisposableActor(Label, 10, 20, 30, false), Json, TEXT("Actor create returns JSON"));
    TestTrue(TEXT("Actor create succeeds"), Json->GetBoolField(TEXT("success")));
    const TSharedPtr<FJsonObject> CreateData = Json->GetObjectField(TEXT("data"));
    TestTrue(TEXT("Actor create returns non-empty canonical data.actor_path"), CreateData.IsValid() && !CreateData->GetStringField(TEXT("actor_path")).IsEmpty());
    const TArray<TSharedPtr<FJsonValue>>& Paths = Json->GetArrayField(TEXT("affected_object_paths"));
    TestTrue(TEXT("Actor create reports exact path"), !Paths.IsEmpty());
    const FString ActorPath = CreateData->GetStringField(TEXT("actor_path"));
    TestTrue(TEXT("Affected object paths contain returned actor path"), Paths.ContainsByPredicate([&ActorPath](const TSharedPtr<FJsonValue>& Value) { return Value.IsValid() && Value->AsString() == ActorPath; }));
    Parse(UCotSInspectionToolset::GetActor(ActorPath), Json, TEXT("Actor pre-inspection returns JSON")); TestTrue(TEXT("Actor exists after create"), Json->GetObjectField(TEXT("data"))->GetBoolField(TEXT("exists")));
    Parse(UCotSMutationToolset::SetActorLocation(ActorPath, 100, 200, 300, true), Json, TEXT("Actor transform dry-run returns JSON")); TestTrue(TEXT("Actor dry-run is marked"), Json->GetBoolField(TEXT("dry_run")));
    Parse(UCotSMutationToolset::SetActorLocation(ActorPath, std::numeric_limits<double>::quiet_NaN(), 0, 0, false), Json, TEXT("Invalid property value returns JSON")); TestFalse(TEXT("Invalid property value rejected"), Json->GetBoolField(TEXT("success")));
    Parse(UCotSMutationToolset::SetActorLocation(ActorPath, 100, 200, 300, false), Json, TEXT("Actor transform returns JSON"));
    Parse(UCotSInspectionToolset::GetActor(ActorPath), Json, TEXT("Actor transform re-inspection returns JSON")); TestTrue(TEXT("Actor transform independently verified"), Json->GetObjectField(TEXT("data"))->GetStringField(TEXT("location")).Contains(TEXT("X=100.000")));
    Parse(UCotSMutationToolset::AddSceneComponent(ActorPath, ComponentName, false), Json, TEXT("Component add returns JSON")); TestTrue(TEXT("Component add succeeds"), Json->GetBoolField(TEXT("success")));
    const FString ComponentPath = Json->GetObjectField(TEXT("data"))->GetStringField(TEXT("component_path"));
    TestTrue(TEXT("Component add returns non-empty canonical component path"), !ComponentPath.IsEmpty());
    Parse(UCotSMutationToolset::AddSceneComponent(ActorPath, ComponentName, false), Json, TEXT("Duplicate component returns JSON")); TestEqual(TEXT("Duplicate component is deterministic no-op"), Json->GetStringField(TEXT("status")), FString(TEXT("no_change"))); TestEqual(TEXT("Duplicate add returns same component path"), Json->GetObjectField(TEXT("data"))->GetStringField(TEXT("component_path")), ComponentPath);
    Parse(UCotSInspectionToolset::GetActor(ActorPath), Json, TEXT("Component re-inspection returns JSON")); TestTrue(TEXT("Component appears in independent inspection at returned path"), Json->GetObjectField(TEXT("data"))->GetArrayField(TEXT("components")).ContainsByPredicate([&ComponentPath](const TSharedPtr<FJsonValue>& Value) { return Value.IsValid() && Value->AsString() == ComponentPath; }));
    Parse(UCotSMutationToolset::RemoveSceneComponent(ActorPath, ComponentName, false), Json, TEXT("Component remove returns JSON")); TestTrue(TEXT("Component remove returns removed canonical component path"), Json->GetObjectField(TEXT("data"))->GetStringField(TEXT("component_path")) == ComponentPath);
    Parse(UCotSInspectionToolset::GetActor(ActorPath), Json, TEXT("Component absence re-inspection returns JSON")); TestFalse(TEXT("Component is absent after remove"), Json->GetObjectField(TEXT("data"))->GetArrayField(TEXT("components")).ContainsByPredicate([&ComponentPath](const TSharedPtr<FJsonValue>& Value) { return Value.IsValid() && Value->AsString() == ComponentPath; }));
    Parse(UCotSMutationToolset::DeleteDisposableActor(ActorPath, false), Json, TEXT("Actor delete returns JSON")); TestTrue(TEXT("Actor delete succeeds"), Json->GetBoolField(TEXT("success")));
    Parse(UCotSInspectionToolset::GetActor(ActorPath), Json, TEXT("Actor absence re-inspection returns JSON")); TestFalse(TEXT("Actor cleaned up"), Json->GetObjectField(TEXT("data"))->GetBoolField(TEXT("exists")));
    return true;
}

#endif
