#pragma once

#include "CoreMinimal.h"
#include "ToolsetRegistry/ToolsetDefinition.h"
#include "CotSValidationToolset.generated.h"

UCLASS()
class COTSDEVELOPERTOOLS_API UCotSValidationToolset : public UToolsetDefinition
{
    GENERATED_BODY()
public:
    virtual FString GetToolsetVersion() const override { return TEXT("1.0"); }
    UFUNCTION(meta=(AICallable), Category="CotS Validation") static FString ValidateAsset(const FString& ObjectPath);
    UFUNCTION(meta=(AICallable), Category="CotS Validation") static FString ValidateFolder(const FString& FolderPath);
    /** Validates exact locomotion clips against one Skeleton's root/IK-bone policy, looping policy, and root-motion mode. */
    UFUNCTION(meta=(AICallable), Category="CotS Validation") static FString ValidateLocomotionPolicy(const FString& SkeletonPath, const TArray<FString>& LoopingClipPaths, const TArray<FString>& OneShotClipPaths, const TArray<FString>& RequiredIKBoneNames, bool bRequireRootMotion);
};
