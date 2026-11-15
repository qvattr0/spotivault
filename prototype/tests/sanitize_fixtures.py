#!/usr/bin/env python3
"""Sanitize the probe's raw Web API responses into test fixtures that can go in the public repo.

Keeps every key, type and structure (that's what the fixtures are for: the 2026 field names,
nesting, `is_playable`, `is_local`, paging), but replaces anything that identifies the account
or its music:
- Spotify IDs (22-character base62) -> stable fake IDs, so cross-references still match;
- user IDs and display names -> "user1", "User One";
- names of playlists, tracks, albums and artists -> "Playlist 3", "Track 12", ...;
- descriptions, copyrights, genres, ISRC/UPC codes -> neutral values;
- image and snapshot IDs -> stable fake hex of the same length.

    python3 -I prototype/tests/sanitize_fixtures.py RAW_DIR OUT_DIR
"""
import hashlib
import json
import os
import re
import sys

B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
ID22 = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{22}(?![A-Za-z0-9])")
HEX = re.compile(r"[0-9a-f]{24,}")


class Sanitizer:
    def __init__(self):
        self.ids, self.users, self.names = {}, {}, {}

    def fake_id(self, real):
        if real not in self.ids:
            h = hashlib.sha256(("id:" + real).encode()).digest()
            self.ids[real] = "".join(B62[b % 62] for b in h[:22])
        return self.ids[real]

    def fake_hex(self, m):
        real = m.group(0)
        return hashlib.sha256(("hex:" + real).encode()).hexdigest()[: len(real)]

    def user(self, real):
        if real not in self.users:
            self.users[real] = f"user{len(self.users) + 1}"
        return self.users[real]

    def label(self, kind, real):
        key = (kind, real)
        if key not in self.names:
            n = sum(1 for k in self.names if k[0] == kind) + 1
            self.names[key] = f"{kind} {n}"
        return self.names[key]

    def text(self, s):
        for real, fake in self.users.items():
            s = s.replace(real, fake)
        s = ID22.sub(lambda m: self.fake_id(m.group(0)), s)
        return HEX.sub(self.fake_hex, s)

    def walk(self, v, parent_type=None, key=None):
        if isinstance(v, dict):
            t = v.get("type") or parent_type
            if t == "user" and isinstance(v.get("id"), str):
                self.user(v["id"])
            out = {}
            for k, x in v.items():
                out[k] = self.walk(x, t, k)
            return out
        if isinstance(v, list):
            return [self.walk(x, parent_type, key) for x in v]
        if not isinstance(v, str):
            return v
        if key == "display_name":
            return "User One"
        if key == "name":
            kind = {"playlist": "Playlist", "track": "Track", "album": "Album", "artist": "Artist",
                    "episode": "Episode"}.get(parent_type, "Name")
            return self.label(kind, v)
        if key in ("description",):
            return ""
        if key in ("text",):  # copyrights
            return "(C) Label"
        if key in ("isrc", "upc", "ean"):
            return "XX0000000000"
        if key == "id" and parent_type == "user":
            return self.user(v)
        if key == "snapshot_id":
            return "snapshot-" + hashlib.sha256(v.encode()).hexdigest()[:12]
        return self.text(v)


def main(raw, out):
    os.makedirs(out, exist_ok=True)
    s = Sanitizer()
    for f in sorted(os.listdir(raw)):
        if not f.endswith(".json"):
            continue
        with open(os.path.join(raw, f)) as fh:
            data = json.load(fh)
        clean = s.walk(data)
        if isinstance(clean, dict) and "genres" in json.dumps(clean):
            clean = json.loads(re.sub(r'"genres": \[[^\]]*\]', '"genres": []', json.dumps(clean)))
        name = s.text(f)
        with open(os.path.join(out, name), "w") as fh:
            json.dump(clean, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        print(f"{f} -> {name}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
