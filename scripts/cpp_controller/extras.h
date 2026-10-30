// extras.h - what controller.py has beyond driving her: her VOICE (arm_voice.ps1), her arm drawn from
// her geometry and joint maths, and the fleet's WiFi ladder (fleet_ladder.py, with --ladder).
#pragma once
#include <windows.h>

#include <chrono>
#include <map>
#include <string>

#include "motor_config.h"

constexpr int ARM_PANEL_W = 300;

class ArmVoice {
public:
    bool on = true;
    // Once a tick: says what changed, as controller.py's main loop does.
    void watch(const std::string& mode, bool recording, bool playing, bool claw);

private:
    void say(const std::string& event);
    std::map<std::string, std::chrono::steady_clock::time_point> last_;
    bool started_ = false;
    std::string mode_;
    bool recording_ = false, playing_ = false, claw_ = false;
};

// The fleet's WiFi ladder while she runs (--ladder or FLEET_LADDER=1), as ARMCTL.
void startLadder(bool asked);
void stopLadder();

// Her arm, as controller.py's draw_arm(): from the side, and from above (the base turning).
void drawArm(HDC dc, const RECT& area, const MotorMap& motors, const Geometry& g, const std::map<int, int>& angles);
