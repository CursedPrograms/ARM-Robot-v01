#include "remote_arm.h"
#include "json.hpp"

#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>

#include <chrono>
#include <cstdlib>

#pragma comment(lib, "ws2_32.lib")

namespace {

// Connects with a short timeout instead of the OS's much longer default, so
// a hub that's down never stalls the background thread (or shutdown) for long.
SOCKET connectWithTimeout(const std::string& host, int port, int timeoutMs) {
    addrinfo hints = {};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    addrinfo* result = nullptr;
    if (getaddrinfo(host.c_str(), std::to_string(port).c_str(), &hints, &result) != 0) return INVALID_SOCKET;

    SOCKET s = socket(result->ai_family, result->ai_socktype, result->ai_protocol);
    if (s == INVALID_SOCKET) {
        freeaddrinfo(result);
        return INVALID_SOCKET;
    }

    u_long nonBlocking = 1;
    ioctlsocket(s, FIONBIO, &nonBlocking);
    connect(s, result->ai_addr, static_cast<int>(result->ai_addrlen));
    freeaddrinfo(result);

    fd_set writeSet;
    FD_ZERO(&writeSet);
    FD_SET(s, &writeSet);
    timeval tv{timeoutMs / 1000, (timeoutMs % 1000) * 1000};
    if (select(0, nullptr, &writeSet, nullptr, &tv) <= 0) {
        closesocket(s);
        return INVALID_SOCKET;
    }

    u_long blocking = 0;
    ioctlsocket(s, FIONBIO, &blocking);
    DWORD ioTimeout = static_cast<DWORD>(timeoutMs);
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&ioTimeout), sizeof(ioTimeout));
    setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, reinterpret_cast<const char*>(&ioTimeout), sizeof(ioTimeout));
    return s;
}

} // namespace

RemoteArm::~RemoteArm() { stop(); }

std::string RemoteArm::start(const std::string& baseUrl, FleetState& state) {
    std::string url = baseUrl;
    const std::string scheme = "http://";
    if (url.compare(0, scheme.size(), scheme) == 0) url = url.substr(scheme.size());
    size_t slash = url.find('/');
    if (slash != std::string::npos) url = url.substr(0, slash);
    size_t colon = url.find(':');
    if (colon == std::string::npos) {
        host_ = url;
        port_ = 80;
    } else {
        host_ = url.substr(0, colon);
        port_ = std::atoi(url.c_str() + colon + 1);
    }
    if (host_.empty() || port_ <= 0) return "Bad --connect URL '" + baseUrl + "' (expected http://host:port)";

    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);

    state_ = &state;
    running_ = true;
    thread_ = std::thread(&RemoteArm::loop, this);
    return "";
}

void RemoteArm::stop() {
    if (!running_) return;
    running_ = false;
    if (thread_.joinable()) thread_.join();
}

void RemoteArm::queue(const std::map<int, int>& changed) {
    std::lock_guard<std::mutex> lock(state_->mutex);
    for (const auto& kv : changed) pending_[kv.first] = kv.second;
}

// HTTP/1.0 on purpose: the server then replies without chunked encoding and
// closes the connection, so the body is simply everything after the headers.
bool RemoteArm::httpGet(const std::string& path, std::string& body) {
    SOCKET s = connectWithTimeout(host_, port_, 1000);
    if (s == INVALID_SOCKET) return false;

    std::string request = "GET " + path + " HTTP/1.0\r\nHost: " + host_ + "\r\n\r\n";
    if (send(s, request.data(), static_cast<int>(request.size()), 0) <= 0) {
        closesocket(s);
        return false;
    }

    std::string raw;
    char buf[4096];
    for (;;) {
        int n = recv(s, buf, sizeof(buf), 0);
        if (n <= 0) break;
        raw.append(buf, n);
        if (raw.size() > (1u << 20)) break;
    }
    closesocket(s);

    size_t headerEnd = raw.find("\r\n\r\n");
    if (headerEnd == std::string::npos || raw.compare(0, 5, "HTTP/") != 0) return false;
    size_t sp = raw.find(' ');
    if (sp == std::string::npos || raw.compare(sp + 1, 3, "200") != 0) return false;
    body = raw.substr(headerEnd + 4);
    return true;
}

void RemoteArm::loop() {
    while (running_) {
        std::map<int, int> toSend;
        {
            std::lock_guard<std::mutex> lock(state_->mutex);
            toSend.swap(pending_);
        }

        bool ok = true;
        for (const auto& kv : toSend) {
            std::string ignored;
            if (!httpGet("/cmd?motor=" + std::to_string(kv.first) + "&angle=" + std::to_string(kv.second), ignored)) {
                ok = false;
                break;
            }
        }

        std::string body;
        if (ok && httpGet("/status", body)) {
            try {
                Json status = Json::parse(body);
                const Json* motors = status.find("motors");
                if (motors && motors->isObject()) {
                    std::lock_guard<std::mutex> lock(state_->mutex);
                    for (const auto& kv : motors->obj_value) {
                        int n = std::atoi(kv.first.c_str());
                        if (pending_.count(n) == 0) { // don't overwrite a change we haven't sent yet
                            state_->angles[n] = kv.second.get("angle", state_->angles[n]);
                        }
                    }
                    connected_ = true;
                    synced_ = true;
                }
            } catch (...) {
                connected_ = false;
            }
        } else {
            connected_ = false;
            std::lock_guard<std::mutex> lock(state_->mutex);
            for (const auto& kv : toSend) pending_.insert(kv); // retry next round (doesn't overwrite newer values)
        }

        for (int i = 0; i < 10 && running_; i++) std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
}
