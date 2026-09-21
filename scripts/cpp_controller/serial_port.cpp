#include "serial_port.h"

#include <windows.h>
#include <setupapi.h>

#include <algorithm>
#include <cctype>
#include <chrono>
#include <thread>

namespace {

// Ports device setup class GUID ({4D36E978-E325-11CE-BFC1-08002BE10318}),
// defined by hand so this file doesn't depend on devguid.h/uuid.lib.
const GUID GUID_PORTS_CLASS = {
    0x4D36E978, 0xE325, 0x11CE, {0xBF, 0xC1, 0x08, 0x00, 0x2B, 0xE1, 0x03, 0x18}};

const char* ARDUINO_HINTS[] = {"arduino", "ch340", "usb-serial", "usb serial", "cp210", "ftdi"};

std::string toLower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return std::tolower(c); });
    return s;
}

// Pulls "COM6" out of a friendly name like "USB-SERIAL CH340 (COM6)".
std::string extractComName(const std::string& friendlyName) {
    size_t open = friendlyName.rfind('(');
    size_t close = friendlyName.rfind(')');
    if (open == std::string::npos || close == std::string::npos || close <= open) return "";
    std::string inner = friendlyName.substr(open + 1, close - open - 1);
    if (inner.size() > 3 && toLower(inner.substr(0, 3)) == "com") return inner;
    return "";
}

} // namespace

std::vector<PortInfo> listSerialPorts() {
    std::vector<PortInfo> ports;

    HDEVINFO devInfo = SetupDiGetClassDevsA(&GUID_PORTS_CLASS, nullptr, nullptr, DIGCF_PRESENT);
    if (devInfo == INVALID_HANDLE_VALUE) return ports;

    SP_DEVINFO_DATA data;
    data.cbSize = sizeof(SP_DEVINFO_DATA);
    for (DWORD i = 0; SetupDiEnumDeviceInfo(devInfo, i, &data); i++) {
        char friendlyName[256] = {0};
        if (!SetupDiGetDeviceRegistryPropertyA(devInfo, &data, SPDRP_FRIENDLYNAME, nullptr,
                                                reinterpret_cast<PBYTE>(friendlyName), sizeof(friendlyName) - 1, nullptr)) {
            // Some virtual/composite devices only expose the plain device description.
            SetupDiGetDeviceRegistryPropertyA(devInfo, &data, SPDRP_DEVICEDESC, nullptr,
                                               reinterpret_cast<PBYTE>(friendlyName), sizeof(friendlyName) - 1, nullptr);
        }
        std::string name(friendlyName);
        std::string comName = extractComName(name);
        if (!comName.empty()) {
            ports.push_back({comName, name});
        }
    }

    SetupDiDestroyDeviceInfoList(devInfo);
    return ports;
}

namespace {

bool looksLikeArduino(const PortInfo& p) {
    std::string lower = toLower(p.description);
    for (const char* hint : ARDUINO_HINTS) {
        if (lower.find(hint) != std::string::npos) return true;
    }
    return false;
}

// True if the board on `device` answers "WHO" with "I am Arm".
bool answersIAmArm(const std::string& device) {
    SerialPort port;
    if (!port.open(device, 115200).empty()) return false; // busy or unusable
    std::this_thread::sleep_for(std::chrono::seconds(2)); // board resets when the port opens
    port.flushInput();
    port.writeLine("WHO");
    std::string buf;
    auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(1500);
    while (std::chrono::steady_clock::now() < deadline) {
        buf += port.readAvailable();
        if (toLower(buf).find("i am arm") != std::string::npos) return true;
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    return false;
}

} // namespace

std::string autodetectPort() {
    std::string firstGuess;
    for (const auto& p : listSerialPorts()) {
        if (!looksLikeArduino(p)) continue;
        if (answersIAmArm(p.device)) return p.device;
        if (firstGuess.empty()) firstGuess = p.device;
    }
    return firstGuess;
}

SerialPort::~SerialPort() { close(); }

std::string SerialPort::open(const std::string& device, int baud) {
    close();

    // "\\\\.\\COM10"-style path is required for COM10 and above, and works
    // fine for lower numbers too.
    std::string path = "\\\\.\\" + device;
    HANDLE h = CreateFileA(path.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                            OPEN_EXISTING, 0, nullptr);
    if (h == INVALID_HANDLE_VALUE) {
        return "Could not open " + device + " (error " + std::to_string(GetLastError()) + ")";
    }

    DCB dcb = {0};
    dcb.DCBlength = sizeof(DCB);
    if (!GetCommState(h, &dcb)) {
        CloseHandle(h);
        return "Could not read " + device + "'s current settings";
    }
    dcb.BaudRate = static_cast<DWORD>(baud);
    dcb.ByteSize = 8;
    dcb.Parity = NOPARITY;
    dcb.StopBits = ONESTOPBIT;
    dcb.fBinary = TRUE;
    dcb.fParity = FALSE;
    if (!SetCommState(h, &dcb)) {
        CloseHandle(h);
        return "Could not configure " + device + " for " + std::to_string(baud) + " baud";
    }

    COMMTIMEOUTS timeouts = {0};
    timeouts.ReadIntervalTimeout = MAXDWORD;
    timeouts.ReadTotalTimeoutConstant = 0;
    timeouts.ReadTotalTimeoutMultiplier = 0;
    timeouts.WriteTotalTimeoutConstant = 1000;
    timeouts.WriteTotalTimeoutMultiplier = 0;
    SetCommTimeouts(h, &timeouts);

    handle_ = h;
    return "";
}

void SerialPort::close() {
    if (handle_) {
        CloseHandle(static_cast<HANDLE>(handle_));
        handle_ = nullptr;
    }
}

std::string SerialPort::readAvailable() {
    if (!handle_) return "";
    char buf[256];
    DWORD got = 0;
    if (!ReadFile(static_cast<HANDLE>(handle_), buf, sizeof(buf), &got, nullptr)) return "";
    return std::string(buf, got);
}

void SerialPort::flushInput() {
    if (handle_) PurgeComm(static_cast<HANDLE>(handle_), PURGE_RXCLEAR);
}

void SerialPort::writeLine(const std::string& line) {
    if (!handle_) return;
    std::string withNewline = line + "\n";
    DWORD written = 0;
    WriteFile(static_cast<HANDLE>(handle_), withNewline.data(), static_cast<DWORD>(withNewline.size()), &written, nullptr);
}
