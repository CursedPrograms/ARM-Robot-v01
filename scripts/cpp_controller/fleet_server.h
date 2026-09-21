// fleet_server.h - HTTP bridge that lets RIFT (https://github.com/CursedPrograms/RIFT)
// see and control this arm over the network, the same way it talks to
// MILA/WHIP/NORA/KIDA - and also serves the scripts/web/ browser control
// page. Same wire protocol as controller.py's Fleet mode
// (/status, /cmd?motor=&angle=, /reset, /ping), so either implementation can
// sit behind the same URL.
#pragma once

#include <functional>
#include <map>
#include <mutex>
#include <string>
#include <thread>

#include "motor_config.h"

struct FleetState {
    std::mutex mutex;
    std::map<int, int> angles; // motor number -> current commanded angle
};

class FleetServer {
public:
    ~FleetServer();

    // motors/state must outlive the server. connectedFn reports whether the
    // Arduino's serial connection is currently open, for /status.
    // Returns an empty string on success, or an error message on failure.
    std::string start(const MotorMap& motors, FleetState& state,
                       std::function<bool()> connectedFn, int port,
                       bool registerToRift, const std::string& riftHost, int riftPort);

    void stop();

private:
    void acceptLoop();
    void heartbeatLoop(std::string riftHost, int riftPort);
    void handleConnection(uintptr_t clientSocket);

    const MotorMap* motors_ = nullptr;
    FleetState* state_ = nullptr;
    std::function<bool()> connected_;

    uintptr_t listenSocket_ = 0; // SOCKET, kept as uintptr_t to avoid <winsock2.h> here
    std::thread serverThread_;
    std::thread heartbeatThread_;
    volatile bool running_ = false;
};
