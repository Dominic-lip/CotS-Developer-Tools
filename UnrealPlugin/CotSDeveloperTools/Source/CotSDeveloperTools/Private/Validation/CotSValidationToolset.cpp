#include "Validation/CotSValidationToolset.h"
#include "Animation/AnimSequence.h"
#include "Animation/Skeleton.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Core/CotSOperationResult.h"
#include "Dom/JsonObject.h"
#include "UObject/SoftObjectPath.h"
#include UE_INLINE_GENERATED_CPP_BY_NAME(CotSValidationToolset)

FString UCotSValidationToolset::ValidateAsset(const FString& ObjectPath)
{
    const FString Op = TEXT("CotS.Validation.ValidateAsset");
    FCotSOperationResult Result = FCotSOperationResult::Succeed(Op); Result.Data = MakeShared<FJsonObject>();
    FAssetData Asset;
    const EExists Exists = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get().TryGetAssetByObjectPath(FSoftObjectPath(ObjectPath), Asset);
    if (Exists != EExists::Exists) { if (UObject* Loaded = FindObject<UObject>(nullptr, *ObjectPath)) { Asset = FAssetData(Loaded); } }
    Result.Data->SetStringField(TEXT("object_path"), ObjectPath); Result.Data->SetBoolField(TEXT("exists"), Asset.IsValid());
    if (!Asset.IsValid()) { return FCotSOperationResult::Fail(Op, TEXT("asset_not_found"), TEXT("The exact asset object path does not resolve.")).ToJson(); }
    Result.AddAffectedObject(Asset.GetObjectPathString()); Result.Data->SetStringField(TEXT("class"), Asset.AssetClassPath.ToString()); Result.Validation.Add(TEXT("asset_registry_exact_path_resolved")); return Result.ToJson();
}

FString UCotSValidationToolset::ValidateFolder(const FString& FolderPath)
{
    const FString Op = TEXT("CotS.Validation.ValidateFolder");
    if (!FolderPath.StartsWith(TEXT("/Game"))) return FCotSOperationResult::Fail(Op, TEXT("invalid_folder_scope"), TEXT("Folder validation is restricted to /Game paths.")).ToJson();
    FCotSOperationResult Result = FCotSOperationResult::Succeed(Op); Result.Data = MakeShared<FJsonObject>(); TArray<FAssetData> Assets;
    FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get().GetAssetsByPath(FName(FolderPath), Assets, true);
    Assets.Sort([](const FAssetData& A, const FAssetData& B){ return A.GetObjectPathString() < B.GetObjectPathString(); });
    TArray<TSharedPtr<FJsonValue>> Paths; for (const FAssetData& Asset : Assets) { Paths.Add(MakeShared<FJsonValueString>(Asset.GetObjectPathString())); Result.AddAffectedObject(Asset.GetObjectPathString()); }
    Result.Data->SetStringField(TEXT("folder_path"), FolderPath); Result.Data->SetNumberField(TEXT("asset_count"), Assets.Num()); Result.Data->SetArrayField(TEXT("asset_paths"), Paths); return Result.ToJson();
}

