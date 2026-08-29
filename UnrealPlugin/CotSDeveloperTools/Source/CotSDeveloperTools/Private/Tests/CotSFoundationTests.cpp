#include "Core/CotSOperationResult.h"
#include "Execution/CotSExecutionToolset.h"
#include "Foundation/CotSFoundationToolset.h"
#include "Inspection/CotSInspectionToolset.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Curves/CurveFloat.h"
#include "Misc/AutomationTest.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "ToolsetRegistry/UToolsetRegistry.h"

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

#endif
