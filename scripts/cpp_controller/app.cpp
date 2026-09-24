// app.cpp - controller.cpp's C++/Win32 counterpart: the same four modes
// (Joystick/Sliders/IK/Fleet), the same macro record/replay, and the same
// wire protocol to scripts/arm/arm.ino and the Fleet HTTP API, so it can be
// used interchangeably with the Python controller.py (same config.json,
// same scripts/macros/*.json, same scripts/web/ page).
//
// Built as a console-subsystem exe on purpose: like the Python scripts (run
// from a .bat that keeps its console open), this prints status/errors to
// the console alongside the native GUI window.
//
// Usage:
//   controller.exe --list-ports
//   controller.exe --port COM6
//   controller.exe --port COM6 --mode slider
//   controller.exe --port COM6 --mode fleet --fleet-port 5011

#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <commctrl.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "fleet_server.h"
#include "joystick.h"
#include "kinematics.h"
#include "macros.h"
#include "colour_scheme.h"
#include "motor_config.h"
#include "remote_arm.h"
#include "serial_port.h"

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "comctl32.lib")
#pragma comment(lib, "setupapi.lib")
#pragma comment(lib, "winmm.lib")

using Clock = std::chrono::steady_clock;

namespace {

enum class Mode { Joystick, Slider, Ik, Fleet };

// ---- Window layout (mirrors controller.py's WINDOW_WIDTH/MARGIN_TOP/etc.) ----
constexpr int WINDOW_WIDTH = 580;
constexpr int WINDOW_HEIGHT = 700;
constexpr int MODE_BUTTON_Y = 56;
constexpr int TRANSPORT_BUTTON_Y = 100;
constexpr int MACRO_LIST_Y = 138;
constexpr int MACRO_LIST_H = 90;
constexpr int MARGIN_TOP = 250;
constexpr int ROW_HEIGHT = 60;
constexpr double DEADZONE = 0.05;
constexpr int BUTTON_STEP_DEG = 5; // hat/button motors (3, 4) move this much per press
// Resend unchanged commands this often, so arm.ino knows the PC is still here
// (it eases back to rest after 2 s of silence).
constexpr double KEEPALIVE_SECS = 0.5;

// ---- Control IDs ----
enum ControlId {
    ID_MODE_JOYSTICK = 100,
    ID_MODE_SLIDER,
    ID_MODE_IK,
    ID_MODE_FLEET,
    ID_RECORD,
    ID_PLAY,
    ID_MACRO_LIST,
    ID_ELBOW_TOGGLE,
    ID_CLAW_TOGGLE,
    ID_TIMER = 1,
};

struct Args {
    std::string port;
    int baud = 115200;
    double rateHz = 30.0;
    std::optional<Mode> mode;
    int device = 0;
    int fleetPort = 5011;
    std::string riftHost = "127.0.0.1";
    int riftPort = 5000;
    bool noRegister = false;
    bool listPorts = false;
    bool serve = false;
    std::string connect; // --connect URL: client mode, no serial port
};

struct SliderRow {
    int motor = 0;
    HWND label = nullptr;
    HWND track = nullptr;
    HWND value = nullptr;
};

struct App {
    Args args;
    MotorMap motors;
    Geometry geometry;
    double reach = 300;

    SerialPort serial;
    std::string status;

    Joystick joystick;
    bool joystickAvailable = false;
    int prevHatY = 0;             // last frame's hat/buttons, to step once per press
    unsigned long prevButtons = 0;

    Mode mode = Mode::Slider;

    // ---- window + controls ----
    HWND hwnd = nullptr;
    HWND btnMode[4] = {};
    HWND btnRecord = nullptr;
    HWND btnPlay = nullptr;
    HWND listMacros = nullptr;
    HWND staticHeading = nullptr;
    HWND staticStatus = nullptr;
    HWND staticWarn = nullptr;
    HWND btnElbow = nullptr;
    HWND btnClaw = nullptr;
    HWND motorLines[6] = {};

    std::vector<SliderRow> sliderRows;   // one per motor, Slider mode
    std::map<std::string, SliderRow> ikRows; // "x","y","z","pitch","roll"

    bool elbowDown = false;
    bool clawClosed = false;
    bool ikReachable = true;
    std::optional<std::map<int, int>> lastValidIkCommands;

    // ---- macros ----
    std::vector<MacroFile> macros;
    int selectedMacro = -1;
    bool recording = false;
    std::vector<MacroStep> recordSteps;
    Clock::time_point recordStart;

    bool playing = false;
    std::vector<MacroStep> playSteps;
    Clock::time_point playStart;
    size_t playIndex = 0;
    Mode playPrevMode = Mode::Slider;

    std::map<int, int> lastSent; // channel -> angle
    Clock::time_point lastWrite;

