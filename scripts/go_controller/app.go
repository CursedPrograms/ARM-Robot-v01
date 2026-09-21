package main

// The controller window: Fyne counterpart of controller.py and the C++
// controller's app.cpp. Same four modes (Joystick/Sliders/IK/Fleet), same macro
// record/replay, same wire protocol to scripts/arm/arm.ino, same shared-angle
// sync with the web page / other controllers.
//
// A single ticker plays the role of controller.py's per-frame loop: tick()
// merges this mode's input into the shared angles, then sends/records the
// shared state.

import (
	"fmt"
	"image/color"
	"math"
	"path/filepath"
	"sort"
	"strings"
	"sync/atomic"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/app"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/widget"
)

// Joystick wiring (Joystick mode only, mirrors controller.py).
const (
	axisMotor1           = 0
	axisMotor2           = 1
	axisMotor5           = 2 // A2 and A3 move together on this stick; only A2 is read
	hatMotor3            = 0
	buttonMotor4Backward = 2
	buttonMotor4Forward  = 3
	buttonMotor6Close    = 0
	deadzone             = 0.05
)

type sliderRow struct {
	motor  int
	slider *widget.Slider
	value  *widget.Label
	box    fyne.CanvasObject
	suffix string
}

func newSliderRow(label string, lo, hi, initial float64, suffix string) *sliderRow {
	s := widget.NewSlider(lo, hi)
	s.Step = 1
	s.SetValue(initial)
	val := widget.NewLabel(fmt.Sprintf("%d%s", int(initial), suffix))
	return &sliderRow{
		slider: s, value: val, suffix: suffix,
		box: container.NewBorder(nil, nil, widget.NewLabel(label), val, s),
	}
}

func (r *sliderRow) position() int { return int(math.Round(r.slider.Value)) }

func (r *sliderRow) setText(v int) {
	if text := fmt.Sprintf("%d%s", v, r.suffix); r.value.Text != text {
		r.value.SetText(text)
	}
}

type ikState struct {
	elbowDown, clawClosed bool
}

type App struct {
	opts     Options
	motors   map[int]Motor
	order    []int
	geometry Geometry
	reach    int

	serial      *SerialLink
	serialOpen  atomic.Bool
	joystick    *Joystick
	statusBase  string
	statusShown string

	mode, lastMode Mode

	shared    *Shared
	prevLocal map[int]int // last angle each local input produced, by motor number
	remote    *RemoteArm
	adopted   bool // a client waits for the hub's real angles before its own inputs may write

	fleet      *FleetServer
	fleetError string
	lanIP      string

	ik          ikState
	lastValidIK map[int]int
	warn        string

	lastSent map[int]int // channel -> angle

	macroFiles    []string
	selectedMacro int
	recording     bool
	recordSteps   []MacroStep
	recordStart   time.Time
	playing       bool
	playSteps     []MacroStep
	playStart     time.Time
	playIndex     int
	playPrevMode  Mode

	// widgets
	fyneApp    fyne.App
	win        fyne.Window
	statusLbl  *widget.Label
	warnText   *canvas.Text
	modeBtns   [4]*widget.Button
	recordBtn  *widget.Button
	playBtn    *widget.Button
	macroList  *widget.List
	motorRows  []*sliderRow
	ikRows     map[string]*sliderRow
	elbowBtn   *widget.Button
	clawBtn    *widget.Button
	motorLines []*widget.Label
	sliderBox  *fyne.Container
	ikBox      *fyne.Container
	linesBox   *fyne.Container
}

