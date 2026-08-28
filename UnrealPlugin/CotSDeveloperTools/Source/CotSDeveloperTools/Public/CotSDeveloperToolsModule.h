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
    void HandleStatusCommand();
    void HandleListAssetsCommand(const TArray<FString>& Args);
    void HandleInspectAssetCommand(const TArray<FString>& Args);

    IConsoleObject* StatusCommand = nullptr;
    IConsoleObject* ListAssetsCommand = nullptr;
    IConsoleObject* InspectAssetCommand = nullptr;
};
