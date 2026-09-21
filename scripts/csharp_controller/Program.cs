// Program.cs - Entry point. Handles --list / --list-ports without opening a
// window, otherwise starts the Avalonia UI.
//
// Usage:
//   ArmController --list-ports
//   ArmController --port COM6            (Linux: --port /dev/ttyACM0)
//   ArmController --port COM6 --mode slider
//   ArmController --port COM6 --mode fleet --fleet-port 5011

using Avalonia;

namespace ArmController;

internal static class Program
{
    [STAThread]
    public static int Main(string[] args)
    {
        if (!Options.TryParse(args, out var options, out var error))
        {
            Console.Error.WriteLine(error);
            return 1;
        }

        if (options.ListPorts)
        {
            var ports = SerialLink.ListPorts();
            if (ports.Length == 0)
            {
                Console.WriteLine("No serial ports found.");
            }
            else
            {
                Console.WriteLine("Available serial ports:");
                foreach (var p in ports) Console.WriteLine($"  {p}");
            }
            return 0;
        }

        if (options.ListJoysticks)
        {
            var devices = JoystickInput.Describe();
            if (devices.Count == 0)
            {
                Console.WriteLine("No joystick/controller devices found.");
            }
            else
            {
                Console.WriteLine($"Found {devices.Count} device(s):");
                foreach (var d in devices) Console.WriteLine(d);
            }
            return 0;
        }

        Options.Current = options;
        return BuildAvaloniaApp().StartWithClassicDesktopLifetime(Array.Empty<string>());
    }

    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<App>().UsePlatformDetect();
}
