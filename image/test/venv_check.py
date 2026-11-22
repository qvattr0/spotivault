"""Smoke test helper: checks the controller's venv, from inside the container, as app.

    docker exec -i -u app NAME /opt/spotivault/venv/bin/python -I - < venv_check.py

The app user can't write to /opt/spotivault, so Python can't cache bytecode there at runtime:
every module must come with a valid .pyc, or each start compiles it again. A timestamp .pyc is
valid when the source's mtime and size match the ones it records (COPY between build stages
must keep them). Prints one JSON line; exits 0 when every check passes.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

site = Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
site = site / "site-packages"
sources = missing = stale = 0
examples: list[str] = []
for source in sorted(site.rglob("*.py")):
    sources += 1
    pyc = Path(importlib.util.cache_from_source(str(source)))
    try:
        header = pyc.read_bytes()[:16]
    except FileNotFoundError:
        missing += 1
        examples.append(f"no pyc: {source.relative_to(site)}")
        continue
    flags = int.from_bytes(header[4:8], "little")
    valid = header[:4] == importlib.util.MAGIC_NUMBER
    if valid and flags == 0:  # timestamp-based
        st = source.stat()
        mtime = int.from_bytes(header[8:12], "little")
        size = int.from_bytes(header[12:16], "little")
        valid = mtime == int(st.st_mtime) & 0xFFFFFFFF and size == st.st_size & 0xFFFFFFFF
    if not valid:
        stale += 1
        examples.append(f"stale pyc: {source.relative_to(site)}")

has_pip = (Path(sys.prefix) / "bin" / "pip").exists() or importlib.util.find_spec("pip") is not None
result = {
    "python": sys.version.split()[0],
    "prefix": sys.prefix,
    "sources": sources,
    "missing_pyc": missing,
    "stale_pyc": stale,
    "examples": examples[:5],
    "writable_by_app": os.access(sys.prefix, os.W_OK) or os.access(site, os.W_OK),
    "pip": has_pip,
    "spotivault": importlib.util.find_spec("spotivault") is not None,
}
print(json.dumps(result))
ok = (
    sources > 0
    and not missing
    and not stale
    and not result["writable_by_app"]
    and not result["pip"]
    and result["spotivault"]
)
sys.exit(0 if ok else 1)
