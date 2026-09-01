#pragma once

#include "CoreMinimal.h"
#include "ToolsetRegistry/ToolsetDefinition.h"

#include "CotSLifecycleToolset.generated.h"

class UPackage;

/** Guarded editor-only lifecycle operations for CotS ToolLab and production projects. */
UCLASS()
class COTSDEVELOPERTOOLS_API UCotSLifecycleToolset : public UToolsetDefinition
{
    GENERATED_BODY()

public:
    virtual FString GetToolsetVersion() const override { return TEXT("2.0"); }

    /** Backward-compatible ToolLab-only shutdown request. */
    UFUNCTION(meta = (AICallable), Category = "CotS Lifecycle")
    static FString RequestToolLabShutdown();

    /**
     * Requests UE's normal non-forced exit for either CotSToolLab or the CotS
     * production project, only when no modal/PIE session or persistent dirty
     * package remains. The host must still verify the exact editor PID exits.
     */
    UFUNCTION(meta = (AICallable), Category = "CotS Lifecycle")
    static FString RequestProjectShutdown();

    // Intentionally not AI-callable: retained for automation coverage of package classification.
    static bool IsPersistentPackageForShutdown(const UPackage* Package);
    static TArray<FString> GetPersistentDirtyPackagePaths();
};
