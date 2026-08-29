#pragma once

#include "CoreMinimal.h"
#include "ToolsetRegistry/ToolsetDefinition.h"

#include "CotSLifecycleToolset.generated.h"

class UPackage;

/** Narrow editor-only lifecycle operation for the disposable CotSToolLab project. */
UCLASS()
class COTSDEVELOPERTOOLS_API UCotSLifecycleToolset : public UToolsetDefinition
{
    GENERATED_BODY()

public:
    virtual FString GetToolsetVersion() const override { return TEXT("1.0"); }

    /** Validates ToolLab safety preconditions then requests UE's normal, non-forced exit. */
    UFUNCTION(meta = (AICallable), Category = "CotS Lifecycle")
    static FString RequestToolLabShutdown();

    // Intentionally not AI-callable: retained for automation coverage of package classification.
    static bool IsPersistentPackageForShutdown(const UPackage* Package);
    static TArray<FString> GetPersistentDirtyPackagePaths();
};
