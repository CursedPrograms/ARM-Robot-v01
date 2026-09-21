// joystick.h - Generic joystick/gamepad input via the Windows multimedia
// joystick API (winmm), analogous to pygame's joystick module used by
// controller.py: numbered axes, a POV hat, and numbered buttons.
#pragma once

#include <string>
#include <vector>

struct JoystickState {
    double axis[6] = {0, 0, 0, 0, 0, 0}; // normalized [-1, 1]: X,Y,Z,R,U,V
    int numAxes = 0;
    unsigned long buttons = 0; // bit i set = button i held
    int numButtons = 0;
    int hatX = 0; // -1, 0, or 1
    int hatY = 0; // -1, 0, or 1 (1 = up, matching pygame's get_hat() convention)
};

// IDs (0-based, matching winmm's JOYSTICKID1.. range) of currently connected
// joysticks, in enumeration order - device index 0 here is "the first
// connected joystick", same as controller.py's --device default.
std::vector<unsigned int> connectedJoystickIds();
std::string joystickName(unsigned int id);

class Joystick {
public:
    bool open(unsigned int id);
    bool poll(JoystickState& out) const;
    int numAxes() const { return numAxes_; }
    int numButtons() const { return numButtons_; }

private:
    unsigned int id_ = 0;
    bool opened_ = false;
    int numAxes_ = 0;
    int numButtons_ = 0;
    bool hasPov_ = false;
};
