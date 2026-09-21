#include "fleet_server.h"
#include "json.hpp"
#include "motor_config.h"

#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cstdio>
#include <fstream>
#include <sstream>

#pragma comment(lib, "ws2_32.lib")

namespace {

const char* FLEET_NAME = "ARM";
const char* FLEET_TYPE = "robot";
const char* FLEET_CAPABILITIES = "servo_control,6dof,arm";

std::string urlDecode(const std::string& s) {
    std::string out;
    for (size_t i = 0; i < s.size(); i++) {
        if (s[i] == '%' && i + 2 < s.size()) {
            int hi = std::isxdigit((unsigned char)s[i + 1]) ? std::stoi(s.substr(i + 1, 1), nullptr, 16) : -1;
            int lo = std::isxdigit((unsigned char)s[i + 2]) ? std::stoi(s.substr(i + 2, 1), nullptr, 16) : -1;
            if (hi >= 0 && lo >= 0) {
                out += static_cast<char>((hi << 4) | lo);
                i += 2;
                continue;
            }
        }
        out += (s[i] == '+') ? ' ' : s[i];
    }
    return out;
}

std::map<std::string, std::string> parseQuery(const std::string& query) {
    std::map<std::string, std::string> params;
    size_t pos = 0;
    while (pos < query.size()) {
        size_t amp = query.find('&', pos);
        std::string pair = query.substr(pos, amp == std::string::npos ? std::string::npos : amp - pos);
        size_t eq = pair.find('=');
        if (eq != std::string::npos) {
            params[urlDecode(pair.substr(0, eq))] = urlDecode(pair.substr(eq + 1));
        } else if (!pair.empty()) {
            params[urlDecode(pair)] = "";
        }
        if (amp == std::string::npos) break;
        pos = amp + 1;
    }
    return params;
}

struct HttpRequest {
    std::string method;
    std::string path;
    std::map<std::string, std::string> query;
};

bool parseRequestLine(const std::string& raw, HttpRequest& req) {
    size_t lineEnd = raw.find("\r\n");
    std::string line = raw.substr(0, lineEnd);
    std::istringstream iss(line);
    std::string fullPath, version;
    if (!(iss >> req.method >> fullPath >> version)) return false;

    size_t q = fullPath.find('?');
    if (q == std::string::npos) {
        req.path = fullPath;
    } else {
        req.path = fullPath.substr(0, q);
        req.query = parseQuery(fullPath.substr(q + 1));
    }
    return true;
}

std::string contentTypeFor(const std::string& path) {
    if (path.size() >= 5 && path.compare(path.size() - 5, 5, ".html") == 0) return "text/html; charset=utf-8";
    if (path.size() >= 4 && path.compare(path.size() - 4, 4, ".css") == 0) return "text/css; charset=utf-8";
    if (path.size() >= 3 && path.compare(path.size() - 3, 3, ".js") == 0) return "application/javascript; charset=utf-8";
    if (path.size() >= 4 && path.compare(path.size() - 4, 4, ".xml") == 0) return "application/xml; charset=utf-8";
    return "application/octet-stream";
}

bool readFileBytes(const std::string& path, std::string& out) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return false;
    std::ostringstream ss;
    ss << f.rdbuf();
    out = ss.str();
    return true;
}

void sendAll(SOCKET s, const std::string& data) {
    size_t sent = 0;
    while (sent < data.size()) {
        int n = send(s, data.data() + sent, static_cast<int>(data.size() - sent), 0);
        if (n <= 0) return;
        sent += static_cast<size_t>(n);
    }
}

void sendResponse(SOCKET s, int status, const char* statusText, const std::string& contentType, const std::string& body) {
    std::ostringstream head;
    head << "HTTP/1.1 " << status << " " << statusText << "\r\n"
         << "Content-Type: " << contentType << "\r\n"
         << "Content-Length: " << body.size() << "\r\n"
         << "Connection: close\r\n\r\n";
    sendAll(s, head.str());
    sendAll(s, body);
}

void sendJson(SOCKET s, int status, const char* statusText, const Json& body) {
    sendResponse(s, status, statusText, "application/json", body.dump());
}

void sendFile(SOCKET s, const std::string& fullPath, const std::string& urlPath) {
    std::string data;
    if (!readFileBytes(fullPath, data)) {
        sendResponse(s, 404, "Not Found", "text/plain", "Not found");
        return;
    }
    sendResponse(s, 200, "OK", contentTypeFor(urlPath), data);
}

