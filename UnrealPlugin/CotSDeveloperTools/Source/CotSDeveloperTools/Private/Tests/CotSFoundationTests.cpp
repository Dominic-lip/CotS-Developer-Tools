#include "Core/CotSOperationResult.h"
#include "Foundation/CotSFoundationToolset.h"
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

#endif