    // Last angle each local input produced, keyed by motor number - see mergeLocal().
    std::map<int, int> prevLocal;

    // Client mode (--connect): mirror another controller's arm instead of owning serial.
    RemoteArm remote;
    bool remoteActive = false;
    bool adopted = true; // a client waits for the hub's real angles before its own inputs may write

    // ---- fleet ----
    FleetServer fleetServer;
    FleetState fleetState;
    bool fleetStarted = false;
    std::string fleetError;
    std::string fleetLanIp;
};

App g_app;

// ---------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------

std::string getLocalLanIp() {
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);

    std::string ip = "127.0.0.1";
    SOCKET s = socket(AF_INET, SOCK_DGRAM, 0);
    if (s != INVALID_SOCKET) {
        sockaddr_in addr = {};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(80);
        inet_pton(AF_INET, "8.8.8.8", &addr.sin_addr);
        if (connect(s, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0) {
            sockaddr_in local = {};
            int len = sizeof(local);
            if (getsockname(s, reinterpret_cast<sockaddr*>(&local), &len) == 0) {
                char buf[64];
                if (inet_ntop(AF_INET, &local.sin_addr, buf, sizeof(buf))) ip = buf;
            }
        }
        closesocket(s);
    }
    return ip;
}

// A centred (released) stick maps to rest; full deflection to lo/hi.
int axisToAngle(double value, int lo, int hi, int rest, double deadzone = DEADZONE) {
    if (std::fabs(value) < deadzone) return rest;
    double angle = rest + value * (value > 0 ? hi - rest : rest - lo);
    return static_cast<int>(std::lround(angle));
}

// Mirrors controller.py's joystick_commands(): returns {channel: angle} for
// the stick motors (1, 2, 5) and the claw (6). The hat/button motors (3, 4)
// step per press instead, see joystickSteps().
std::map<int, int> joystickCommands(const JoystickState& js, const MotorMap& motors) {
    double m1 = js.numAxes > 0 ? js.axis[0] : 0.0;
    double m2 = js.numAxes > 1 ? js.axis[1] : 0.0;
    double m5 = js.numAxes > 2 ? js.axis[2] : 0.0;

    bool closeBtn = js.numButtons > 0 && (js.buttons & 1);

    auto inv = [&](int n, double v) { return motors.at(n).invert ? -v : v; };
    m1 = inv(1, m1);
    m2 = inv(2, m2);
    m5 = inv(5, m5);
    if (motors.at(6).invert) closeBtn = !closeBtn;

    std::map<int, int> cmd;
    cmd[motors.at(1).channel] = axisToAngle(m1, motors.at(1).min, motors.at(1).max, motors.at(1).rest);
    cmd[motors.at(2).channel] = axisToAngle(m2, motors.at(2).min, motors.at(2).max, motors.at(2).rest);
    cmd[motors.at(5).channel] = axisToAngle(m5, motors.at(5).min, motors.at(5).max, motors.at(5).rest);
    cmd[motors.at(6).channel] = closeBtn ? motors.at(6).max : motors.at(6).min;
    return cmd;
}

// Mirrors controller.py's joystick_step(): the (motor, direction) pairs for
// hat/buttons pressed since last frame, direction +1/-1 before invert.
std::vector<std::pair<int, int>> joystickSteps(const JoystickState& js, int prevHatY, unsigned long prevButtons) {
    std::vector<std::pair<int, int>> steps;
    if (js.hatY != 0 && js.hatY != prevHatY) steps.push_back({3, js.hatY > 0 ? 1 : -1});
    auto pressed = [&](int b) { return js.numButtons > b && ((js.buttons >> b) & 1) && !((prevButtons >> b) & 1); };
    if (pressed(3)) steps.push_back({4, 1});
    if (pressed(2)) steps.push_back({4, -1});
    return steps;
}

// Sends when the commands changed, or unchanged every KEEPALIVE_SECS.
void sendCommands(App& app, const std::map<int, int>& commands) {
    auto now = Clock::now();
    if (commands == app.lastSent && std::chrono::duration<double>(now - app.lastWrite).count() < KEEPALIVE_SECS) return;
    app.lastWrite = now;
    if (commands.empty()) return;
    std::string line;
    for (const auto& kv : commands) {
        if (!line.empty()) line += ",";
        line += std::to_string(kv.first) + ":" + std::to_string(kv.second);
    }
    app.serial.writeLine(line);
    app.lastSent = commands;
}

HWND makeStatic(HWND parent, int x, int y, int w, int h, const char* text = "") {
    return CreateWindowExA(0, "STATIC", text, WS_CHILD | WS_VISIBLE,
                            x, y, w, h, parent, nullptr, GetModuleHandle(nullptr), nullptr);
}

HWND makeButton(HWND parent, int id, int x, int y, int w, int h, const char* text) {
    return CreateWindowExA(0, "BUTTON", text, WS_CHILD | WS_VISIBLE | BS_OWNERDRAW,
                            x, y, w, h, parent, reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)),
                            GetModuleHandle(nullptr), nullptr);
}