func newApp(opts Options) *App {
	a := &App{opts: opts, prevLocal: map[int]int{}, lastSent: map[int]int{}, selectedMacro: -1, lanIP: localLanIP()}
	a.motors = loadMotors()
	a.order = sortedMotorNumbers(a.motors)
	a.geometry = loadGeometry()
	reach := a.geometry.UpperArm + a.geometry.Forearm + a.geometry.Wrist
	if reach <= 0 {
		reach = 300
	}
	a.reach = int(reach)

	if j, err := OpenJoystick(opts.Device); err == nil {
		a.joystick = j
		fmt.Printf("Using joystick: %s\n", j.Name)
	} else {
		fmt.Printf("No joystick found - Joystick mode will be unavailable. (%v)\n", err)
	}

	switch {
	case opts.Connect != "":
		a.statusBase = fmt.Sprintf("Remote arm at %s (no local serial port).", opts.Connect)
	default:
		port := opts.Port
		if port == "" {
			port = autodetectPort()
		}
		if port == "" {
			a.statusBase = "No Arduino-like serial port found - display-only mode."
		} else if link, err := OpenSerial(port, opts.Baud); err != nil {
			a.statusBase = fmt.Sprintf("Could not open %s: %v", port, err)
		} else {
			a.serial = link
			a.serialOpen.Store(true)
			a.statusBase = fmt.Sprintf("Connected to %s @ %d baud.", port, opts.Baud)
		}
	}
	fmt.Println(a.statusBase)

	angles := map[int]int{}
	for n, m := range a.motors {
		angles[n] = m.Rest
	}
	a.shared = NewShared(angles)

	if opts.Connect != "" {
		remote, err := StartRemoteArm(opts.Connect, a.shared)
		if err != nil {
			fmt.Println(err)
			return nil
		}
		a.remote = remote
	}
	a.adopted = a.remote == nil

	switch {
	case opts.Mode != nil:
		a.mode = *opts.Mode
	case a.joystick != nil:
		a.mode = ModeJoystick
	default:
		a.mode = ModeSlider
	}
	a.lastMode, a.playPrevMode = a.mode, a.mode
	a.macroFiles = listMacros()
	return a
}

func (a *App) ensureFleetStarted() {
	if a.fleet != nil || a.fleetError != "" || a.opts.Connect != "" {
		return // a client has no arm of its own to serve
	}
	fs, err := StartFleetServer(a.motors, a.shared, &a.serialOpen, a.opts.FleetPort,
		!a.opts.NoRegister, a.opts.RiftHost, a.opts.RiftPort)
	if err != nil {
		a.fleetError = err.Error()
		fmt.Println(a.fleetError)
		return
	}
	a.fleet = fs
	url := fmt.Sprintf("http://%s:%d", a.lanIP, a.opts.FleetPort)
	fmt.Println("Web control on", url)
	a.statusBase += "  |  Web: " + url
}

// ---------------------------------------------------------------------
// UI
// ---------------------------------------------------------------------

