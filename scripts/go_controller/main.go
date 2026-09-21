// Go/Fyne counterpart of controller.py: Joystick/Sliders/IK/Fleet modes, macro
// record/replay, live sync with the web page, and --connect client mode. Reads
// the same config.json, records to the same scripts/macros/*.json and serves
// the same scripts/web/ page as the other controllers.
//
// Usage:
//
//	go_controller --list-ports
//	go_controller --port COM6            (Linux: --port /dev/ttyACM0)
//	go_controller --port COM6 --mode slider
//	go_controller --port COM6 --serve
//	go_controller --connect http://192.168.0.10:5011
package main

import (
	"fmt"
	"os"
)

func main() {
	opts, err := parseOptions(os.Args[1:])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	if opts.ListPorts {
		ports := listPorts()
		if len(ports) == 0 {
			fmt.Println("No serial ports found.")
			return
		}
		fmt.Println("Available serial ports:")
		for _, p := range ports {
			fmt.Printf("  %s  -  %s\n", p.Name, p.Description)
		}
		return
	}
	if opts.ListJoysticks {
		lines, err := describeJoysticks()
		if err != nil || len(lines) == 0 {
			fmt.Printf("No joystick/controller devices found (%v).\n", err)
			return
		}
		fmt.Printf("Found %d device(s):\n", len(lines))
		for _, l := range lines {
			fmt.Println(l)
		}
		return
	}

	a := newApp(opts)
	if a == nil {
		os.Exit(1)
	}
	a.run()
}
