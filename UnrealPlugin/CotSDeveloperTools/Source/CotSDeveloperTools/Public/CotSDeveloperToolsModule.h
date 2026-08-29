#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

class IConsoleObject;

DECLARE_LOG_CATEGORY_EXTERN(LogCotSDeveloperTools, Log, All);

class FCotSDeveloperToolsModule : public IModuleInterface
{
public:
    virtual void StartupModule() override;
    virtual void ShutdownModule() override;

private:
    void RegisterToolsets();

    FDelegateHandle PostEngineInitHandle;
    bool bToolsetsRegistered = false;
};
