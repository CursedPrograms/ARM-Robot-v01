package main

import (
	"reflect"
	"testing"
)

func TestFirstFrameWritesEverything(t *testing.T) {
	s := NewShared(map[int]int{1: 135, 2: 50})
	prev := map[int]int{}
	changed := s.MergeLocal(&prev, map[int]int{1: 100, 2: 50})
	if !reflect.DeepEqual(s.Snapshot(), map[int]int{1: 100, 2: 50}) {
		t.Fatalf("shared = %v", s.Snapshot())
	}
	if !reflect.DeepEqual(changed, map[int]int{1: 100, 2: 50}) {
		t.Fatalf("changed = %v", changed)
	}
}

func TestUntouchedInputsLeaveRemoteChangesAlone(t *testing.T) {
	s := NewShared(map[int]int{1: 135, 2: 50})
	prev := map[int]int{1: 135, 2: 50}
	s.Set(1, 140) // the phone moves motor 1
	changed := s.MergeLocal(&prev, map[int]int{1: 135, 2: 50})
	if a, _ := s.Get(1); a != 140 || len(changed) != 0 {
		t.Fatalf("motor 1 = %d, changed = %v", a, changed)
	}
}

func TestAMovedInputWins(t *testing.T) {
	s := NewShared(map[int]int{1: 140, 2: 50})
	prev := map[int]int{1: 135, 2: 50}
	changed := s.MergeLocal(&prev, map[int]int{1: 135, 2: 80})
	if !reflect.DeepEqual(s.Snapshot(), map[int]int{1: 140, 2: 80}) {
		t.Fatalf("shared = %v", s.Snapshot())
	}
	if !reflect.DeepEqual(changed, map[int]int{2: 80}) {
		t.Fatalf("changed = %v", changed)
	}
}