func (a *App) buildUI() fyne.CanvasObject {
	title := widget.NewLabelWithStyle("Arm Controller (Go)", fyne.TextAlignLeading, fyne.TextStyle{Bold: true})
	a.statusLbl = widget.NewLabel(a.statusBase)
	a.statusLbl.Wrapping = fyne.TextWrapWord

	names := []string{"Joystick", "Sliders", "IK", "Fleet"}
	modeRow := container.NewGridWithColumns(4)
	for i, name := range names {
		mode := Mode(i)
		btn := widget.NewButton(name, func() { a.onModeClicked(mode) })
		a.modeBtns[i] = btn
		modeRow.Add(btn)
	}

	a.recordBtn = widget.NewButton("Record", a.onRecordClicked)
	a.playBtn = widget.NewButton("Play", a.onPlayClicked)
	transport := container.NewGridWithColumns(2, a.recordBtn, a.playBtn)

	a.macroList = widget.NewList(
		func() int { return len(a.macroFiles) },
		func() fyne.CanvasObject { return widget.NewLabel("macro") },
		func(i widget.ListItemID, o fyne.CanvasObject) {
			name := strings.TrimSuffix(filepath.Base(a.macroFiles[i]), ".json")
			o.(*widget.Label).SetText(fmt.Sprintf("%d. %s", i+1, name))
		},
	)
	a.macroList.OnSelected = func(id widget.ListItemID) { a.selectedMacro = int(id) }
	if len(a.macroFiles) > 0 {
		a.macroList.Select(0)
	}
	macroBox := container.NewGridWrap(fyne.NewSize(560, 84), a.macroList)

	a.warnText = canvas.NewText("", color.NRGBA{R: 240, G: 140, B: 60, A: 255})
	a.warnText.TextSize = 12

	a.sliderBox = container.NewVBox()
	for _, n := range a.order {
		m := a.motors[n]
		row := newSliderRow(fmt.Sprintf("Motor %d (ch %d)", n, m.Channel), float64(m.Min), float64(m.Max), float64(m.Rest), "°")
		row.motor = n
		a.motorRows = append(a.motorRows, row)
		a.sliderBox.Add(row.box)
	}

	m5 := a.motors[5]
	reach := float64(a.reach)
	a.ikRows = map[string]*sliderRow{
		"x":     newSliderRow("Target X (mm)", -reach, reach, 0, "mm"),
		"y":     newSliderRow("Target Y (mm)", -reach, reach, 0, "mm"),
		"z":     newSliderRow("Target Z (mm)", 0, reach, a.geometry.BaseHeight, "mm"),
		"pitch": newSliderRow("Pitch (deg)", -90, 90, 0, "°"),
		"roll":  newSliderRow("Roll (motor 5)", float64(m5.Min), float64(m5.Max), float64(m5.Rest), ""),
	}
	a.elbowBtn = widget.NewButton("Elbow: Up", func() {
		a.ik.elbowDown = !a.ik.elbowDown
		a.elbowBtn.SetText(map[bool]string{false: "Elbow: Up", true: "Elbow: Down"}[a.ik.elbowDown])
	})
	a.clawBtn = widget.NewButton("Claw: Open", func() {
		a.ik.clawClosed = !a.ik.clawClosed
		a.clawBtn.SetText(map[bool]string{false: "Claw: Open", true: "Claw: Closed"}[a.ik.clawClosed])
	})
	a.ikBox = container.NewVBox()
	for _, key := range []string{"x", "y", "z", "pitch", "roll"} {
		a.ikBox.Add(a.ikRows[key].box)
	}
	a.ikBox.Add(container.NewGridWithColumns(2, a.elbowBtn, a.clawBtn))

	a.linesBox = container.NewVBox()
	for range a.order {
		lbl := widget.NewLabel("")
		a.motorLines = append(a.motorLines, lbl)
		a.linesBox.Add(lbl)
	}

	a.applyMode()
	return container.NewVBox(title, a.statusLbl, modeRow, transport, macroBox,
		a.warnText, a.sliderBox, a.ikBox, a.linesBox)
}

func show(o fyne.CanvasObject, on bool) {
	if on {
		o.Show()
	} else {
		o.Hide()
	}
}

func (a *App) applyMode() {
	show(a.sliderBox, a.mode == ModeSlider)
	show(a.ikBox, a.mode == ModeIK && a.geometry.Ready())
	show(a.linesBox, a.mode == ModeJoystick || a.mode == ModeFleet)
	for i, b := range a.modeBtns {
		b.Importance = widget.MediumImportance
		if int(a.mode) == i {
			b.Importance = widget.HighImportance
		}
		if a.playing || (i == int(ModeJoystick) && a.joystick == nil) {
			b.Disable()
		} else {
			b.Enable()
		}
		b.Refresh()
	}
}

func (a *App) onModeClicked(m Mode) {
	if a.playing {
		return
	}
	a.mode = m
	if m == ModeFleet {
		a.ensureFleetStarted()
	}
	a.applyMode()
}

func (a *App) onRecordClicked() {
	if a.playing {
		return
	}
	if !a.recording {
		a.recording = true
		a.recordSteps = nil
		a.recordStart = time.Now()
		return
	}
	a.recording = false
	a.recordBtn.SetText("Record")
	if len(a.recordSteps) == 0 {
		return
	}
	path, err := saveMacro(a.recordSteps)
	if err != nil {
		a.statusBase = fmt.Sprintf("Could not save macro: %v", err)
		return
	}
	fmt.Printf("Saved macro: %s (%d steps)\n", filepath.Base(path), len(a.recordSteps))
	a.macroFiles = listMacros()
	a.macroList.Refresh()
	a.macroList.Select(0)
}

