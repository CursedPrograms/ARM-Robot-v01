// SerialLink.cs - USB serial link to the Arduino running scripts/arm/arm.ino.
// Wraps System.IO.Ports (works on Windows COM ports and Linux /dev/ttyACM*,
// /dev/ttyUSB*). Wire protocol is the same as every other controller:
// "channel:angle,channel:angle,...\n".

using System.IO.Ports;

namespace ArmController;

public sealed class SerialLink : IDisposable
{
    SerialPort? _port;

    public bool IsOpen => _port?.IsOpen == true;

    /// <summary>Returns null on success, or an error message.</summary>
    public string? Open(string name, int baud)
    {
        try
        {
            _port = new SerialPort(name, baud)
            {
                WriteTimeout = 200,
                DtrEnable = true, // same as pyserial's default: resets the Arduino on connect
            };
            _port.Open();
            Thread.Sleep(2000); // give the Arduino time to reset after the connection opens
            return null;
        }
        catch (Exception e)
        {
            _port?.Dispose();
            _port = null;
            return e.Message;
        }
    }

    public void WriteLine(string line)
    {
        if (_port is not { IsOpen: true }) return;
        try
        {
            _port.Write(line + "\n");
        }
        catch (Exception e) when (e is TimeoutException or IOException or InvalidOperationException or UnauthorizedAccessException)
        {
            // Device unplugged or stalled: drop this update, the next frame will retry.
        }
    }

    public static string[] ListPorts()
    {
        var names = SerialPort.GetPortNames();
        if (OperatingSystem.IsLinux())
        {
            // GetPortNames() also returns every phantom /dev/ttyS* - keep only USB-serial style devices.
            names = names.Where(n => n.Contains("ttyUSB") || n.Contains("ttyACM") ||
                                     n.Contains("ttyAMA") || n.Contains("rfcomm")).ToArray();
        }
        Array.Sort(names, StringComparer.Ordinal);
        return names;
    }

    /// <summary>
    /// Best-effort guess at the Arduino's port. System.IO.Ports can't read USB
    /// descriptions (unlike pyserial), so on Linux this prefers ttyACM*/ttyUSB*,
    /// and on Windows only auto-picks when there's exactly one COM port.
    /// </summary>
    public static string? AutoDetect()
    {
        var ports = ListPorts();
        if (OperatingSystem.IsLinux())
            return ports.FirstOrDefault(p => p.Contains("ttyACM")) ?? ports.FirstOrDefault(p => p.Contains("ttyUSB"));
        return ports.Length == 1 ? ports[0] : null;
    }

    public void Dispose()
    {
        try { _port?.Close(); } catch { /* already gone */ }
        _port?.Dispose();
        _port = null;
    }
}