std::string percentEncode(const std::string& s) {
    static const char* hex = "0123456789ABCDEF";
    std::string out;
    for (unsigned char c : s) {
        if (std::isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') {
            out += static_cast<char>(c);
        } else {
            out += '%';
            out += hex[c >> 4];
            out += hex[c & 0xF];
        }
    }
    return out;
}

// Connects with a short timeout instead of relying on the OS's (much
// longer) default TCP connect timeout - matters here since the heartbeat
// runs every 10s even if RIFT/NORA isn't reachable yet.
SOCKET connectWithTimeout(const std::string& host, int port, int timeoutMs) {
    addrinfo hints = {};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    addrinfo* result = nullptr;
    if (getaddrinfo(host.c_str(), std::to_string(port).c_str(), &hints, &result) != 0) {
        return INVALID_SOCKET;
    }

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
    return s;
}

void ensureWinsockStarted() {
    static bool started = false;
    if (!started) {
        WSADATA wsa;
        WSAStartup(MAKEWORD(2, 2), &wsa);
        started = true;
    }
}

} // namespace

FleetServer::~FleetServer() { stop(); }

std::string FleetServer::start(const MotorMap& motors, FleetState& state,
                                std::function<bool()> connectedFn, int port,
                                bool registerToRift, const std::string& riftHost, int riftPort) {
    ensureWinsockStarted();

    motors_ = &motors;
    state_ = &state;
    connected_ = std::move(connectedFn);

    SOCKET listenSocket = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (listenSocket == INVALID_SOCKET) return "socket() failed";

    int reuse = 1;
    setsockopt(listenSocket, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<const char*>(&reuse), sizeof(reuse));

    sockaddr_in addr = {};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(static_cast<u_short>(port));

    if (bind(listenSocket, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == SOCKET_ERROR) {
        closesocket(listenSocket);
        return "Could not bind to port " + std::to_string(port) + " (already in use?)";
    }
    if (listen(listenSocket, SOMAXCONN) == SOCKET_ERROR) {
        closesocket(listenSocket);
        return "listen() failed";
    }

    listenSocket_ = static_cast<uintptr_t>(listenSocket);
    running_ = true;
    serverThread_ = std::thread(&FleetServer::acceptLoop, this);

    if (registerToRift) {
        heartbeatThread_ = std::thread(&FleetServer::heartbeatLoop, this, riftHost, riftPort);
    }

    return "";
}

void FleetServer::stop() {
    if (!running_) return;
    running_ = false;
    if (listenSocket_) {
        closesocket(static_cast<SOCKET>(listenSocket_));
        listenSocket_ = 0;
    }
    if (serverThread_.joinable()) serverThread_.join();
    if (heartbeatThread_.joinable()) heartbeatThread_.join();
}

void FleetServer::acceptLoop() {
    SOCKET listenSocket = static_cast<SOCKET>(listenSocket_);
    while (running_) {
        fd_set readSet;
        FD_ZERO(&readSet);
        FD_SET(listenSocket, &readSet);
        timeval tv{0, 200000}; // 200ms, so we periodically notice running_ go false
        int ready = select(0, &readSet, nullptr, nullptr, &tv);
        if (ready <= 0) continue;

        sockaddr_in clientAddr;
        int addrLen = sizeof(clientAddr);
        SOCKET client = accept(listenSocket, reinterpret_cast<sockaddr*>(&clientAddr), &addrLen);
        if (client == INVALID_SOCKET) continue;
        handleConnection(static_cast<uintptr_t>(client));
    }
}

void FleetServer::handleConnection(uintptr_t clientSocketRaw) {
    SOCKET client = static_cast<SOCKET>(clientSocketRaw);

    std::string raw;
    char buf[4096];
    // GET requests: read until we have the blank line ending the headers.
    while (raw.find("\r\n\r\n") == std::string::npos) {
        int n = recv(client, buf, sizeof(buf), 0);
        if (n <= 0) break;
        raw.append(buf, n);
        if (raw.size() > 16384) break; // ignore absurdly large requests
    }

    HttpRequest req;
    if (!parseRequestLine(raw, req)) {
        closesocket(client);
        return;
    }

    const MotorMap& motors = *motors_;
    FleetState& state = *state_;

    if (req.path == "/") {
        sendFile(client, repoRoot() + "\\scripts\\web\\index.html", "/index.html");
    } else if (req.path == "/style.css" || req.path == "/app.js") {
        sendFile(client, repoRoot() + "\\scripts\\web" + req.path, req.path);
    } else if (req.path == "/colour_scheme.xml") {
        sendFile(client, repoRoot() + "\\colour_scheme.xml", req.path);
    } else if (req.path == "/ping") {
        sendResponse(client, 200, "OK", "text/plain", std::string(FLEET_NAME) + " alive");
    } else if (req.path == "/status") {
        Json motorsJson = Json::makeObject();
        {
            std::lock_guard<std::mutex> lock(state.mutex);
            for (const auto& kv : motors) {
                Json m = Json::makeObject();
                m.set("channel", Json::makeNumber(kv.second.channel));
                m.set("angle", Json::makeNumber(state.angles[kv.first]));
                m.set("min", Json::makeNumber(kv.second.min));
                m.set("max", Json::makeNumber(kv.second.max));
                motorsJson.set(std::to_string(kv.first), std::move(m));
            }
        }
        Json root = Json::makeObject();
        root.set("connected", Json::makeBool(connected_ ? connected_() : false));
        root.set("motors", std::move(motorsJson));
        sendJson(client, 200, "OK", root);
    } else if (req.path == "/cmd") {
        auto motorIt = req.query.find("motor");
        auto angleIt = req.query.find("angle");
        int motor = 0, angle = 0;
        bool ok = motorIt != req.query.end() && angleIt != req.query.end();
        if (ok) {
            try {
                motor = std::stoi(motorIt->second);
                angle = std::stoi(angleIt->second);
            } catch (const std::exception&) {
                ok = false;
            }
        }
        if (!ok) {
            Json err = Json::makeObject();
            err.set("error", Json::makeString("expected ?motor=<1-6>&angle=<degrees>"));
            sendJson(client, 400, "Bad Request", err);
        } else if (motors.find(motor) == motors.end()) {
            Json err = Json::makeObject();
            err.set("error", Json::makeString("unknown motor " + std::to_string(motor)));
            sendJson(client, 400, "Bad Request", err);
        } else {
            const Motor& m = motors.at(motor);
            angle = std::max(m.min, std::min(m.max, angle));
            {
                std::lock_guard<std::mutex> lock(state.mutex);
                state.angles[motor] = angle;
            }
            Json resp = Json::makeObject();
            resp.set("motor", Json::makeNumber(motor));
            resp.set("angle", Json::makeNumber(angle));
            sendJson(client, 200, "OK", resp);
        }
    } else if (req.path == "/reset") {
        auto motorIt = req.query.find("motor");
        if (motorIt != req.query.end()) {
            int motor = 0;
            bool ok = true;
            try {
                motor = std::stoi(motorIt->second);
            } catch (const std::exception&) {
                ok = false;
            }
            if (!ok || motors.find(motor) == motors.end()) {
                Json err = Json::makeObject();
                err.set("error", Json::makeString("unknown motor " + motorIt->second));
                sendJson(client, 400, "Bad Request", err);
            } else {
                int restAngle = motors.at(motor).rest;
                {
                    std::lock_guard<std::mutex> lock(state.mutex);
                    state.angles[motor] = restAngle;
                }
                Json resp = Json::makeObject();
                resp.set("motor", Json::makeNumber(motor));
                resp.set("angle", Json::makeNumber(restAngle));
                sendJson(client, 200, "OK", resp);
            }
        } else {
            Json resp = Json::makeObject();
            {
                std::lock_guard<std::mutex> lock(state.mutex);
                for (const auto& kv : motors) {
                    state.angles[kv.first] = kv.second.rest;
                    resp.set(std::to_string(kv.first), Json::makeNumber(kv.second.rest));
                }
            }
            sendJson(client, 200, "OK", resp);
        }
    } else {
        sendResponse(client, 404, "Not Found", "text/plain", "Not found");
    }

    closesocket(client);
}

void FleetServer::heartbeatLoop(std::string riftHost, int riftPort) {
    std::string body = std::string("name=") + percentEncode(FLEET_NAME) +
                        "&type=" + percentEncode(FLEET_TYPE) +
                        "&capabilities=" + percentEncode(FLEET_CAPABILITIES);

    while (running_) {
        SOCKET s = connectWithTimeout(riftHost, riftPort, 2000);
        if (s != INVALID_SOCKET) {
            std::ostringstream req;
            req << "POST /register HTTP/1.1\r\n"
                << "Host: " << riftHost << "\r\n"
                << "Content-Type: application/x-www-form-urlencoded\r\n"
                << "Content-Length: " << body.size() << "\r\n"
                << "Connection: close\r\n\r\n"
                << body;
            sendAll(s, req.str());
            closesocket(s);
        }

        for (int i = 0; i < 100 && running_; i++) { // 10s total, checked every 100ms
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    }
}
