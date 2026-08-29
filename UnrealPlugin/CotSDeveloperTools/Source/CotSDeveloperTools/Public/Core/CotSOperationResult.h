#pragma once

#include "CoreMinimal.h"

class FJsonObject;

/** Schema version emitted by all CotS high-level operations. */
inline constexpr TCHAR CotSOperationResultSchemaVersion[] = TEXT("1.0");

/** Stable error vocabulary for machine-readable operation failures. */
struct FCotSOperationError
{
    FString Code;
    FString Message;
};

/**
 * Shared result envelope for future CotS toolsets. Serialized field names retain
 * compatibility with Schemas/tool-result.schema.json and add stable identifiers.
 */
struct FCotSOperationResult
{
    FString OperationId;
    FString Operation;
    bool bSuccess = false;
    bool bDryRun = false;
    FString Status = TEXT("failure");
    TArray<FString> AffectedObjectPaths;
    TArray<FString> Warnings;
    TArray<FCotSOperationError> Errors;
    TArray<FString> Validation;
    int64 DurationMs = 0;
    TSharedPtr<FJsonObject> Data;

    static FCotSOperationResult Succeed(const FString& InOperation, bool bInDryRun = false);
    static FCotSOperationResult Fail(const FString& InOperation, const FString& ErrorCode, const FString& ErrorMessage, bool bInDryRun = false);

    void AddAffectedObject(const FString& ObjectPath);
    void AddWarning(const FString& Warning);
    void AddError(const FString& ErrorCode, const FString& ErrorMessage);
    FString ToJson() const;
};