SliderRow makeSliderRow(HWND parent, int y, const std::string& label, int lo, int hi, int initial) {
    SliderRow row;
    row.label = makeStatic(parent, 20, y + 6, 150, 20, label.c_str());
    row.track = CreateWindowExA(0, TRACKBAR_CLASSA, "", WS_CHILD | WS_VISIBLE | TBS_HORZ | TBS_NOTICKS,
                                 175, y, 300, 28, parent, nullptr, GetModuleHandle(nullptr), nullptr);
    SendMessage(row.track, TBM_SETRANGE, TRUE, MAKELONG(lo, hi));
    SendMessage(row.track, TBM_SETPOS, TRUE, initial);
    row.value = makeStatic(parent, 485, y + 6, 80, 20, "");
    return row;
}

void showWindowGroup(HWND* handles, size_t count, bool show) {
    for (size_t i = 0; i < count; i++) {
        if (handles[i]) ShowWindow(handles[i], show ? SW_SHOW : SW_HIDE);
    }
}

void applyModeVisibility(App& app) {
    for (auto& row : app.sliderRows) {
        int show = (app.mode == Mode::Slider) ? SW_SHOW : SW_HIDE;
        ShowWindow(row.label, show);
        ShowWindow(row.track, show);
        ShowWindow(row.value, show);
    }
    for (auto& kv : app.ikRows) {
        int show = (app.mode == Mode::Ik) ? SW_SHOW : SW_HIDE;
        ShowWindow(kv.second.label, show);
        ShowWindow(kv.second.track, show);
        ShowWindow(kv.second.value, show);
    }
    ShowWindow(app.btnElbow, app.mode == Mode::Ik ? SW_SHOW : SW_HIDE);
    ShowWindow(app.btnClaw, app.mode == Mode::Ik ? SW_SHOW : SW_HIDE);

    bool showMotorLines = (app.mode == Mode::Joystick || app.mode == Mode::Fleet);
    showWindowGroup(app.motorLines, 6, showMotorLines);

    for (int i = 0; i < 4; i++) EnableWindow(app.btnMode[i], TRUE);
    if (!app.joystickAvailable) EnableWindow(app.btnMode[0], FALSE);

    const char* names[4] = {"Joystick", "Sliders", "IK", "Fleet"};
    for (int i = 0; i < 4; i++) {
        std::string label = names[i];
        if (static_cast<int>(app.mode) == i) label = "[" + label + "]";
        SetWindowTextA(app.btnMode[i], label.c_str());
    }
}

// ---------------------------------------------------------------------
// Shared arm state. fleetState.angles is the single set of angles every
// input writes to and every output (serial, web page, RIFT, this window's
// sliders) reads from. The rule: an input whose value changed since last
// frame writes it (last writer wins); inputs that didn't change leave what
// another input wrote alone and instead follow it.
// ---------------------------------------------------------------------

std::map<int, int> toMotorKeyed(const App& app, const std::map<int, int>& byChannel) {
    std::map<int, int> out;
    for (const auto& kv : app.motors) {
        auto it = byChannel.find(kv.second.channel);
        if (it != byChannel.end()) out[kv.first] = it->second;
    }
    return out;
}

std::map<int, int> mergeLocal(App& app, const std::map<int, int>& localByMotor) {
    std::map<int, int> changed;
    {
        std::lock_guard<std::mutex> lock(app.fleetState.mutex);
        for (const auto& kv : localByMotor) {
            auto prev = app.prevLocal.find(kv.first);
            if (prev == app.prevLocal.end() || prev->second != kv.second) {
                app.fleetState.angles[kv.first] = kv.second;
                changed[kv.first] = kv.second;
            }
        }
    }
    app.prevLocal = localByMotor;
    return changed;
}

std::map<int, int> sharedAsChannelMap(App& app) {
    std::map<int, int> out;
    std::lock_guard<std::mutex> lock(app.fleetState.mutex);
    for (const auto& kv : app.motors) out[kv.second.channel] = app.fleetState.angles[kv.first];
    return out;
}

void publishByChannel(App& app, const std::map<int, int>& byChannel) {
    std::map<int, int> changed;
    {
        std::lock_guard<std::mutex> lock(app.fleetState.mutex);
        for (const auto& kv : app.motors) {
            auto it = byChannel.find(kv.second.channel);
            if (it != byChannel.end()) {
                app.fleetState.angles[kv.first] = it->second;
                changed[kv.first] = it->second;
            }
        }
    }
    if (app.remoteActive) app.remote.queue(changed);
}

