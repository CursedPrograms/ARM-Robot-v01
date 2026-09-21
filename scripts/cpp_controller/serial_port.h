// serial_port.h - USB-serial connection to the Arduino running
// scripts/arm/arm.ino, plus port listing/autodetect. Mirrors the
// list_serial_ports()/autodetect_port() helpers shared by every Python
// script in this project.
#pragma once

#include <string>
#include <vector>

struct PortInfo {
    std::string device;      // e.g. "COM6"
    std::string description; // friendly name, e.g. "USB-SERIAL CH340 (COM6)"
};

std::vector<PortInfo> listSerialPorts();

// Returns the first port whose description matches a likely Arduino
// USB-serial adapter (same ARDUINO_HINTS substrings as the Python scripts),
// or an empty string if none look like one.
std::string autodetectPort();

class SerialPort {
public:
    ~SerialPort();

    // Opens `device` (e.g. "COM6") at `baud`. Returns an error message on
    // failure, or an empty string on success.
    std::string open(const std::string& device, int baud);

    void close();
    bool isOpen() const { return handle_ != nullptr; }

    // Writes `line` followed by '\n'. No-op if not open.
    void writeLine(const std::string& line);

private:
    void* handle_ = nullptr; // HANDLE, kept as void* to avoid <windows.h> in this header
};
