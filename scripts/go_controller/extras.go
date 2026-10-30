package main

// extras.go - what controller.py has beyond driving her: her VOICE (arm_voice.ps1), her arm drawn from
// her geometry and joint maths, and the fleet's WiFi ladder (fleet_ladder.py, with --ladder).

import (
	"fmt"
	"image/color"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/container"
)

const (
	armPanelW     = 300
	voiceCooldown = 8 * time.Second // kit.Voice's: an event at most this often
)

type voiceState struct {
	mode              string
	recording, playing, claw bool
}

type voice struct {
	on   bool
	last map[string]time.Time
	seen *voiceState
}

func newVoice() *voice { return &voice{on: true, last: map[string]time.Time{}} }

func (v *voice) say(event string) {
	if !v.on || time.Since(v.last[event]) < voiceCooldown {
		return
	}
	v.last[event] = time.Now()
	script := filepath.Join(repoRoot(), "scripts", "arm_voice.ps1")
	_ = exec.Command("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", script, event).Start()
}

// watch, once a tick: says what changed, as controller.py's main loop does.
func (v *voice) watch(now voiceState) {
	was := v.seen
	v.seen = &now
	if was == nil {
		v.say("connect")
		return
	}
	if was.mode != now.mode {
		v.say("mode_" + now.mode)
	}
	if was.recording != now.recording {
		v.say(map[bool]string{true: "record_on", false: "record_off"}[now.recording])
	}
	if was.playing != now.playing {
		v.say(map[bool]string{true: "play", false: "stop"}[now.playing])
	}
	if was.claw != now.claw {
		v.say(map[bool]string{true: "claw_close", false: "claw_open"}[now.claw])
	}
}

// startLadder: the fleet's WiFi ladder while she runs (--ladder or FLEET_LADDER=1), as ARMCTL.
func startLadder(asked bool) *exec.Cmd {
	if !asked && os.Getenv("FLEET_LADDER") != "1" {
		return nil
	}
	py := "python3"
	if runtime.GOOS == "windows" {
		py = "python"
	}
	cmd := exec.Command(py, filepath.Join(repoRoot(), "scripts", "fleet_ladder.py"), "ARMCTL", "--run")
	if cmd.Start() != nil {
		return nil
	}
	return cmd
}

// armView is her arm, as controller.py's draw_arm(): from the side, and from above (the base turning).
type armView struct {
	box                *fyne.Container
	segs               [3]*canvas.Line
	joints             [3]*canvas.Circle
	fingers            [2]*canvas.Line
	ring               [72]*canvas.Line // her reach: a ring of short lines, only those inside the panel
	topLine            *canvas.Line
	topTip             *canvas.Circle
	tipText, baseText  *canvas.Text
	last               string
}

func text(s string, col color.Color, x, y float32) *canvas.Text {
	t := canvas.NewText(s, col)
	t.TextSize = 12
	t.Move(fyne.NewPos(x, y))
	return t
}

func setCircle(c *canvas.Circle, x, y, r float32) {
	c.Position1 = fyne.NewPos(x-r, y-r)
	c.Position2 = fyne.NewPos(x+r, y+r)
	c.Refresh()
}

func setLine(l *canvas.Line, x1, y1, x2, y2 float32) {
	l.Position1 = fyne.NewPos(x1, y1)
	l.Position2 = fyne.NewPos(x2, y2)
	l.Refresh()
}