FString UCotSValidationToolset::ValidateLocomotionPolicy(const FString& SkeletonPath, const TArray<FString>& LoopingClipPaths, const TArray<FString>& OneShotClipPaths, const TArray<FString>& RequiredIKBoneNames, bool bRequireRootMotion)
{
    constexpr const TCHAR* Op = TEXT("CotS.Validation.ValidateLocomotionPolicy");
    USkeleton* Skeleton = LoadObject<USkeleton>(nullptr, *SkeletonPath);
    if (!Skeleton) { return FCotSOperationResult::Fail(Op, TEXT("skeleton_not_found"), TEXT("SkeletonPath must resolve to an exact USkeleton object path.")).ToJson(); }
    if (LoopingClipPaths.IsEmpty() && OneShotClipPaths.IsEmpty()) { return FCotSOperationResult::Fail(Op, TEXT("clips_required"), TEXT("At least one looping or one-shot animation clip is required.")).ToJson(); }

    FCotSOperationResult Result = FCotSOperationResult::Succeed(Op);
    Result.AddAffectedObject(Skeleton->GetPathName());
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("skeleton"), Skeleton->GetPathName());
    Result.Data->SetBoolField(TEXT("require_root_motion"), bRequireRootMotion);

    TSet<FString> SeenClips;
    TArray<TSharedPtr<FJsonValue>> Bones;
    for (const FString& BoneName : RequiredIKBoneNames)
    {
        const bool bPresent = !BoneName.IsEmpty() && Skeleton->GetReferenceSkeleton().FindBoneIndex(FName(*BoneName)) != INDEX_NONE;
        TSharedRef<FJsonObject> Bone = MakeShared<FJsonObject>();
        Bone->SetStringField(TEXT("bone"), BoneName); Bone->SetBoolField(TEXT("present"), bPresent); Bones.Add(MakeShared<FJsonValueObject>(Bone));
        if (!bPresent) { Result.AddError(TEXT("required_ik_bone_missing"), FString::Printf(TEXT("Required IK/root policy bone '%s' is absent from the Skeleton."), *BoneName)); }
    }
    Result.Data->SetArrayField(TEXT("required_ik_bones"), Bones);

    TArray<TSharedPtr<FJsonValue>> Clips;
    const auto ValidateClips = [&Result, &SeenClips, &Clips, Skeleton](const TArray<FString>& Paths, bool bExpectedLooping)
    {
        for (const FString& Path : Paths)
        {
            TSharedRef<FJsonObject> Clip = MakeShared<FJsonObject>();
            Clip->SetStringField(TEXT("object_path"), Path); Clip->SetBoolField(TEXT("expected_looping"), bExpectedLooping);
            if (SeenClips.Contains(Path))
            {
                Result.AddError(TEXT("duplicate_clip"), FString::Printf(TEXT("Clip '%s' appears more than once in the policy."), *Path));
                Clip->SetBoolField(TEXT("valid"), false); Clips.Add(MakeShared<FJsonValueObject>(Clip)); continue;
            }
            SeenClips.Add(Path);
            UAnimSequence* Sequence = LoadObject<UAnimSequence>(nullptr, *Path);
            if (!Sequence)
            {
                Result.AddError(TEXT("clip_not_found"), FString::Printf(TEXT("Clip '%s' must resolve to a UAnimSequence."), *Path));
                Clip->SetBoolField(TEXT("valid"), false); Clips.Add(MakeShared<FJsonValueObject>(Clip)); continue;
            }
            Result.AddAffectedObject(Sequence->GetPathName());
            const bool bSkeletonMatches = Sequence->GetSkeleton() == Skeleton;
            const bool bLoopingMatches = Sequence->bLoop == bExpectedLooping;
            Clip->SetBoolField(TEXT("skeleton_matches"), bSkeletonMatches);
            Clip->SetBoolField(TEXT("is_looping"), Sequence->bLoop);
            Clip->SetBoolField(TEXT("has_root_motion"), Sequence->HasRootMotion());
            Clip->SetBoolField(TEXT("valid"), bSkeletonMatches && bLoopingMatches);
            if (!bSkeletonMatches) { Result.AddError(TEXT("clip_skeleton_mismatch"), FString::Printf(TEXT("Clip '%s' does not use the requested Skeleton."), *Path)); }
            if (!bLoopingMatches) { Result.AddError(TEXT("clip_looping_policy_mismatch"), FString::Printf(TEXT("Clip '%s' does not match its expected looping mode."), *Path)); }
            Clips.Add(MakeShared<FJsonValueObject>(Clip));
        }
    };
    ValidateClips(LoopingClipPaths, true);
    ValidateClips(OneShotClipPaths, false);

    for (const TSharedPtr<FJsonValue>& ClipValue : Clips)
    {
        const TSharedPtr<FJsonObject> Clip = ClipValue->AsObject();
        if (!Clip->HasField(TEXT("has_root_motion"))) { continue; }
        if (Clip->GetBoolField(TEXT("has_root_motion")) != bRequireRootMotion)
        {
            Result.AddError(TEXT("root_motion_policy_mismatch"), FString::Printf(TEXT("Clip '%s' does not match the required root-motion mode."), *Clip->GetStringField(TEXT("object_path"))));
            Clip->SetBoolField(TEXT("valid"), false);
        }
    }
    Result.Data->SetArrayField(TEXT("clips"), Clips);
    if (!Result.Errors.IsEmpty()) { Result.bSuccess = false; Result.Status = TEXT("failure"); }
    else { Result.Validation.Add(TEXT("skeleton_ik_bones_clip_looping_and_root_motion_policy_validated")); }
    return Result.ToJson();
}

