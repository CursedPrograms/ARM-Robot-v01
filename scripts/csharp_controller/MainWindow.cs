// MainWindow.cs - The controller window: Avalonia counterpart of controller.py
// and the C++ controller's app.cpp. Same four modes (Joystick/Sliders/IK/Fleet),
// same macro record/replay, same window layout and wire protocol to
// scripts/arm/arm.ino, so it's interchangeable with the other controllers
// (same config.json, same scripts/macros/*.json, same scripts/web/ page).
//
// The UI is built in code (no XAML) and driven by a single DispatcherTimer
// "tick" that plays the role of controller.py's per-frame loop.

using System.Collections.ObjectModel;
using System.Diagnostics;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Threading;

namespace ArmController;

public sealed class MainWindow : Window
{
    // ---- Window layout (mirrors controller.py / app.cpp) ----
    const int WindowWidth = 580, WindowHeight = 700;
    const int ModeButtonY = 56, TransportButtonY = 100, MacroListY = 138, MacroListH = 70;
    const int MarginTop = 250, RowHeight = 60;

    // ---- Joystick wiring (Joystick mode only, mirrors controller.py) ----
    const int AxisMotor1 = 0, AxisMotor2 = 1, AxisMotor5 = 2; // A2 and A3 move together on this stick; only A2 is read
    const int HatMotor3 = 0;
    const int ButtonMotor4Backward = 2, ButtonMotor4Forward = 3, ButtonMotor6Close = 0;
    const double Deadzone = 0.05;

    sealed class SliderRow
    {
        public int Motor;
        public TextBlock Label = null!;
        public Slider Track = null!;
        public TextBlock Value = null!;

        public int Position => (int)Math.Round(Track.Value);

        public void SetVisible(bool visible)
        {
            Label.IsVisible = visible;
            Track.IsVisible = visible;
            Value.IsVisible = visible;
        }
    }

    readonly Options _opts;
    readonly SortedDictionary<int, Motor> _motors;
    readonly ArmGeometry _geometry;
    readonly double _reach;

    readonly SerialLink _serial = new();
    readonly JoystickInput? _joystick;
    string _statusText = "";

    ControlMode _mode;

    // ---- controls ----
    readonly Canvas _canvas = new();
    TextBlock _status = null!;
    TextBlock _warn = null!;
    readonly Button[] _btnMode = new Button[4];
    Button _btnRecord = null!;
    Button _btnPlay = null!;
    ListBox _macroList = null!;
    Button _btnElbow = null!;
    Button _btnClaw = null!;
    readonly TextBlock[] _motorLines = new TextBlock[6];
    readonly List<SliderRow> _sliderRows = new();
    readonly Dictionary<string, SliderRow> _ikRows = new();
    readonly ObservableCollection<string> _macroItems = new();

    bool _elbowDown, _clawClosed, _ikReachable = true;
    Dictionary<int, int>? _lastValidIk;

    // ---- macros ----
    List<string> _macros = new();
    int _selectedMacro = -1;
    bool _recording;
    List<MacroStep> _recordSteps = new();
    readonly Stopwatch _recordClock = new();
    bool _playing;
    List<MacroStep> _playSteps = new();
    readonly Stopwatch _playClock = new();
    int _playIndex;
    ControlMode _playPrevMode;

    Dictionary<int, int> _lastSent = new(); // channel -> angle
    Dictionary<int, int> _prevLocal = new(); // last angle each local input produced, by motor number (see MergeLocal)
    ControlMode _lastMode;
    readonly RemoteArm? _remote;
    bool _adopted; // a client waits for the hub's real angles before its own inputs may write

    // ---- fleet ----
    readonly FleetServer _fleet = new();
    readonly FleetState _fleetState = new();
    bool _fleetStarted;
    string _fleetError = "";
    readonly string _fleetLanIp = FleetServer.LocalLanIp();

    readonly DispatcherTimer _timer;

