#include "joystick.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>

#include <cstdio>

namespace {

double normalize(DWORD value, DWORD lo, DWORD hi) {
    if (hi <= lo) return 0.0;
    return (static_cast<double>(value) - lo) / (hi - lo) * 2.0 - 1.0;
}

// ---- XInput, loaded at run time (MinGW has no xinput import library) ----

struct XInputGamepad {
    WORD buttons;
    BYTE leftTrigger, rightTrigger;
    SHORT thumbLX, thumbLY, thumbRX, thumbRY;
};

struct XInputState {
    DWORD packet;
    XInputGamepad pad;
};

using XInputGetStateFn = DWORD(WINAPI*)(DWORD, XInputState*);

XInputGetStateFn xinputGetState() {
    static XInputGetStateFn fn = [] {
        for (const char* dll : {"xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"}) {
            if (HMODULE h = LoadLibraryA(dll)) {
                if (auto f = reinterpret_cast<XInputGetStateFn>(GetProcAddress(h, "XInputGetState"))) return f;
            }
        }
        return static_cast<XInputGetStateFn>(nullptr);
    }();
    return fn;
}

bool readPad(unsigned int slot, XInputState& state) {
    auto fn = xinputGetState();
    return fn && fn(slot, &state) == ERROR_SUCCESS;
}

constexpr WORD PAD_DPAD_UP = 0x0001, PAD_DPAD_DOWN = 0x0002, PAD_DPAD_LEFT = 0x0004, PAD_DPAD_RIGHT = 0x0008;
constexpr WORD PAD_BACK = 0x0020, PAD_START = 0x0010, PAD_LSTICK = 0x0040, PAD_RSTICK = 0x0080;
constexpr WORD PAD_LB = 0x0100, PAD_RB = 0x0200, PAD_A = 0x1000, PAD_B = 0x2000, PAD_X = 0x4000, PAD_Y = 0x8000;

double stick(SHORT v) { return v < 0 ? v / 32768.0 : v / 32767.0; }

// winmm's own name is usually "Microsoft PC-joystick driver"; the real one is
// the OEM name in the registry, found through the device's settings key.
std::string registryString(HKEY root, const std::string& key, const std::string& value) {
    char buf[256] = {0};
    DWORD size = sizeof(buf) - 1;
    if (RegGetValueA(root, key.c_str(), value.c_str(), RRF_RT_REG_SZ, nullptr, buf, &size) != ERROR_SUCCESS) return "";
    return buf;
}

std::string oemName(unsigned int id, const JOYCAPSA& caps) {
    std::string settings = std::string("System\\CurrentControlSet\\Control\\MediaResources\\Joystick\\") +
                           caps.szRegKey + "\\CurrentJoystickSettings";
    std::string value = "Joystick" + std::to_string(id + 1) + "OEMName";
    for (HKEY root : {HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE}) {
        std::string oem = registryString(root, settings, value);
        if (oem.empty()) continue;
        std::string key = "System\\CurrentControlSet\\Control\\MediaProperties\\PrivateProperties\\Joystick\\OEM\\" + oem;
        for (HKEY root2 : {HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE}) {
            std::string name = registryString(root2, key, "OEMName");
            if (!name.empty()) return name;
        }
    }
    return caps.szPname;
}

// An XInput pad also shows up in winmm; XInput reads it with the right layout,
// so leave it out of the joysticks. Windows names them "Controller (...)".
bool looksLikeXInputPad(const std::string& name) {
    if (name.rfind("Controller (", 0) == 0) return true;
    for (const char* hint : {"XINPUT", "XInput", "Xbox", "XBOX", "X-Box"}) {
        if (name.find(hint) != std::string::npos) return true;
    }
    return false;
}

} // namespace

void refreshJoysticks() {
    joyConfigChanged(0);
}

std::vector<InputDevice> connectedDevices() {
    std::vector<InputDevice> sticks, pads;
    UINT count = joyGetNumDevs();
    for (UINT id = 0; id < count && id < 16; id++) {
        JOYINFO info;
        JOYCAPSA caps;
        if (joyGetPos(id, &info) != JOYERR_NOERROR) continue;
        if (joyGetDevCapsA(id, &caps, sizeof(caps)) != JOYERR_NOERROR) continue;
        std::string name = oemName(id, caps);
        if (looksLikeXInputPad(name)) continue;
        sticks.push_back({InputDevice::Kind::Stick, id, name});
    }
    for (unsigned int slot = 0; slot < 4; slot++) {
        XInputState state;
        if (readPad(slot, state)) pads.push_back({InputDevice::Kind::Pad, slot, "XInput gamepad " + std::to_string(slot + 1)});
    }
    sticks.insert(sticks.end(), pads.begin(), pads.end());
    return sticks;
}

