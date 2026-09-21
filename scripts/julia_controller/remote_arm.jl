# remote_arm.jl - Client mode (--connect URL): this controller has no serial
# port. A background task mirrors another controller's shared angles
# (GET /status) into fleet_state.angles and pushes local changes back
# (GET /cmd), so every controller and browser pointed at the same arm stays in
# sync. Same behaviour as controller.py's RemoteArm.
#
# Note: Julia tasks are cooperative - the main loop must yield (it uses
# sleep(), not SDL_Delay) for this task and the Fleet HTTP server to run.

import HTTP
import JSON3

mutable struct RemoteArm
    base::String
    state::FleetState
    pending::Dict{Int,Int}   # guarded by state.lock
    connected::Bool
    synced::Bool             # true once we've seen the hub's real angles at least once
    running::Bool
end

function start_remote_arm(base_url::AbstractString, state::FleetState)
    ra = RemoteArm(String(rstrip(base_url, '/')), state, Dict{Int,Int}(), false, false, true)
    @async remote_loop(ra)
    return ra
end

stop_remote_arm!(ra::RemoteArm) = (ra.running = false)

function queue_remote!(ra::RemoteArm, changed)
    lock(ra.state.lock) do
        for (n, a) in changed
            ra.pending[n] = a
        end
    end
end

function remote_loop(ra::RemoteArm)
    while ra.running
        to_send = lock(ra.state.lock) do
            d = copy(ra.pending)
            empty!(ra.pending)
            d
        end
        try
            for (n, a) in to_send
                HTTP.get("$(ra.base)/cmd?motor=$n&angle=$a"; readtimeout=1, connect_timeout=1, retry=false)
            end
            resp = HTTP.get("$(ra.base)/status"; readtimeout=1, connect_timeout=1, retry=false)
            data = JSON3.read(String(resp.body), Dict{String,Any})
            lock(ra.state.lock) do
                for (key, m) in data["motors"]
                    n = parse(Int, key)
                    haskey(ra.pending, n) || (ra.state.angles[n] = round(Int, m["angle"]))  # don't overwrite an unsent change
                end
            end
            ra.connected = true
            ra.synced = true
        catch
            ra.connected = false
            lock(ra.state.lock) do
                for (n, a) in to_send
                    haskey(ra.pending, n) || (ra.pending[n] = a)  # retry next round
                end
            end
        end
        sleep(0.1)
    end
end
