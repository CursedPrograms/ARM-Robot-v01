#include "joystick.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>

namespace {

double normalize(DWORD value, DWORD lo, DWORD hi) {
    if (hi <= lo) return 0.0;
    return (static_cast<double>(value) - lo) / (hi - lo) * 2.0 - 1.0;
}

} // namespace

std::vector<unsigned int> connectedJoystickIds() {
    std::vector<unsigned int> ids;
    UINT count = joyGetNumDevs();
    JOYINFO info;
    for (UINT id = 0; id < count; id++) {
        if (joyGetPos(id, &info) == JOYERR_NOERROR) ids.push_back(id);
    }
    return ids;
}

std::string joystickName(unsigned int id) {
    JOYCAPSA caps;
    if (joyGetDevCapsA(id, &caps, sizeof(caps)) != JOYERR_NOERROR) return "Unknown joystick";
    return std::string(caps.szPname);
}

bool Joystick::open(unsigned int id) {
    JOYCAPSA caps;
    if (joyGetDevCapsA(id, &caps, sizeof(caps)) != JOYERR_NOERROR) return false;
    id_ = id;
    numAxes_ = static_cast<int>(caps.wNumAxes);
    numButtons_ = static_cast<int>(caps.wNumButtons);
    hasPov_ = (caps.wCaps & JOYCAPS_HASPOV) != 0;
    opened_ = true;
    return true;
}

bool Joystick::poll(JoystickState& out) const {
    if (!opened_) return false;

    JOYINFOEX info;
    info.dwSize = sizeof(JOYINFOEX);
    info.dwFlags = JOY_RETURNALL;
    if (joyGetPosEx(id_, &info) != JOYERR_NOERROR) return false;

    JOYCAPSA caps;
    if (joyGetDevCapsA(id_, &caps, sizeof(caps)) != JOYERR_NOERROR) return false;

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
