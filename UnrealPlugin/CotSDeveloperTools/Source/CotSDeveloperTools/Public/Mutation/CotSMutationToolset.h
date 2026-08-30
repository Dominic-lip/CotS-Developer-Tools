#pragma once

#include "CoreMinimal.h"
#include "ToolsetRegistry/ToolsetDefinition.h"

#include "CotSMutationToolset.generated.h"

/** Guarded, exact-path composites over UE's native mutation primitives. */
UCLASS()
class COTSDEVELOPERTOOLS_API UCotSMutationToolset : public UToolsetDefinition
{
    GENERATED_BODY()

public:
    virtual FString GetToolsetVersion() const override { return TEXT("1.0"); }

    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString CreateCurveFloat(const FString& ObjectPath, bool bDryRun = false);
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString MoveAsset(const FString& SourceObjectPath, const FString& DestinationObjectPath, bool bDryRun = false);
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString DuplicateAsset(const FString& SourceObjectPath, const FString& DestinationObjectPath, bool bDryRun = false);
    /** Runs UE 5.8's native duplicate-and-retarget operation only into /Game/CotSMutationLive/, after exact-path and skeleton preflight. */
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString BatchRetargetAnimationAssets(const TArray<FString>& SourceAssetPaths, const FString& RetargeterPath, const FString& TargetPath, bool bDryRun = false);
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString DeleteDisposableAsset(const FString& ObjectPath, bool bDryRun = false);
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString SaveAsset(const FString& ObjectPath, bool bDryRun = false);
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString SetCurveEventFlag(const FString& ObjectPath, bool bIsEventCurve, bool bDryRun = false);
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString CompileBlueprint(const FString& ObjectPath, bool bDryRun = false);
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString CreateDisposableMap(const FString& MapAssetPath, bool bDryRun = false);

    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString CreateDisposableActor(const FString& ActorLabel, double X, double Y, double Z, bool bDryRun = false);
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString SetActorLocation(const FString& ActorPath, double X, double Y, double Z, bool bDryRun = false);
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString AddSceneComponent(const FString& ActorPath, const FString& ComponentName, bool bDryRun = false);
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString RemoveSceneComponent(const FString& ActorPath, const FString& ComponentName, bool bDryRun = false);
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString DeleteDisposableActor(const FString& ActorPath, bool bDryRun = false);
};
