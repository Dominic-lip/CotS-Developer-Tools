using UnrealBuildTool;
using System.Collections.Generic;

public class CotSToolLabEditorTarget : TargetRules
{
    public CotSToolLabEditorTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Editor;
        DefaultBuildSettings = BuildSettingsVersion.Latest;
        IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
        ExtraModuleNames.Add("CotSToolLab");
    }
}
