// JoystickInput.cs - Joystick polling through SDL2 (Silk.NET.SDL), the same
// library pygame's joystick module wraps. Only SDL's joystick subsystem is
// initialised - Avalonia owns the window - and it's polled once per UI tick,
// matching controller.py's per-frame js.get_axis()/get_hat()/get_button().

using System.Runtime.InteropServices;
using Silk.NET.SDL;

namespace ArmController;

public sealed unsafe class JoystickInput : IDisposable
{
    static Sdl? _sdl;
    static bool _initTried;
    static string? _initError;

    readonly Joystick* _js;

    public string Name { get; }
    public int NumAxes { get; }
    public int NumHats { get; }
    public int NumButtons { get; }

    JoystickInput(Joystick* js)
    {
        _js = js;
        Name = Marshal.PtrToStringUTF8((nint)_sdl!.JoystickName(js)) ?? "?";
        NumAxes = _sdl.JoystickNumAxes(js);
        NumHats = _sdl.JoystickNumHats(js);
        NumButtons = _sdl.JoystickNumButtons(js);
    }

    static bool EnsureInit(out string? error)
    {
        if (!_initTried)
        {
            _initTried = true;
            try
            {
                var sdl = Sdl.GetApi();
                // Without this, DirectInput on Windows only reports input while an SDL window has focus - and we have none.
                sdl.SetHint(Sdl.HintJoystickAllowBackgroundEvents, "1"u8);
                if (sdl.Init(Sdl.InitJoystick) != 0)
                    _initError = Marshal.PtrToStringUTF8((nint)sdl.GetError()) ?? "SDL_Init failed";
                else
                    _sdl = sdl;
            }
            catch (Exception e)
            {
                _initError = $"could not load SDL2: {e.Message}";
            }
        }
        error = _initError;
        return _sdl != null;
    }

    /// <summary>One line per connected device, for --list.</summary>
    public static List<string> Describe()
    {
        var lines = new List<string>();
        if (!EnsureInit(out _)) return lines;
        int count = _sdl!.NumJoysticks();
        for (int i = 0; i < count; i++)
        {
            var js = _sdl.JoystickOpen(i);
            if (js == null) continue;
            var dev = new JoystickInput(js);
            lines.Add($"  [{i}] {dev.Name}  (axes={dev.NumAxes}, buttons={dev.NumButtons}, hats={dev.NumHats})");
            dev.Dispose();
        }
        return lines;
    }

    /// <summary>Opens device <paramref name="index"/>, or returns null (with a reason) if there isn't one.</summary>
    public static JoystickInput? Open(int index, out string? problem)
    {
        problem = null;
        if (!EnsureInit(out problem)) return null;
        if (index < 0 || index >= _sdl!.NumJoysticks())
        {
            problem = "no joystick device at that index";
            return null;
        }
        var js = _sdl.JoystickOpen(index);
        if (js == null)
        {
            problem = Marshal.PtrToStringUTF8((nint)_sdl.GetError()) ?? "JoystickOpen failed";
            return null;
        }
        return new JoystickInput(js);
    }

    public void Update() => _sdl!.JoystickUpdate();

    /// <summary>Axis value in [-1, 1] (0 if the device doesn't have that axis).</summary>
    public double Axis(int axis) => NumAxes > axis ? _sdl!.JoystickGetAxis(_js, axis) / 32768.0 : 0.0;

    /// <summary>Hat Y component like pygame's get_hat(): +1 up, -1 down, 0 centred.</summary>
    public int HatY(int hat)
    {
        if (NumHats <= hat) return 0;
        byte h = _sdl!.JoystickGetHat(_js, hat);
        if ((h & Sdl.HatUp) != 0) return 1;
        if ((h & Sdl.HatDown) != 0) return -1;
        return 0;
    }

    public bool Button(int button) => NumButtons > button && _sdl!.JoystickGetButton(_js, button) != 0;

    public void Dispose() => _sdl?.JoystickClose(_js);
}