FString UCotSValidationToolset::ValidateLocomotionPolicyWithRootMotionSet(const FString& SkeletonPath, const TArray<FString>& LoopingClipPaths, const TArray<FString>& OneShotClipPaths, const TArray<FString>& RootMotionClipPaths, const TArray<FString>& RequiredIKBoneNames)
{
    constexpr const TCHAR* Op = TEXT("CotS.Validation.ValidateLocomotionPolicyWithRootMotionSet");
    USkeleton* Skeleton = LoadObject<USkeleton>(nullptr, *SkeletonPath);
    if (!Skeleton) { return FCotSOperationResult::Fail(Op, TEXT("skeleton_not_found"), TEXT("SkeletonPath must resolve to an exact USkeleton object path.")).ToJson(); }
    if (LoopingClipPaths.IsEmpty() && OneShotClipPaths.IsEmpty()) { return FCotSOperationResult::Fail(Op, TEXT("clips_required"), TEXT("At least one looping or one-shot animation clip is required.")).ToJson(); }

    FCotSOperationResult Result = FCotSOperationResult::Succeed(Op);
    Result.AddAffectedObject(Skeleton->GetPathName());
    Result.Data = MakeShared<FJsonObject>();
    Result.Data->SetStringField(TEXT("skeleton"), Skeleton->GetPathName());
    TSet<FString> RootMotionClips;
    for (const FString& Path : RootMotionClipPaths)
    {
        if (Path.IsEmpty() || RootMotionClips.Contains(Path)) { Result.AddError(TEXT("duplicate_root_motion_clip"), FString::Printf(TEXT("Root-motion clip '%s' is empty or repeated."), *Path)); }
        else { RootMotionClips.Add(Path); }
    }

    TSet<FString> SeenClips;
    TArray<TSharedPtr<FJsonValue>> Bones;
    for (const FString& BoneName : RequiredIKBoneNames)
    {
        const bool bPresent = !BoneName.IsEmpty() && Skeleton->GetReferenceSkeleton().FindBoneIndex(FName(*BoneName)) != INDEX_NONE;
        TSharedRef<FJsonObject> Bone = MakeShared<FJsonObject>();
        Bone->SetStringField(TEXT("bone"), BoneName); Bone->SetBoolField(TEXT("present"), bPresent); Bones.Add(MakeShared<FJsonValueObject>(Bone));
        if (!bPresent) { Result.AddError(TEXT("required_ik_bone_missing"), FString::Printf(TEXT("Required IK/root policy bone '%s' is absent from the Skeleton."), *BoneName)); }
    }
    Result.Data->SetArrayField(TEXT("required_ik_bones"), Bones);

    TArray<TSharedPtr<FJsonValue>> Clips;
    const auto ValidateClips = [&Result, &SeenClips, &Clips, &RootMotionClips, Skeleton](const TArray<FString>& Paths, bool bExpectedLooping)
    {
        for (const FString& Path : Paths)
        {
            TSharedRef<FJsonObject> Clip = MakeShared<FJsonObject>();
            Clip->SetStringField(TEXT("object_path"), Path); Clip->SetBoolField(TEXT("expected_looping"), bExpectedLooping);
            const bool bExpectedRootMotion = RootMotionClips.Contains(Path);
            Clip->SetBoolField(TEXT("expected_root_motion"), bExpectedRootMotion);
            if (SeenClips.Contains(Path))
            {
                Result.AddError(TEXT("duplicate_clip"), FString::Printf(TEXT("Clip '%s' appears more than once in the policy."), *Path));
                Clip->SetBoolField(TEXT("valid"), false); Clips.Add(MakeShared<FJsonValueObject>(Clip)); continue;
            }
            SeenClips.Add(Path);
            UAnimSequence* Sequence = LoadObject<UAnimSequence>(nullptr, *Path);
            if (!Sequence)
            {
                Result.AddError(TEXT("clip_not_found"), FString::Printf(TEXT("Clip '%s' must resolve to a UAnimSequence."), *Path));
                Clip->SetBoolField(TEXT("valid"), false); Clips.Add(MakeShared<FJsonValueObject>(Clip)); continue;
            }
            Result.AddAffectedObject(Sequence->GetPathName());
            const bool bSkeletonMatches = Sequence->GetSkeleton() == Skeleton;
            const bool bLoopingMatches = Sequence->bLoop == bExpectedLooping;
            const bool bRootMotionMatches = Sequence->HasRootMotion() == bExpectedRootMotion;
            Clip->SetBoolField(TEXT("skeleton_matches"), bSkeletonMatches);
            Clip->SetBoolField(TEXT("is_looping"), Sequence->bLoop);
            Clip->SetBoolField(TEXT("has_root_motion"), Sequence->HasRootMotion());
            Clip->SetBoolField(TEXT("valid"), bSkeletonMatches && bLoopingMatches && bRootMotionMatches);
            if (!bSkeletonMatches) { Result.AddError(TEXT("clip_skeleton_mismatch"), FString::Printf(TEXT("Clip '%s' does not use the requested Skeleton."), *Path)); }
            if (!bLoopingMatches) { Result.AddError(TEXT("clip_looping_policy_mismatch"), FString::Printf(TEXT("Clip '%s' does not match its expected looping mode."), *Path)); }
            if (!bRootMotionMatches) { Result.AddError(TEXT("root_motion_policy_mismatch"), FString::Printf(TEXT("Clip '%s' does not match its expected root-motion mode."), *Path)); }
            Clips.Add(MakeShared<FJsonValueObject>(Clip));
        }
    };
    ValidateClips(LoopingClipPaths, true);
    ValidateClips(OneShotClipPaths, false);
    for (const FString& RootMotionPath : RootMotionClips)
    {
        if (!SeenClips.Contains(RootMotionPath)) { Result.AddError(TEXT("root_motion_clip_not_in_policy"), FString::Printf(TEXT("Root-motion clip '%s' is not present in the looping or one-shot set."), *RootMotionPath)); }
    }
    Result.Data->SetArrayField(TEXT("clips"), Clips);
    if (!Result.Errors.IsEmpty()) { Result.bSuccess = false; Result.Status = TEXT("failure"); }
    else { Result.Validation.Add(TEXT("skeleton_ik_bones_clip_looping_and_per_clip_root_motion_policy_validated")); }
    return Result.ToJson();
}
