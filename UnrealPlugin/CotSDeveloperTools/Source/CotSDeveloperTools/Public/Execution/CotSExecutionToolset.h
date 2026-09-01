#pragma once

#include "CoreMinimal.h"
#include "ToolsetRegistry/ToolsetDefinition.h"

#include "CotSExecutionToolset.generated.h"

/**
 * Development-only, capability-constrained editor query bridge.
 *
 * This deliberately does not execute submitted Python, console commands, UObject
 * functions, or operating-system commands. Add repeated capabilities as typed CotS
 * toolsets rather than broadening this bridge into a scripting endpoint.
 */
UCLASS()
class COTSDEVELOPERTOOLS_API UCotSExecutionToolset : public UToolsetDefinition
{
    GENERATED_BODY()

public:
    virtual FString GetToolsetVersion() const override { return TEXT("2.0"); }

    /** Executes one allowlisted, read-only editor query. */
    UFUNCTION(meta = (AICallable), Category = "CotS Execution")
    static FString ExecuteReadOnlyQuery(const FString& Query, bool bDryRun = false);
};
