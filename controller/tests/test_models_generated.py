"""api/models.py is exactly what scripts/gen_models.py makes from contracts/openapi.yaml."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "gen_models.py"


def load_script():
    spec = importlib.util.spec_from_file_location("gen_models", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_models_match_the_contract() -> None:
    gen = load_script()
    fresh = gen.generate()
    committed = gen.MODELS.read_text(encoding="utf-8")
    assert fresh == committed, (
        "api/models.py is out of date with contracts/openapi.yaml: "
        "run `uv run python scripts/gen_models.py` and commit the result"
    )
