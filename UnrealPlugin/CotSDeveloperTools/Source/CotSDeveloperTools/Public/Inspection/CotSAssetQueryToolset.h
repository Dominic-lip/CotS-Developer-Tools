#pragma once

#include "CoreMinimal.h"
#include "ToolsetRegistry/ToolsetDefinition.h"

#include "CotSAssetQueryToolset.generated.h"

/** Bounded Asset Registry queries intended for large CotS production registries. */
UCLASS()
class COTSDEVELOPERTOOLS_API UCotSAssetQueryToolset : public UToolsetDefinition
{
    GENERATED_BODY()

public:
    virtual FString GetToolsetVersion() const override { return TEXT("1.0"); }

    /**
     * Searches with an Asset Registry FARFilter first, then applies the optional
     * short-name substring. MaxResults is bounded to 1..5000 and results are
     * deterministically sorted by exact object path.
     */
    UFUNCTION(meta = (AICallable), Category = "CotS Inspection")
    static FString SearchAssetsFiltered(
        const FString& NameQuery,
        const FString& PackagePath,
        const FString& ClassPath,
        bool bRecursivePaths = true,
        bool bRecursiveClasses = true,
        int32 MaxResults = 200);
};
