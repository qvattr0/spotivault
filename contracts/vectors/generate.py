#!/usr/bin/env python3
"""Build and check spotivault's language-neutral test vectors (contracts/vectors/*.json).

Usage, from the repository root:

    python3 contracts/vectors/generate.py
        Check mode (CI). Recomputes every expected value from the inputs stored in each JSON
        file and fails on any difference. Needs only Python 3.11+ and the repo.

    python3 contracts/vectors/generate.py --write [--recorded FILE] [--runs DIR] [--go DIR]
        Rewrites the four files.
        --recorded  Spytify's duplicate index from the prototype (gitignored):
                    prototype/data/music/.spytify/recorded.jsonl
        --runs      the prototype's probe run logs, used to find each index line's original
                    artist and title by file path: prototype/data/config/probe/runs
                    Without both, the recorded cases already in track-keys.json are kept.
        --go        a Spytify 2.0.2 source tree. Runs tools/spytify_vectors_test.go in Docker
                    (golang:1.26) to get Spytify's own answers: its trackKey for every key case,
                    whether it accepts each layout's --set values, and the example paths its
                    naming code gives. Without it, the Spytify-derived fields already in the
                    files are kept.

Where expected values come from:
    track-keys.json         track_key / web_track_key from prototype/probe.py (as the M1 plan asks),
                            cross-checked against Spytify's Go trackKey and, for the recorded cases,
                            against the key Spytify wrote to its index.
    layouts.json            validate_layout / spytify_settings below: web-ui.md § Edit layout modal's
                            rules, plus three rules Spytify 2.0.2 forces (marked "extra"). Example
                            paths and Spytify's verdicts come from Spytify's Go code.
    schedule-windows.json   windows / next_windows below: web-ui.md § Schedule rules, plus the DST
                            rule stated in the file.
    backlog.json            backlog below: design.md § Backlog estimate with the M1 plan's D13.
"""

import argparse
import datetime as dt
import glob
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
GENERATOR = "contracts/vectors/generate.py"


