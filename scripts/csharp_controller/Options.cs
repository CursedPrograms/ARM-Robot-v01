// Options.cs - Command-line options, same flags as controller.py / the C++ controller.

using System.Globalization;

namespace ArmController;

public enum ControlMode { Joystick, Slider, Ik, Fleet }

public sealed class Options
{
    public static Options Current { get; set; } = new();

    public int Device { get; set; }
    public string? Port { get; set; }
    public int Baud { get; set; } = 115200;
    public double Rate { get; set; } = 30;
    public ControlMode? Mode { get; set; }
    public bool ListJoysticks { get; set; }
    public bool ListPorts { get; set; }
    public int FleetPort { get; set; } = FleetServer.DefaultPort;
    public string RiftHost { get; set; } = "127.0.0.1";
    public int RiftPort { get; set; } = 5000;
    public bool NoRegister { get; set; }
    public bool Serve { get; set; }
    public string? Connect { get; set; }

    public static bool TryParse(string[] args, out Options options, out string error)
    {
        options = new Options();
        string? problem = Parse(args, options);
        error = problem ?? "";
        return problem == null;
    }

    static string? Parse(string[] args, Options o)
    {
        for (int i = 0; i < args.Length; i++)
        {
            string a = args[i];

            string? value = null;
            if (a is "--port" or "--connect" or "--rift-host" or "--device" or "--baud" or "--fleet-port" or "--rift-port" or "--rate" or "--mode")
            {
                if (i + 1 >= args.Length) return $"{a} requires a value";
                value = args[++i];
            }

            switch (a)
            {
                case "--list": o.ListJoysticks = true; break;
                case "--list-ports": o.ListPorts = true; break;
                case "--no-register": o.NoRegister = true; break;
                case "--serve": o.Serve = true; break;
                case "--connect": o.Connect = value; break;
                case "--port": o.Port = value; break;
                case "--rift-host": o.RiftHost = value!; break;
                case "--device":
                    if (!int.TryParse(value, out int device)) return $"{a} requires an integer";
                    o.Device = device;
                    break;
                case "--baud":
                    if (!int.TryParse(value, out int baud)) return $"{a} requires an integer";
                    o.Baud = baud;
                    break;
                case "--fleet-port":
                    if (!int.TryParse(value, out int fleetPort)) return $"{a} requires an integer";
                    o.FleetPort = fleetPort;
                    break;
                case "--rift-port":
                    if (!int.TryParse(value, out int riftPort)) return $"{a} requires an integer";
                    o.RiftPort = riftPort;
                    break;
                case "--rate":
                    if (!double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out double rate))
                        return $"{a} requires a number";
                    o.Rate = rate;
                    break;
                case "--mode":
                    switch (value)
                    {
                        case "joystick": o.Mode = ControlMode.Joystick; break;
                        case "slider": o.Mode = ControlMode.Slider; break;
                        case "ik": o.Mode = ControlMode.Ik; break;
                        case "fleet": o.Mode = ControlMode.Fleet; break;
                        default: return $"Unknown --mode '{value}' (expected joystick, slider, ik or fleet)";
                    }
                    break;
                default:
                    return $"Unknown argument: {a}";
            }
        }
        if (o.Connect != null && (o.Serve || o.Mode == ControlMode.Fleet))
            return "--connect can't be combined with --serve or --mode fleet (this controller has no arm of its own)";
        return null;
    }
}
