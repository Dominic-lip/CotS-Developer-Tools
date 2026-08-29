#pragma once

#include "CoreMinimal.h"
#include "ToolsetRegistry/ToolsetDefinition.h"

#include "CotSFoundationToolset.generated.h"

/** Minimal MCP proof toolset. Future domain toolsets are registered independently. */
UCLASS()
class COTSDEVELOPERTOOLS_API UCotSFoundationToolset : public UToolsetDefinition
{
    GENERATED_BODY()

public:
    virtual FString GetToolsetVersion() const override { return TEXT("1.0"); }

    /** Returns read-only CotSDeveloperTools, engine, and result-contract version information. */
    UFUNCTION(meta = (AICallable), Category = "CotS Foundation")
    static FString GetStatus();
};
