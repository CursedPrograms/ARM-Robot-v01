package main

// Every key and joystick input in its own window (F1), the Go counterpart of
// scripts/keymap.py's window. It shows scripts/keymap.json, which keymap.py
// writes (python scripts/keymap.py --json scripts/keymap.json).

import (
	"encoding/json"
	"image/color"
	"os"
	"path/filepath"
	"strings"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/widget"
)

type keymapSection struct {
	Title string      `json:"title"`
	Keys  [][2]string `json:"keys"` // (key, does); an empty key is a note
}

type keymapFile struct {
	Title    string          `json:"title"`
	Sections []keymapSection `json:"sections"`
}

// loadKeymap reads keymap.json again each time the window opens, so a fresh one shows without a restart.
func loadKeymap() keymapFile {
	km := keymapFile{Title: "ARM - controls"}
	data, err := os.ReadFile(filepath.Join(repoRoot(), "scripts", "keymap.json"))
	if err == nil {
		err = json.Unmarshal(data, &km)
	}
	if err != nil {
		km.Sections = []keymapSection{{"keymap.json not readable",
			[][2]string{{"", err.Error()}, {"", "run: python scripts/keymap.py --json scripts/keymap.json"}}}}
	}
	return km
}

// openKeysWindow opens the window, or brings it to the front if it's already open.
func (a *App) openKeysWindow() {
	if a.keysWin != nil {
		a.keysWin.RequestFocus()
		return
	}
	km := loadKeymap()
	w := a.fyneApp.NewWindow(km.Title)
	mono := fyne.TextStyle{Monospace: true}

	text := func(s string, size float32, role string, style fyne.TextStyle) *canvas.Text {
		t := canvas.NewText(s, schemeColour(role))
		t.TextSize, t.TextStyle = size, style
		return t
	}
	// wrapped is a label that wraps inside its column (canvas.Text doesn't wrap).
	wrapped := func(s string, style fyne.TextStyle) *widget.Label {
		l := widget.NewLabelWithStyle(s, fyne.TextAlignLeading, style)
		l.Wrapping = fyne.TextWrapWord
		return l
	}

	body := container.NewVBox(text(strings.ToUpper(km.Title), 18, "accent", fyne.TextStyle{Monospace: true, Bold: true}))
	for _, s := range km.Sections {
		gap := canvas.NewRectangle(color.Transparent)
		gap.SetMinSize(fyne.NewSize(0, 8))
		body.Add(gap)
		body.Add(text(s.Title, 14, "accent", fyne.TextStyle{Monospace: true, Bold: true}))
		rows := container.NewVBox()
		for _, r := range s.Keys {
			if r[0] == "" {
				note := wrapped(r[1], fyne.TextStyle{Monospace: true, Italic: true})
				note.Importance = widget.LowImportance // dim, like the other controllers' notes
				rows.Add(note)
				continue
			}
			key := wrapped(r[0], fyne.TextStyle{Monospace: true, Bold: true})
			rows.Add(container.New(&keyColumns{keyWidth: 170}, key, wrapped(r[1], mono)))
		}
		body.Add(container.NewStack(canvas.NewRectangle(schemeColour("panel")), rows))
	}

	w.SetContent(container.NewVScroll(container.NewPadded(body)))
	w.Resize(fyne.NewSize(580, 760))
	w.Canvas().SetOnTypedKey(func(e *fyne.KeyEvent) {
		if e.Name == fyne.KeyEscape || e.Name == fyne.KeyF1 {
			w.Close()
		}
	})
	w.SetOnClosed(func() { a.keysWin = nil })
	a.keysWin = w
	w.Show()
}

// keyColumns lays out a key and what it does side by side: the key in a fixed
// column, the description wrapping in the rest of the width.
type keyColumns struct{ keyWidth float32 }

func (k *keyColumns) Layout(objects []fyne.CanvasObject, size fyne.Size) {
	objects[0].Move(fyne.NewPos(0, 0))
	objects[0].Resize(fyne.NewSize(k.keyWidth, size.Height))
	objects[1].Move(fyne.NewPos(k.keyWidth, 0))
	objects[1].Resize(fyne.NewSize(size.Width-k.keyWidth, size.Height))
}

func (k *keyColumns) MinSize(objects []fyne.CanvasObject) fyne.Size {
	h := fyne.Max(objects[0].MinSize().Height, objects[1].MinSize().Height)
	return fyne.NewSize(k.keyWidth+objects[1].MinSize().Width, h)
}
