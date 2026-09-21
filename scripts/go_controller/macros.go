package main

// Record/replay motor-pose macros as JSON. Go counterpart of controller.py's
// macro helpers; reads/writes the same scripts/macros/*.json files as every
// other controller.

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"time"
)

type MacroStep struct {
	T        float64
	Commands map[int]int // channel -> angle
}

// listMacros returns macro files newest first (file names embed the timestamp).
func listMacros() []string {
	files, _ := filepath.Glob(filepath.Join(macrosDir(), "*.json"))
	sort.Slice(files, func(i, j int) bool { return filepath.Base(files[i]) > filepath.Base(files[j]) })
	return files
}

func saveMacro(steps []MacroStep) (string, error) {
	if err := os.MkdirAll(macrosDir(), 0o755); err != nil {
		return "", err
	}
	now := time.Now()
	path := filepath.Join(macrosDir(), "macro_"+now.Format("20060102_150405")+".json")

	stepList := make([]map[string]any, 0, len(steps))
	for _, s := range steps {
		commands := map[string]int{}
		for ch, a := range s.Commands {
			commands[strconv.Itoa(ch)] = a
		}
		stepList = append(stepList, map[string]any{"t": s.T, "commands": commands})
	}
	data, err := json.Marshal(map[string]any{"created": now.Format("2006-01-02 15:04:05"), "steps": stepList})
	if err != nil {
		return "", err
	}
	return path, os.WriteFile(path, data, 0o644)
}

func loadMacro(path string) ([]MacroStep, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var root struct {
		Steps []struct {
			T        float64            `json:"t"`
			Commands map[string]float64 `json:"commands"`
		} `json:"steps"`
	}
	if err := json.Unmarshal(data, &root); err != nil {
		return nil, err
	}
	steps := make([]MacroStep, 0, len(root.Steps))
	for _, s := range root.Steps {
		commands := map[int]int{}
		for key, a := range s.Commands {
			if ch, err := strconv.Atoi(key); err == nil {
				commands[ch] = int(math.Round(a))
			}
		}
		steps = append(steps, MacroStep{T: s.T, Commands: commands})
	}
	return steps, nil
}