// Slider positions adopt the shared angles.
void followSliders(App& app) {
    std::lock_guard<std::mutex> lock(app.fleetState.mutex);
    for (auto& row : app.sliderRows) {
        int shared = app.fleetState.angles[row.motor];
        if (static_cast<int>(SendMessage(row.track, TBM_GETPOS, 0, 0)) != shared) {
            SendMessage(row.track, TBM_SETPOS, TRUE, shared);
        }
        app.prevLocal[row.motor] = shared;
        SetWindowTextA(row.value, (std::to_string(shared) + "\xB0").c_str());
    }
}

void ensureFleetStarted(App& app) {
    if (app.remoteActive) return; // a client has no arm of its own to serve
    if (app.fleetStarted || !app.fleetError.empty()) return;
    if (app.fleetLanIp.empty()) app.fleetLanIp = getLocalLanIp();

    auto connectedFn = [&app]() { return app.serial.isOpen(); };
    std::string err = app.fleetServer.start(app.motors, app.fleetState, connectedFn,
                                             app.args.fleetPort, !app.args.noRegister,
                                             app.args.riftHost, app.args.riftPort);
    if (!err.empty()) {
        app.fleetError = err;
    } else {
        app.fleetStarted = true;
        std::string url = "http://" + app.fleetLanIp + ":" + std::to_string(app.args.fleetPort);
        std::printf("Web control on %s\n", url.c_str());
        if (app.staticStatus) SetWindowTextA(app.staticStatus, (app.status + "  |  Web: " + url).c_str());
    }
}

void refreshMacroList(App& app) {
    app.macros = listMacros();
    SendMessage(app.listMacros, LB_RESETCONTENT, 0, 0);
    for (const auto& m : app.macros) {
        SendMessageA(app.listMacros, LB_ADDSTRING, 0, reinterpret_cast<LPARAM>(m.name.c_str()));
    }
    app.selectedMacro = app.macros.empty() ? -1 : 0;
    if (app.selectedMacro >= 0) SendMessage(app.listMacros, LB_SETCURSEL, app.selectedMacro, 0);
}

void setMode(App& app, Mode m) {
    app.mode = m;
    applyModeVisibility(app);
    app.prevLocal.clear();
    if (m == Mode::Slider) followSliders(app);
    if (m == Mode::Fleet) ensureFleetStarted(app);
}

// ---------------------------------------------------------------------
// Per-frame update (called from the WM_TIMER handler)
// ---------------------------------------------------------------------

