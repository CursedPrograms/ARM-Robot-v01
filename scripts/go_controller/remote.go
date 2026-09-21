package main

// Client mode (--connect URL): this controller has no serial port. A goroutine
// mirrors another controller's shared angles (GET /status) into the local
// shared state and pushes local changes back (GET /cmd), so every controller
// and browser pointed at the same arm stays in sync. Same behaviour as
// controller.py's RemoteArm.

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync/atomic"
	"time"
)

type RemoteArm struct {
	base      string
	shared    *Shared
	client    *http.Client
	Connected atomic.Bool
	// Synced is true once we've seen the hub's real angles at least once.
	Synced atomic.Bool
	stop   chan struct{}
}

func StartRemoteArm(baseURL string, shared *Shared) (*RemoteArm, error) {
	base := strings.TrimRight(baseURL, "/")
	if !strings.HasPrefix(base, "http://") {
		return nil, fmt.Errorf("bad --connect URL '%s' (expected http://host:port)", baseURL)
	}
	r := &RemoteArm{base: base, shared: shared, client: &http.Client{Timeout: time.Second}, stop: make(chan struct{})}
	go r.loop()
	return r, nil
}

func (r *RemoteArm) Close() { close(r.stop) }

func (r *RemoteArm) loop() {
	for {
		r.shared.mu.Lock()
		toSend := r.shared.pending
		r.shared.pending = map[int]int{}
		r.shared.mu.Unlock()

		if err := r.roundTrip(toSend); err != nil {
			r.Connected.Store(false)
			r.shared.mu.Lock()
			for n, a := range toSend {
				if _, newer := r.shared.pending[n]; !newer {
					r.shared.pending[n] = a // retry next round
				}
			}
			r.shared.mu.Unlock()
		} else {
			r.Connected.Store(true)
			r.Synced.Store(true)
		}

		select {
		case <-r.stop:
			return
		case <-time.After(100 * time.Millisecond):
		}
	}
}

func (r *RemoteArm) roundTrip(toSend map[int]int) error {
	for n, a := range toSend {
		q := url.Values{"motor": {strconv.Itoa(n)}, "angle": {strconv.Itoa(a)}}
		resp, err := r.client.Get(r.base + "/cmd?" + q.Encode())
		if err != nil {
			return err
		}
		resp.Body.Close()
	}

	resp, err := r.client.Get(r.base + "/status")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	var status struct {
		Motors map[string]struct {
			Angle float64 `json:"angle"`
		} `json:"motors"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&status); err != nil {
		return err
	}

	r.shared.mu.Lock()
	defer r.shared.mu.Unlock()
	for key, m := range status.Motors {
		n, err := strconv.Atoi(key)
		if err != nil {
			continue
		}
		if _, unsent := r.shared.pending[n]; !unsent { // don't overwrite a change we haven't sent yet
			r.shared.angles[n] = int(m.Angle + 0.5)
		}
	}
	return nil
}
