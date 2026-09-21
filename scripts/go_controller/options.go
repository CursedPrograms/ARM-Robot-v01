package main

// Command-line options, same flags as controller.py / the other controllers.

import (
	"fmt"
	"strconv"
)

type Mode int

const (
	ModeJoystick Mode = iota
	ModeSlider
	ModeIK
	ModeFleet
)

type Options struct {
	Device        int
	Port          string
	Baud          int
	Rate          float64
	Mode          *Mode
	ListJoysticks bool
	ListPorts     bool
	FleetPort     int
	RiftHost      string
	RiftPort      int
	NoRegister    bool
	Serve         bool
	Connect       string
}

func parseOptions(args []string) (Options, error) {
	o := Options{Baud: 115200, Rate: 30, FleetPort: defaultFleetPort, RiftHost: "127.0.0.1", RiftPort: 5000}
	for i := 0; i < len(args); i++ {
		a := args[i]
		value := func() (string, error) {
			if i+1 >= len(args) {
				return "", fmt.Errorf("%s requires a value", a)
			}
			i++
			return args[i], nil
		}
		intValue := func() (int, error) {
			v, err := value()
			if err != nil {
				return 0, err
			}
			n, err := strconv.Atoi(v)
			if err != nil {
				return 0, fmt.Errorf("%s requires an integer", a)
			}
			return n, nil
		}
		var err error
		switch a {
		case "--list":
			o.ListJoysticks = true
		case "--list-ports":
			o.ListPorts = true
		case "--no-register":
			o.NoRegister = true
		case "--serve":
			o.Serve = true
		case "--port":
			o.Port, err = value()
		case "--connect":
			o.Connect, err = value()
		case "--rift-host":
			o.RiftHost, err = value()
		case "--device":
			o.Device, err = intValue()
		case "--baud":
			o.Baud, err = intValue()
		case "--fleet-port":
			o.FleetPort, err = intValue()
		case "--rift-port":
			o.RiftPort, err = intValue()
		case "--rate":
			var v string
			if v, err = value(); err == nil {
				if o.Rate, err = strconv.ParseFloat(v, 64); err != nil {
					err = fmt.Errorf("--rate requires a number")
				}
			}
		case "--mode":
			var v string
			if v, err = value(); err == nil {
				m := map[string]Mode{"joystick": ModeJoystick, "slider": ModeSlider, "ik": ModeIK, "fleet": ModeFleet}
				mode, ok := m[v]
				if !ok {
					return o, fmt.Errorf("unknown --mode '%s' (expected joystick, slider, ik or fleet)", v)
				}
				o.Mode = &mode
			}
		default:
			return o, fmt.Errorf("unknown argument: %s", a)
		}
		if err != nil {
			return o, err
		}
	}
	if o.Connect != "" && (o.Serve || (o.Mode != nil && *o.Mode == ModeFleet)) {
		return o, fmt.Errorf("--connect can't be combined with --serve or --mode fleet (this controller has no arm of its own)")
	}
	return o, nil
}
