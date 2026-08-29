#include "CotSDeveloperToolsModule.h"

#include "Foundation/CotSFoundationToolset.h"
#include "Execution/CotSExecutionToolset.h"
#include "Inspection/CotSInspectionToolset.h"
#include "Lifecycle/CotSLifecycleToolset.h"
#include "Mutation/CotSMutationToolset.h"
#include "Validation/CotSValidationToolset.h"
#include "Misc/CoreDelegates.h"
#include "ToolsetRegistry/UToolsetRegistry.h"

DEFINE_LOG_CATEGORY(LogCotSDeveloperTools);

void FCotSDeveloperToolsModule::StartupModule()
{
    if (UToolsetRegistry::IsAvailable())
    {
        RegisterToolsets();
        return;
    }

    PostEngineInitHandle = FCoreDelegates::GetOnPostEngineInit().AddRaw(this, &FCotSDeveloperToolsModule::RegisterToolsets);
}

void FCotSDeveloperToolsModule::RegisterToolsets()
{
    if (bToolsetsRegistered)
    {
        return;
    }

    UToolsetRegistry::RegisterToolsetClass(UCotSFoundationToolset::StaticClass());
    UToolsetRegistry::RegisterToolsetClass(UCotSInspectionToolset::StaticClass());
    UToolsetRegistry::RegisterToolsetClass(UCotSExecutionToolset::StaticClass());
    UToolsetRegistry::RegisterToolsetClass(UCotSMutationToolset::StaticClass());
    UToolsetRegistry::RegisterToolsetClass(UCotSLifecycleToolset::StaticClass());
    UToolsetRegistry::RegisterToolsetClass(UCotSValidationToolset::StaticClass());
    bToolsetsRegistered = UToolsetRegistry::IsToolsetClassRegistered(UCotSFoundationToolset::StaticClass())
        && UToolsetRegistry::IsToolsetClassRegistered(UCotSInspectionToolset::StaticClass())
        && UToolsetRegistry::IsToolsetClassRegistered(UCotSExecutionToolset::StaticClass())
        && UToolsetRegistry::IsToolsetClassRegistered(UCotSMutationToolset::StaticClass())
        && UToolsetRegistry::IsToolsetClassRegistered(UCotSLifecycleToolset::StaticClass())
        && UToolsetRegistry::IsToolsetClassRegistered(UCotSValidationToolset::StaticClass());
    UE_LOG(LogCotSDeveloperTools, Display, TEXT("CotS Developer Tools loaded; toolset registration: %s."),
        bToolsetsRegistered ? TEXT("ready") : TEXT("unavailable"));
}

void FCotSDeveloperToolsModule::ShutdownModule()
{
    if (PostEngineInitHandle.IsValid())
    {
        FCoreDelegates::GetOnPostEngineInit().Remove(PostEngineInitHandle);
        PostEngineInitHandle.Reset();
    }

    if (bToolsetsRegistered)
    {
        UToolsetRegistry::UnregisterToolsetClass(UCotSMutationToolset::StaticClass());
        UToolsetRegistry::UnregisterToolsetClass(UCotSLifecycleToolset::StaticClass());
        UToolsetRegistry::UnregisterToolsetClass(UCotSValidationToolset::StaticClass());
        UToolsetRegistry::UnregisterToolsetClass(UCotSExecutionToolset::StaticClass());
        UToolsetRegistry::UnregisterToolsetClass(UCotSInspectionToolset::StaticClass());
        UToolsetRegistry::UnregisterToolsetClass(UCotSFoundationToolset::StaticClass());
        bToolsetsRegistered = false;
    }
}

IMPLEMENT_MODULE(FCotSDeveloperToolsModule, CotSDeveloperTools)
