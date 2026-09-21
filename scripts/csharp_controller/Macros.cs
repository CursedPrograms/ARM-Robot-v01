// Macros.cs - Record/replay motor-pose macros as JSON. C# counterpart of
// controller.py's macro helpers; reads/writes the same scripts/macros/*.json
// files as the Python, C++ and Julia controllers.

using System.Globalization;
using System.Text.Json.Nodes;

namespace ArmController;

public sealed record MacroStep(double T, Dictionary<int, int> Commands);

public static class Macros
{
    public static List<string> List()
    {
        if (!Directory.Exists(Config.MacrosDir)) return new List<string>();
        var files = Directory.GetFiles(Config.MacrosDir, "*.json").ToList();
        files.Sort((a, b) => string.CompareOrdinal(Path.GetFileName(b), Path.GetFileName(a))); // newest first
        return files;
    }

    public static string Save(List<MacroStep> steps)
    {
        Directory.CreateDirectory(Config.MacrosDir);
        var now = DateTime.Now;
        string path = Path.Combine(Config.MacrosDir, $"macro_{now:yyyyMMdd_HHmmss}.json");

        var stepArray = new JsonArray();
        foreach (var s in steps)
        {
            var commands = new JsonObject();
            foreach (var (ch, ang) in s.Commands.OrderBy(kv => kv.Key))
                commands[ch.ToString(CultureInfo.InvariantCulture)] = ang;
            stepArray.Add(new JsonObject { ["t"] = s.T, ["commands"] = commands });
        }
        var root = new JsonObject
        {
            ["created"] = now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture),
            ["steps"] = stepArray,
        };
        File.WriteAllText(path, root.ToJsonString());
        return path;
    }

    public static List<MacroStep> Load(string path)
    {
        var steps = new List<MacroStep>();
        if (JsonNode.Parse(File.ReadAllText(path)) is not JsonObject root || root["steps"] is not JsonArray arr)
            return steps;

        foreach (var node in arr)
        {
            if (node is not JsonObject s || s["commands"] is not JsonObject cmds) continue;
            double t = s["t"] is JsonValue tv && tv.TryGetValue<double>(out var td) ? td : 0;
            var commands = new Dictionary<int, int>();
            foreach (var (key, val) in cmds)
            {
                if (int.TryParse(key, out int ch) && val is JsonValue v && v.TryGetValue<double>(out var angle))
                    commands[ch] = (int)Math.Round(angle);
            }
            steps.Add(new MacroStep(t, commands));
        }
        return steps;
    }
}
