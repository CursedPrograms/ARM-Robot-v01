package main

// UI colours from colour_scheme.xml at the repo root, shared by every
// controller. Edit that file and restart - no rebuild. Any role missing from it
// (or the whole file being unreadable) falls back to schemeDefaults.

import (
	"encoding/xml"
	"fmt"
	"image/color"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/theme"
)

var schemeDefaults = map[string]string{
	"background": "#33292F",
	"panel": "#331F2B",
	"border": "#361529",
	"text": "#FFFFFF",
	"text_dim": "#C9B6C1",
	"button": "#361529",
	"button_hover": "#691548",
	"button_active": "#9C0060",
	"button_disabled": "#331F2B",
	"accent": "#9C0060",
	"accent_hover": "#C21F82",
	"track": "#691548",
	"selected": "#691548",
	"danger": "#963232",
	"danger_hover": "#AD3A3A",
	"warn": "#F08C3C",
}

var scheme = loadScheme()

func parseHexColour(s string) (color.NRGBA, error) {
	s = strings.TrimPrefix(strings.TrimSpace(s), "#")
	if len(s) != 6 {
		return color.NRGBA{}, fmt.Errorf("expected #RRGGBB, got %q", s)
	}
	n, err := strconv.ParseUint(s, 16, 32)
	if err != nil {
		return color.NRGBA{}, err
	}
	return color.NRGBA{R: uint8(n >> 16), G: uint8(n >> 8), B: uint8(n), A: 255}, nil
}

func loadScheme() map[string]color.NRGBA {
	out := map[string]color.NRGBA{}
	for name, value := range schemeDefaults {
		c, _ := parseHexColour(value)
		out[name] = c
	}
	data, err := os.ReadFile(filepath.Join(repoRoot(), "colour_scheme.xml"))
	if err != nil {
		fmt.Printf("Warning: could not read colour_scheme.xml (%v), using default colours.\n", err)
		return out
	}
	var doc struct {
		Colours []struct {
			Name  string `xml:"name,attr"`
			Value string `xml:"value,attr"`
		} `xml:"colour"`
	}
	if err := xml.Unmarshal(data, &doc); err != nil {
		fmt.Printf("Warning: could not parse colour_scheme.xml (%v), using default colours.\n", err)
		return out
	}
	for _, c := range doc.Colours {
		parsed, err := parseHexColour(c.Value)
		if err != nil {
			fmt.Printf("Warning: colour_scheme.xml: bad value for %q (%v), keeping default.\n", c.Name, err)
			continue
		}
		out[c.Name] = parsed
	}
	return out
}

// schemeColour returns the colour for a role such as "background" or "warn".
func schemeColour(name string) color.NRGBA { return scheme[name] }

// Fyne theme colour -> colour_scheme.xml role.
var themeRoles = map[fyne.ThemeColorName]string{
	theme.ColorNameBackground:        "background",
	theme.ColorNameOverlayBackground: "panel",
	theme.ColorNameMenuBackground:    "panel",
	theme.ColorNameInputBackground:   "panel",
	theme.ColorNameInputBorder:       "border",
	theme.ColorNameSeparator:         "border",
	theme.ColorNameForeground:        "text",
	theme.ColorNameForegroundOnPrimary: "text",
	theme.ColorNameDisabled:          "text_dim",
	theme.ColorNamePlaceholder:       "text_dim",
	theme.ColorNameButton:            "button",
	theme.ColorNameDisabledButton:    "button_disabled",
	theme.ColorNameHover:             "button_hover",
	theme.ColorNamePressed:           "button_active",
	theme.ColorNamePrimary:           "accent",
	theme.ColorNameFocus:             "accent_hover",
	theme.ColorNameSelection:         "selected",
	theme.ColorNameScrollBar:         "track",
	theme.ColorNameWarning:           "warn",
	theme.ColorNameError:             "danger",
}

type schemeTheme struct{ fyne.Theme }

func newSchemeTheme() fyne.Theme { return schemeTheme{theme.DefaultTheme()} }

func (t schemeTheme) Color(name fyne.ThemeColorName, variant fyne.ThemeVariant) color.Color {
	if role, ok := themeRoles[name]; ok {
		return schemeColour(role)
	}
	return t.Theme.Color(name, variant)
}
