#include "extras.h"

#include "colour_scheme.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <vector>

namespace {

const auto COOLDOWN = std::chrono::seconds(8);   // kit.Voice's: an event at most this often
HANDLE g_ladder = nullptr;

HANDLE spawn(std::string line) {
    STARTUPINFOA si{};
    si.cb = sizeof(si);
    PROCESS_INFORMATION pi{};
    if (!CreateProcessA(nullptr, line.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW, nullptr, nullptr, &si, &pi))
        return nullptr;
    CloseHandle(pi.hThread);
    return pi.hProcess;
}

void line(HDC dc, COLORREF c, int width, double x1, double y1, double x2, double y2) {
    HPEN pen = CreatePen(PS_SOLID, width, c);
    HGDIOBJ old = SelectObject(dc, pen);
    MoveToEx(dc, (int)x1, (int)y1, nullptr);
    LineTo(dc, (int)x2, (int)y2);
    SelectObject(dc, old);
    DeleteObject(pen);
}

void circle(HDC dc, COLORREF outline, COLORREF* fill, double x, double y, double r) {
    HPEN pen = CreatePen(PS_SOLID, 1, outline);
    HBRUSH brush = fill ? CreateSolidBrush(*fill) : nullptr;
    HGDIOBJ oldPen = SelectObject(dc, pen);
    HGDIOBJ oldBrush = SelectObject(dc, brush ? (HGDIOBJ)brush : GetStockObject(NULL_BRUSH));
    Ellipse(dc, (int)(x - r), (int)(y - r), (int)(x + r), (int)(y + r));
    SelectObject(dc, oldBrush);
    SelectObject(dc, oldPen);
    DeleteObject(pen);
    if (brush) DeleteObject(brush);
}

void label(HDC dc, COLORREF c, int x, int y, const char* text) {
    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, c);
    TextOutA(dc, x, y, text, (int)strlen(text));
}

}  // namespace

void ArmVoice::say(const std::string& event) {
    auto now = std::chrono::steady_clock::now();
    auto it = last_.find(event);
    if (!on || (it != last_.end() && now - it->second < COOLDOWN)) return;
    last_[event] = now;
    HANDLE h = spawn("powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + repoRoot() +
                     "\\scripts\\arm_voice.ps1\" " + event);
    if (h) CloseHandle(h);
}

void ArmVoice::watch(const std::string& mode, bool recording, bool playing, bool claw) {
    if (!started_) {
        started_ = true;
        say("connect");
    } else {
        if (mode != mode_) say("mode_" + mode);
        if (recording != recording_) say(recording ? "record_on" : "record_off");
        if (playing != playing_) say(playing ? "play" : "stop");
        if (claw != claw_) say(claw ? "claw_close" : "claw_open");
    }
    mode_ = mode;
    recording_ = recording;
    playing_ = playing;
    claw_ = claw;
}

void startLadder(bool asked) {
    const char* env = std::getenv("FLEET_LADDER");
    if (!asked && !(env && std::string(env) == "1")) return;
    g_ladder = spawn("python \"" + repoRoot() + "\\scripts\\fleet_ladder.py\" ARMCTL --run");
}

void stopLadder() {
    if (g_ladder) TerminateProcess(g_ladder, 0);
}

void drawArm(HDC dc, const RECT& area, const MotorMap& motors, const Geometry& g, const std::map<int, int>& angles) {
    COLORREF panel = schemeColour("panel"), track = schemeColour("track"), knob = schemeColour("button_hover"),
             accent = schemeColour("accent"), dim = schemeColour("text_dim"), text = schemeColour("text");
    const double x0 = area.left + 8, y0 = area.top + 56, w = ARM_PANEL_W - 16;
    HBRUSH bg = CreateSolidBrush(panel);
    RECT box = {(LONG)x0, (LONG)y0, (LONG)(x0 + w), (LONG)(y0 + 560)};
    FillRect(dc, &box, bg);
    DeleteObject(bg);
    label(dc, dim, (int)x0 + 10, (int)y0 + 8, "from the side");

    auto rad = [&](int n) {
        auto m = motors.find(n);
        if (m == motors.end()) return 0.0;
        auto a = angles.find(n);
        int raw = a != angles.end() ? a->second : m->second.rest;
        int zero = m->second.kinematicZero >= 0 ? m->second.kinematicZero : m->second.rest;
        return (raw - zero) * m->second.kinematicSign * 3.14159265358979 / 180;
    };
    double l[3] = {g.upperArmLength, g.forearmLength, g.wristLength};
    double reach = l[0] + l[1] + l[2];
    if (reach <= 0) reach = 300;
    double s = std::min((w - 60) / reach, 230 / (reach + g.baseHeight));
    auto X = [&](double r) { return x0 + 30 + r * s; };
    auto Z = [&](double z) { return y0 + 270 - z * s; };
    line(dc, track, 1, x0 + 10, y0 + 270, x0 + w - 10, y0 + 270);
    int saved = SaveDC(dc);    // her reach: only what fits in the panel
    IntersectClipRect(dc, (int)x0, (int)y0 + 24, (int)(x0 + w), (int)y0 + 300);
    circle(dc, track, nullptr, X(0), Z(g.baseHeight), reach * s);
    RestoreDC(dc, saved);

    double a[3] = {rad(2), 0, 0};
    a[1] = a[0] + rad(3);
    a[2] = a[1] + rad(4);
    double r = 0, z = g.baseHeight;
    std::vector<std::pair<double, double>> joints;
    for (int i = 0; i < 3; i++) {
        double r2 = r + l[i] * std::cos(a[i]), z2 = z + l[i] * std::sin(a[i]);
        line(dc, knob, 6, X(r), Z(z), X(r2), Z(z2));
        joints.push_back({r2, z2});
        r = r2;
        z = z2;
    }
    for (auto& q : joints) {
        circle(dc, accent, &accent, X(q.first), Z(q.second), 6);
        circle(dc, panel, &panel, X(q.first), Z(q.second), 3);
    }
    auto claw = motors.find(6);
    auto clawNow = angles.find(6);
    double open = claw != motors.end() && clawNow != angles.end() && clawNow->second < claw->second.rest ? 0.25 : 0.5;
    for (int sgn : {-1, 1}) {
        double f = a[2] + sgn * open;
        line(dc, accent, 3, X(r), Z(z), X(r) + 14 * std::cos(f), Z(z) - 14 * std::sin(f));
    }
    char buf[64];
    std::snprintf(buf, sizeof(buf), "tip  r %.0f  z %.0f mm", r, z);
    label(dc, text, (int)x0 + 10, (int)y0 + 280, buf);

    double base = rad(1), cx = x0 + w / 2, cy = y0 + 440, rr = r * 100 / reach;
    double tx = cx + rr * std::sin(base), ty = cy - rr * std::cos(base);
    label(dc, dim, (int)x0 + 10, (int)y0 + 315, "from above");
    circle(dc, track, nullptr, cx, cy, 100);
    line(dc, knob, 6, cx, cy, tx, ty);
    circle(dc, accent, &accent, cx, cy, 8);
    circle(dc, accent, &accent, tx, ty, 5);
    std::snprintf(buf, sizeof(buf), "base %+.0f deg", base * 180 / 3.14159265358979);
    label(dc, text, (int)x0 + 10, (int)y0 + 544, buf);
}
