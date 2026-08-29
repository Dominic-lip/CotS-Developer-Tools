#include "Foundation/CotSFoundationToolset.h"

#include "Core/CotSOperationResult.h"
#include "Dom/JsonObject.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/EngineVersion.h"

#include UE_INLINE_GENERATED_CPP_BY_NAME(CotSFoundationToolset)

FString UCotSFoundationToolset::GetStatus()
{
    FCotSOperationResult Result = FCotSOperationResult::Succeed(TEXT("CotS.Foundation.GetStatus"));
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("plugin"), TEXT("CotSDeveloperTools"));
    Result.Data->SetStringField(TEXT("plugin_version"), IPluginManager::Get().FindPlugin(TEXT("CotSDeveloperTools")).IsValid()
        ? IPluginManager::Get().FindPlugin(TEXT("CotSDeveloperTools"))->GetDescriptor().VersionName
        : TEXT("unknown"));
    Result.Data->SetStringField(TEXT("unreal_version"), FEngineVersion::Current().ToString());
    Result.Data->SetStringField(TEXT("foundation_api_version"), TEXT("1.0"));
    Result.Data->SetStringField(TEXT("operation_result_schema_version"), CotSOperationResultSchemaVersion);
    return Result.ToJson();
}