func (a *App) onPlayClicked() {
	if a.playing {
		a.stopPlayback()
		return
	}
	if a.selectedMacro < 0 || a.selectedMacro >= len(a.macroFiles) {
		return
	}
	steps, err := loadMacro(a.macroFiles[a.selectedMacro])
	if err != nil {
		a.statusBase = fmt.Sprintf("Could not load macro: %v", err)
		return
	}
	a.playSteps, a.playIndex, a.playPrevMode = steps, 0, a.mode
	a.playStart = time.Now()
	a.playing = true
	a.applyMode()
}

func (a *App) stopPlayback() {
	a.playing = false
	a.playBtn.SetText("Play")
	a.mode = a.playPrevMode
	if a.mode == ModeFleet {
		a.ensureFleetStarted()
	}
	a.applyMode()
}

func (a *App) onKey(e *fyne.KeyEvent) {
	if e.Name == fyne.KeyEscape {
		a.fyneApp.Quit()
		return
	}
	if a.playing {
		return
	}
	keys := []fyne.KeyName{fyne.Key1, fyne.Key2, fyne.Key3, fyne.Key4, fyne.Key5, fyne.Key6, fyne.Key7, fyne.Key8, fyne.Key9}
	for i, k := range keys {
		if e.Name == k && i < len(a.macroFiles) {
			a.macroList.Select(widget.ListItemID(i))
		}
	}
}

// ---------------------------------------------------------------------
// Shared-angle sync
// ---------------------------------------------------------------------

func (a *App) toMotorKeyed(byChannel map[int]int) map[int]int {
	out := map[int]int{}
	for n, m := range a.motors {
		if angle, ok := byChannel[m.Channel]; ok {
			out[n] = angle
		}
	}
	return out
}

func (a *App) sharedAsChannelMap() map[int]int {
	angles := a.shared.Snapshot()
	out := map[int]int{}
	for n, m := range a.motors {
		out[m.Channel] = angles[n]
	}
	return out
}

// publishByChannel writes channel-keyed angles into the shared state (macro playback).
func (a *App) publishByChannel(byChannel map[int]int) map[int]int {
	changed := a.toMotorKeyed(byChannel)
	for n, angle := range changed {
		a.shared.Set(n, angle)
	}
	return changed
}

// followSliders makes the slider positions adopt the shared angles (so
// web-page/other-input changes show up).
func (a *App) followSliders() {
	for _, row := range a.motorRows {
		if v, ok := a.shared.Get(row.motor); ok {
			if row.position() != v {
				row.slider.SetValue(float64(v))
			}
			a.prevLocal[row.motor] = v
			row.setText(v)
		}
	}
}

func (a *App) send(commands map[int]int) {
	if mapsEqual(commands, a.lastSent) {
		return
	}
	channels := make([]int, 0, len(commands))
	for ch := range commands {
		channels = append(channels, ch)
	}
	sort.Ints(channels)
	parts := make([]string, len(channels))
	for i, ch := range channels {
		parts[i] = fmt.Sprintf("%d:%d", ch, commands[ch])
	}
	if a.serial != nil {
		a.serial.WriteLine(strings.Join(parts, ","))
	}
	a.lastSent = make(map[int]int, len(commands))
	for ch, v := range commands {
		a.lastSent[ch] = v
	}
}

func mapsEqual(x, y map[int]int) bool {
	if len(x) != len(y) {
		return false
	}
	for k, v := range x {
		if w, ok := y[k]; !ok || w != v {
			return false
		}
	}
	return true
}

// ---------------------------------------------------------------------
// Per-frame update (controller.py's main loop body)
// ---------------------------------------------------------------------