void tick(App& app) {
    if (app.playing) {
        double elapsed = std::chrono::duration<double>(Clock::now() - app.playStart).count();
        while (app.playIndex < app.playSteps.size() && app.playSteps[app.playIndex].t <= elapsed) {
            sendCommands(app, app.playSteps[app.playIndex].commands);
            publishByChannel(app, app.playSteps[app.playIndex].commands);
            app.playIndex++;
        }
        sendCommands(app, app.lastSent); // keepalive between macro steps
        if (app.mode == Mode::Slider) followSliders(app);
        if (app.playIndex >= app.playSteps.size()) {
            app.playing = false;
            setMode(app, app.playPrevMode);
            SetWindowTextA(app.btnPlay, "Play");
        }
        return;
    }

    std::optional<std::map<int, int>> commands;
    std::optional<std::map<int, int>> local; // this mode's own input, keyed by motor number

    if (app.mode == Mode::Joystick && app.joystickAvailable) {
        JoystickState state;
        if (app.joystick.poll(state)) {
            local = toMotorKeyed(app, joystickCommands(state, app.motors));
            if (app.adopted) {
                std::map<int, int> changed;
                for (auto [n, dir] : joystickSteps(state, app.prevHatY, app.prevButtons)) {
                    const auto& m = app.motors.at(n);
                    if (m.invert) dir = -dir;
                    std::lock_guard<std::mutex> lock(app.fleetState.mutex);
                    int angle = std::clamp(app.fleetState.angles[n] + dir * BUTTON_STEP_DEG, m.min, m.max);
                    app.fleetState.angles[n] = angle;
                    changed[n] = angle;
                }
                if (app.remoteActive && !changed.empty()) app.remote.queue(changed);
            }
            app.prevHatY = state.hatY;
            app.prevButtons = state.buttons;
        }
    } else if (app.mode == Mode::Slider) {
        std::map<int, int> byMotor;
        for (auto& row : app.sliderRows) {
            byMotor[row.motor] = static_cast<int>(SendMessage(row.track, TBM_GETPOS, 0, 0));
        }
        local = byMotor;
    } else if (app.mode == Mode::Ik) {
        if (!geometryReady(app.geometry)) {
            SetWindowTextA(app.staticWarn, "Geometry not measured - fill in config.json's \"geometry\" section.");
        } else {
            auto pos = [&](const char* key) { return static_cast<int>(SendMessage(app.ikRows[key].track, TBM_GETPOS, 0, 0)); };
            int x = pos("x"), y = pos("y"), z = pos("z"), pitch = pos("pitch"), roll = pos("roll");
            for (const char* key : {"x", "y", "z", "pitch", "roll"}) {
                int v = pos(key);
                std::string suffix = (std::string(key) == "roll") ? "" : (std::string(key) == "pitch" ? "\xB0" : "mm");
                SetWindowTextA(app.ikRows[key].value, (std::to_string(v) + suffix).c_str());
            }

            auto sol = inverseKinematics(app.motors, app.geometry, x, y, z, pitch, app.elbowDown);
            if (sol) {
                app.ikReachable = true;
                std::map<int, int> cmd;
                for (const auto& kv : *sol) cmd[app.motors.at(kv.first).channel] = kv.second;
                cmd[app.motors.at(5).channel] = roll;
                cmd[app.motors.at(6).channel] = app.clawClosed ? app.motors.at(6).max : app.motors.at(6).min;
                app.lastValidIkCommands = cmd;
                local = toMotorKeyed(app, cmd);
            } else {
                app.ikReachable = false;
                if (app.lastValidIkCommands) local = toMotorKeyed(app, *app.lastValidIkCommands);
            }
            SetWindowTextA(app.staticWarn, app.ikReachable ? "" : "Target unreachable - holding last valid pose.");
        }
    } else if (app.mode == Mode::Fleet) {
        if (!app.fleetError.empty()) {
            SetWindowTextA(app.staticWarn, app.fleetError.c_str());
        } else {
            std::string msg = "Open http://" + app.fleetLanIp + ":" + std::to_string(app.args.fleetPort) + " in a browser to control";
            if (!app.args.noRegister) msg += "  -  heartbeating to RIFT at " + app.args.riftHost + ":" + std::to_string(app.args.riftPort);
            SetWindowTextA(app.staticWarn, msg.c_str());
        }
    }

    if (app.mode == Mode::Joystick) {
        SetWindowTextA(app.staticWarn, app.joystickAvailable ? "" : "No joystick connected.");
    }

    // Merge this mode's input into the shared angles, then always send/record
    // the shared state (so web-page and RIFT changes reach the arm in any mode).
    if (local) {
        if (!app.adopted) {
            if (app.remote.synced()) { // connected: take the hub's state as-is, don't move the arm
                app.prevLocal = *local;
                app.adopted = true;
            }
        } else {
            auto changed = mergeLocal(app, *local);
            if (app.remoteActive && !changed.empty()) app.remote.queue(changed);
        }
    }
    if (app.remoteActive) {
        std::string st = "Remote arm " + app.args.connect + ": " + (app.remote.connected() ? "connected" : "UNREACHABLE");
        SetWindowTextA(app.staticStatus, st.c_str());
    }
    if (app.mode == Mode::Slider) followSliders(app);
    commands = sharedAsChannelMap(app);

    if (commands) {
        sendCommands(app, *commands);
        if (app.recording) {
            MacroStep step;
            step.t = std::chrono::duration<double>(Clock::now() - app.recordStart).count();
            step.commands = *commands;
            app.recordSteps.push_back(std::move(step));
        }
    }

    // Motor read-out lines, shared by Joystick and Fleet mode display.
    if (app.mode == Mode::Joystick || app.mode == Mode::Fleet) {
        int i = 0;
        for (const auto& kv : app.motors) {
            if (i >= 6) break;
            int angle = 0;
            auto it = app.lastSent.find(kv.second.channel);
            if (it != app.lastSent.end()) angle = it->second;
            std::string text = "Motor " + std::to_string(kv.first) + " (ch " + std::to_string(kv.second.channel) + "): " + std::to_string(angle);
            SetWindowTextA(app.motorLines[i], text.c_str());
            i++;
        }
    }

    if (app.recording) {
        double secs = std::chrono::duration<double>(Clock::now() - app.recordStart).count();
        char buf[64];
        std::snprintf(buf, sizeof(buf), "Recording... %.1fs", secs);
        SetWindowTextA(app.btnRecord, buf);
    }
}

// ---------------------------------------------------------------------
// Window procedure
// ---------------------------------------------------------------------

void onModeButton(App& app, Mode m) {
    if (app.playing) return;
    setMode(app, m);
}

