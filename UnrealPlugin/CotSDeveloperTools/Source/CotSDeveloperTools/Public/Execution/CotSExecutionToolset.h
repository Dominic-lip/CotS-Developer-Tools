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
    /**
     * Executes one allowlisted, read-only editor query. Supported queries are:
     * project.context, project.name, engine.version, map.current, and cvar.<name>.
     */
    UFUNCTION(meta = (AICallable), Category = "CotS Execution")
    static FString ExecuteReadOnlyQuery(const FString& Query, bool bDryRun = false);
};
