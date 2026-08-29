#pragma once

#include "CoreMinimal.h"
#include "ToolsetRegistry/ToolsetDefinition.h"

#include "CotSInspectionToolset.generated.h"

/** Read-only, exact-path-oriented inspection operations that compose UE 5.8 editor APIs. */
UCLASS()
class COTSDEVELOPERTOOLS_API UCotSInspectionToolset : public UToolsetDefinition
{
    GENERATED_BODY()

public:
    virtual FString GetToolsetVersion() const override { return TEXT("1.0"); }

    UFUNCTION(meta = (AICallable), Category = "CotS Inspection") static FString GetProjectStatus();
    UFUNCTION(meta = (AICallable), Category = "CotS Inspection") static FString SearchAssets(const FString& NameQuery, const FString& PathQuery, const FString& ClassPath);
    UFUNCTION(meta = (AICallable), Category = "CotS Inspection") static FString GetAsset(const FString& ObjectPath);
    UFUNCTION(meta = (AICallable), Category = "CotS Inspection") static FString GetCurveFloat(const FString& ObjectPath);
    UFUNCTION(meta = (AICallable), Category = "CotS Inspection") static FString GetActor(const FString& ActorPath);
    UFUNCTION(meta = (AICallable), Category = "CotS Inspection") static FString GetReferences(const FString& ObjectPath, bool bReferencers);
    UFUNCTION(meta = (AICallable), Category = "CotS Inspection") static FString GetBlueprint(const FString& ObjectPath);
    UFUNCTION(meta = (AICallable), Category = "CotS Inspection") static FString GetAnimationAsset(const FString& ObjectPath);
    UFUNCTION(meta = (AICallable), Category = "CotS Inspection") static FString GetPlugins(const FString& NameFilter);
    UFUNCTION(meta = (AICallable), Category = "CotS Inspection") static FString FindDuplicateNames(const FString& ShortName);
};
