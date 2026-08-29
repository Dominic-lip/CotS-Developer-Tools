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
};
