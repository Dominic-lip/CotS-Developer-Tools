#pragma once

#include "CoreMinimal.h"
#include "ToolsetRegistry/ToolsetDefinition.h"

#include "CotSFoundationToolset.generated.h"

/** Minimal MCP proof/toolchain identity toolset. */
UCLASS()
class COTSDEVELOPERTOOLS_API UCotSFoundationToolset : public UToolsetDefinition
{
    GENERATED_BODY()

public:
    virtual FString GetToolsetVersion() const override { return TEXT("2.0"); }

    /** Returns read-only CotSDeveloperTools, engine, and result-contract version information. */
    UFUNCTION(meta = (AICallable), Category = "CotS Foundation")
    static FString GetStatus();
};