func newArmView() *armView {
	v := &armView{}
	track, knob, accent := schemeColour("track"), schemeColour("button_hover"), schemeColour("accent")
	panel := canvas.NewRectangle(schemeColour("panel"))
	panel.Resize(fyne.NewSize(armPanelW-8, 560))
	desk := canvas.NewLine(track)
	desk.Position1, desk.Position2 = fyne.NewPos(10, 270), fyne.NewPos(armPanelW-18, 270)
	objs := []fyne.CanvasObject{panel, text("from the side", schemeColour("text_dim"), 10, 8), desk}
	for i := range v.ring {
		v.ring[i] = canvas.NewLine(track)
		objs = append(objs, v.ring[i])
	}
	for i := range v.segs {
		v.segs[i] = canvas.NewLine(knob)
		v.segs[i].StrokeWidth = 6
		objs = append(objs, v.segs[i])
	}
	for i := range v.joints {
		v.joints[i] = canvas.NewCircle(accent)
		objs = append(objs, v.joints[i])
	}
	for i := range v.fingers {
		v.fingers[i] = canvas.NewLine(accent)
		v.fingers[i].StrokeWidth = 3
		objs = append(objs, v.fingers[i])
	}
	round := canvas.NewCircle(color.Transparent)
	round.StrokeColor, round.StrokeWidth = track, 1
	setCircle(round, (armPanelW-8)/2, 440, 100)
	v.topLine = canvas.NewLine(knob)
	v.topLine.StrokeWidth = 6
	v.topTip = canvas.NewCircle(accent)
	centre := canvas.NewCircle(accent)
	setCircle(centre, (armPanelW-8)/2, 440, 8)
	v.tipText = text("", schemeColour("text"), 10, 280)
	v.baseText = text("", schemeColour("text"), 10, 544)
	objs = append(objs, text("from above", schemeColour("text_dim"), 10, 315), round, v.topLine, centre, v.topTip, v.tipText, v.baseText)
	v.box = container.NewWithoutLayout(objs...)
	return v
}

func (v *armView) object() fyne.CanvasObject {
	return container.NewGridWrap(fyne.NewSize(armPanelW-8, 560), v.box)
}

func (v *armView) update(motors map[int]Motor, g Geometry, angles map[int]int) {
	key := fmt.Sprint(angles)
	if key == v.last {
		return
	}
	v.last = key
	deg := func(n int) float64 {
		m := motors[n]
		a, ok := angles[n]
		if !ok {
			a = m.Rest
		}
		return float64(a-m.Rest) * m.KinematicSign * math.Pi / 180
	}
	base, sh, el, wr := deg(1), deg(2), deg(3), deg(4)
	reach := g.UpperArm + g.Forearm + g.Wrist
	if reach <= 0 {
		reach = 300
	}
	s := math.Min((armPanelW-68)/reach, 230/(reach+g.BaseHeight))
	pt := func(r, z float64) (float32, float32) { return float32(30 + r*s), float32(270 - z*s) }
	cx, cy := pt(0, g.BaseHeight)
	for i, seg := range v.ring {
		a1, a2 := 2*math.Pi*float64(i)/72, 2*math.Pi*float64(i+1)/72
		x1, y1 := cx+float32(reach*s*math.Cos(a1)), cy+float32(reach*s*math.Sin(a1))
		x2, y2 := cx+float32(reach*s*math.Cos(a2)), cy+float32(reach*s*math.Sin(a2))
		if x1 < 0 || x2 < 0 || x1 > armPanelW-8 || x2 > armPanelW-8 || y1 < 24 || y2 < 24 || y1 > 300 || y2 > 300 {
			seg.Hide()
			continue
		}
		seg.Show()
		setLine(seg, x1, y1, x2, y2)
	}
	a := [3]float64{sh, sh + el, sh + el + wr}
	l := [3]float64{g.UpperArm, g.Forearm, g.Wrist}
	r, z := 0.0, g.BaseHeight
	for i := range v.segs {
		x1, y1 := pt(r, z)
		r += l[i] * math.Cos(a[i])
		z += l[i] * math.Sin(a[i])
		x2, y2 := pt(r, z)
		setLine(v.segs[i], x1, y1, x2, y2)
		setCircle(v.joints[i], x2, y2, 6)
	}
	tx, ty := pt(r, z)
	open := 0.5
	if c, ok := angles[6]; ok && c < motors[6].Rest {
		open = 0.25
	}
	for i, sgn := range []float64{-1, 1} {
		f := a[2] + sgn*open
		setLine(v.fingers[i], tx, ty, tx+float32(14*math.Cos(f)), ty-float32(14*math.Sin(f)))
	}
	rr := r * 100 / reach
	x, y := float32(rr*math.Sin(base)), float32(rr*math.Cos(base))
	setLine(v.topLine, (armPanelW-8)/2, 440, (armPanelW-8)/2+x, 440-y)
	setCircle(v.topTip, (armPanelW-8)/2+x, 440-y, 5)
	v.tipText.Text = fmt.Sprintf("tip  r %.0f  z %.0f mm", r, z)
	v.tipText.Refresh()
	v.baseText.Text = fmt.Sprintf("base %+.0f deg", base*180/math.Pi)
	v.baseText.Refresh()
}