func axisToAngle(value float64, lo, hi int) int {
	if math.Abs(value) < deadzone {
		value = 0
	}
	return int(math.RoundToEven((value+1.0)/2.0*float64(hi-lo) + float64(lo)))
}

func (a *App) joystickCommands() map[int]int {
	js := a.joystick
	js.Update()
	m := a.motors

	m1, m2, m5 := js.Axis(axisMotor1), js.Axis(axisMotor2), js.Axis(axisMotor5)
	m3 := float64(js.HatY(hatMotor3))
	forward, backward := js.Button(buttonMotor4Forward), js.Button(buttonMotor4Backward)
	m4 := 0.0
	if forward && !backward {
		m4 = 1
	} else if backward && !forward {
		m4 = -1
	}
	closeClaw := js.Button(buttonMotor6Close)
	if m[6].Invert {
		closeClaw = !closeClaw
	}
	inv := func(n int, v float64) float64 {
		if m[n].Invert {
			return -v
		}
		return v
	}
	claw := m[6].Min
	if closeClaw {
		claw = m[6].Max
	}
	return map[int]int{
		m[1].Channel: axisToAngle(inv(1, m1), m[1].Min, m[1].Max),
		m[2].Channel: axisToAngle(inv(2, m2), m[2].Min, m[2].Max),
		m[3].Channel: axisToAngle(inv(3, m3), m[3].Min, m[3].Max),
		m[4].Channel: axisToAngle(inv(4, m4), m[4].Min, m[4].Max),
		m[5].Channel: axisToAngle(inv(5, m5), m[5].Min, m[5].Max),
		m[6].Channel: claw,
	}
}