def load_probe():
    spec = importlib.util.spec_from_file_location("probe", os.path.join(REPO, "prototype", "probe.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


probe = load_probe()


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return json.load(f)


def write(name, doc):
    with open(os.path.join(HERE, name), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ============================================================================== track keys

EDGE_KEY_CASES = [
    ("edge-dotted-capital-i", "İstanbul Trio", "İnce", "U+0130 lowercases to plain 'i' in Go; Python's lower() gives 'i' + U+0307."),
    ("edge-final-sigma", "ΟΔΥΣΣΕΑΣ", "ΧΟΡΟΣ", "A final capital sigma lowercases to σ in Go; Python's lower() gives ς at the end of a word."),
    ("edge-sigma-mid-and-final", "Σ Σ", "ΣΑΣ", "Every Σ becomes σ, wherever it is."),
    ("edge-unit-separators-kept", "\u001cArtist\u001d", "\u001eTitle\u001f", "U+001C–U+001F are not white space to Go's TrimSpace, so they stay; Python's strip() removes them."),
    ("edge-nbsp-trimmed", " Artist ", " Title ", "NBSP (U+00A0) is white space to Go and is trimmed."),
    ("edge-ideographic-space-trimmed", "　Artist　", "　Title　", "Ideographic space (U+3000) is trimmed."),
    ("edge-nel-and-ascii-space", " \t\u0085Artist \n", "\r\u000bTitle\u000c ", "ASCII white space and NEL (U+0085) are trimmed."),
    ("edge-inner-space-kept", "Artist  Name", "Title Two", "Only the ends are trimmed; inner spaces, NBSP included, stay."),
    ("edge-no-normalization", "Beyoncé", "Café", "No Unicode normalization: a combining accent and a precomposed é stay as they are."),
    ("edge-feat-kept", "Daft Punk", "Get Lucky (feat. Pharrell Williams) - Radio Edit", "No stripping of 'feat.' or ' - Radio Edit'."),
    ("edge-empty-artist", "", "Untitled", "No artist: the key starts with the separator."),
    ("edge-sharp-s", "STRASSE", "ẞ", "Capital sharp s (U+1E9E) lowercases to ß."),
    ("edge-turkish-dotless-i", "I", "ı", "Plain I lowercases to i; dotless ı stays."),
]

WEB_KEY_CASES = [
    ("web-multi-artist", ["Erik Satie", "Olga Scheps"], "Cinq Grimaces pour le songe d'une nuit d'été: IV. Fanfaronnade",
     "Only the first artist counts: Spotify's MPRIS xesam:artist holds just one name."),
    ("web-remaster-title", ["David Bowie"], "Ashes to Ashes - 2017 Remaster", "The title is the Web API name, character for character."),
    ("web-no-artists", [], "Track With No Artist", "An empty artist list gives an empty artist."),
    ("web-padded", ["  ZØMB  "], "  I'M A STAR!  ", "Trimmed and lowercased like the event's artist and title."),
]


def recorded_cases(recorded_path, runs_dir):
    """Every line of Spytify's index, with the artist and title it was keyed from.

    The index only has the key and the path, so the original artist and title come from the probe
    run logs: track.finished and track.skipped name the path, and their take id leads back to the
    take's track.started. That join never uses track_key, so the check below is a real test."""
    by_path = {}
    for f in sorted(glob.glob(os.path.join(runs_dir, "*.json"))):
        with open(f, encoding="utf-8") as fh:
            run = json.load(fh)
        started = {}
        for e in run.get("events", []):
            p = e.get("params") or {}
            if e.get("method") == "track.started":
                started[p.get("id")] = (p.get("artist"), p.get("title"))
            elif e.get("method") in ("track.finished", "track.skipped") and p.get("path") and p.get("id") in started:
                by_path.setdefault(p["path"], started[p["id"]])
    cases, pending = [], []
    with open(recorded_path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry["Path"] not in by_path:
                # A recording whose probe run log isn't saved yet (S0 appends to the index live).
                pending.append({"line": n, "spytify_index_key": entry["Key"], "path": entry["Path"]})
                continue
            artist, title = by_path[entry["Path"]]
            cases.append({
                "id": f"recorded-{n:02d}",
                "source": f"prototype/data/music/.spytify/recorded.jsonl line {n}",
                "artist": artist,
                "title": title,
                "spytify_index_key": entry["Key"],
            })
    return cases, pending


def track_key_doc(old, recorded, go_keys, pending=None):
    cases = []
    if recorded is None:
        recorded = [{k: c[k] for k in ("id", "source", "artist", "title", "spytify_index_key")}
                    for c in old["cases"] if c["id"].startswith("recorded-")]
        pending = old.get("recorded_lines_pending", [])
    cases += recorded
    for cid, artist, title, note in EDGE_KEY_CASES:
        cases.append({"id": cid, "artist": artist, "title": title, "note": note})
    for c in cases:
        c["expected"] = probe.track_key(c["artist"], c["title"])
    web = []
    for cid, artists, name, note in WEB_KEY_CASES:
        web.append({"id": cid, "artists": artists, "name": name, "note": note,
                    "expected": probe.web_track_key({"artists": artists, "name": name})})
    if go_keys is not None:
        flat = [(c["artist"], c["title"]) for c in cases] + [((w["artists"] or [""])[0], w["name"]) for w in web]
        for (a, t), got, case in zip(flat, go_keys, cases + web):
            if got != case["expected"]:
                raise SystemExit(f"{case['id']}: probe.py gives {case['expected']!r}, Spytify's trackKey gives {got!r}")
        go_note = "Every expected key was also produced by Spytify 2.0.2's own trackKey (tools/spytify_vectors_test.go), and matched."
    else:
        go_note = old["generator"]["cross_checks"][1] if old else "Not cross-checked against Go yet."
    for c in cases:
        if "spytify_index_key" in c and c["spytify_index_key"] != c["expected"]:
            raise SystemExit(f"{c['id']}: probe.py gives {c['expected']!r}, the index has {c['spytify_index_key']!r}")
    return {
        "about": "Spytify's duplicate key (internal/core/records.go trackKey): lower(trim(artist)) + U+001F + lower(trim(title)), with Go's strings.ToLower and strings.TrimSpace. The controller matches the Web API's artists[0].name and name against Spytify's index with it.",
        "generator": {
            "script": GENERATOR,
            "how": "expected = track_key(artist, title), and for web_cases web_track_key({artists, name}), both from prototype/probe.py, which mirror Go's rules (go_lower, go_trim). The recorded cases are every line of the prototype's recorded.jsonl; their artist and title were recovered from the probe run logs by file path.",
            "cross_checks": [
                "Each recorded case's expected key equals spytify_index_key, the key Spytify itself wrote to its index.",
                go_note,
            ],
            "regenerate": "python3 contracts/vectors/generate.py --write --recorded prototype/data/music/.spytify/recorded.jsonl --runs prototype/data/config/probe/runs --go <spytify-2.0.2-src>",
        },
        "rules": [
            "Trim: Go's unicode.IsSpace at both ends: \\t \\n \\v \\f \\r, space, U+0085, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000. Not U+001C–U+001F.",
            "Lower: per rune, Unicode simple case mapping. U+0130 İ → i; Σ → σ everywhere (no final-sigma rule).",
            "No normalization (no NFC), and nothing stripped from titles.",
            "Join: artist + U+001F + title.",
            "From the Web API: artist = artists[0].name, or '' when there are none; title = name.",
        ],
        "cases": cases,
        "web_cases": web,
        "recorded_lines_pending": pending or [],
        "recorded_lines_pending_note": "Index lines with no probe run log yet, so their original artist and title can't be recovered. S0 was recording while this file was generated; run the regenerate command again once its run logs are saved.",
    }


def check_track_keys(doc):
    errors = []
    for c in doc["cases"]:
        got = probe.track_key(c["artist"], c["title"])
        if got != c["expected"]:
            errors.append(f"{c['id']}: expected {c['expected']!r}, got {got!r}")
        if "spytify_index_key" in c and c["spytify_index_key"] != c["expected"]:
            errors.append(f"{c['id']}: expected {c['expected']!r} differs from Spytify's index key")
    for w in doc["web_cases"]:
        got = probe.web_track_key({"artists": w["artists"], "name": w["name"]})
        if got != w["expected"]:
            errors.append(f"{w['id']}: expected {w['expected']!r}, got {got!r}")
    return errors


# ============================================================================== layouts

PLACEHOLDERS = ("album_artist", "artists", "title", "album", "track", "year")
NAMING = ("album_artist", "artists", "title", "album", "track")  # Spytify's "needs at least one of"
FOLDERS = {"{album_artist}": "artist", "{album_artist}/{album}": "artist/album"}
PREFIX = {"none": "none", "counter": "counter", "track_number": "album_track"}
BRACED = re.compile(r"\{[^{}]*\}")

REASONS = [
    ("unknown_placeholder", "web-ui.md: only {album_artist}, {artists}, {title}, {album}, {track} and {year} are accepted. Spytify's old name {artist} is refused too. details.placeholder names the first one."),
    ("stray_brace", "extra: a { or } that isn't part of a placeholder. Spytify would keep it as text; refused as a likely typo."),
    ("backslash", "extra: Spytify refuses a template with \\ ('folders come from output.group_by')."),
    ("bad_folder", "web-ui.md: the folder part, before the last /, must be none, {album_artist} or {album_artist}/{album}, exactly."),
    ("empty_file_name", "web-ui.md: the file name, after the last /, can't be empty or only spaces."),
    ("no_placeholder", "extra: Spytify refuses a template with no placeholder; {year} alone doesn't count, since it's always empty on Linux."),
]


def validate_layout(pattern):
    """Return (reason, placeholder) for the first rule that fails, in REASONS order, or (None, None)."""
    for m in BRACED.findall(pattern):
        if m[1:-1] not in PLACEHOLDERS:
            return "unknown_placeholder", m
    if "{" in BRACED.sub("", pattern) or "}" in BRACED.sub("", pattern):
        return "stray_brace", None
    if "\\" in pattern:
        return "backslash", None
    folder, sep, name = pattern.rpartition("/")
    if sep and folder not in FOLDERS:
        return "bad_folder", None
    if not name.strip():
        return "empty_file_name", None
    if not any(m[1:-1] in NAMING for m in BRACED.findall(name)):
        return "no_placeholder", None
    return None, None


def spytify_settings(layout):
    folder, sep, name = layout["pattern"].rpartition("/")
    return {
        "output.group_by": FOLDERS[folder] if sep else "none",
        "output.template": name,
        "output.prefix": PREFIX[layout["prefix"]],
        "output.underscores": layout["underscores"],
        "output.ascii_filenames": layout["strip_accents"],
    }


def L(pattern, prefix="none", underscores=False, strip_accents=False):
    return {"pattern": pattern, "prefix": prefix, "underscores": underscores, "strip_accents": strip_accents}


LAYOUT_CASES = [
    ("default", L("{album_artist}/{album}/{track} - {title}"), "The default layout."),
    ("default-track-number-prefix", L("{album_artist}/{album}/{title}", prefix="track_number"), "Prefix 'Album track number' maps to Spytify's album_track."),
    ("artist-folder-counter", L("{album_artist}/{title}", prefix="counter"), "One folder per artist; a three-digit counter before the name."),
    ("no-folder", L("{artists} - {title}"), "No folder: every file in the music folder's root."),
    ("underscores", L("{album_artist}/{album}/{track} - {title}", underscores=True), "Spaces become underscores in folders and names."),
    ("strip-accents", L("{album_artist}/{album}/{track} - {title}", strip_accents=True), "Accents are removed from folders and names."),
    ("old-prototype-naming", L("{album_artist}/{album}/{album_artist} - {title}"), "The prototype's first naming."),
    ("year-empty", L("{album_artist}/{album}/{title} ({year})"), "{year} is always empty on Linux, and Spytify drops the empty ()."),
    ("trailing-space", L("{album_artist}/{album}/{track} - {title} "), "Spytify trims the expanded name."),
    ("album-in-name", L("{album} - {track} - {title}"), "{album} can be used in the file name."),
    ("unknown-genre", L("{album_artist}/{genre}"), None),
    ("unknown-capitalised", L("{album_artist}/{album}/{Title}"), "Placeholders are case-sensitive."),
    ("unknown-old-artist", L("{artist} - {title}"), "Spytify accepts {artist} as {album_artist}'s old name; the UI doesn't offer it."),
    ("unknown-with-spaces", L("{ title }"), None),
    ("stray-open", L("{album_artist}/{title"), None),
    ("stray-close", L("{title}}"), None),
    ("backslash-in-name", L("{album_artist}/{album}/{track}\\{title}"), None),
    ("folder-album-only", L("{album}/{title}"), None),
    ("folder-three-levels", L("{album_artist}/{album}/{track}/{title}"), None),
    ("folder-all-artists", L("{artists}/{title}"), "Spytify can group by all artists; the UI doesn't offer it."),
    ("folder-leading-slash", L("/{title}"), "A slash with nothing before it is a folder part that isn't allowed."),
    ("folder-spaced", L("{album_artist} /{album}/{title}"), "The folder part must match exactly."),
    ("empty", L(""), None),
    ("empty-file-name", L("{album_artist}/"), None),
    ("blank-file-name", L("{album_artist}/{album}/   "), None),
    ("no-placeholder", L("{album_artist}/{album}/Track"), None),
    ("year-only", L("{album_artist}/{album}/{year}"), None),
]

SAMPLE_TRACKS = {
    "elsewhere": {"artists": ["fakename"], "album_artists": ["fakename"], "title": "Last Hours", "album": "Elsewhere", "track_number": 5, "year": 0},
    "collaboration": {"artists": ["Erik Satie", "Olga Scheps"], "album_artists": ["Erik Satie"],
                      "title": "Cinq Grimaces pour le songe d'une nuit d'été: IV. Fanfaronnade", "album": "Satie: Gymnopédies", "track_number": 10, "year": 0},
    "no-number": {"artists": ["fakename"], "album_artists": ["fakename"], "title": "No Number", "album": "Singles", "track_number": 0, "year": 0},
}


def layout_doc(old, go):
    """go: dict of Spytify-derived answers keyed by case id, or None to keep the old ones."""
    old_by_id = {c["id"]: c for c in old["cases"]} if old else {}
    cases = []
    for cid, layout, note in LAYOUT_CASES:
        reason, placeholder = validate_layout(layout["pattern"])
        c = {"id": cid, "layout": layout}
        if note:
            c["note"] = note
        if reason:
            c["expected"] = {"valid": False, "reason": reason}
            if placeholder:
                c["expected"]["placeholder"] = placeholder
        else:
            c["expected"] = {"valid": True, "spytify_settings": spytify_settings(layout)}
        src = go.get(cid) if go is not None else old_by_id.get(cid, {}).get("spytify")
        if src:
            c["spytify"] = src
        cases.append(c)
    return {
        "about": "Settings › Files › Edit layout: which layouts are valid, the error each invalid one gets (PUT /api/settings → 422 invalid_layout, details.reason), and the Spytify --set values a valid one maps to.",
        "generator": {
            "script": GENERATOR,
            "how": "expected = validate_layout and spytify_settings in generate.py, which encode the rules below. Cases get a 'spytify' block only when the file is generated with --go: Spytify 2.0.2's own code, run by tools/spytify_vectors_test.go, gives 'accepts' (settings.Def.Coerce on every mapped --set value), 'template_error' (Coerce's error for an invalid layout's file name) and 'examples' (naming.Build + naming.FileName for sample_tracks, counter 1, extension m4a). Check mode recomputes 'expected' only.",
            "regenerate": "python3 contracts/vectors/generate.py --write --go <spytify-2.0.2-src>",
        },
        "rules": [
            "Split the pattern at its last '/': the folder part before it, the file name after it. No '/' means no folder.",
            "Validation runs these checks in order and reports the first that fails:",
            *[f"{r}: {why}" for r, why in REASONS],
            "Mapping: folder none → output.group_by=none; {album_artist} → artist; {album_artist}/{album} → artist/album. output.template = the file name, unchanged. prefix none/counter/track_number → output.prefix none/counter/album_track. underscores → output.underscores. strip_accents → output.ascii_filenames.",
            "Spytify's naming then: {track} is two digits and empty without a number; {year} is empty (none on Linux); empty () is dropped and the name trimmed of ' -_'; characters / \\ : * ? \" < > | and controls are removed; the album folder gets ' (YYYY)' only if the player sends a year.",
            "The counter prefix is three digits ('001 ') and continues across items (Spytify's output.counter_next).",
        ],
        "extra_rules_note": "stray_brace, backslash and no_placeholder aren't in web-ui.md § Edit layout modal yet. They're the cautious reading: backslash and no_placeholder would make Spytify refuse its settings at the start of every item (exit 2). web-ui.md should list them.",
        "sample_tracks": SAMPLE_TRACKS,
        "cases": cases,
    }


def check_layouts(doc):
    errors = []
    for c in doc["cases"]:
        reason, placeholder = validate_layout(c["layout"]["pattern"])
        if reason:
            want = {"valid": False, "reason": reason}
            if placeholder:
                want["placeholder"] = placeholder
        else:
            want = {"valid": True, "spytify_settings": spytify_settings(c["layout"])}
        if want != c["expected"]:
            errors.append(f"{c['id']}: expected {c['expected']}, recomputed {want}")
        sp = c.get("spytify")
        if sp and c["expected"]["valid"] and not sp.get("accepts"):
            errors.append(f"{c['id']}: Spytify refused a layout we call valid: {sp}")
    return errors


def go_layout_requests():
    settings, examples, index = [], [], []
    for cid, layout, _ in LAYOUT_CASES:
        reason, _p = validate_layout(layout["pattern"])
        if reason is None:
            m = spytify_settings(layout)
            s0 = len(settings)
            settings += [{"key": k, "value": v} for k, v in m.items()]
            e0 = len(examples)
            for name, tr in SAMPLE_TRACKS.items():
                examples.append({"group_by": m["output.group_by"], "template": m["output.template"], "prefix": m["output.prefix"],
                                 "underscores": m["output.underscores"], "ascii_filenames": m["output.ascii_filenames"],
                                 "extension": "m4a", "counter": 1, "track": tr})
            index.append((cid, "valid", s0, len(settings), e0, len(examples)))
        elif reason in ("backslash", "no_placeholder", "stray_brace", "unknown_placeholder"):
            name = layout["pattern"].rpartition("/")[2]
            s0 = len(settings)
            settings.append({"key": "output.template", "value": name})
            index.append((cid, "template", s0, s0 + 1, None, None))
    return settings, examples, index


def go_layout_answers(index, settings_out, examples_out):
    out = {}
    names = list(SAMPLE_TRACKS)
    for cid, kind, s0, s1, e0, e1 in index:
        res = settings_out[s0:s1]
        if kind == "valid":
            out[cid] = {"accepts": all(r["ok"] for r in res),
                        "examples": {names[i]: "Music/" + p for i, p in enumerate(examples_out[e0:e1])}}
        else:
            r = res[0]
            out[cid] = {"template_accepted": r["ok"], "template_error": r["error"] or None,
                        "template_saved_as": r["value"] if r["ok"] else None}
    return out


# ============================================================================== schedule windows

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def parse_time(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def fmt_local(t, tz):
    return t.astimezone(tz).isoformat(timespec="seconds")


def fmt_utc(t):
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def grid(hours):
    """168 booleans, Monday 00:00 first."""
    g = [False] * 168
    for d, day in enumerate(DAYS):
        for h in hours.get(day, []):
            g[d * 24 + h] = True
    return g


def weekly_windows(hours):
    """Contiguous active hours, wrapping from Sunday 23:00 to Monday 00:00."""
    g = grid(hours)
    if not any(g):
        return [], False
    if all(g):
        return [{"start_day": "mon", "start_hour": 0, "hours": 168}], True
    out = []
    for j in range(168):
        if g[j] and not g[j - 1]:  # a block starts here; g[-1] is Sunday 23:00
            n = 0
            while g[(j + n) % 168]:
                n += 1
            out.append({"start_day": DAYS[j // 24], "start_hour": j % 24, "hours": n})
    out.sort(key=lambda w: (DAYS.index(w["start_day"]), w["start_hour"]))
    return out, False


def resolve(naive, tz):
    """A local wall-clock time to an instant. fold=0: a time in the spring-forward gap moves forward by
    the gap (02:00 → 03:00), and a repeated time on fall-back night takes its first occurrence."""
    return naive.replace(tzinfo=tz, fold=0).astimezone(dt.timezone.utc)


def window_instances(hours, tz, now, limit=None, horizon_days=21):
    """Concrete windows whose end is after now, in order: [(start, end)] as UTC instants."""
    weekly, continuous = weekly_windows(hours)
    if not weekly:
        return []
    if continuous:
        return [(now, None)]
    local_now = now.astimezone(tz).replace(tzinfo=None)
    monday = (local_now - dt.timedelta(days=local_now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for week in range(-1, horizon_days // 7 + 2):
        base = monday + dt.timedelta(weeks=week)
        for w in weekly:
            s_naive = base + dt.timedelta(days=DAYS.index(w["start_day"]), hours=w["start_hour"])
            e_naive = s_naive + dt.timedelta(hours=w["hours"])
            s, e = resolve(s_naive, tz), resolve(e_naive, tz)
            if e <= s or e <= now:
                continue
            out.append((s, e))
    out.sort()
    return out[:limit] if limit else out


def schedule_expected(hours, tz_name, now_s):
    tz = ZoneInfo(tz_name)
    now = parse_time(now_s)
    weekly, continuous = weekly_windows(hours)
    inst = window_instances(hours, tz, now, limit=3)
    return {
        "windows_per_week": len(weekly),
        "hours_per_week": sum(grid(hours)),
        "continuous": continuous,
        "weekly_windows": weekly,
        "in_window": bool(inst) and inst[0][0] <= now,
        "next_windows": [{"start": fmt_local(s, tz), "end": fmt_local(e, tz) if e else None,
                          "hours": round((e - s).total_seconds() / 3600, 3) if e else None} for s, e in inst],
    }


def H(**days):
    """Hours helper: H(mon=range(1, 7)) → the full seven-day dict."""
    return {d: sorted(days.get(d, [])) for d in DAYS}


EVERY = {d: list(range(1, 7)) for d in DAYS[:5]}
NIGHTLY = H(**EVERY, sat=range(0, 9), sun=range(0, 9))

SCHEDULE_CASES = [
    ("manual-only", H(), "Europe/Berlin", "2026-11-15T10:00:00Z", "No active hours: Manual only, no windows."),
    ("nightly-web-ui-example", NIGHTLY, "Europe/Berlin", "2026-11-11T12:00:00Z",
     "web-ui.md's example grid, 'Mon–Fri 01:00–07:00 · Sat–Sun 00:00–09:00'. That's 48 h in 7 windows; web-ui.md's '44 h a week' is a slip."),
    ("across-midnight", H(mon=[23], tue=[0]), "Europe/Berlin", "2026-11-09T12:00:00Z", "Mon 23:00 and Tue 00:00 are one window, 23:00–01:00 (web-ui.md's example)."),
    ("sunday-to-monday", H(sun=[22, 23], mon=[0, 1]), "Europe/Berlin", "2026-11-12T12:00:00Z", "The week wraps: Sun 22:00–Mon 02:00 is one window."),
    ("every-night-across-midnight", {d: [0, 23] for d in DAYS}, "Europe/Berlin", "2026-11-15T21:30:00Z",
     "23:00 and the next day's 00:00 join every night, the Sunday one wrapping to Monday: 7 windows of 2 h."),
    ("two-blocks-one-day", H(mon=[1, 2, 3, 20, 21]), "UTC", "2026-11-09T00:30:00Z", "Two separate blocks on one day are two windows."),
    ("now-inside-window", NIGHTLY, "Europe/Berlin", "2026-11-12T02:30:00Z", "Now is inside Thu 01:00–07:00: it's the first next window, already started."),
    ("now-at-window-start", NIGHTLY, "Europe/Berlin", "2026-11-12T00:00:00Z", "Now is exactly a window's start (01:00 local): that window is in progress."),
    ("now-at-window-end", NIGHTLY, "Europe/Berlin", "2026-11-12T06:00:00Z", "Now is exactly a window's end (07:00 local): that window is over and not listed."),
    ("continuous", {d: list(range(24)) for d in DAYS}, "Europe/Berlin", "2026-11-15T10:20:00Z",
     "Every hour active: one window that never ends. next_windows has one entry starting now, with no end."),
    ("dst-spring-forward-short-window", H(sun=[1, 2, 3]), "Europe/Berlin", "2026-03-27T12:00:00Z",
     "29 Mar 2026: 02:00 doesn't exist. The 01:00–04:00 window is 2 real hours."),
    ("dst-spring-forward-window-in-gap", H(sun=[2]), "Europe/Berlin", "2026-03-27T12:00:00Z",
     "A window made only of the missing 02:00 hour has no length that night and is skipped; the next Sunday has it."),
    ("dst-fall-back-long-window", H(sun=[1, 2, 3]), "Europe/Berlin", "2026-10-23T12:00:00Z",
     "25 Oct 2026: 02:00–03:00 happens twice. The 01:00–04:00 window is 4 real hours: the 02:00 cell covers both."),
    ("dst-fall-back-overnight", H(sat=[23], sun=[0, 1, 2, 3, 4]), "Europe/Berlin", "2026-10-23T12:00:00Z",
     "Sat 23:00–Sun 05:00 across the change: 7 real hours."),
    ("dst-new-york", H(sun=[1, 2, 3]), "America/New_York", "2026-03-06T12:00:00Z", "8 Mar 2026 in New York: the same rule in another zone."),
]


def schedule_doc():
    cases = []
    for cid, hours, tz, now, note in SCHEDULE_CASES:
        cases.append({"id": cid, "note": note, "input": {"hours": hours, "tz": tz, "now": now},
                      "expected": schedule_expected(hours, tz, now)})
    return {
        "about": "How the weekly hour grid (GET/PUT /api/schedule) turns into windows: windows_per_week and hours_per_week (Schedule), the next windows (/api/schedule/next, the Schedule preview), and when the scheduler starts and stops runs.",
        "generator": {
            "script": GENERATOR,
            "how": "expected = schedule_expected in generate.py (weekly_windows, window_instances, resolve), which encode the rules below with Python's zoneinfo. The DST rule is a contract decision, not from web-ui.md.",
            "regenerate": "python3 contracts/vectors/generate.py --write",
        },
        "rules": [
            "The grid is 7 × 24 one-hour cells in local wall-clock time (TZ), Monday 00:00 first.",
            "Contiguous active cells form one window, across midnight and from Sunday 23:00 to Monday 00:00 (web-ui.md § Schedule modal).",
            "windows_per_week counts those blocks; hours_per_week counts active cells. All 168 active: one continuous window that never ends.",
            "A window's start and end are wall-clock times. Each is turned into an instant on its own date. DST (contract decision): a time in the spring-forward gap moves forward by the gap, so 02:00 becomes 03:00; a time repeated on fall-back night takes its first occurrence. So a window is shorter or longer in real time across a change, and a window lying entirely in the gap has no length and is skipped that night.",
            "next_windows lists the first three windows whose end is after now, a window in progress included, with their offsets in TZ. in_window says now is inside the first.",
            "Starts and ends are exact: a window starting at now is in progress; a window ending at now is over.",
        ],
        "cases": cases,
    }


def check_schedule(doc):
    errors = []
    for c in doc["cases"]:
        got = schedule_expected(c["input"]["hours"], c["input"]["tz"], c["input"]["now"])
        if got != c["expected"]:
            errors.append(f"{c['id']}: expected {c['expected']}, recomputed {got}")
    return errors


# ============================================================================== backlog

ITEM_OVERHEAD_S = 35


def half_up_seconds(ms):
    return (ms + 500) // 1000


def d13_up_to_date(item):
    d = item.get("d13") or {}
    return (d.get("last_full_pass_snapshot") is not None
            and d.get("last_full_pass_snapshot") == d.get("snapshot_id")
            and d.get("observed_all_in_index") is True)


def backlog_expected(inp):
    tz = ZoneInfo(inp["tz"])
    now = parse_time(inp["now"])
    recorded = set(inp["recorded_track_ids"])
    durations = {}
    items_to_record = 0
    unknown = 0
    for item in inp["items"]:
        if item["kind"] != "album" and not item["tracked"]:
            continue
        if item.get("unavailable"):
            continue
        if not item["item_access"] or item["tracks"] is None:
            if not d13_up_to_date(item):
                unknown += 1
            continue
        has_missing = False
        for t in item["tracks"]:
            if t["id"] is None or t.get("is_local") or not t.get("playable", True):
                continue
            durations.setdefault(t["id"], t["duration_ms"])
            if t["id"] not in recorded:
                has_missing = True
        if has_missing:
            items_to_record += 1
    total_ms = sum(durations.values())
    recorded_ms = sum(ms for i, ms in durations.items() if i in recorded)
    left_ms = total_ms - recorded_ms
    seconds_left = half_up_seconds(left_ms) + ITEM_OVERHEAD_S * items_to_record
    finish = None
    if seconds_left:
        remaining = dt.timedelta(seconds=seconds_left)
        for s, e in window_instances(inp["hours"], tz, now):
            begin = max(s, now)
            if e is None or remaining <= e - begin:
                finish = begin + remaining
                break
            remaining -= e - begin
    return {
        "tracks_total": len(durations),
        "tracks_recorded": sum(1 for i in durations if i in recorded),
        "seconds_total": half_up_seconds(total_ms),
        "seconds_recorded": half_up_seconds(recorded_ms),
        "seconds_left": seconds_left,
        "items_to_record": items_to_record,
        "unknown_items": unknown,
        "finish_at": fmt_local(finish, tz) if finish else None,
        "as_of": fmt_utc(now),
    }


def T(i, ms, **kw):
    t = {"id": i, "duration_ms": ms, "playable": True, "is_local": False}
    t.update(kw)
    return t


def item(iid, kind, tracks, tracked=True, item_access=True, unavailable=False, d13=None):
    return {"id": iid, "kind": kind, "tracked": tracked, "item_access": item_access, "unavailable": unavailable,
            "tracks": tracks, "d13": d13}


def tid(n):
    return f"track{n:017d}"


def iid(prefix, n):
    return f"{prefix}{n:0{22 - len(prefix)}d}"


ALBUM = item(iid("album", 1), "album", [T(tid(i), 180_000) for i in range(1, 11)])
OWNED = item(iid("plist", 1), "owned", [T(tid(5), 180_000), T(tid(20), 240_000), T(tid(21), 200_400)])
NIGHT_HOURS = NIGHTLY
BACKLOG_CASES = [
    ("empty-library", {"items": [], "recorded_track_ids": [], "hours": H(), "tz": "Europe/Berlin", "now": "2026-11-15T10:00:00Z"},
     "Nothing tracked: all zeros, no finish date."),
    ("album-manual-only", {"items": [ALBUM], "recorded_track_ids": [tid(i) for i in range(1, 7)], "hours": H(), "tz": "Europe/Berlin", "now": "2026-11-15T10:00:00Z"},
     "4 of 10 tracks left: 720 s + 35 s. Manual only, so no finish date."),
    ("shared-track-counted-once", {"items": [ALBUM, OWNED], "recorded_track_ids": [tid(i) for i in range(1, 5)], "hours": H(), "tz": "UTC", "now": "2026-11-15T10:00:00Z"},
     "Track 5 is on the album and the playlist: counted once. Both items have something to record: 2 × 35 s."),
    ("unplayable-excluded", {"items": [item(iid("plist", 2), "owned", [
        T(tid(30), 100_000), T(None, 50_000, is_local=True), T(tid(31), 70_000, playable=False), T(None, 0, playable=False), T(tid(32), 90_000)])],
        "recorded_track_ids": [tid(30)], "hours": H(), "tz": "UTC", "now": "2026-11-15T10:00:00Z"},
     "Local files, entries with no item and is_playable false are left out of every figure."),
    ("untracked-and-unavailable-excluded", {"items": [
        item(iid("plist", 3), "owned", [T(tid(40), 100_000)], tracked=False),
        item(iid("plist", 4), "followed", None, tracked=False, item_access=False),
        item(iid("plist", 5), "owned", [T(tid(41), 100_000)], unavailable=True),
        item("liked", "liked", [T(tid(42), 100_000)])],
        "recorded_track_ids": [], "hours": H(), "tz": "UTC", "now": "2026-11-15T10:00:00Z"},
     "Untracked playlists and unavailable items don't count. Liked Songs counts like a playlist."),
    ("d13-unknown-items", {"items": [
        item(iid("follow", 1), "followed", None, item_access=False, d13={"snapshot_id": "snapB", "last_full_pass_snapshot": "snapA", "observed_all_in_index": True}),
        item(iid("follow", 2), "followed", None, item_access=False, d13={"snapshot_id": "snapC", "last_full_pass_snapshot": "snapC", "observed_all_in_index": True}),
        item(iid("follow", 3), "followed", None, item_access=False, d13={"snapshot_id": "snapD", "last_full_pass_snapshot": None, "observed_all_in_index": False}),
        item(iid("follow", 4), "linked", None, item_access=False, d13={"snapshot_id": "snapE", "last_full_pass_snapshot": "snapE", "observed_all_in_index": False}),
        item(iid("follow", 5), "followed", [T(tid(50), 120_000)], item_access=True)],
        "recorded_track_ids": [], "hours": H(), "tz": "UTC", "now": "2026-11-15T10:00:00Z"},
     "D13: 1 changed snapshot, 3 never fully passed, 4 a deleted file: unknown. 2 is up to date and not counted. 5 is followed but collaborative (item access): it counts like an owned playlist."),
    ("everything-recorded", {"items": [ALBUM], "recorded_track_ids": [tid(i) for i in range(1, 11)], "hours": NIGHT_HOURS, "tz": "Europe/Berlin", "now": "2026-11-15T10:00:00Z"},
     "Nothing left: seconds_left 0 and no finish date, whatever the schedule."),
    ("rounding-half-up", {"items": [item(iid("plist", 6), "owned", [T(tid(60), 1_500), T(tid(61), 1_000)])],
                          "recorded_track_ids": [tid(61)], "hours": H(), "tz": "UTC", "now": "2026-11-15T10:00:00Z"},
     "Milliseconds are summed, then rounded half up: 1,500 ms left is 2 s, plus 35 s."),
    ("walks-several-windows", {"items": [item(iid("plist", 7), "owned", [T(tid(70 + i), 3_600_000) for i in range(8)])],
                               "recorded_track_ids": [], "hours": NIGHT_HOURS, "tz": "Europe/Berlin", "now": "2026-11-11T12:00:00Z"},
     "8 h of music + 35 s: Thu 01:00–07:00 (6 h), then 2 h 0 m 35 s into Fri's window."),
    ("starts-inside-window", {"items": [item(iid("plist", 8), "owned", [T(tid(80), 3_600_000)])],
                              "recorded_track_ids": [], "hours": NIGHT_HOURS, "tz": "Europe/Berlin", "now": "2026-11-12T05:30:00Z"},
     "Now is 06:30 local, inside Thu's window: 30 min there, the rest on Fri from 01:00."),
    ("across-midnight-window", {"items": [item(iid("plist", 9), "owned", [T(tid(90), 5_400_000)])],
                                "recorded_track_ids": [], "hours": H(mon=[23], tue=[0, 1]), "tz": "Europe/Berlin", "now": "2026-11-09T12:00:00Z"},
     "One 3 h window from Mon 23:00 across midnight: done Tue 00:30:35."),
    ("dst-fall-back-gives-an-hour", {"items": [item(iid("plist", 10), "owned", [T(tid(100), 3 * 3_600_000 + 1_800_000)])],
                                     "recorded_track_ids": [], "hours": H(sun=[1, 2, 3]), "tz": "Europe/Berlin", "now": "2026-10-23T12:00:00Z"},
     "3.5 h fits in the 25 Oct window, which is 4 real hours on fall-back night."),
    ("dst-spring-forward-takes-an-hour", {"items": [item(iid("plist", 11), "owned", [T(tid(110), 3 * 3_600_000 - 35_000)])],
                                          "recorded_track_ids": [], "hours": H(sun=[1, 2, 3]), "tz": "Europe/Berlin", "now": "2026-03-27T12:00:00Z"},
     "3 h doesn't fit in the 29 Mar window (2 real hours): 1 h more the next Sunday."),
    ("continuous-grid", {"items": [ALBUM], "recorded_track_ids": [], "hours": {d: list(range(24)) for d in DAYS}, "tz": "Europe/Berlin", "now": "2026-11-15T10:20:00Z"},
     "Every hour active: the finish is now + seconds_left."),
]


def backlog_doc():
    cases = [{"id": cid, "note": note, "input": inp, "expected": backlog_expected(inp)} for cid, inp, note in BACKLOG_CASES]
    return {
        "about": "The backlog estimate (GET /api/backlog, the `backlog` event): the Dashboard's Full backup card, wizard step 9 and the Schedule preview.",
        "generator": {
            "script": GENERATOR,
            "how": "expected = backlog_expected in generate.py, which encodes design.md § Backlog estimate with the M1 plan's D13 and the window rules of schedule-windows.json.",
            "regenerate": "python3 contracts/vectors/generate.py --write",
        },
        "rules": [
            "Items counted: albums on the Albums page and tracked playlists (Liked Songs included), except Unavailable ones.",
            "Known items have item access and a track list. Their tracks count when they have an id, aren't local files, and are playable (market=from_token). Each track id counts once, however many items it's in.",
            "tracks_total, seconds_total: every counted track. tracks_recorded, seconds_recorded: those in History's records (recorded_track_ids).",
            "seconds_left = the unrecorded tracks' duration + 35 s for each known item with at least one unrecorded track (items_to_record).",
            "Seconds: milliseconds are summed first, then rounded half up to whole seconds.",
            "unknown_items: counted items without item access, except those Up to date by D13 (snapshot_id equals last_full_pass_snapshot and every observed track is still in Spytify's index). They're left out of every figure.",
            "finish_at: walk the schedule's windows forward from now (a window in progress counts from now), using the real length of each window (schedule-windows.json's DST rule), until seconds_left is used up. Null with Manual only, or when seconds_left is 0. Continuous grid: now + seconds_left.",
            "as_of: when the estimate was made (here, now).",
        ],
        "cases": cases,
    }


def check_backlog(doc):
    errors = []
    for c in doc["cases"]:
        got = backlog_expected(c["input"])
        if got != c["expected"]:
            errors.append(f"{c['id']}: expected {c['expected']}, recomputed {got}")
    return errors


# ============================================================================== Go (Spytify) answers

def run_go(src, keys_in, settings_in, examples_in):
    """Run tools/spytify_vectors_test.go inside a Spytify source tree, in Docker."""
    src = os.path.abspath(src)
    target = os.path.join(src, "internal", "core", "spotivault_vectors_test.go")
    shutil.copyfile(os.path.join(HERE, "tools", "spytify_vectors_test.go"), target)
    with tempfile.TemporaryDirectory() as io_dir:
        with open(os.path.join(io_dir, "in.json"), "w", encoding="utf-8") as f:
            json.dump({"keys": keys_in, "settings": settings_in, "examples": examples_in}, f, ensure_ascii=False)
        env = dict(os.environ)
        cmd = ["docker", "run", "--rm", "-v", f"{src}:/src", "-v", f"{io_dir}:/io", "-w", "/src",
               "-e", "SPOTIVAULT_VECTORS_IN=/io/in.json", "-e", "SPOTIVAULT_VECTORS_OUT=/io/out.json",
               "-e", "CGO_ENABLED=0", "golang:1.26",
               "go", "test", "./internal/core", "-run", "TestSpotivaultVectors", "-count=1"]
        try:
            subprocess.run(cmd, check=True, env=env)
        finally:
            os.remove(target)
        with open(os.path.join(io_dir, "out.json"), encoding="utf-8") as f:
            return json.load(f)


# ============================================================================== main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--recorded")
    ap.add_argument("--runs")
    ap.add_argument("--go", metavar="SPYTIFY_SRC")
    a = ap.parse_args()

    if not a.write:
        errors = (check_track_keys(read("track-keys.json")) + check_layouts(read("layouts.json"))
                  + check_schedule(read("schedule-windows.json")) + check_backlog(read("backlog.json")))
        for e in errors:
            print("FAIL", e)
        print(f"{len(errors)} problem(s)" if errors else "vectors OK")
        return 1 if errors else 0

    def old(name):
        try:
            return read(name)
        except FileNotFoundError:
            return None

    recorded, pending = recorded_cases(a.recorded, a.runs) if a.recorded and a.runs else (None, None)
    keys = track_key_doc(old("track-keys.json"), recorded, None, pending)
    go_keys = go_layouts = None
    if a.go:
        key_inputs = [{"artist": c["artist"], "title": c["title"]} for c in keys["cases"]]
        key_inputs += [{"artist": (w["artists"] or [""])[0], "title": w["name"]} for w in keys["web_cases"]]
        settings_in, examples_in, index = go_layout_requests()
        res = run_go(a.go, key_inputs, settings_in, examples_in)
        go_keys = res["keys"]
        go_layouts = go_layout_answers(index, res["settings"], res["examples"])
        keys = track_key_doc(old("track-keys.json"), [
            {k: c[k] for k in ("id", "source", "artist", "title", "spytify_index_key")}
            for c in keys["cases"] if c["id"].startswith("recorded-")], go_keys, keys["recorded_lines_pending"])
    write("track-keys.json", keys)
    write("layouts.json", layout_doc(old("layouts.json"), go_layouts))
    write("schedule-windows.json", schedule_doc())
    write("backlog.json", backlog_doc())
    print("wrote track-keys.json, layouts.json, schedule-windows.json, backlog.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
