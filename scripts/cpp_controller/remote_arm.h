// remote_arm.h - Client mode (--connect URL): this controller has no serial
// port. A background thread mirrors another controller's shared angles
// (GET /status) into FleetState::angles and pushes local changes back
// (GET /cmd), so every controller and browser pointed at the same arm stays
// in sync. Same behaviour as controller.py's RemoteArm.
#pragma once

#include <atomic>
#include <map>
#include <string>
#include <thread>

#include "fleet_server.h"

class RemoteArm {
public:
    ~RemoteArm();

    // baseUrl like "http://192.168.0.10:5011". Returns "" on success or an error message.
    std::string start(const std::string& baseUrl, FleetState& state);
    void stop();

    // Angles (motor number -> angle) that changed locally and must be pushed to the hub.
    void queue(const std::map<int, int>& changed);

    bool connected() const { return connected_; }
    // True once we've seen the hub's real angles at least once.
    bool synced() const { return synced_; }

private:
    void loop();
    bool httpGet(const std::string& path, std::string& body);

    std::string host_;
    int port_ = 80;
    FleetState* state_ = nullptr;
    std::map<int, int> pending_; // guarded by state_->mutex

    std::atomic<bool> running_{false};
    std::atomic<bool> connected_{false};
    std::atomic<bool> synced_{false};
    std::thread thread_;
};
