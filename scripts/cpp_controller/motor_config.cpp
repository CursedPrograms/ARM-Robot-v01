#include "motor_config.h"
#include "json.hpp"

#include <windows.h>

#include <fstream>
#include <sstream>

namespace {

std::string exeDir() {
    char buf[MAX_PATH] = {0};
    GetModuleFileNameA(nullptr, buf, MAX_PATH);
    std::string path(buf);
    size_t slash = path.find_last_of("\\/");
    return slash == std::string::npos ? "." : path.substr(0, slash);
}

bool fileExists(const std::string& path) {
    DWORD attrs = GetFileAttributesA(path.c_str());
    return attrs != INVALID_FILE_ATTRIBUTES && !(attrs & FILE_ATTRIBUTE_DIRECTORY);
}

std::string readFile(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return "";
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

MotorMap defaultMotors() {
    MotorMap m;
    for (int n = 1; n <= 6; n++) {
        Motor motor;
        motor.channel = n - 1;
        motor.min = 0;
        motor.max = 270;
        motor.rest = 135;
        motor.invert = false;
        motor.kinematicSign = 1;
        m[n] = motor;
    }
    return m;
}

Geometry defaultGeometry() {
    return Geometry{0, 0, 0, 0};
}

} // namespace

std::string configPath() {
    std::string dir = exeDir();
    for (int i = 0; i < 6; i++) {
        std::string candidate = dir + "\\config.json";
        if (fileExists(candidate)) return candidate;
        size_t slash = dir.find_last_of("\\/");
        if (slash == std::string::npos) break;
        dir = dir.substr(0, slash);
    }
    return exeDir() + "\\config.json";
}

std::string repoRoot() {
    std::string path = configPath();
    size_t slash = path.find_last_of("\\/");
    return slash == std::string::npos ? "." : path.substr(0, slash);
}

MotorMap loadMotorConfig() {
    MotorMap motors = defaultMotors();

    std::string text = readFile(configPath());
    if (text.empty()) return motors;

    Json data;
    try {
        data = Json::parse(text);
    } catch (const std::exception&) {
        return motors;
    }

    const Json* motorsObj = data.find("motors");
    if (!motorsObj || !motorsObj->isObject()) return motors;

    for (const auto& kv : motorsObj->obj_value) {
        int n = 0;
        try {
            n = std::stoi(kv.first);
        } catch (const std::exception&) {
            continue;
        }
        Motor& m = motors[n]; // default-constructed (rest=135, etc.) if new
        const Json& overrides = kv.second;
        if (const Json* v = overrides.find("channel")) m.channel = v->asInt(m.channel);
        if (const Json* v = overrides.find("min")) m.min = v->asInt(m.min);
        if (const Json* v = overrides.find("max")) m.max = v->asInt(m.max);
        if (const Json* v = overrides.find("rest")) m.rest = v->asInt(m.rest);
        if (const Json* v = overrides.find("invert")) m.invert = v->asBool(m.invert);
        if (const Json* v = overrides.find("kinematicSign")) m.kinematicSign = v->asInt(m.kinematicSign);
    }

    return motors;
}

Geometry loadGeometry() {
    Geometry geometry = defaultGeometry();

    std::string text = readFile(configPath());
    if (text.empty()) return geometry;

    Json data;
    try {
        data = Json::parse(text);
    } catch (const std::exception&) {
        return geometry;
    }

    const Json* geo = data.find("geometry");
    if (!geo || !geo->isObject()) return geometry;

    geometry.baseHeight = geo->get("baseHeight", geometry.baseHeight);
    geometry.upperArmLength = geo->get("upperArmLength", geometry.upperArmLength);
    geometry.forearmLength = geo->get("forearmLength", geometry.forearmLength);
    geometry.wristLength = geo->get("wristLength", geometry.wristLength);
    return geometry;
}

bool geometryReady(const Geometry& g) {
    return g.upperArmLength != 0 && g.forearmLength != 0;
}
