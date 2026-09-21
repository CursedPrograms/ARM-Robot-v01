// RemoteArm.cs - Client mode (--connect URL): this controller has no serial
// port. A background loop mirrors another controller's shared angles
// (GET /status) into FleetState.Angles and pushes local changes back
// (GET /cmd), so every controller and browser pointed at the same arm stays
// in sync. Same behaviour as controller.py's RemoteArm.

using System.Text.Json;

namespace ArmController;

public sealed class RemoteArm : IDisposable
{
    readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(1) };
    readonly string _base;
    readonly FleetState _state;
    readonly CancellationTokenSource _cts = new();
    readonly Dictionary<int, int> _pending = new(); // guarded by _state.Lock

    public volatile bool Connected;
    /// <summary>True once we've seen the hub's real angles at least once.</summary>
    public volatile bool Synced;

    public RemoteArm(string baseUrl, FleetState state)
    {
        _base = baseUrl.TrimEnd('/');
        _state = state;
        _ = Task.Run(Loop);
    }

    public void Queue(Dictionary<int, int> changed)
    {
        lock (_state.Lock)
            foreach (var (n, angle) in changed) _pending[n] = angle;
    }

    async Task Loop()
    {
        var ct = _cts.Token;
        while (!ct.IsCancellationRequested)
        {
            Dictionary<int, int> toSend;
            lock (_state.Lock)
            {
                toSend = new Dictionary<int, int>(_pending);
                _pending.Clear();
            }

            try
            {
                foreach (var (n, angle) in toSend)
                    using (await _http.GetAsync($"{_base}/cmd?motor={n}&angle={angle}", ct)) { }

                string json = await _http.GetStringAsync($"{_base}/status", ct);
                using var doc = JsonDocument.Parse(json);
                lock (_state.Lock)
                {
                    foreach (var prop in doc.RootElement.GetProperty("motors").EnumerateObject())
                        if (int.TryParse(prop.Name, out int n) && !_pending.ContainsKey(n)) // don't overwrite an unsent change
                            _state.Angles[n] = prop.Value.GetProperty("angle").GetInt32();
                }
                Connected = true;
                Synced = true;
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch
            {
                Connected = false;
                lock (_state.Lock)
                    foreach (var (n, angle) in toSend) _pending.TryAdd(n, angle); // retry next round
            }

            try { await Task.Delay(100, ct); }
            catch (OperationCanceledException) { break; }
        }
    }

    public void Dispose()
    {
        _cts.Cancel();
        _http.Dispose();
    }
}