InputDevice pickDevice(int device) {
    auto all = connectedDevices();
    size_t index = device < 0 ? 0 : static_cast<size_t>(device);
    return index < all.size() ? all[index] : InputDevice();
}

bool Joystick::open(const InputDevice& device) {
    opened_ = false;
    device_ = device;
    if (device.kind == InputDevice::Kind::Pad) {
        // pygame's layout of an XInput pad: left stick 0/1, right stick 2/3,
        // triggers 4/5; A, B, X, Y, LB, RB, Back, Start, sticks 0-9; D-pad = hat.
        numAxes_ = 6;
        numButtons_ = 10;
        hasPov_ = true;
        XInputState state;
        opened_ = readPad(device.id, state);
        return opened_;
    }
    if (device.kind != InputDevice::Kind::Stick) return false;
    JOYCAPSA caps;
    if (joyGetDevCapsA(device.id, &caps, sizeof(caps)) != JOYERR_NOERROR) return false;
    numAxes_ = static_cast<int>(caps.wNumAxes);
    numButtons_ = static_cast<int>(caps.wNumButtons);
    hasPov_ = (caps.wCaps & JOYCAPS_HASPOV) != 0;
    opened_ = true;
    return true;
}

bool Joystick::poll(JoystickState& out) const {
    if (!opened_) return false;
    return device_.kind == InputDevice::Kind::Pad ? pollPad(out) : pollStick(out);
}

bool Joystick::pollStick(JoystickState& out) const {
    JOYINFOEX info;
    info.dwSize = sizeof(JOYINFOEX);
    info.dwFlags = JOY_RETURNALL;
    if (joyGetPosEx(device_.id, &info) != JOYERR_NOERROR) return false;

    JOYCAPSA caps;
    if (joyGetDevCapsA(device_.id, &caps, sizeof(caps)) != JOYERR_NOERROR) return false;

    out.numAxes = numAxes_;
    out.numButtons = numButtons_;
    out.axis[0] = normalize(info.dwXpos, caps.wXmin, caps.wXmax);
    out.axis[1] = normalize(info.dwYpos, caps.wYmin, caps.wYmax);
    out.axis[2] = numAxes_ > 2 ? normalize(info.dwZpos, caps.wZmin, caps.wZmax) : 0.0;
    out.axis[3] = numAxes_ > 3 ? normalize(info.dwRpos, caps.wRmin, caps.wRmax) : 0.0;
    out.axis[4] = numAxes_ > 4 ? normalize(info.dwUpos, caps.wUmin, caps.wUmax) : 0.0;
    out.axis[5] = numAxes_ > 5 ? normalize(info.dwVpos, caps.wVmin, caps.wVmax) : 0.0;
    out.buttons = info.dwButtons;

    out.hatX = 0;
    out.hatY = 0;
    if (hasPov_ && info.dwPOV != JOY_POVCENTERED) {
        // 8-way bucket, nearest of the 45-degree compass points.
        int bucket = static_cast<int>(((info.dwPOV / 100.0) + 22.5) / 45.0) % 8;
        static const int dx[8] = {0, 1, 1, 1, 0, -1, -1, -1};
        static const int dy[8] = {1, 1, 0, -1, -1, -1, 0, 1};
        out.hatX = dx[bucket];
        out.hatY = dy[bucket];
    }

    return true;
}

bool Joystick::pollPad(JoystickState& out) const {
    XInputState state;
    if (!readPad(device_.id, state)) return false;
    const XInputGamepad& p = state.pad;

    out.numAxes = numAxes_;
    out.numButtons = numButtons_;
    out.axis[0] = stick(p.thumbLX);
    out.axis[1] = -stick(p.thumbLY); // pygame: pushed up = negative
    out.axis[2] = stick(p.thumbRX);
    out.axis[3] = -stick(p.thumbRY);
    out.axis[4] = p.leftTrigger / 127.5 - 1.0;
    out.axis[5] = p.rightTrigger / 127.5 - 1.0;

    static const WORD order[10] = {PAD_A, PAD_B, PAD_X, PAD_Y, PAD_LB, PAD_RB, PAD_BACK, PAD_START, PAD_LSTICK, PAD_RSTICK};
    out.buttons = 0;
    for (int i = 0; i < 10; i++) {
        if (p.buttons & order[i]) out.buttons |= 1ul << i;
    }
    out.hatX = (p.buttons & PAD_DPAD_RIGHT) ? 1 : (p.buttons & PAD_DPAD_LEFT) ? -1 : 0;
    out.hatY = (p.buttons & PAD_DPAD_UP) ? 1 : (p.buttons & PAD_DPAD_DOWN) ? -1 : 0;
    return true;
}
