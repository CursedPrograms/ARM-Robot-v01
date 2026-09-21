#include "macros.h"
#include "json.hpp"
#include "motor_config.h"

#include <windows.h>

#include <algorithm>
#include <cstdio>
#include <fstream>
#include <sstream>

std::string macrosDir() {
    return repoRoot() + "\\scripts\\macros";
}

std::vector<MacroFile> listMacros() {
    std::vector<MacroFile> macros;
    std::string dir = macrosDir();

    WIN32_FIND_DATAA findData;
    std::string pattern = dir + "\\*.json";
    HANDLE h = FindFirstFileA(pattern.c_str(), &findData);
    if (h == INVALID_HANDLE_VALUE) return macros;

    do {
        std::string filename(findData.cFileName);
        std::string stem = filename.substr(0, filename.size() - 5); // strip ".json"
        macros.push_back({dir + "\\" + filename, stem});
    } while (FindNextFileA(h, &findData));
    FindClose(h);

    std::sort(macros.begin(), macros.end(), [](const MacroFile& a, const MacroFile& b) {
        return a.name > b.name; // newest timestamp first, same as Python's reverse=True
    });
    return macros;
}

std::string saveMacro(const std::vector<MacroStep>& steps) {
    std::string dir = macrosDir();
    CreateDirectoryA(dir.c_str(), nullptr); // no-op if it already exists

    SYSTEMTIME st;
    GetLocalTime(&st);
    char stamp[32];
    std::snprintf(stamp, sizeof(stamp), "%04d%02d%02d_%02d%02d%02d",
                  st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond);
    char created[32];
    std::snprintf(created, sizeof(created), "%04d-%02d-%02d %02d:%02d:%02d",
                  st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond);

    Json root = Json::makeObject();
    root.set("created", Json::makeString(created));
    Json stepsArr = Json::makeArray();
    for (const auto& step : steps) {
        Json stepObj = Json::makeObject();
        stepObj.set("t", Json::makeNumber(step.t));
        Json cmds = Json::makeObject();
        for (const auto& kv : step.commands) {
            cmds.set(std::to_string(kv.first), Json::makeNumber(kv.second));
        }
        stepObj.set("commands", std::move(cmds));
        stepsArr.push_back(std::move(stepObj));
    }
    root.set("steps", std::move(stepsArr));

    std::string path = dir + "\\macro_" + stamp + ".json";
    std::ofstream out(path, std::ios::binary);
    out << root.dump();
    return path;
}

std::vector<MacroStep> loadMacro(const std::string& path) {
    std::vector<MacroStep> steps;

    std::ifstream f(path, std::ios::binary);
    if (!f) return steps;
    std::ostringstream ss;
    ss << f.rdbuf();

    Json root;
    try {
        root = Json::parse(ss.str());
    } catch (const std::exception&) {
        return steps;
    }

    const Json* stepsArr = root.find("steps");
    if (!stepsArr || !stepsArr->isArray()) return steps;

    for (const Json& stepJson : stepsArr->arr_value) {
        MacroStep step;
        step.t = stepJson.get("t", 0.0);
        if (const Json* cmds = stepJson.find("commands")) {
            for (const auto& kv : cmds->obj_value) {
                try {
                    step.commands[std::stoi(kv.first)] = kv.second.asInt();
                } catch (const std::exception&) {
                    continue;
                }
            }
        }
        steps.push_back(std::move(step));
    }
    return steps;
}