void onCommand(App& app, WPARAM wParam) {
    int id = LOWORD(wParam);
    int notify = HIWORD(wParam);

    switch (id) {
        case ID_MODE_JOYSTICK: onModeButton(app, Mode::Joystick); break;
        case ID_MODE_SLIDER: onModeButton(app, Mode::Slider); break;
        case ID_MODE_IK: onModeButton(app, Mode::Ik); break;
        case ID_MODE_FLEET: onModeButton(app, Mode::Fleet); break;
        case ID_ELBOW_TOGGLE:
            app.elbowDown = !app.elbowDown;
            SetWindowTextA(app.btnElbow, app.elbowDown ? "Elbow: Down" : "Elbow: Up");
            break;
        case ID_CLAW_TOGGLE:
            app.clawClosed = !app.clawClosed;
            SetWindowTextA(app.btnClaw, app.clawClosed ? "Claw: Closed" : "Claw: Open");
            break;
        case ID_RECORD:
            if (!app.recording) {
                app.recording = true;
                app.recordSteps.clear();
                app.recordStart = Clock::now();
            } else {
                app.recording = false;
                SetWindowTextA(app.btnRecord, "Record");
                if (!app.recordSteps.empty()) {
                    saveMacro(app.recordSteps);
                    refreshMacroList(app);
                }
            }
            break;
        case ID_PLAY:
            if (app.playing) {
                app.playing = false;
                setMode(app, app.playPrevMode);
                SetWindowTextA(app.btnPlay, "Play");
            } else if (app.selectedMacro >= 0 && app.selectedMacro < static_cast<int>(app.macros.size())) {
                app.playSteps = loadMacro(app.macros[app.selectedMacro].path);
                app.playStart = Clock::now();
                app.playIndex = 0;
                app.playPrevMode = app.mode;
                app.playing = true;
                SetWindowTextA(app.btnPlay, "Stop");
            }
            break;
        case ID_MACRO_LIST:
            if (notify == LBN_SELCHANGE) {
                app.selectedMacro = static_cast<int>(SendMessage(app.listMacros, LB_GETCURSEL, 0, 0));
            }
            break;
    }
}

// Brushes for the colour scheme (colour_scheme.xml); created once, live for the process.
HBRUSH backgroundBrush() {
    static HBRUSH b = CreateSolidBrush(schemeColour("background"));
    return b;
}

HBRUSH panelBrush() {
    static HBRUSH b = CreateSolidBrush(schemeColour("panel"));
    return b;
}

// Buttons are owner-drawn so they can take the scheme's colours. Native
// buttons don't report hover, so button_hover isn't used here.
void drawButton(const DRAWITEMSTRUCT& d) {
    char label[128] = {0};
    GetWindowTextA(d.hwndItem, label, sizeof(label) - 1);

    bool disabled = (d.itemState & ODS_DISABLED) != 0;
    bool active = label[0] == '[' || std::string(label) == "Stop"; // selected mode / recording / playing
    const char* role = disabled ? "button_disabled"
                       : (d.itemState & ODS_SELECTED) || active ? "button_active"
                       : "button";

    HBRUSH fill = CreateSolidBrush(schemeColour(role));
    FillRect(d.hDC, &d.rcItem, fill);
    DeleteObject(fill);

    SetBkMode(d.hDC, TRANSPARENT);
    SetTextColor(d.hDC, schemeColour(disabled ? "text_dim" : "text"));
    RECT r = d.rcItem;
    DrawTextA(d.hDC, label, -1, &r, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
}

LRESULT CALLBACK WindowProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
        case WM_CTLCOLORSTATIC: { // labels, and the sliders' backgrounds
            HDC dc = reinterpret_cast<HDC>(wParam);
            HWND ctl = reinterpret_cast<HWND>(lParam);
            const char* role = ctl == g_app.staticWarn ? "warn" : ctl == g_app.staticStatus ? "text_dim" : "text";
            SetTextColor(dc, schemeColour(role));
            SetBkColor(dc, schemeColour("background"));
            return reinterpret_cast<LRESULT>(backgroundBrush());
        }
        case WM_CTLCOLORLISTBOX: {
            HDC dc = reinterpret_cast<HDC>(wParam);
            SetTextColor(dc, schemeColour("text"));
            SetBkColor(dc, schemeColour("panel"));
            return reinterpret_cast<LRESULT>(panelBrush());
        }
        case WM_DRAWITEM:
            drawButton(*reinterpret_cast<const DRAWITEMSTRUCT*>(lParam));
            return TRUE;
        case WM_COMMAND:
            onCommand(g_app, wParam);
            return 0;
        case WM_TIMER:
            tick(g_app);
            return 0;
        case WM_DESTROY:
            PostQuitMessage(0);
            return 0;
    }
    return DefWindowProc(hwnd, msg, wParam, lParam);
}

// ---------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------

