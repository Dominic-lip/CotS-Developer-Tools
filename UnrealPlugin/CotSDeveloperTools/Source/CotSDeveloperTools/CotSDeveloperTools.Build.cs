using UnrealBuildTool;

public class CotSDeveloperTools : ModuleRules
{
    public CotSDeveloperTools(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new[]
        {
            "Core"
        });

        PrivateDependencyModuleNames.AddRange(new[]
        {
            "CoreUObject",
            "Engine",
            "UnrealEd",
            "AssetRegistry",
            "Projects",
            "Json",
            "ToolsetRegistry"
        });
    }
}
