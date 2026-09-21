package main

// Fleet mode: bridges RIFT's HTTP protocol (https://github.com/CursedPrograms/RIFT)
// to the shared angles, which the UI tick reads each frame and sends over
// serial like any other mode. Also serves the scripts/web/ control page, so the
// arm can be driven from any browser on the network. Same endpoints and wire
// protocol as controller.py's Flask app and the C++ controller's fleet_server.cpp.

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"sync/atomic"
	"time"
)

const (
	fleetName         = "ARM"
	fleetType         = "robot"
	fleetCapabilities = "servo_control,6dof,arm"
	defaultFleetPort  = 5011
	// Must stay under RIFT's FLEET_TTL_SECS (20s).
	fleetHeartbeat = 10 * time.Second
)

type FleetServer struct {
	server *http.Server
	stop   chan struct{}
}

// localLanIP is a best-effort LAN IP, so the UI can show an address RIFT (on
// another device) can reach.
func localLanIP() string {
	conn, err := net.Dial("udp", "8.8.8.8:80") // UDP dial: no traffic is actually sent
	if err != nil {
		return "127.0.0.1"
	}
	defer conn.Close()
	return conn.LocalAddr().(*net.UDPAddr).IP.String()
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func serveWebFile(name, contentType string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		data, err := os.ReadFile(filepath.Join(webDir(), name))
		if err != nil {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", contentType)
		_, _ = w.Write(data)
	}
}

// StartFleetServer starts the HTTP bridge (and RIFT heartbeat if requested).
func StartFleetServer(motors map[int]Motor, shared *Shared, serialConnected *atomic.Bool,
	port int, register bool, riftHost string, riftPort int) (*FleetServer, error) {

	listener, err := net.Listen("tcp", fmt.Sprintf(":%d", port))
	if err != nil {
		return nil, fmt.Errorf("could not start Fleet server on port %d (already in use?): %v", port, err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/{$}", serveWebFile("index.html", "text/html; charset=utf-8"))
	mux.HandleFunc("/style.css", serveWebFile("style.css", "text/css; charset=utf-8"))
	mux.HandleFunc("/app.js", serveWebFile("app.js", "application/javascript; charset=utf-8"))
	mux.HandleFunc("/colour_scheme.xml", func(w http.ResponseWriter, r *http.Request) {
		data, err := os.ReadFile(filepath.Join(repoRoot(), "colour_scheme.xml"))
		if err != nil {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/xml; charset=utf-8")
		_, _ = w.Write(data)
	})
	mux.HandleFunc("/ping", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain")
		fmt.Fprintf(w, "%s alive", fleetName)
	})

	mux.HandleFunc("/status", func(w http.ResponseWriter, r *http.Request) {
		angles := shared.Snapshot()
		out := map[string]any{}
		for n, m := range motors {
			angle, ok := angles[n]
			if !ok {
				angle = m.Rest
			}
			out[strconv.Itoa(n)] = map[string]int{"channel": m.Channel, "angle": angle, "min": m.Min, "max": m.Max}
		}
		writeJSON(w, http.StatusOK, map[string]any{"connected": serialConnected.Load(), "motors": out})
	})

	mux.HandleFunc("/cmd", func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		motor, err1 := strconv.Atoi(q.Get("motor"))
		angle, err2 := strconv.Atoi(q.Get("angle"))
		if err1 != nil || err2 != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "expected ?motor=<1-6>&angle=<degrees>"})
			return
		}
		m, ok := motors[motor]
		if !ok {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": fmt.Sprintf("unknown motor %d", motor)})
			return
		}
		angle = min(max(angle, m.Min), m.Max)
		shared.Set(motor, angle)
		writeJSON(w, http.StatusOK, map[string]int{"motor": motor, "angle": angle})
	})

	mux.HandleFunc("/reset", func(w http.ResponseWriter, r *http.Request) {
		if text := r.URL.Query().Get("motor"); text != "" {
			n, err := strconv.Atoi(text)
			m, ok := motors[n]
			if err != nil || !ok {
				writeJSON(w, http.StatusBadRequest, map[string]string{"error": "unknown motor " + text})
				return
			}
			shared.Set(n, m.Rest)
			writeJSON(w, http.StatusOK, map[string]int{"motor": n, "angle": m.Rest})
			return
		}
		all := map[string]int{}
		for n, m := range motors {
			shared.Set(n, m.Rest)
			all[strconv.Itoa(n)] = m.Rest
		}
		writeJSON(w, http.StatusOK, all)
	})

	fs := &FleetServer{server: &http.Server{Handler: mux}, stop: make(chan struct{})}
	go func() { _ = fs.server.Serve(listener) }()

	if register {
		go func() {
			client := &http.Client{Timeout: 2 * time.Second}
			target := fmt.Sprintf("http://%s:%d/register", riftHost, riftPort)
			form := url.Values{"name": {fleetName}, "type": {fleetType}, "capabilities": {fleetCapabilities}}
			for {
				// RIFT/NORA may not be reachable yet - keep retrying.
				if resp, err := client.PostForm(target, form); err == nil {
					resp.Body.Close()
				}
				select {
				case <-fs.stop:
					return
				case <-time.After(fleetHeartbeat):
				}
			}
		}()
	}
	return fs, nil
}

func (f *FleetServer) Close() {
	close(f.stop)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	_ = f.server.Shutdown(ctx)
}
