package main

// Shared motor configuration, loaded from config.json at the repo root. Go
// counterpart of scripts/motor_config.py: config.json stays the single source
// of truth for the arm's physical limits across all controllers.

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
)

type Motor struct {
	Channel       int
	Min, Max      int
	Rest          int
	Invert        bool
	KinematicSign float64
}

type Geometry struct {
	BaseHeight, UpperArm, Forearm, Wrist float64
}

func (g Geometry) Ready() bool { return g.UpperArm != 0 && g.Forearm != 0 }

// repoRoot works whether launched from the repo root (the launchers) or from a
// build directory: walk up until config.json and scripts/ are found.
func repoRoot() string {
	var starts []string
	if exe, err := os.Executable(); err == nil {
		starts = append(starts, filepath.Dir(exe))
	}
	if wd, err := os.Getwd(); err == nil {
		starts = append(starts, wd)
	}
	for _, start := range starts {
		dir := start
		for {
			_, errCfg := os.Stat(filepath.Join(dir, "config.json"))
			info, errScripts := os.Stat(filepath.Join(dir, "scripts"))
			if errCfg == nil && errScripts == nil && info.IsDir() {
				return dir
			}
			parent := filepath.Dir(dir)
			if parent == dir {
				break
			}
			dir = parent
		}
	}
	wd, _ := os.Getwd()
	return wd
}

func webDir() string    { return filepath.Join(repoRoot(), "scripts", "web") }
func macrosDir() string { return filepath.Join(repoRoot(), "scripts", "macros") }

func readConfig() map[string]any {
	data, err := os.ReadFile(filepath.Join(repoRoot(), "config.json"))
	if err != nil {
		return nil
	}
	var root map[string]any
	if err := json.Unmarshal(data, &root); err != nil {
		fmt.Printf("Warning: could not read config.json (%v), using defaults.\n", err)
		return nil
	}
	return root
}

func number(o map[string]any, key string, fallback float64) float64 {
	if v, ok := o[key].(float64); ok {
		return v
	}
	return fallback
}

func loadMotors() map[int]Motor {
	motors := map[int]Motor{}
	for n := 1; n <= 6; n++ {
		motors[n] = Motor{Channel: n - 1, Min: 0, Max: 270, Rest: 135, KinematicSign: 1}
	}
	overrides, _ := readConfig()["motors"].(map[string]any)
	for key, raw := range overrides {
		n, err := strconv.Atoi(key)
		o, ok := raw.(map[string]any)
		if err != nil || !ok {
			continue
		}
		m, exists := motors[n]
		if !exists {
			m = Motor{Channel: n - 1, Min: 0, Max: 270, Rest: 135, KinematicSign: 1}
		}
		m.Channel = int(math.Round(number(o, "channel", float64(m.Channel))))
		m.Min = int(math.Round(number(o, "min", float64(m.Min))))
		m.Max = int(math.Round(number(o, "max", float64(m.Max))))
		m.Rest = int(math.Round(number(o, "rest", float64(m.Rest))))
		if b, ok := o["invert"].(bool); ok {
			m.Invert = b
		}
		m.KinematicSign = number(o, "kinematicSign", m.KinematicSign)
		motors[n] = m
	}
	return motors
}

func loadGeometry() Geometry {
	var g Geometry
	if o, ok := readConfig()["geometry"].(map[string]any); ok {
		g.BaseHeight = number(o, "baseHeight", 0)
		g.UpperArm = number(o, "upperArmLength", 0)
		g.Forearm = number(o, "forearmLength", 0)
		g.Wrist = number(o, "wristLength", 0)
	}
	return g
}

func sortedMotorNumbers(motors map[int]Motor) []int {
	order := make([]int, 0, len(motors))
	for n := range motors {
		order = append(order, n)
	}
	sort.Ints(order)
	return order
}
