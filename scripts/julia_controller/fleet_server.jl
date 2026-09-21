# fleet_server.jl - Fleet mode: bridges RIFT's HTTP protocol
# (https://github.com/CursedPrograms/RIFT) to fleet_state.angles, which the
# main loop reads each frame and sends over serial like any other mode. Also
# serves the scripts/web/ control page, so the arm can be driven from any
# browser on the network, not just RIFT. Julia counterpart of controller.py's
# create_fleet_app()/start_fleet_heartbeat() and the C++ controller's
# fleet_server.cpp - same endpoints, same wire protocol.

import HTTP
import JSON3
import Sockets

const FLEET_NAME = "ARM"
const FLEET_TYPE = "robot"
const FLEET_CAPABILITIES = ["servo_control", "6dof", "arm"]
const DEFAULT_FLEET_PORT = 5011
# Must stay under RIFT's FLEET_TTL_SECS (20s).
const FLEET_HEARTBEAT_SECS = 10

mutable struct FleetState
    angles::Dict{Int,Int}
    lock::ReentrantLock
end
FleetState(angles::Dict{Int,Int}) = FleetState(angles, ReentrantLock())

function local_lan_ip()
    try
        return string(Sockets.getipaddr())
    catch
        return "127.0.0.1"
    end
end

function content_type_for(path)
    endswith(path, ".html") && return "text/html; charset=utf-8"
    endswith(path, ".css") && return "text/css; charset=utf-8"
    endswith(path, ".js") && return "application/javascript; charset=utf-8"
    return "application/octet-stream"
end

function serve_file(full_path::AbstractString, url_path::AbstractString)
    isfile(full_path) || return HTTP.Response(404, "Not found")
    body = read(full_path)
    return HTTP.Response(200, ["Content-Type" => content_type_for(url_path)], body)
end

json_response(status::Int, obj) =
    HTTP.Response(status, ["Content-Type" => "application/json"], JSON3.write(obj))

function make_handler(motors, fleet_state::FleetState, connected_fn::Function, web_dir::AbstractString)
    return function (req::HTTP.Request)
        uri = HTTP.URI(req.target)
        path = uri.path

        if path == "/"
            return serve_file(joinpath(web_dir, "index.html"), "/index.html")
        elseif path == "/style.css" || path == "/app.js"
            return serve_file(joinpath(web_dir, path[2:end]), path)
        elseif path == "/ping"
            return HTTP.Response(200, "$FLEET_NAME alive")
        elseif path == "/status"
            motors_json = Dict{String,Any}()
            lock(fleet_state.lock) do
                for (n, m) in motors
                    motors_json[string(n)] = Dict(
                        "channel" => m["channel"], "angle" => fleet_state.angles[n],
                        "min" => m["min"], "max" => m["max"],
                    )
                end
            end
            return json_response(200, Dict("connected" => connected_fn(), "motors" => motors_json))
        elseif path == "/cmd"
            q = HTTP.queryparams(uri)
            motor = tryparse(Int, get(q, "motor", ""))
            angle = tryparse(Int, get(q, "angle", ""))
            if motor === nothing || angle === nothing
                return json_response(400, Dict("error" => "expected ?motor=<1-6>&angle=<degrees>"))
            elseif !haskey(motors, motor)
                return json_response(400, Dict("error" => "unknown motor $motor"))
            else
                m = motors[motor]
                angle = clamp(angle, m["min"], m["max"])
                lock(fleet_state.lock) do
                    fleet_state.angles[motor] = angle
                end
                return json_response(200, Dict("motor" => motor, "angle" => angle))
            end
        elseif path == "/reset"
            q = HTTP.queryparams(uri)
            if haskey(q, "motor")
                motor = tryparse(Int, q["motor"])
                if motor === nothing || !haskey(motors, motor)
                    return json_response(400, Dict("error" => "unknown motor $(get(q, "motor", ""))"))
                end
                rest_angle = motors[motor]["rest"]
                lock(fleet_state.lock) do
                    fleet_state.angles[motor] = rest_angle
                end
                return json_response(200, Dict("motor" => motor, "angle" => rest_angle))
            else
                resp = Dict{String,Any}()
                lock(fleet_state.lock) do
                    for (n, m) in motors
                        fleet_state.angles[n] = m["rest"]
                        resp[string(n)] = m["rest"]
                    end
                end
                return json_response(200, resp)
            end
        else
            return HTTP.Response(404, "Not found")
        end
    end
end

function start_fleet_heartbeat(rift_host::AbstractString, rift_port::Int; interval::Real=FLEET_HEARTBEAT_SECS)
    @async begin
        while true
            try
                HTTP.post(
                    "http://$rift_host:$rift_port/register",
                    ["Content-Type" => "application/x-www-form-urlencoded"],
                    HTTP.escapeuri(Dict(
                        "name" => FLEET_NAME, "type" => FLEET_TYPE,
                        "capabilities" => join(FLEET_CAPABILITIES, ","),
                    ));
                    readtimeout=2, connect_timeout=2,
                )
            catch
                # RIFT/NORA not reachable yet - keep retrying.
            end
            sleep(interval)
        end
    end
end

"""
    start_fleet_server(motors, fleet_state, connected_fn; port, register, rift_host, rift_port, web_dir)

Starts the Fleet-mode HTTP bridge (non-blocking) and, if `register`, a
background RIFT/NORA heartbeat. Returns "" on success, or an error message
(e.g. port already in use) - never throws, so Fleet mode failing doesn't
crash the rest of the controller.
"""
function start_fleet_server(motors, fleet_state::FleetState, connected_fn::Function;
                             port::Int=DEFAULT_FLEET_PORT, register::Bool=true,
                             rift_host::AbstractString="127.0.0.1", rift_port::Int=5000,
                             web_dir::AbstractString)
    try
        probe = Sockets.listen(Sockets.InetAddr(Sockets.ip"0.0.0.0", port))
        close(probe)
    catch e
        return "Could not bind to port $port (already in use?): $e"
    end

    handler = make_handler(motors, fleet_state, connected_fn, web_dir)
    try
        # HTTP.serve! is itself non-blocking (spawns its own background
        # accept loop and returns immediately) - calling it directly here
        # means a synchronous startup failure is actually caught below.
        HTTP.serve!(handler, "0.0.0.0", port; verbose=false)
    catch e
        return "Failed to start Fleet HTTP server: $e"
    end

    register && start_fleet_heartbeat(rift_host, rift_port)
    return ""
end
