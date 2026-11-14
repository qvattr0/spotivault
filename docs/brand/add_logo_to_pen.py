"""Add the logo components to a Pencil file and swap the placeholder marks.

Usage:  python3 docs/brand/add_logo_to_pen.py [path/to/file.pen]
Default file: docs/ui-design/spotivault.pen. Close the file in Pencil first,
or Pencil may overwrite the change. Safe to run once; it refuses to run twice.

Adds "Section · BRAND" (Logo/Mark, Logo/Mark Light, Logo/Mark 64, 32, 16) under
the Components board header, and replaces every sidebar/wizard "Mark" (green
circle with the Lucide archive icon) with a ref to Logo/Mark 32.
"""
import json, sys, random, string, importlib.util
from pathlib import Path
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("make_logo", HERE / "make_logo.py")
ml = importlib.util.module_from_spec(spec); sys.modules["make_logo"] = ml; spec.loader.exec_module(ml)
pen_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "ui-design" / "spotivault.pen"
raw = open(pen_path).read()
d = json.loads(raw)

idx, parent = {}, {}
def walk(n, p):
    idx[n["id"]] = n; parent[n["id"]] = p
    for ch in n.get("children") or []: walk(ch, n)
for c in d["children"]: walk(c, None)
assert not any((n.get("name") or "").startswith("Logo/") for n in idx.values()), "already patched"

rng = random.Random(20261115)
def nid():
    while True:
        s = "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(5))
        if s not in idx: idx[s] = None; return s

def mark(name, size, level, tile, record, groove):
    k = size / ml.TILE
    kids = [{"type": "rectangle", "id": nid(), "name": "Tile", "x": 0, "y": 0,
             "width": size, "height": size, "cornerRadius": round(ml.TILE_RADIUS * k, 2), "fill": tile}]
    for L in ml.record_layers(level, record, groove):
        n = {"type": "path", "id": nid(), "name": L.name, "x": 0, "y": 0, "width": size, "height": size,
             "viewBox": [-70, -70, 140, 140], "geometry": L.d, "fill": L.fill}
        if L.evenodd: n["fillRule"] = "evenodd"
        kids.append(n)
    return {"type": "frame", "id": nid(), "name": name, "reusable": True, "width": size, "height": size,
            "layout": "none", "children": kids}

D = (ml.DARK_TILE, ml.DARK_RECORD, ml.DARK_GROOVE)
Lt = (ml.LIGHT_TILE, ml.LIGHT_RECORD, ml.LIGHT_GROOVE)
comps = [
    (mark("Logo/Mark", 140, "full", *D), "Logo/Mark · 140 · master"),
    (mark("Logo/Mark Light", 140, "full", *Lt), "Logo/Mark Light · on light surfaces"),
    (mark("Logo/Mark 64", 64, "64", *D), "Logo/Mark 64 · 8 notches"),
    (mark("Logo/Mark 32", 32, "32", *D), "Logo/Mark 32 · UI, favicon"),
    (mark("Logo/Mark 16", 16, "16", *D), "Logo/Mark 16 · favicon"),
]
small_id = comps[3][0]["id"]

def text(content, fill, size, weight, **kw):
    t = {"type": "text", "id": nid(), "name": content[:24], "fill": fill, "content": content,
         "fontFamily": "$font", "fontSize": size, "fontWeight": weight}
    t.update(kw); return t

items = []
for comp, cap in comps:
    items.append({"type": "frame", "id": nid(), "name": "Item " + comp["name"], "layout": "vertical",
                  "gap": 10, "children": [comp, text(cap, "$text-sub", 12, "500")]})
section = {"type": "frame", "id": nid(), "name": "Section · BRAND", "width": "fill_container",
           "layout": "vertical", "gap": 24, "children": [
    text("BRAND", "$text-sub", 13, "700"),
    {"type": "frame", "id": nid(), "name": "Logo sizes", "gap": 40, "alignItems": "end", "children": items},
    text("Vinyl vault: a record as a safe dial, keyhole in the label, 12 notches cut into the rim. "
         "Fixed colours, not tokens: tile #121212, record #2A2A2A, grooves #3A3A3A, label #34D399, keyhole #121212. "
         "Notches are see-through. Smaller sizes drop detail; never scale the 140 master below 64. "
         "SVG source: docs/brand/.", "$text-muted", 13, "normal",
         textGrowth="fixed-width", width=900),
]}
board = idx["E3ZmN"]
hdr = [i for i, c in enumerate(board["children"]) if c["id"] == "JhPjq"][0]
board["children"].insert(hdr + 1, section)

# Replace the placeholder marks (green circle + archive icon) with the logo.
replaced = []
for n in list(idx.values()):
    if not n or n.get("type") != "frame" or n.get("name") != "Brand": continue
    for i, ch in enumerate(n.get("children") or []):
        if ch.get("name") == "Mark" and any(g.get("icon") == "archive" for g in ch.get("children") or []):
            n["children"][i] = {"id": ch["id"], "type": "ref", "ref": small_id, "name": "Logo"}
            replaced.append(ch["id"])
print("placeholder marks replaced:", len(replaced))

out = json.dumps(d, indent=2, ensure_ascii=False) + ("\n" if raw.endswith("\n") else "")
open(pen_path, "w").write(out)