    public MainWindow(Options opts)
    {
        _opts = opts;
        Title = "Arm Controller (C#)";
        Width = WindowWidth;
        Height = WindowHeight;
        CanResize = false;

        _motors = Config.LoadMotors();
        _geometry = Config.LoadGeometry();
        double reach = _geometry.UpperArmLength + _geometry.ForearmLength + _geometry.WristLength;
        _reach = reach > 0 ? reach : 300;
        foreach (var (n, m) in _motors) _fleetState.Angles[n] = m.Rest;

        _joystick = JoystickInput.Open(opts.Device, out string? joystickProblem);
        if (_joystick != null) Console.WriteLine($"Using joystick: {_joystick.Name}");
        else Console.WriteLine($"No joystick found - Joystick mode will be unavailable. ({joystickProblem})");

        string? port = opts.Connect != null ? null : opts.Port ?? SerialLink.AutoDetect();
        if (port != null)
        {
            string? err = _serial.Open(port, opts.Baud);
            _statusText = err == null ? $"Connected to {port} @ {opts.Baud} baud." : $"Could not open {port}: {err}";
        }
        else if (opts.Connect != null)
        {
            _statusText = $"Remote arm at {opts.Connect} (no local serial port).";
        }
        else
        {
            _statusText = "No Arduino-like serial port found - display-only mode (use --port).";
        }
        Console.WriteLine(_statusText);

        _mode = opts.Mode ?? (_joystick != null ? ControlMode.Joystick : ControlMode.Slider);
        _playPrevMode = _mode;
        _lastMode = _mode;
        _remote = opts.Connect != null ? new RemoteArm(opts.Connect, _fleetState) : null;
        _adopted = _remote == null;

        BuildControls();
        Content = _canvas;
        RefreshMacroList();
        ApplyModeVisibility();
        if (_mode == ControlMode.Fleet || opts.Serve) EnsureFleetStarted();

        _timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(opts.Rate > 0 ? 1000.0 / opts.Rate : 33) };
        _timer.Tick += (_, _) => Tick();
        _timer.Start();
    }

    // =====================================================================
    // UI construction
    // =====================================================================

    T Place<T>(T control, double x, double y, double width = double.NaN, double height = double.NaN) where T : Control
    {
        Canvas.SetLeft(control, x);
        Canvas.SetTop(control, y);
        if (!double.IsNaN(width)) control.Width = width;
        if (!double.IsNaN(height)) control.Height = height;
        _canvas.Children.Add(control);
        return control;
    }

    Button MakeButton(string text, double x, double y, double w, double h) =>
        Place(new Button { Content = text, HorizontalContentAlignment = HorizontalAlignment.Center }, x, y, w, h);

    SliderRow MakeSliderRow(int y, string label, double lo, double hi, double initial) => new()
    {
        Label = Place(new TextBlock { Text = label }, 20, y + 6, 150, 20),
        Track = Place(new Slider { Minimum = lo, Maximum = hi, Value = initial }, 175, y, 300),
        Value = Place(new TextBlock(), 485, y + 6, 80, 20),
    };

    void BuildControls()
    {
        Place(new TextBlock { Text = "Arm Controller (C#)", FontSize = 18 }, 20, 6);
        _status = Place(new TextBlock { Text = _statusText, FontSize = 12, Opacity = 0.7 }, 20, 34, 540, 18);

        string[] names = { "Joystick", "Sliders", "IK", "Fleet" };
        ControlMode[] modes = { ControlMode.Joystick, ControlMode.Slider, ControlMode.Ik, ControlMode.Fleet };
        for (int i = 0; i < 4; i++)
        {
            var mode = modes[i];
            _btnMode[i] = MakeButton(names[i], 20 + i * 132, ModeButtonY, 122, 34);
            _btnMode[i].Click += (_, _) => OnModeClicked(mode);
        }

        _btnRecord = MakeButton("Record", 30, TransportButtonY, 160, 30);
        _btnRecord.Click += (_, _) => OnRecordClicked();
        _btnPlay = MakeButton("Play", 200, TransportButtonY, 160, 30);
        _btnPlay.Click += (_, _) => OnPlayClicked();

        _macroList = Place(new ListBox { ItemsSource = _macroItems, FontSize = 12 }, 30, MacroListY, 520, MacroListH);
        _macroList.SelectionChanged += (_, _) => _selectedMacro = _macroList.SelectedIndex;

        _warn = Place(new TextBlock
        {
            FontSize = 12,
            TextWrapping = Avalonia.Media.TextWrapping.Wrap,
            Foreground = Avalonia.Media.Brushes.Orange,
        }, 20, MarginTop - 38, 540, 34);

        int row = 0;
        foreach (var (n, m) in _motors)
        {
            var r = MakeSliderRow(MarginTop + row * RowHeight, $"Motor {n}", m.Min, m.Max, m.Rest);
            r.Motor = n;
            _sliderRows.Add(r);
            row++;
        }

        var m5 = _motors[5];
        _ikRows["x"] = MakeSliderRow(MarginTop + 0 * RowHeight, "Target X (mm)", -_reach, _reach, 0);
        _ikRows["y"] = MakeSliderRow(MarginTop + 1 * RowHeight, "Target Y (mm)", -_reach, _reach, 0);
        _ikRows["z"] = MakeSliderRow(MarginTop + 2 * RowHeight, "Target Z (mm)", 0, _reach, _geometry.BaseHeight);
        _ikRows["pitch"] = MakeSliderRow(MarginTop + 3 * RowHeight, "Pitch (deg)", -90, 90, 0);
        _ikRows["roll"] = MakeSliderRow(MarginTop + 4 * RowHeight, "Roll (motor 5)", m5.Min, m5.Max, m5.Rest);

        _btnElbow = MakeButton("Elbow: Up", 30, MarginTop + 5 * RowHeight, 150, 30);
        _btnElbow.Click += (_, _) =>
        {
            _elbowDown = !_elbowDown;
            _btnElbow.Content = _elbowDown ? "Elbow: Down" : "Elbow: Up";
        };
        _btnClaw = MakeButton("Claw: Open", 200, MarginTop + 5 * RowHeight, 150, 30);
        _btnClaw.Click += (_, _) =>
        {
            _clawClosed = !_clawClosed;
            _btnClaw.Content = _clawClosed ? "Claw: Closed" : "Claw: Open";
        };

        for (int i = 0; i < _motorLines.Length; i++)
            _motorLines[i] = Place(new TextBlock { FontSize = 16 }, 20, MarginTop + i * 28, 500, 22);
    }

    void ApplyModeVisibility()
    {
        bool ikOk = _geometry.Ready;
        foreach (var r in _sliderRows) r.SetVisible(_mode == ControlMode.Slider);
        foreach (var r in _ikRows.Values) r.SetVisible(_mode == ControlMode.Ik && ikOk);
        _btnElbow.IsVisible = _btnClaw.IsVisible = _mode == ControlMode.Ik && ikOk;

        bool showLines = _mode is ControlMode.Joystick or ControlMode.Fleet;
        foreach (var line in _motorLines) line.IsVisible = showLines;

        string[] names = { "Joystick", "Sliders", "IK", "Fleet" };
        for (int i = 0; i < 4; i++)
        {
            _btnMode[i].IsEnabled = i != 0 || _joystick != null;
            _btnMode[i].Content = (int)_mode == i ? $"[{names[i]}]" : names[i];
        }
    }

    void SetMode(ControlMode mode)
    {
        _mode = mode;
        ApplyModeVisibility();
        if (mode == ControlMode.Fleet) EnsureFleetStarted();
    }

    void EnsureFleetStarted()
    {
        if (_fleetStarted || _fleetError != "" || _opts.Connect != null) return; // a client has no arm of its own to serve
        string err = _fleet.Start(_motors, _fleetState, () => _serial.IsOpen,
                                  _opts.FleetPort, !_opts.NoRegister, _opts.RiftHost, _opts.RiftPort);
        if (err == "")
        {
            _fleetStarted = true;
            string url = $"http://{_fleetLanIp}:{_opts.FleetPort}";
            Console.WriteLine($"Web control on {url}");
            _status.Text = $"{_statusText}  |  Web: {url}";
        }
        else
        {
            _fleetError = err;
            Console.WriteLine(err);
        }
    }

    void RefreshMacroList()
    {
        _macros = Macros.List();
        _macroItems.Clear();
        foreach (var path in _macros) _macroItems.Add(Path.GetFileNameWithoutExtension(path));
        _macroList.SelectedIndex = _macros.Count > 0 ? 0 : -1;
        _selectedMacro = _macroList.SelectedIndex;
    }

    // =====================================================================
    // Button handlers
    // =====================================================================

    void OnModeClicked(ControlMode mode)
    {
        if (_playing) return;
        SetMode(mode);
    }

    void OnRecordClicked()
    {
        if (_playing) return;
        if (!_recording)
        {
            _recording = true;
            _recordSteps = new List<MacroStep>();
            _recordClock.Restart();
            return;
        }

        _recording = false;
        _btnRecord.Content = "Record";
        if (_recordSteps.Count == 0) return;
        try
        {
            string path = Macros.Save(_recordSteps);
            Console.WriteLine($"Saved macro: {Path.GetFileName(path)} ({_recordSteps.Count} steps)");
            RefreshMacroList();
        }
        catch (Exception e)
        {
            _status.Text = $"Could not save macro: {e.Message}";
        }
    }

    void OnPlayClicked()
    {
        if (_playing)
        {
            StopPlayback();
            return;
        }
        if (_selectedMacro < 0 || _selectedMacro >= _macros.Count) return;

        try
        {
            _playSteps = Macros.Load(_macros[_selectedMacro]);
        }
        catch (Exception e)
        {
            _status.Text = $"Could not load macro: {e.Message}";
            return;
        }
        _playIndex = 0;
        _playPrevMode = _mode;
        _playClock.Restart();
        _playing = true;
        _btnPlay.Content = "Stop";
    }

    void StopPlayback()
    {
        _playing = false;
        _btnPlay.Content = "Play";
        SetMode(_playPrevMode);
    }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        base.OnKeyDown(e);
        if (e.Key == Key.Escape)
        {
            Close();
        }
        else if (!_playing && e.Key >= Key.D1 && e.Key <= Key.D9)
        {
            int idx = (int)e.Key - (int)Key.D1;
            if (idx < _macros.Count) _macroList.SelectedIndex = idx;
        }
    }

    protected override void OnClosed(EventArgs e)
    {
        _timer.Stop();
        _fleet.Dispose();
        _remote?.Dispose();
        _joystick?.Dispose();
        _serial.Dispose();
        base.OnClosed(e);
    }

    // =====================================================================
    // Per-frame update (controller.py's main loop body)
    // =====================================================================

    static int AxisToAngle(double value, int lo, int hi)
    {
        if (Math.Abs(value) < Deadzone) value = 0.0;
        return (int)Math.Round((value + 1.0) / 2.0 * (hi - lo) + lo);
    }

    Dictionary<int, int> JoystickCommands()
    {
        var js = _joystick!;
        js.Update();

        double m1 = js.Axis(AxisMotor1);
        double m2 = js.Axis(AxisMotor2);
        double m3 = js.HatY(HatMotor3);
        double m5 = js.Axis(AxisMotor5);

        bool forward = js.Button(ButtonMotor4Forward), backward = js.Button(ButtonMotor4Backward);
        double m4 = forward && !backward ? 1.0 : backward && !forward ? -1.0 : 0.0;

        bool close = js.Button(ButtonMotor6Close);
        if (_motors[6].Invert) close = !close;

        double Inv(int n, double v) => _motors[n].Invert ? -v : v;
        m1 = Inv(1, m1); m2 = Inv(2, m2); m3 = Inv(3, m3); m4 = Inv(4, m4); m5 = Inv(5, m5);

        return new Dictionary<int, int>
        {
            [_motors[1].Channel] = AxisToAngle(m1, _motors[1].Min, _motors[1].Max),
            [_motors[2].Channel] = AxisToAngle(m2, _motors[2].Min, _motors[2].Max),
            [_motors[3].Channel] = AxisToAngle(m3, _motors[3].Min, _motors[3].Max),
            [_motors[4].Channel] = AxisToAngle(m4, _motors[4].Min, _motors[4].Max),
            [_motors[5].Channel] = AxisToAngle(m5, _motors[5].Min, _motors[5].Max),
            [_motors[6].Channel] = close ? _motors[6].Max : _motors[6].Min,
        };
    }

    static bool SameCommands(Dictionary<int, int> a, Dictionary<int, int> b) =>
        a.Count == b.Count && a.All(kv => b.TryGetValue(kv.Key, out int v) && v == kv.Value);

    void Send(Dictionary<int, int> commands)
    {
        if (SameCommands(commands, _lastSent)) return;
        string line = string.Join(",", commands.OrderBy(kv => kv.Key).Select(kv => $"{kv.Key}:{kv.Value}"));
        _serial.WriteLine(line);
        _lastSent = new Dictionary<int, int>(commands);
    }

    void Tick()
    {
        try
        {
            TickCore();
        }
        catch (Exception e)
        {
            _status.Text = $"Error: {e.Message}";
        }
    }

    // =====================================================================
    // Shared arm state. _fleetState.Angles is the single set of angles every
    // input writes to and every output (serial, web page, RIFT, the sliders)
    // reads from. An input whose value changed since last frame writes it (last
    // writer wins); inputs that didn't change leave what another input wrote
    // alone and instead follow it.
    // =====================================================================

    Dictionary<int, int> ToMotorKeyed(Dictionary<int, int> byChannel)
    {
        var result = new Dictionary<int, int>();
        foreach (var (n, m) in _motors)
            if (byChannel.TryGetValue(m.Channel, out int angle)) result[n] = angle;
        return result;
    }

    Dictionary<int, int> MergeLocal(Dictionary<int, int> localByMotor)
    {
        var changed = new Dictionary<int, int>();
        lock (_fleetState.Lock)
        {
            foreach (var (n, angle) in localByMotor)
                if (!_prevLocal.TryGetValue(n, out int prev) || prev != angle)
                {
                    _fleetState.Angles[n] = angle;
                    changed[n] = angle;
                }
        }
        _prevLocal = new Dictionary<int, int>(localByMotor);
        return changed;
    }

    Dictionary<int, int> SharedAsChannelMap()
    {
        var result = new Dictionary<int, int>();
        lock (_fleetState.Lock)
        {
            foreach (var (n, m) in _motors) result[m.Channel] = _fleetState.Angles[n];
        }
        return result;
    }

    void PublishByChannel(Dictionary<int, int> byChannel)
    {
        var changed = new Dictionary<int, int>();
        lock (_fleetState.Lock)
        {
            foreach (var (n, m) in _motors)
                if (byChannel.TryGetValue(m.Channel, out int angle))
                {
                    _fleetState.Angles[n] = angle;
                    changed[n] = angle;
                }
        }
        _remote?.Queue(changed);
    }

    // Slider positions adopt the shared angles (so web-page/other-input changes show up).
    void FollowSliders()
    {
        lock (_fleetState.Lock)
        {
            foreach (var row in _sliderRows)
            {
                int shared = _fleetState.Angles[row.Motor];
                if (row.Position != shared) row.Track.Value = shared;
                _prevLocal[row.Motor] = shared;
                row.Value.Text = $"{shared}\u00B0";
            }
        }
    }

    void TickCore()
    {
        if (_playing)
        {
            double elapsed = _playClock.Elapsed.TotalSeconds;
            while (_playIndex < _playSteps.Count && _playSteps[_playIndex].T <= elapsed)
            {
                Send(_playSteps[_playIndex].Commands);
                PublishByChannel(_playSteps[_playIndex].Commands);
                _playIndex++;
            }
            if (_mode == ControlMode.Slider) FollowSliders();
            _btnPlay.Content = $"Stop {_playIndex}/{_playSteps.Count}";
            if (_playIndex >= _playSteps.Count) StopPlayback();
            return;
        }

        if (_mode != _lastMode)
        {
            _prevLocal.Clear();
            if (_mode == ControlMode.Slider) FollowSliders();
            _lastMode = _mode;
        }

        Dictionary<int, int>? local = null; // channel -> angle from this mode's own input, if any
        string warn = "";

        switch (_mode)
        {
            case ControlMode.Joystick:
                if (_joystick != null) local = JoystickCommands();
                else warn = "No joystick connected.";
                break;

            case ControlMode.Slider:
                local = new Dictionary<int, int>();
                foreach (var row in _sliderRows) local[_motors[row.Motor].Channel] = row.Position;
                break;

            case ControlMode.Ik:
                if (!_geometry.Ready)
                {
                    warn = "Geometry not measured - fill in config.json's \"geometry\" section.";
                    break;
                }
                int x = _ikRows["x"].Position, y = _ikRows["y"].Position, z = _ikRows["z"].Position;
                int pitch = _ikRows["pitch"].Position, roll = _ikRows["roll"].Position;
                _ikRows["x"].Value.Text = $"{x}mm";
                _ikRows["y"].Value.Text = $"{y}mm";
                _ikRows["z"].Value.Text = $"{z}mm";
                _ikRows["pitch"].Value.Text = $"{pitch}\u00B0";
                _ikRows["roll"].Value.Text = $"{roll}";

                var sol = Kinematics.InverseKinematics(_motors, _geometry, x, y, z, pitch, _elbowDown);
                if (sol != null)
                {
                    _ikReachable = true;
                    var cmd = new Dictionary<int, int>();
                    foreach (var (n, angle) in sol) cmd[_motors[n].Channel] = angle;
                    cmd[_motors[5].Channel] = roll;
                    cmd[_motors[6].Channel] = _clawClosed ? _motors[6].Max : _motors[6].Min;
                    _lastValidIk = cmd;
                    local = cmd;
                }
                else
                {
                    _ikReachable = false;
                    local = _lastValidIk; // hold the last good pose
                }
                if (!_ikReachable) warn = "Target unreachable - holding last valid pose.";
                break;

            case ControlMode.Fleet:
                if (_opts.Connect != null)
                {
                    warn = "Showing the remote arm's angles.";
                }
                else if (_fleetError != "")
                {
                    warn = _fleetError;
                }
                else
                {
                    warn = $"Open http://{_fleetLanIp}:{_opts.FleetPort} in a browser to control";
                    if (!_opts.NoRegister) warn += $"  -  heartbeating to RIFT at {_opts.RiftHost}:{_opts.RiftPort}";
                }
                break;
        }

        _warn.Text = warn;

        // Merge this mode's input into the shared angles, then always send/record the
        // shared state (so web-page and RIFT changes reach the arm in any mode).
        if (local != null)
        {
            var localByMotor = ToMotorKeyed(local);
            if (!_adopted)
            {
                if (_remote!.Synced) // connected: take the hub's state as-is, don't move the arm
                {
                    _prevLocal = new Dictionary<int, int>(localByMotor);
                    _adopted = true;
                }
            }
            else
            {
                var changed = MergeLocal(localByMotor);
                if (_remote != null && changed.Count > 0) _remote.Queue(changed);
            }
            if (_mode == ControlMode.Slider) FollowSliders();
        }
        if (_remote != null)
            _status.Text = $"Remote arm {_opts.Connect}: " + (_remote.Connected ? "connected" : "UNREACHABLE");
        var commands = SharedAsChannelMap();
        Send(commands);
        if (_recording)
            _recordSteps.Add(new MacroStep(_recordClock.Elapsed.TotalSeconds, new Dictionary<int, int>(commands)));

        if (_mode is ControlMode.Joystick or ControlMode.Fleet) UpdateMotorLines();
        if (_recording) _btnRecord.Content = $"Recording... {_recordClock.Elapsed.TotalSeconds:F1}s";
    }

    void UpdateMotorLines()
    {
        int i = 0;
        foreach (var (n, m) in _motors)
        {
            if (i >= _motorLines.Length) break;
            _lastSent.TryGetValue(m.Channel, out int angle);
            _motorLines[i++].Text = $"Motor {n} (ch {m.Channel}): {angle}";
        }
    }
}
