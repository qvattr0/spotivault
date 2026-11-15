// Command spotivault-controller is a throwaway stub of the controller, for the S2 container work
// only. The real controller replaces it in S4 (its stack is decided at Gate A).
//
// It serves:
//   - GET /api/health: the container's health check;
//   - GET /vnc.html: a full-screen view of the client's screen, with noVNC's core bundled in;
//   - WS /vnc: a bridge to the VNC server on 127.0.0.1:5900, so only port 8080 is published.
package main

import (
	"context"
	"embed"
	"encoding/json"
	"errors"
	"io"
	"io/fs"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/coder/websocket"
)

//go:embed web
var web embed.FS

const (
	listenAddr = ":8080"
	vncAddr    = "127.0.0.1:5900"
	spotifyBin = "/config/spotify/current/spotify"
)

func main() {
	log.SetFlags(0)
	root, err := fs.Sub(web, "web")
	if err != nil {
		log.Fatal(err)
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/health", health)
	mux.HandleFunc("GET /vnc", bridge)
	mux.Handle("GET /", http.FileServerFS(root))

	srv := &http.Server{Addr: listenAddr, Handler: mux, ReadHeaderTimeout: 10 * time.Second}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, os.Interrupt)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = srv.Shutdown(shutdown)
	}()
	log.Printf("stub controller listening on %s", listenAddr)
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}

// health answers 200 while the controller runs, with what it can see of the rest.
func health(w http.ResponseWriter, _ *http.Request) {
	_, err := os.Stat(spotifyBin)
	installed := err == nil
	vnc := false
	if c, err := net.DialTimeout("tcp", vncAddr, time.Second); err == nil {
		vnc = true
		c.Close()
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"status":            "ok",
		"stub":              true,
		"vnc":               vnc,
		"spotify_installed": installed,
	})
}

// bridge copies bytes both ways between a WebSocket and the VNC server.
func bridge(w http.ResponseWriter, r *http.Request) {
	// Accept checks that the page came from this same host, so another site can't open the screen.
	ws, err := websocket.Accept(w, r, &websocket.AcceptOptions{Subprotocols: []string{"binary"}})
	if err != nil {
		return
	}
	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()
	vnc, err := net.DialTimeout("tcp", vncAddr, 5*time.Second)
	if err != nil {
		log.Printf("vnc: %v", err)
		ws.Close(websocket.StatusTryAgainLater, "the screen isn't running yet")
		return
	}
	defer vnc.Close()
	conn := websocket.NetConn(ctx, ws, websocket.MessageBinary)
	defer conn.Close()
	log.Printf("vnc: viewer connected from %s", r.RemoteAddr)
	done := make(chan struct{}, 2)
	go func() { _, _ = io.Copy(vnc, conn); done <- struct{}{} }()
	go func() { _, _ = io.Copy(conn, vnc); done <- struct{}{} }()
	<-done
	log.Printf("vnc: viewer from %s left", r.RemoteAddr)
}
