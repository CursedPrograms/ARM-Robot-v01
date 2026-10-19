// joystick.h - Joystick and gamepad input, analogous to pygame's joystick
// module used by controller.py: numbered axes, a POV hat, and numbered buttons.
// A joystick (ARM's own stick) is read through the Windows multimedia
// joystick API (winmm); a gamepad (Xbox pads, a Logitech F710 switched to X)
// through XInput, laid out the way pygame lays it out on Windows.
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

// One plugged-in device: a winmm joystick (id 0..15) or an XInput pad (slot 0..3).
struct InputDevice {
    enum class Kind { None, Stick, Pad };
    Kind kind = Kind::None;
    unsigned int id = 0;
    std::string name;

    bool operator==(const InputDevice& o) const { return kind == o.kind && id == o.id; }
    bool operator!=(const InputDevice& o) const { return !(*this == o); }
};

// Every plugged-in device in controller.py's order: plain joysticks first
// (ARM's own stick), then gamepads. Call refreshJoysticks() after a device
// was plugged in or out, so winmm sees it.
std::vector<InputDevice> connectedDevices();
void refreshJoysticks();

// The device to drive with: index `device` of connectedDevices() if
// device >= 0, else the first one (a joystick wins over a gamepad).
// Kind::None if nothing is plugged in.
InputDevice pickDevice(int device);

class Joystick {
public:
    bool open(const InputDevice& device);
    void close() { opened_ = false; device_ = InputDevice(); }
    bool poll(JoystickState& out) const;
    const InputDevice& device() const { return device_; }
    bool isGamepad() const { return device_.kind == InputDevice::Kind::Pad; }

private:
    bool pollStick(JoystickState& out) const;
    bool pollPad(JoystickState& out) const;

    InputDevice device_;
    bool opened_ = false;
    int numAxes_ = 0;
    int numButtons_ = 0;
    bool hasPov_ = false;
};
