cmake_minimum_required(VERSION 3.15)
project(arm_controller_cpp CXX)

if(NOT WIN32)
    message(FATAL_ERROR "This controller uses the Win32 API (windows.h, winmm, setupapi) and only builds on Windows.")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(controller
    app.cpp
    motor_config.cpp
    kinematics.cpp
    serial_port.cpp
    joystick.cpp
    macros.cpp
    fleet_server.cpp
)

target_link_libraries(controller PRIVATE ws2_32 setupapi winmm comctl32)
