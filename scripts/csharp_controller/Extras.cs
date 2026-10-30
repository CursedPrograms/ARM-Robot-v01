// Extras.cs - what controller.py has beyond driving her: her VOICE (arm_voice.ps1), her arm drawn from
// her geometry and joint maths, and the fleet's WiFi ladder (fleet_ladder.py, with --ladder).
using System.Diagnostics;
using System.Globalization;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;

namespace ArmController;

public sealed class ArmVoice
{
    static readonly TimeSpan Cooldown = TimeSpan.FromSeconds(8);   // kit.Voice's: an event at most this often
    readonly Dictionary<string, DateTime> _last = new();
    (string Mode, bool Recording, bool Playing, bool Claw)? _seen;
    public bool On { get; set; } = true;

    void Say(string name)
    {
        if (!On || (_last.TryGetValue(name, out var t) && DateTime.Now - t < Cooldown)) return;
        _last[name] = DateTime.Now;
        try
        {
            var script = Path.Combine(Config.RepoRoot, "scripts", "arm_voice.ps1");
            Process.Start(new ProcessStartInfo("powershell",
                $"-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"{script}\" {name}") { CreateNoWindow = true, UseShellExecute = false });
        }
        catch (Exception) { }   // no PowerShell: she's just quiet
    }

    // Once a tick: says what changed, as controller.py's main loop does.
    public void Watch(string mode, bool recording, bool playing, bool claw)
    {
        var was = _seen;
        _seen = (mode, recording, playing, claw);
        if (was is not { } w) { Say("connect"); return; }
        if (w.Mode != mode) Say("mode_" + mode);
        if (w.Recording != recording) Say(recording ? "record_on" : "record_off");
        if (w.Playing != playing) Say(playing ? "play" : "stop");
        if (w.Claw != claw) Say(claw ? "claw_close" : "claw_open");
    }
}

public static class FleetLadder
{
    // The fleet's WiFi ladder while she runs (--ladder or FLEET_LADDER=1), as ARMCTL.
    public static Process? Start(bool asked)
    {
        if (!asked && Environment.GetEnvironmentVariable("FLEET_LADDER") != "1") return null;
        try
        {
            var script = Path.Combine(Config.RepoRoot, "scripts", "fleet_ladder.py");
            return Process.Start(new ProcessStartInfo(OperatingSystem.IsWindows() ? "python" : "python3",
                $"\"{script}\" ARMCTL --run") { CreateNoWindow = true, UseShellExecute = false });
        }
        catch (Exception) { return null; }
    }
}

// Her arm, as controller.py's draw_arm(): from the side, and from above (the base turning).
public sealed class ArmView : Control
{
    public const int PanelWidth = 300;
    readonly IReadOnlyDictionary<int, Motor> _motors;
    readonly ArmGeometry _g;
    Dictionary<int, int> _angles = new();

    public ArmView(IReadOnlyDictionary<int, Motor> motors, ArmGeometry geometry)
    {
        _motors = motors;
        _g = geometry;
        Width = PanelWidth - 16;
        Height = 560;
    }

    public void Show(Dictionary<int, int> angles)
    {
        if (_angles.Count == angles.Count && _angles.All(kv => angles.TryGetValue(kv.Key, out int v) && v == kv.Value)) return;
        _angles = angles;
        InvalidateVisual();
    }

    double Rad(int n)
    {
        if (!_motors.TryGetValue(n, out var m)) return 0;
        return (_angles.GetValueOrDefault(n, m.Rest) - m.Rest) * m.KinematicSign * Math.PI / 180;
    }

    public override void Render(DrawingContext c)
    {
        double w = Width;
        IBrush track = ColourScheme.Brush("track"), knob = ColourScheme.Brush("button_hover"), accent = ColourScheme.Brush("accent"),
               panel = ColourScheme.Brush("panel"), dim = ColourScheme.Brush("text_dim"), text = ColourScheme.Brush("text");
        void Text(string s, IBrush b, double x, double y) =>
            c.DrawText(new FormattedText(s, CultureInfo.InvariantCulture, FlowDirection.LeftToRight, Typeface.Default, 12, b), new Point(x, y));

        c.FillRectangle(panel, new Rect(0, 0, w, Height), 8);
        Text("from the side", dim, 10, 8);
        double l1 = _g.UpperArmLength, l2 = _g.ForearmLength, l3 = _g.WristLength, h0 = _g.BaseHeight;
        double reach = l1 + l2 + l3;
        if (reach <= 0) reach = 300;
        double s = Math.Min((w - 60) / reach, 230 / (reach + h0));
        Point Pt(double r, double z) => new(30 + r * s, 270 - z * s);
        var thin = new Pen(track, 1);
        c.DrawLine(thin, new Point(10, 270), new Point(w - 10, 270));
        using (c.PushClip(new Rect(0, 24, w, 276))) c.DrawEllipse(null, thin, Pt(0, h0), reach * s, reach * s);

        double a1 = Rad(2), a2 = a1 + Rad(3), a3 = a2 + Rad(4), r = 0, z = h0;
        var limb = new Pen(knob, 6, lineCap: PenLineCap.Round);
        foreach (var (len, a) in new[] { (l1, a1), (l2, a2), (l3, a3) })
        {
            var from = Pt(r, z);
            r += len * Math.Cos(a);
            z += len * Math.Sin(a);
            c.DrawLine(limb, from, Pt(r, z));
            c.DrawEllipse(accent, null, Pt(r, z), 6, 6);
            c.DrawEllipse(panel, null, Pt(r, z), 3, 3);
        }
        var tip = Pt(r, z);
        double open = _motors.TryGetValue(6, out var claw) && _angles.GetValueOrDefault(6, claw.Rest) < claw.Rest ? 0.25 : 0.5;
        var finger = new Pen(accent, 3);
        foreach (int sgn in new[] { -1, 1 })
            c.DrawLine(finger, tip, tip + new Point(14 * Math.Cos(a3 + sgn * open), -14 * Math.Sin(a3 + sgn * open)));
        Text($"tip  r {r:0}  z {z:0} mm", text, 10, 280);

        double cx = w / 2, cy = 440, rr = r * 100 / reach, b = Rad(1);
        Text("from above", dim, 10, 315);
        c.DrawEllipse(null, thin, new Point(cx, cy), 100, 100);
        var end = new Point(cx + rr * Math.Sin(b), cy - rr * Math.Cos(b));
        c.DrawLine(limb, new Point(cx, cy), end);
        c.DrawEllipse(accent, null, new Point(cx, cy), 8, 8);
        c.DrawEllipse(accent, null, end, 5, 5);
        Text($"base {b * 180 / Math.PI:+0;-0;0} deg", text, 10, 544);
    }
}
