#include "Core/CotSOperationResult.h"
#include "Execution/CotSExecutionToolset.h"
#include "Foundation/CotSFoundationToolset.h"
#include "Inspection/CotSInspectionToolset.h"
#include "Lifecycle/CotSLifecycleToolset.h"
#include "Mutation/CotSMutationToolset.h"
#include "Validation/CotSValidationToolset.h"
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

    FAssetRegistryModule::AssetDeleted(AssetA);
    FAssetRegistryModule::AssetDeleted(AssetB);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCotSMutationRegistrationTest, "CotS.Mutation.ToolRegistration", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FCotSMutationRegistrationTest::RunTest(const FString& Parameters)
{
    TestTrue(TEXT("Mutation toolset is registered"), UToolsetRegistry::IsToolsetClassRegistered(UCotSMutationToolset::StaticClass()));
    const FString Schema = UToolsetRegistry::GetToolsetJsonSchema(UCotSMutationToolset::StaticClass());
    TestTrue(TEXT("Mutation schema exposes preview-capable asset move"), Schema.Contains(TEXT("MoveAsset")) && Schema.Contains(TEXT("bDryRun")));
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
