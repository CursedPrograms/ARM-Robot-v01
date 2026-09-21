// ColourScheme.cs - UI colours from colour_scheme.xml at the repo root, shared
// by every controller. Edit that file and restart - no rebuild. Any role
// missing from it (or the whole file being unreadable) falls back to Defaults.

using System.Xml.Linq;
using Avalonia;
using Avalonia.Media;

namespace ArmController;

public static class ColourScheme
{
    static readonly Dictionary<string, string> Defaults = new()
    {
        ["background"] = "#33292F",
        ["panel"] = "#331F2B",
        ["border"] = "#361529",
        ["text"] = "#FFFFFF",
        ["text_dim"] = "#C9B6C1",
        ["button"] = "#361529",
        ["button_hover"] = "#691548",
        ["button_active"] = "#9C0060",
        ["button_disabled"] = "#331F2B",
        ["accent"] = "#9C0060",
        ["accent_hover"] = "#C21F82",
        ["track"] = "#691548",
        ["selected"] = "#691548",
        ["danger"] = "#963232",
        ["danger_hover"] = "#AD3A3A",
        ["warn"] = "#F08C3C",
    };

    static readonly Dictionary<string, Color> Colours = Load();

    static Dictionary<string, Color> Load()
    {
        var colours = Defaults.ToDictionary(kv => kv.Key, kv => Color.Parse(kv.Value));
        try
        {
            var path = Path.Combine(Config.RepoRoot, "colour_scheme.xml");
            if (!File.Exists(path)) return colours;
            foreach (var el in XDocument.Load(path).Descendants("colour"))
            {
                var name = (string?)el.Attribute("name");
                var value = (string?)el.Attribute("value");
                if (name != null && value != null && Color.TryParse(value, out var c)) colours[name] = c;
            }
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"Warning: could not read colour_scheme.xml ({e.Message}), using default colours.");
        }
        return colours;
    }

    public static Color Colour(string role) => Colours[role];

    public static SolidColorBrush Brush(string role) => new(Colours[role]);

    /// <summary>Overrides the Fluent theme's colours app-wide (buttons, sliders, list).</summary>
    public static void Apply(Application app)
    {
        var r = app.Resources;
        r["SystemAccentColor"] = Colour("accent");
        r["ButtonBackground"] = Brush("button");
        r["ButtonBackgroundPointerOver"] = Brush("button_hover");
        r["ButtonBackgroundPressed"] = Brush("button_active");
        r["ButtonBackgroundDisabled"] = Brush("button_disabled");
        r["ButtonForeground"] = Brush("text");
        r["ButtonForegroundPointerOver"] = Brush("text");
        r["ButtonForegroundPressed"] = Brush("text");
        r["ButtonForegroundDisabled"] = Brush("text_dim");
        r["SliderTrackFill"] = Brush("track");
        r["SliderTrackFillPointerOver"] = Brush("track");
        r["SliderTrackValueFill"] = Brush("accent");
        r["SliderTrackValueFillPointerOver"] = Brush("accent_hover");
        r["SliderThumbBackground"] = Brush("accent");
        r["SliderThumbBackgroundPointerOver"] = Brush("accent_hover");
        r["SliderThumbBackgroundPressed"] = Brush("accent_hover");
        r["ListBoxBackground"] = Brush("panel");
        r["ListBoxItemBackgroundSelected"] = Brush("selected");
        r["ListBoxItemBackgroundSelectedPointerOver"] = Brush("selected");
    }
}
