#include "Core/CotSOperationResult.h"

#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"

namespace
{
    TArray<TSharedPtr<FJsonValue>> ToJsonStringArray(const TArray<FString>& Values)
    {
        TArray<TSharedPtr<FJsonValue>> Result;
        Result.Reserve(Values.Num());
        for (const FString& Value : Values)
        {
            Result.Add(MakeShared<FJsonValueString>(Value));
        }
        return Result;
    }
}

FCotSOperationResult FCotSOperationResult::Succeed(const FString& InOperation, bool bInDryRun)
{
    FCotSOperationResult Result;
    Result.OperationId = FGuid::NewGuid().ToString(EGuidFormats::DigitsWithHyphensLower);
    Result.Operation = InOperation;
    Result.bSuccess = true;
    Result.bDryRun = bInDryRun;
    Result.Status = bInDryRun ? TEXT("preview") : TEXT("success");
    return Result;
}

FCotSOperationResult FCotSOperationResult::Fail(const FString& InOperation, const FString& ErrorCode, const FString& ErrorMessage, bool bInDryRun)
{
    FCotSOperationResult Result = Succeed(InOperation, bInDryRun);
    Result.bSuccess = false;
    Result.Status = TEXT("failure");
    Result.AddError(ErrorCode, ErrorMessage);
    return Result;
}

void FCotSOperationResult::AddAffectedObject(const FString& ObjectPath)
{
    if (!ObjectPath.IsEmpty())
    {
        AffectedObjectPaths.AddUnique(ObjectPath);
    }
}

void FCotSOperationResult::AddWarning(const FString& Warning)
{
    if (!Warning.IsEmpty())
    {
        Warnings.Add(Warning);
    }
}

void FCotSOperationResult::AddError(const FString& ErrorCode, const FString& ErrorMessage)
{
    Errors.Add({ ErrorCode, ErrorMessage });
}

FString FCotSOperationResult::ToJson() const
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("operation_id"), OperationId);
    Root->SetStringField(TEXT("operation"), Operation);
    Root->SetStringField(TEXT("status"), Status);
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetBoolField(TEXT("dry_run"), bDryRun);
    Root->SetStringField(TEXT("schema_version"), CotSOperationResultSchemaVersion);
    Root->SetArrayField(TEXT("changed_objects"), ToJsonStringArray(AffectedObjectPaths));
    Root->SetArrayField(TEXT("affected_object_paths"), ToJsonStringArray(AffectedObjectPaths));
    Root->SetArrayField(TEXT("warnings"), ToJsonStringArray(Warnings));
    Root->SetArrayField(TEXT("validation"), ToJsonStringArray(Validation));
    Root->SetNumberField(TEXT("duration_ms"), DurationMs);

    TArray<TSharedPtr<FJsonValue>> ErrorMessages;
    TArray<TSharedPtr<FJsonValue>> ErrorDetails;
    for (const FCotSOperationError& Error : Errors)
    {
        ErrorMessages.Add(MakeShared<FJsonValueString>(Error.Message));
        TSharedRef<FJsonObject> Detail = MakeShared<FJsonObject>();
        Detail->SetStringField(TEXT("code"), Error.Code);
        Detail->SetStringField(TEXT("message"), Error.Message);
        ErrorDetails.Add(MakeShared<FJsonValueObject>(Detail));
    }
    Root->SetArrayField(TEXT("errors"), ErrorMessages);
    Root->SetArrayField(TEXT("error_details"), ErrorDetails);
    Root->SetObjectField(TEXT("data"), Data.IsValid() ? Data.ToSharedRef() : MakeShared<FJsonObject>());

    FString Json;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Json);
    FJsonSerializer::Serialize(Root, Writer);
    return Json;
}