void createControls(App& app) {
    HWND hwnd = app.hwnd;

    app.staticHeading = makeStatic(hwnd, 20, 8, 300, 22, "Arm Controller (C++)");
    app.staticStatus = makeStatic(hwnd, 20, 32, 540, 18, app.status.c_str());

    const char* names[4] = {"Joystick", "Sliders", "IK", "Fleet"};
    int ids[4] = {ID_MODE_JOYSTICK, ID_MODE_SLIDER, ID_MODE_IK, ID_MODE_FLEET};
    for (int i = 0; i < 4; i++) {
        app.btnMode[i] = makeButton(hwnd, ids[i], 20 + i * 132, MODE_BUTTON_Y, 122, 34, names[i]);
    }

    app.btnRecord = makeButton(hwnd, ID_RECORD, 30, TRANSPORT_BUTTON_Y, 160, 30, "Record");
    app.btnPlay = makeButton(hwnd, ID_PLAY, 200, TRANSPORT_BUTTON_Y, 160, 30, "Play");

    app.listMacros = CreateWindowExA(WS_EX_CLIENTEDGE, "LISTBOX", "",
                                      WS_CHILD | WS_VISIBLE | WS_VSCROLL | LBS_NOTIFY,
                                      30, MACRO_LIST_Y, 520, MACRO_LIST_H, hwnd,
                                      reinterpret_cast<HMENU>(ID_MACRO_LIST), GetModuleHandle(nullptr), nullptr);

    app.staticWarn = makeStatic(hwnd, 20, MARGIN_TOP - 20, 540, 18, "");

    int row = 0;
    for (const auto& kv : app.motors) {
        app.sliderRows.push_back(makeSliderRow(hwnd, MARGIN_TOP + row * ROW_HEIGHT,
                                                "Motor " + std::to_string(kv.first), kv.second.min, kv.second.max, kv.second.rest));
        app.sliderRows.back().motor = kv.first;
        row++;
    }

    app.ikRows["x"] = makeSliderRow(hwnd, MARGIN_TOP + 0 * ROW_HEIGHT, "Target X (mm)", static_cast<int>(-app.reach), static_cast<int>(app.reach), 0);
    app.ikRows["y"] = makeSliderRow(hwnd, MARGIN_TOP + 1 * ROW_HEIGHT, "Target Y (mm)", static_cast<int>(-app.reach), static_cast<int>(app.reach), 0);
    app.ikRows["z"] = makeSliderRow(hwnd, MARGIN_TOP + 2 * ROW_HEIGHT, "Target Z (mm)", 0, static_cast<int>(app.reach), static_cast<int>(app.geometry.baseHeight));
    app.ikRows["pitch"] = makeSliderRow(hwnd, MARGIN_TOP + 3 * ROW_HEIGHT, "Pitch (deg)", -90, 90, 0);
    app.ikRows["roll"] = makeSliderRow(hwnd, MARGIN_TOP + 4 * ROW_HEIGHT, "Roll (motor 5)", app.motors.at(5).min, app.motors.at(5).max, app.motors.at(5).rest);

    app.btnElbow = makeButton(hwnd, ID_ELBOW_TOGGLE, 30, MARGIN_TOP + 5 * ROW_HEIGHT, 150, 30, "Elbow: Up");
    app.btnClaw = makeButton(hwnd, ID_CLAW_TOGGLE, 200, MARGIN_TOP + 5 * ROW_HEIGHT, 150, 30, "Claw: Open");

    for (int i = 0; i < 6; i++) {
        app.motorLines[i] = makeStatic(hwnd, 20, MARGIN_TOP + i * 28, 500, 22, "");
    }

    refreshMacroList(app);
    applyModeVisibility(app);
}

bool parseArgs(int argc, char** argv, Args& out) {
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        auto next = [&](const char* flag) -> std::string {
            if (i + 1 >= argc) { std::fprintf(stderr, "%s requires a value\n", flag); exit(1); }
            return argv[++i];
        };
        if (a == "--port") out.port = next("--port");
        else if (a == "--baud") out.baud = std::stoi(next("--baud"));
        else if (a == "--rate") out.rateHz = std::stod(next("--rate"));
        else if (a == "--device") out.device = std::stoi(next("--device"));
        else if (a == "--fleet-port") out.fleetPort = std::stoi(next("--fleet-port"));
        else if (a == "--rift-host") out.riftHost = next("--rift-host");
        else if (a == "--rift-port") out.riftPort = std::stoi(next("--rift-port"));
        else if (a == "--no-register") out.noRegister = true;
        else if (a == "--list-ports") out.listPorts = true;
        else if (a == "--serve") out.serve = true;
        else if (a == "--connect") out.connect = next("--connect");
        else if (a == "--mode") {
            std::string m = next("--mode");
            if (m == "joystick") out.mode = Mode::Joystick;
            else if (m == "slider") out.mode = Mode::Slider;
            else if (m == "ik") out.mode = Mode::Ik;
            else if (m == "fleet") out.mode = Mode::Fleet;
            else { std::fprintf(stderr, "Unknown --mode '%s'\n", m.c_str()); return false; }
        } else {
            std::fprintf(stderr, "Unknown argument: %s\n", a.c_str());
            return false;
        }
    }
    return true;
}

} // namespace

