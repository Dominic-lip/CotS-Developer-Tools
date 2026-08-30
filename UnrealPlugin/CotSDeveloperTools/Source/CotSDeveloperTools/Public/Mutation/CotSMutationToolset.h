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
    /** Creates a disposable 2D locomotion Blend Space with typed Speed and Direction axes; PreviewMeshPath may be empty to use the Skeleton's native preview-mesh resolver. */
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString CreateDisposableLocomotionBlendSpace(const FString& ObjectPath, const FString& SkeletonPath, const FString& PreviewMeshPath, bool bDryRun = false);
    /** Adds one exact-skeleton animation sequence to a disposable locomotion Blend Space at a Speed/Direction coordinate. */
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString AddLocomotionBlendSpaceSample(const FString& BlendSpacePath, const FString& AnimationPath, double Speed, double Direction, bool bDryRun = false);
    /** Creates a disposable AnimBlueprint asset after exact Skeleton/preview-mesh preflight; graph topology remains an explicit subsequent operation. */
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString CreateDisposableAnimBlueprint(const FString& ObjectPath, const FString& SkeletonPath, const FString& PreviewMeshPath, bool bDryRun = false);
    /** Adds one default-initialized State Machine to an exact disposable AnimBlueprint; state and transition authoring remains explicit. */
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString AddDisposableAnimBlueprintStateMachine(const FString& ObjectPath, bool bDryRun = false);
    /** Adds one named State to a disposable State Machine and wires the State Machine entry node; transition authoring remains explicit. */
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString AddDisposableAnimBlueprintState(const FString& ObjectPath, const FString& StateName, bool bDryRun = false);
    /** Adds one directional transition between two named States in a disposable State Machine; rule logic remains explicit. */
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString AddDisposableAnimBlueprintTransition(const FString& ObjectPath, const FString& SourceStateName, const FString& TargetStateName, double CrossfadeSeconds = 0.2, bool bDryRun = false);
    /** Assigns one exact-skeleton sequence player to a named disposable State and links it to that State's result node. */
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString SetDisposableAnimBlueprintStateSequence(const FString& ObjectPath, const FString& StateName, const FString& AnimationPath, bool bLooping, bool bDryRun = false);
    /** Sets the typed constant entry rule on one exact directed transition in a disposable State Machine. */
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString SetDisposableAnimBlueprintTransitionRule(const FString& ObjectPath, const FString& SourceStateName, const FString& TargetStateName, bool bCanEnterTransition, bool bDryRun = false);
    /** Wires the single disposable State Machine pose output to the AnimBlueprint's AnimGraph Root result. */
    UFUNCTION(meta = (AICallable), Category = "CotS Mutation") static FString WireDisposableAnimBlueprintStateMachineOutput(const FString& ObjectPath, bool bDryRun = false);
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
