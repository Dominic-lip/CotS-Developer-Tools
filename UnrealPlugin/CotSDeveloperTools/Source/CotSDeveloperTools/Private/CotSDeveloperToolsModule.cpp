#include "CotSDeveloperToolsModule.h"

#include "Foundation/CotSFoundationToolset.h"
#include "Misc/CoreDelegates.h"
#include "ToolsetRegistry/UToolsetRegistry.h"

DEFINE_LOG_CATEGORY(LogCotSDeveloperTools);

void FCotSDeveloperToolsModule::StartupModule()
{
    if (UToolsetRegistry::IsAvailable())
    {
        RegisterFoundationToolset();
        return;
    }

    PostEngineInitHandle = FCoreDelegates::GetOnPostEngineInit().AddRaw(this, &FCotSDeveloperToolsModule::RegisterFoundationToolset);
}

void FCotSDeveloperToolsModule::RegisterFoundationToolset()
{
    if (bFoundationToolsetRegistered)
    {
        return;
    }

    UToolsetRegistry::RegisterToolsetClass(UCotSFoundationToolset::StaticClass());
    bFoundationToolsetRegistered = UToolsetRegistry::IsToolsetClassRegistered(UCotSFoundationToolset::StaticClass());
    UE_LOG(LogCotSDeveloperTools, Display, TEXT("CotS Developer Tools foundation loaded; registered %s."),
        bFoundationToolsetRegistered ? TEXT("CotS.Foundation.GetStatus") : TEXT("no toolset (registry unavailable)"));
}

void FCotSDeveloperToolsModule::ShutdownModule()
{
    if (PostEngineInitHandle.IsValid())
    {
        FCoreDelegates::GetOnPostEngineInit().Remove(PostEngineInitHandle);
        PostEngineInitHandle.Reset();
    }

    if (bFoundationToolsetRegistered)
    {
        UToolsetRegistry::UnregisterToolsetClass(UCotSFoundationToolset::StaticClass());
        bFoundationToolsetRegistered = false;
    }
}

IMPLEMENT_MODULE(FCotSDeveloperToolsModule, CotSDeveloperTools)
