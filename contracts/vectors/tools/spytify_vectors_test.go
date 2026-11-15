// Ground truth from Spytify itself, for contracts/vectors/generate.py.
//
// generate.py --go copies this file into a Spytify 2.0.2 source tree as
// internal/core/spotivault_vectors_test.go and runs it with `go test`. It reads the cases from
// $SPOTIVAULT_VECTORS_IN and writes Spytify's answers to $SPOTIVAULT_VECTORS_OUT:
//   - keys:      Spytify's own trackKey (internal/core/records.go);
//   - settings:  whether settings.Def.Coerce accepts a --set value, and how it normalises it;
//   - examples:  the path naming.Build + naming.FileName give a sample track.
// It's not part of spotivault's build.
package core

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/spytify/spytify/internal/core/naming"
	"github.com/spytify/spytify/internal/settings"
)

type vectorsIn struct {
	Keys []struct {
		Artist string `json:"artist"`
		Title  string `json:"title"`
	} `json:"keys"`
	Settings []struct {
		Key   string `json:"key"`
		Value any    `json:"value"`
	} `json:"settings"`
	Examples []struct {
		GroupBy     string `json:"group_by"`
		Template    string `json:"template"`
		Prefix      string `json:"prefix"`
		Underscores bool   `json:"underscores"`
		ASCII       bool   `json:"ascii_filenames"`
		Extension   string `json:"extension"`
		Counter     int64  `json:"counter"`
		Track       struct {
			Artists      []string `json:"artists"`
			AlbumArtists []string `json:"album_artists"`
			Title        string   `json:"title"`
			Album        string   `json:"album"`
			TrackNumber  int      `json:"track_number"`
			Year         int      `json:"year"`
		} `json:"track"`
	} `json:"examples"`
}

type settingOut struct {
	OK    bool   `json:"ok"`
	Value any    `json:"value"`
	Error string `json:"error"`
}

type vectorsOut struct {
	Keys     []string     `json:"keys"`
	Settings []settingOut `json:"settings"`
	Examples []string     `json:"examples"`
}

func TestSpotivaultVectors(t *testing.T) {
	in, out := os.Getenv("SPOTIVAULT_VECTORS_IN"), os.Getenv("SPOTIVAULT_VECTORS_OUT")
	if in == "" || out == "" {
		t.Skip("SPOTIVAULT_VECTORS_IN and SPOTIVAULT_VECTORS_OUT are not set")
	}
	raw, err := os.ReadFile(in)
	if err != nil {
		t.Fatal(err)
	}
	var v vectorsIn
	if err := json.Unmarshal(raw, &v); err != nil {
		t.Fatal(err)
	}
	res := vectorsOut{Keys: []string{}, Settings: []settingOut{}, Examples: []string{}}
	for _, k := range v.Keys {
		res.Keys = append(res.Keys, trackKey(k.Artist, k.Title))
	}
	for _, s := range v.Settings {
		d, ok := settings.Lookup(s.Key)
		if !ok {
			res.Settings = append(res.Settings, settingOut{Error: "unknown key"})
			continue
		}
		val, err := d.Coerce(s.Value)
		if err != nil {
			res.Settings = append(res.Settings, settingOut{Error: err.Error()})
			continue
		}
		res.Settings = append(res.Settings, settingOut{OK: true, Value: val})
	}
	for _, e := range v.Examples {
		o := naming.Options{
			GroupBy:      settings.GroupBy(e.GroupBy),
			Prefix:       settings.Prefix(e.Prefix),
			Underscores:  e.Underscores,
			Template:     e.Template,
			CounterWidth: 3,
			ASCII:        e.ASCII,
			Extension:    e.Extension,
		}
		tr := naming.Track{
			Artists:      e.Track.Artists,
			AlbumArtists: e.Track.AlbumArtists,
			Title:        e.Track.Title,
			Album:        e.Track.Album,
			TrackNumber:  e.Track.TrackNumber,
			Year:         e.Track.Year,
		}
		p := naming.Build(tr, o)
		res.Examples = append(res.Examples, filepath.ToSlash(filepath.Join(p.Dir, naming.FileName(p, o, e.Counter, e.Track.TrackNumber))))
	}
	b, err := json.MarshalIndent(res, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(out, b, 0o644); err != nil {
		t.Fatal(err)
	}
}
