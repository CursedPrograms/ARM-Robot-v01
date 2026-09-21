// MotorConfig.cs - Shared motor configuration, loaded from config.json at the
// repo root. C# counterpart of scripts/motor_config.py: config.json stays the
// single source of truth for the arm's physical limits across all controllers.

using System.Text.Json.Nodes;

namespace ArmController;

public sealed class Motor
{
    public int Channel { get; set; }
    public int Min { get; set; } = 0;
    public int Max { get; set; } = 270;
    public int Rest { get; set; } = 135;
    public bool Invert { get; set; }
    public double KinematicSign { get; set; } = 1;
}

public sealed class ArmGeometry
{
    public double BaseHeight { get; set; }
    public double UpperArmLength { get; set; }
    public double ForearmLength { get; set; }
    public double WristLength { get; set; }

    public bool Ready => UpperArmLength != 0 && ForearmLength != 0;
}

public static class Config
{
    public static string RepoRoot { get; } = FindRepoRoot();
    public static string ConfigPath => Path.Combine(RepoRoot, "config.json");
    public static string WebDir => Path.Combine(RepoRoot, "scripts", "web");
    public static string MacrosDir => Path.Combine(RepoRoot, "scripts", "macros");

    // Works whether launched from the repo root (the .bat/.sh launchers) or from
    // bin/Release/... (dotnet run / a published exe): walk up until config.json + scripts/ are found.
    static string FindRepoRoot()
    {
        foreach (var start in new[] { AppContext.BaseDirectory, Directory.GetCurrentDirectory() })
        {
            var dir = new DirectoryInfo(start);
            while (dir != null)
            {
                if (File.Exists(Path.Combine(dir.FullName, "config.json")) &&
                    Directory.Exists(Path.Combine(dir.FullName, "scripts")))
                    return dir.FullName;
                dir = dir.Parent;
            }
        }
        return Directory.GetCurrentDirectory();
    }

    static JsonObject? ReadRoot()
    {
        if (!File.Exists(ConfigPath)) return null;
        try
        {
            return JsonNode.Parse(File.ReadAllText(ConfigPath)) as JsonObject;
        }
        catch (Exception e)
        {
            Console.WriteLine($"Warning: could not read {Path.GetFileName(ConfigPath)} ({e.Message}), using defaults.");
            return null;
        }
    }

    static double GetNumber(JsonObject o, string key, double fallback) =>
        o[key] is JsonValue v && v.TryGetValue<double>(out var d) ? d : fallback;

    static bool GetBool(JsonObject o, string key, bool fallback) =>
        o[key] is JsonValue v && v.TryGetValue<bool>(out var b) ? b : fallback;

    public static SortedDictionary<int, Motor> LoadMotors()
    {
        var motors = new SortedDictionary<int, Motor>();
        for (int n = 1; n <= 6; n++) motors[n] = new Motor { Channel = n - 1 };

        if (ReadRoot()?["motors"] is JsonObject overrides)
        {
            foreach (var (key, node) in overrides)
            {
                if (!int.TryParse(key, out int n) || node is not JsonObject o) continue;
                if (!motors.TryGetValue(n, out var m)) motors[n] = m = new Motor { Channel = n - 1 };
                m.Channel = (int)Math.Round(GetNumber(o, "channel", m.Channel));
                m.Min = (int)Math.Round(GetNumber(o, "min", m.Min));
                m.Max = (int)Math.Round(GetNumber(o, "max", m.Max));
                m.Rest = (int)Math.Round(GetNumber(o, "rest", m.Rest));
                m.Invert = GetBool(o, "invert", m.Invert);
                m.KinematicSign = GetNumber(o, "kinematicSign", m.KinematicSign);
            }
        }
        return motors;
    }

    public static ArmGeometry LoadGeometry()
    {
        var g = new ArmGeometry();
        if (ReadRoot()?["geometry"] is JsonObject o)
        {
            g.BaseHeight = GetNumber(o, "baseHeight", 0);
            g.UpperArmLength = GetNumber(o, "upperArmLength", 0);
            g.ForearmLength = GetNumber(o, "forearmLength", 0);
            g.WristLength = GetNumber(o, "wristLength", 0);
        }
        return g;
    }
}
