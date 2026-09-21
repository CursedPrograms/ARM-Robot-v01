// FleetServer.cs - Fleet mode: bridges RIFT's HTTP protocol
// (https://github.com/CursedPrograms/RIFT) to FleetState.Angles, which the UI
// tick reads each frame and sends over serial like any other mode. Also serves
// the scripts/web/ control page so the arm can be driven from any browser on
// the network. Same endpoints and wire protocol as controller.py's Flask app
// and the C++ controller's fleet_server.cpp.

using System.Net;
using System.Net.Sockets;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace ArmController;

public sealed class FleetState
{
    public readonly object Lock = new();
    public readonly Dictionary<int, int> Angles = new();
}

public sealed class FleetServer : IDisposable
{
    const string FleetName = "ARM";
    const string FleetType = "robot";
    const string FleetCapabilities = "servo_control,6dof,arm";
    public const int DefaultPort = 5011;
    static readonly TimeSpan HeartbeatInterval = TimeSpan.FromSeconds(10); // must stay under RIFT's 20s TTL

    WebApplication? _app;
    CancellationTokenSource? _cts;

    /// <summary>Best-effort LAN IP, so the UI can show an address RIFT (on another device) can reach.</summary>
    public static string LocalLanIp()
    {
        try
        {
            using var s = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp);
            s.Connect("8.8.8.8", 80); // UDP connect: no traffic is actually sent
            return ((IPEndPoint)s.LocalEndPoint!).Address.ToString();
        }
        catch
        {
            return "127.0.0.1";
        }
    }

    /// <summary>Starts the HTTP bridge (and RIFT heartbeat if requested). Returns "" on success, else an error message.</summary>
    public string Start(IReadOnlyDictionary<int, Motor> motors, FleetState state, Func<bool> connected,
                        int port, bool register, string riftHost, int riftPort)
    {
        try
        {
            var builder = WebApplication.CreateBuilder();
            builder.Logging.ClearProviders();
            builder.WebHost.UseUrls($"http://0.0.0.0:{port}");
            var app = builder.Build();
            MapRoutes(app, motors, state, connected);
            Task.Run(() => app.StartAsync()).GetAwaiter().GetResult();
            _app = app;
        }
        catch (Exception e)
        {
            return $"Could not start Fleet server on port {port} (already in use?): {e.Message}";
        }

        if (register)
        {
            _cts = new CancellationTokenSource();
            _ = Task.Run(() => HeartbeatLoop(riftHost, riftPort, _cts.Token));
        }
        return "";
    }

    static IResult ServeFile(string name, string contentType)
    {
        string path = Path.Combine(Config.WebDir, name);
        return File.Exists(path) ? Results.Bytes(File.ReadAllBytes(path), contentType) : Results.NotFound("Not found");
    }

    static IResult Error(string message) => Results.Json(new Dictionary<string, object> { ["error"] = message }, statusCode: 400);

    static void MapRoutes(WebApplication app, IReadOnlyDictionary<int, Motor> motors, FleetState state, Func<bool> connected)
    {
        app.MapGet("/", () => ServeFile("index.html", "text/html; charset=utf-8"));
        app.MapGet("/style.css", () => ServeFile("style.css", "text/css; charset=utf-8"));
        app.MapGet("/app.js", () => ServeFile("app.js", "application/javascript; charset=utf-8"));
        app.MapGet("/ping", () => Results.Text($"{FleetName} alive", "text/plain"));

        app.MapGet("/status", () =>
        {
            var motorsJson = new Dictionary<string, object>();
            lock (state.Lock)
            {
                foreach (var (n, m) in motors)
                    motorsJson[n.ToString()] = new Dictionary<string, object>
                    {
                        ["channel"] = m.Channel, ["angle"] = state.Angles[n], ["min"] = m.Min, ["max"] = m.Max,
                    };
            }
            return Results.Json(new Dictionary<string, object> { ["connected"] = connected(), ["motors"] = motorsJson });
        });

        app.MapGet("/cmd", (HttpRequest req) =>
        {
            if (!int.TryParse(req.Query["motor"].ToString(), out int motor) || !int.TryParse(req.Query["angle"].ToString(), out int angle))
                return Error("expected ?motor=<1-6>&angle=<degrees>");
            if (!motors.TryGetValue(motor, out var m))
                return Error($"unknown motor {motor}");
            angle = Math.Clamp(angle, m.Min, m.Max);
            lock (state.Lock) state.Angles[motor] = angle;
            return Results.Json(new Dictionary<string, object> { ["motor"] = motor, ["angle"] = angle });
        });

        app.MapGet("/reset", (HttpRequest req) =>
        {
            if (req.Query.ContainsKey("motor"))
            {
                if (!int.TryParse(req.Query["motor"].ToString(), out int motor) || !motors.TryGetValue(motor, out var m))
                    return Error($"unknown motor {req.Query["motor"]}");
                lock (state.Lock) state.Angles[motor] = m.Rest;
                return Results.Json(new Dictionary<string, object> { ["motor"] = motor, ["angle"] = m.Rest });
            }

            var all = new Dictionary<string, object>();
            lock (state.Lock)
            {
                foreach (var (n, m) in motors)
                {
                    state.Angles[n] = m.Rest;
                    all[n.ToString()] = m.Rest;
                }
            }
            return Results.Json(all);
        });
    }

    static async Task HeartbeatLoop(string host, int port, CancellationToken ct)
    {
        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
        string url = $"http://{host}:{port}/register";
        while (!ct.IsCancellationRequested)
        {
            try
            {
                using var form = new FormUrlEncodedContent(new Dictionary<string, string>
                {
                    ["name"] = FleetName, ["type"] = FleetType, ["capabilities"] = FleetCapabilities,
                });
                using var _ = await http.PostAsync(url, form, ct);
            }
            catch
            {
                // RIFT/NORA not reachable yet - keep retrying.
            }

            try { await Task.Delay(HeartbeatInterval, ct); }
            catch (OperationCanceledException) { break; }
        }
    }

    public void Dispose()
    {
        _cts?.Cancel();
        if (_app != null)
        {
            try { Task.Run(() => _app.StopAsync(TimeSpan.FromSeconds(1))).Wait(TimeSpan.FromSeconds(2)); }
            catch { /* shutting down anyway */ }
        }
    }
}