func (a *App) tick() {
	shown := a.statusBase
	if a.remote != nil {
		state := "UNREACHABLE"
		if a.remote.Connected.Load() {
			state = "connected"
		}
		shown = fmt.Sprintf("Remote arm %s: %s", a.opts.Connect, state)
	}
	if shown != a.statusShown {
		a.statusShown = shown
		a.statusLbl.SetText(shown)
	}

	if a.playing {
		elapsed := time.Since(a.playStart).Seconds()
		for a.playIndex < len(a.playSteps) && a.playSteps[a.playIndex].T <= elapsed {
			commands := a.playSteps[a.playIndex].Commands
			a.send(commands)
			changed := a.publishByChannel(commands)
			if a.remote != nil {
				a.shared.Queue(changed)
			}
			a.playIndex++
		}
		if a.mode == ModeSlider {
			a.followSliders()
		}
		a.playBtn.SetText(fmt.Sprintf("Stop %d/%d", a.playIndex, len(a.playSteps)))
		if a.playIndex >= len(a.playSteps) {
			a.stopPlayback()
		}
		return
	}

	if a.mode != a.lastMode {
		a.prevLocal = map[int]int{}
		if a.mode == ModeSlider {
			a.followSliders()
		}
		a.lastMode = a.mode
	}

	var local map[int]int // channel -> angle from this mode's own input, if any
	a.warn = ""

	switch a.mode {
	case ModeJoystick:
		if a.joystick != nil {
			local = a.joystickCommands()
		} else {
			a.warn = "No joystick connected."
		}
	case ModeSlider:
		local = map[int]int{}
		for _, row := range a.motorRows {
			local[a.motors[row.motor].Channel] = row.position()
		}
	case ModeIK:
		if !a.geometry.Ready() {
			a.warn = "Geometry not measured - fill in config.json's \"geometry\" section."
			break
		}
		r := a.ikRows
		x, y, z := r["x"].position(), r["y"].position(), r["z"].position()
		pitch, roll := r["pitch"].position(), r["roll"].position()
		for _, key := range []string{"x", "y", "z", "pitch", "roll"} {
			r[key].setText(r[key].position())
		}
		if sol, ok := inverseKinematics(a.motors, a.geometry, float64(x), float64(y), float64(z), float64(pitch), a.ik.elbowDown); ok {
			cmd := map[int]int{}
			for n, angle := range sol {
				cmd[a.motors[n].Channel] = angle
			}
			cmd[a.motors[5].Channel] = roll
			claw := a.motors[6].Min
			if a.ik.clawClosed {
				claw = a.motors[6].Max
			}
			cmd[a.motors[6].Channel] = claw
			a.lastValidIK = cmd
			local = cmd
		} else {
			local = a.lastValidIK // hold the last good pose
			a.warn = "Target unreachable - holding last valid pose."
		}
	case ModeFleet:
		switch {
		case a.fleetError != "":
			a.warn = a.fleetError
		case a.opts.Connect != "":
			a.warn = "Showing the remote arm's angles."
		default:
			a.warn = fmt.Sprintf("Open http://%s:%d in a browser to control", a.lanIP, a.opts.FleetPort)
			if !a.opts.NoRegister {
				a.warn += fmt.Sprintf("  -  heartbeating to RIFT at %s:%d", a.opts.RiftHost, a.opts.RiftPort)
			}
		}
	}

	// Merge this mode's input into the shared angles, then always send/record the
	// shared state (so web-page and RIFT changes reach the arm in any mode).
	if local != nil {
		localByMotor := a.toMotorKeyed(local)
		if !a.adopted {
			if a.remote.Synced.Load() { // connected: take the hub's state as-is, don't move the arm
				a.prevLocal = localByMotor
				a.adopted = true
			}
		} else {
			changed := a.shared.MergeLocal(&a.prevLocal, localByMotor)
			if a.remote != nil && len(changed) > 0 {
				a.shared.Queue(changed)
			}
		}
		if a.mode == ModeSlider {
			a.followSliders()
		}
	}

	commands := a.sharedAsChannelMap()
	a.send(commands)
	if a.recording {
		cp := make(map[int]int, len(commands))
		for ch, v := range commands {
			cp[ch] = v
		}
		a.recordSteps = append(a.recordSteps, MacroStep{T: time.Since(a.recordStart).Seconds(), Commands: cp})
		a.recordBtn.SetText(fmt.Sprintf("Recording... %.1fs", time.Since(a.recordStart).Seconds()))
	}

	if a.warnText.Text != a.warn {
		a.warnText.Text = a.warn
		a.warnText.Refresh()
	}
	if a.mode == ModeJoystick || a.mode == ModeFleet {
		for i, n := range a.order {
			text := fmt.Sprintf("Motor %d (ch %d): %d", n, a.motors[n].Channel, a.lastSent[a.motors[n].Channel])
			if a.motorLines[i].Text != text {
				a.motorLines[i].SetText(text)
			}
		}
	}
}

func (a *App) run() {
	a.fyneApp = app.NewWithID("io.github.cursedprograms.arm-controller")
	a.win = a.fyneApp.NewWindow("Arm Controller (Go)")
	a.win.SetContent(container.NewPadded(a.buildUI()))
	a.win.Resize(fyne.NewSize(620, 720))
	a.win.Canvas().SetOnTypedKey(a.onKey)

	if a.mode == ModeFleet || a.opts.Serve {
		a.ensureFleetStarted()
		a.statusLbl.SetText(a.statusBase)
	}

	interval := 33 * time.Millisecond
	if a.opts.Rate > 0 {
		interval = time.Duration(float64(time.Second) / a.opts.Rate)
	}
	done := make(chan struct{})
	go func() {
		t := time.NewTicker(interval)
		defer t.Stop()
		for {
			select {
			case <-done:
				return
			case <-t.C:
				fyne.Do(a.tick)
			}
		}
	}()

	a.win.ShowAndRun()
	close(done)
	a.close()
}

func (a *App) close() {
	if a.remote != nil {
		a.remote.Close()
	}
	if a.fleet != nil {
		a.fleet.Close()
	}
	if a.joystick != nil {
		a.joystick.Close()
	}
	if a.serial != nil {
		a.serial.Close()
	}
}
