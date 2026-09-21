package main

// USB serial link to the Arduino running scripts/arm/arm.ino. Wire protocol is
// the same as every other controller: "channel:angle,channel:angle,...\n".

import (
	"fmt"
	"strings"
	"sync"
	"time"

	"go.bug.st/serial"
	"go.bug.st/serial/enumerator"
)

// Descriptions/vendor ids that identify likely Arduino USB-serial adapters,
// for --port auto-detect (Arduino, CH340, CP210x, FTDI).
var (
	arduinoHints = []string{"arduino", "ch340", "usb-serial", "usb serial", "cp210", "ftdi"}
	arduinoVIDs  = map[string]bool{"2341": true, "2A03": true, "1A86": true, "10C4": true, "0403": true}
)

type SerialLink struct {
	port  serial.Port
	lines chan string
	once  sync.Once
}

func OpenSerial(name string, baud int) (*SerialLink, error) {
	port, err := serial.Open(name, &serial.Mode{BaudRate: baud})
	if err != nil {
		return nil, err
	}
	_ = port.SetDTR(true)       // same as pyserial's default: resets the Arduino on connect
	time.Sleep(2 * time.Second) // give the Arduino time to reset
	s := &SerialLink{port: port, lines: make(chan string, 64)}
	go func() {
		for line := range s.lines {
			_, _ = s.port.Write([]byte(line + "\n"))
		}
	}()
	return s, nil
}

// WriteLine never blocks the UI: a stalled or unplugged device just drops
// updates, and the next frame retries.
func (s *SerialLink) WriteLine(line string) {
	select {
	case s.lines <- line:
	default:
	}
}

func (s *SerialLink) Close() {
	s.once.Do(func() {
		close(s.lines)
		_ = s.port.Close()
	})
}

type PortInfo struct{ Name, Description string }

func listPorts() []PortInfo {
	details, err := enumerator.GetDetailedPortsList()
	if err != nil || len(details) == 0 {
		names, _ := serial.GetPortsList()
		ports := make([]PortInfo, 0, len(names))
		for _, n := range names {
			ports = append(ports, PortInfo{Name: n, Description: "serial port"})
		}
		return ports
	}
	ports := make([]PortInfo, 0, len(details))
	for _, d := range details {
		desc := "serial port"
		if d.IsUSB {
			desc = strings.TrimSpace(d.Product)
			if desc == "" {
				desc = fmt.Sprintf("USB %s:%s", d.VID, d.PID)
			}
		}
		ports = append(ports, PortInfo{Name: d.Name, Description: desc})
	}
	return ports
}

func autodetectPort() string {
	details, err := enumerator.GetDetailedPortsList()
	if err != nil {
		return ""
	}
	for _, d := range details {
		if !d.IsUSB {
			continue
		}
		text := strings.ToLower(d.Product)
		if arduinoVIDs[strings.ToUpper(d.VID)] {
			return d.Name
		}
		for _, hint := range arduinoHints {
			if strings.Contains(text, hint) {
				return d.Name
			}
		}
	}
	return ""
}
