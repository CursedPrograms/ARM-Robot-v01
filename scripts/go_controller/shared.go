package main

// Shared arm state. Shared.angles is the single set of motor angles every
// input (window sliders, joystick, IK, the web page, RIFT, remote clients)
// writes to and every output (serial, the sliders, the web page) reads from.
//
// The sync rule: an input whose value changed since last frame writes it
// (last writer wins); inputs that didn't change leave what another input wrote
// alone and instead follow it. All maps are keyed by motor number.

import "sync"

type Shared struct {
	mu      sync.Mutex
	angles  map[int]int
	pending map[int]int // client mode only: local changes not yet pushed to the hub
}

func NewShared(angles map[int]int) *Shared {
	cp := make(map[int]int, len(angles))
	for n, a := range angles {
		cp[n] = a
	}
	return &Shared{angles: cp, pending: map[int]int{}}
}

func (s *Shared) Snapshot() map[int]int {
	s.mu.Lock()
	defer s.mu.Unlock()
	cp := make(map[int]int, len(s.angles))
	for n, a := range s.angles {
		cp[n] = a
	}
	return cp
}

func (s *Shared) Set(motor, angle int) {
	s.mu.Lock()
	s.angles[motor] = angle
	s.mu.Unlock()
}

// Step adds delta to motor's angle, kept within [lo, hi], and returns the new angle.
func (s *Shared) Step(motor, delta, lo, hi int) int {
	s.mu.Lock()
	defer s.mu.Unlock()
	a := s.angles[motor] + delta
	if a < lo {
		a = lo
	} else if a > hi {
		a = hi
	}
	s.angles[motor] = a
	return a
}

func (s *Shared) Get(motor int) (int, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	a, ok := s.angles[motor]
	return a, ok
}

// MergeLocal writes every entry of local that differs from *prev into the
// shared angles, remembers local for next frame, and returns what it changed.
func (s *Shared) MergeLocal(prev *map[int]int, local map[int]int) map[int]int {
	changed := map[int]int{}
	s.mu.Lock()
	for n, a := range local {
		if old, ok := (*prev)[n]; !ok || old != a {
			s.angles[n] = a
			changed[n] = a
		}
	}
	s.mu.Unlock()
	next := make(map[int]int, len(local))
	for n, a := range local {
		next[n] = a
	}
	*prev = next
	return changed
}

// Queue records local changes that a client must push to its hub.
func (s *Shared) Queue(changed map[int]int) {
	s.mu.Lock()
	for n, a := range changed {
		s.pending[n] = a
	}
	s.mu.Unlock()
}