int main(int argc, char** argv) {
    App& app = g_app;
    if (!parseArgs(argc, argv, app.args)) return 1;

    if (!app.args.connect.empty() && (app.args.serve || app.args.mode == Mode::Fleet)) {
        std::fprintf(stderr, "--connect can't be combined with --serve or --mode fleet (this controller has no arm of its own)\n");
        return 1;
    }

    if (app.args.listPorts) {
        auto ports = listSerialPorts();
        if (ports.empty()) {
            std::printf("No serial ports found.\n");
        } else {
            std::printf("Available serial ports:\n");
            for (auto& p : ports) std::printf("  %s  -  %s\n", p.device.c_str(), p.description.c_str());
        }
        return 0;
    }

    app.motors = loadMotorConfig();
    app.geometry = loadGeometry();
    for (const auto& kv : app.motors) app.fleetState.angles[kv.first] = kv.second.rest;
    double reach = app.geometry.upperArmLength + app.geometry.forearmLength + app.geometry.wristLength;
    app.reach = reach > 0 ? reach : 300;

    auto jsIds = connectedJoystickIds();
    if (static_cast<size_t>(app.args.device) < jsIds.size()) {
        app.joystickAvailable = app.joystick.open(jsIds[app.args.device]);
        if (app.joystickAvailable) {
            std::printf("Using joystick: %s\n", joystickName(jsIds[app.args.device]).c_str());
        }
    }
    if (!app.joystickAvailable) std::printf("No joystick found - Joystick mode will be unavailable.\n");

    std::string port = !app.args.connect.empty() ? "" : (app.args.port.empty() ? autodetectPort() : app.args.port);
    if (!app.args.connect.empty()) {
        app.status = "Remote arm at " + app.args.connect + " (no local serial port).";
    } else if (!port.empty()) {
        std::string err = app.serial.open(port, app.args.baud);
        app.status = err.empty() ? ("Connected to " + port + " @ " + std::to_string(app.args.baud) + " baud.") : err;
    } else {
        app.status = "No Arduino-like serial port found - display-only mode.";
    }
    std::printf("%s\n", app.status.c_str());

    if (!app.args.connect.empty()) {
        std::string err = app.remote.start(app.args.connect, app.fleetState);
        if (!err.empty()) {
            std::fprintf(stderr, "%s\n", err.c_str());
            return 1;
        }
        app.remoteActive = true;
        app.adopted = false;
    }

    app.mode = app.args.mode.value_or(app.joystickAvailable ? Mode::Joystick : Mode::Slider);
    app.playPrevMode = app.mode;

    INITCOMMONCONTROLSEX icc = {sizeof(icc), ICC_BAR_CLASSES};
    InitCommonControlsEx(&icc);

    WNDCLASSA wc = {};
    wc.lpfnWndProc = WindowProc;
    wc.hInstance = GetModuleHandle(nullptr);
    wc.lpszClassName = "ArmControllerWindowCpp";
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    wc.hbrBackground = backgroundBrush();
    RegisterClassA(&wc);

    RECT rect = {0, 0, WINDOW_WIDTH, WINDOW_HEIGHT};
    AdjustWindowRect(&rect, WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX, FALSE);

    app.hwnd = CreateWindowExA(0, wc.lpszClassName, "Arm Controller",
                                WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
                                CW_USEDEFAULT, CW_USEDEFAULT, rect.right - rect.left, rect.bottom - rect.top,
                                nullptr, nullptr, wc.hInstance, nullptr);
    if (!app.hwnd) {
        std::fprintf(stderr, "Failed to create window (error %lu)\n", GetLastError());
        return 1;
    }

    createControls(app);
    if (app.mode == Mode::Fleet || app.args.serve) ensureFleetStarted(app);

    ShowWindow(app.hwnd, SW_SHOW);
    UpdateWindow(app.hwnd);

    UINT intervalMs = app.args.rateHz > 0 ? static_cast<UINT>(1000.0 / app.args.rateHz) : 33;
    SetTimer(app.hwnd, ID_TIMER, intervalMs, nullptr);

    MSG msg;
    while (GetMessage(&msg, nullptr, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }

    app.fleetServer.stop();
    app.remote.stop();
    return 0;
}
