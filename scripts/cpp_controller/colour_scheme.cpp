#include "colour_scheme.h"

#include "motor_config.h"

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>
#include <string>

namespace {

std::map<std::string, COLORREF> loadScheme() {
    std::map<std::string, COLORREF> scheme = {
        {"background", RGB(0x33, 0x29, 0x2F)},
        {"panel", RGB(0x33, 0x1F, 0x2B)},
        {"border", RGB(0x36, 0x15, 0x29)},
        {"text", RGB(0xFF, 0xFF, 0xFF)},
        {"text_dim", RGB(0xC9, 0xB6, 0xC1)},
        {"button", RGB(0x36, 0x15, 0x29)},
        {"button_hover", RGB(0x69, 0x15, 0x48)},
        {"button_active", RGB(0x9C, 0x00, 0x60)},
        {"button_disabled", RGB(0x33, 0x1F, 0x2B)},
        {"accent", RGB(0x9C, 0x00, 0x60)},
        {"accent_hover", RGB(0xC2, 0x1F, 0x82)},
        {"track", RGB(0x69, 0x15, 0x48)},
        {"selected", RGB(0x69, 0x15, 0x48)},
        {"danger", RGB(0x96, 0x32, 0x32)},
        {"danger_hover", RGB(0xAD, 0x3A, 0x3A)},
        {"warn", RGB(0xF0, 0x8C, 0x3C)},
    };

    std::ifstream f(repoRoot() + "\\colour_scheme.xml");
    if (!f) {
        std::fprintf(stderr, "Warning: could not read colour_scheme.xml, using default colours.\n");
        return scheme;
    }
    std::string line;
    while (std::getline(f, line)) {
        // <colour name="..." value="#RRGGBB"/> - one per line
        size_t tag = line.find("<colour ");
        if (tag == std::string::npos) continue;
        size_t n0 = line.find("name=\"", tag);
        if (n0 == std::string::npos) continue;
        n0 += 6;
        size_t n1 = line.find('"', n0);
        size_t v0 = line.find("value=\"#", n1 == std::string::npos ? n0 : n1);
        if (n1 == std::string::npos || v0 == std::string::npos) continue;
        v0 += 8;
        if (v0 + 6 > line.size()) continue;
        std::string hex = line.substr(v0, 6);
        char* end = nullptr;
        unsigned long n = std::strtoul(hex.c_str(), &end, 16);
        if (end != hex.c_str() + 6) continue;
        scheme[line.substr(n0, n1 - n0)] = RGB((n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF);
    }
    return scheme;
}

} // namespace

COLORREF schemeColour(const std::string& role) {
    static const std::map<std::string, COLORREF> scheme = loadScheme();
    auto it = scheme.find(role);
    return it == scheme.end() ? RGB(255, 0, 255) : it->second;
}
