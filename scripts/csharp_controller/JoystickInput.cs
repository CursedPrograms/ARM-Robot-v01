// JoystickInput.cs - Joystick and gamepad polling through SDL2 (Silk.NET.SDL),
// the same library pygame's joystick module wraps. Only SDL's joystick and
// game controller subsystems are initialised - Avalonia owns the window - and
// it's polled once per UI tick, matching controller.py's per-frame
// js.get_axis()/get_hat()/get_button().
//
// A plain joystick (ARM's own stick) is read as-is. A gamepad SDL knows the
// layout of (Xbox, PlayStation, Switch Pro...) is read through SDL's game
// controller API and handed out in the stick's numbering: left stick = axes
// 0/1, right stick across = axis 2 (wrist roll), D-pad = the hat, A/B/X/Y =
// buttons 0-3. Pick() takes a joystick first, else a gamepad, like
// controller.py's pick_joystick().

using System.Runtime.InteropServices;
using Silk.NET.SDL;

namespace ArmController;

public sealed unsafe class JoystickInput : IDisposable
{
    static Sdl? _sdl;
    static bool _initTried;
    static string? _initError;

    readonly Joystick* _js;
    readonly GameController* _pad;

    public string Name { get; }
    public bool IsGamepad => _pad != null;
    public int InstanceId { get; }
    public int NumAxes { get; }
    public int NumHats { get; }
    public int NumButtons { get; }

    JoystickInput(Joystick* js, GameController* pad)
    {
        _js = js;
        _pad = pad;
        InstanceId = _sdl!.JoystickInstanceID(js);
        if (pad != null)
        {
            Name = Marshal.PtrToStringUTF8((nint)_sdl.GameControllerName(pad)) ?? "?";
            NumAxes = 3;
            NumHats = 1;
            NumButtons = 4;
        }
        else
        {
            Name = Marshal.PtrToStringUTF8((nint)_sdl.JoystickName(js)) ?? "?";
            NumAxes = _sdl.JoystickNumAxes(js);
            NumHats = _sdl.JoystickNumHats(js);
            NumButtons = _sdl.JoystickNumButtons(js);
        }
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
                if (sdl.Init(Sdl.InitJoystick | Sdl.InitGamecontroller) != 0)
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

    static bool IsPadIndex(int index) => _sdl!.IsGameController(index) == SdlBool.True;

    /// <summary>One line per connected device, for --list.</summary>
    public static List<string> Describe()
    {
        var lines = new List<string>();
        if (!EnsureInit(out _)) return lines;
        int count = _sdl!.NumJoysticks();
        for (int i = 0; i < count; i++)
        {
            var dev = OpenIndex(i);
            if (dev == null) continue;
            lines.Add($"  [{i}] {dev.Name}  ({(dev.IsGamepad ? "gamepad" : "joystick")}, axes={dev.NumAxes}, buttons={dev.NumButtons}, hats={dev.NumHats})");
            dev.Dispose();
        }
        return lines;
    }

    static JoystickInput? OpenIndex(int index)
    {
        if (IsPadIndex(index))
        {
            var pad = _sdl!.GameControllerOpen(index);
            if (pad != null) return new JoystickInput(_sdl.GameControllerGetJoystick(pad), pad);
        }
        var js = _sdl!.JoystickOpen(index);
        return js == null ? null : new JoystickInput(js, null);
    }

    /// <summary>
    /// The device index to drive with: <paramref name="device"/> if given, else
    /// the first plain joystick (ARM's own stick comes first), else the first
    /// gamepad. -1 if nothing is plugged in.
    /// </summary>
    static int PickIndex(int? device)
    {
        int count = _sdl!.NumJoysticks();
        if (device is int d) return d >= 0 && d < count ? d : -1;
        for (int i = 0; i < count; i++)
            if (!IsPadIndex(i)) return i;
        return count > 0 ? 0 : -1;
    }

    /// <summary>
    /// Looks at what's plugged in (call it every second or so) and returns the
    /// device to use: <paramref name="current"/> if it's still the right one,
    /// else a newly opened one (the old one is closed), or null with a reason.
    /// </summary>
    public static JoystickInput? Pick(int? device, JoystickInput? current, out string? problem)
    {
        problem = null;
        if (!EnsureInit(out problem)) return null;
        _sdl!.JoystickUpdate(); // also notices devices plugged in or out
        int index = PickIndex(device);
        if (current != null && current.Attached && index >= 0 && _sdl.JoystickGetDeviceInstanceID(index) == current.InstanceId)
            return current;
        current?.Dispose();
        if (index < 0)
        {
            problem = "nothing plugged in";
            return null;
        }
        var dev = OpenIndex(index);
        if (dev == null) problem = Marshal.PtrToStringUTF8((nint)_sdl.GetError()) ?? "JoystickOpen failed";
        return dev;
    }

    public bool Attached => _sdl!.JoystickGetAttached(_js) == SdlBool.True;

    public void Update() => _sdl!.JoystickUpdate();

    /// <summary>Axis value in [-1, 1] (0 if the device doesn't have that axis).</summary>
    public double Axis(int axis)
    {
        if (_pad != null)
        {
            var a = axis switch
            {
                0 => GameControllerAxis.Leftx,
                1 => GameControllerAxis.Lefty,
                2 => GameControllerAxis.Rightx,
                _ => GameControllerAxis.Invalid,
            };
            return a == GameControllerAxis.Invalid ? 0.0 : _sdl!.GameControllerGetAxis(_pad, a) / 32768.0;
        }
        return NumAxes > axis ? _sdl!.JoystickGetAxis(_js, axis) / 32768.0 : 0.0;
    }

    /// <summary>Hat Y component like pygame's get_hat(): +1 up, -1 down, 0 centred.</summary>
    public int HatY(int hat)
    {
        if (NumHats <= hat) return 0;
        if (_pad != null)
        {
            if (_sdl!.GameControllerGetButton(_pad, GameControllerButton.DpadUp) != 0) return 1;
            if (_sdl.GameControllerGetButton(_pad, GameControllerButton.DpadDown) != 0) return -1;
            return 0;
        }
        byte h = _sdl!.JoystickGetHat(_js, hat);
        if ((h & Sdl.HatUp) != 0) return 1;
        if ((h & Sdl.HatDown) != 0) return -1;
        return 0;
    }

    public bool Button(int button)
    {
        if (_pad != null)
        {
            var b = button switch
            {
                0 => GameControllerButton.A,
                1 => GameControllerButton.B,
                2 => GameControllerButton.X,
                3 => GameControllerButton.Y,
                _ => GameControllerButton.Invalid,
            };
            return b != GameControllerButton.Invalid && _sdl!.GameControllerGetButton(_pad, b) != 0;
        }
        return NumButtons > button && _sdl!.JoystickGetButton(_js, button) != 0;
    }

    public void Dispose()
    {
        if (_pad != null) _sdl?.GameControllerClose(_pad);
        else _sdl?.JoystickClose(_js);
    }
}
