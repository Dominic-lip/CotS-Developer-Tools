using UnrealBuildTool;
using System.Collections.Generic;

public class CotSToolLabTarget : TargetRules
{
    public CotSToolLabTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Game;
        DefaultBuildSettings = BuildSettingsVersion.Latest;
        IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
        ExtraModuleNames.Add("CotSToolLab");
    }
}
