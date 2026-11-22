"""Regenerate src/spotivault/api/models.py from contracts/openapi.yaml.

    uv run python scripts/gen_models.py           # rewrite models.py
    uv run python scripts/gen_models.py --check   # exit 1 if models.py is out of date

The contract is the source of the API's shapes (design.md § Stack), so models.py is never edited
by hand. tests/test_models_generated.py calls `generate()` and fails when the result differs
from the committed file.
"""

import argparse
import subprocess
import sys
from pathlib import Path

CONTROLLER = Path(__file__).resolve().parent.parent
CONTRACT = CONTROLLER.parent / "contracts" / "openapi.yaml"
MODELS = CONTROLLER / "src" / "spotivault" / "api" / "models.py"
HEADER = "# Generated from contracts/openapi.yaml by scripts/gen_models.py. Do not edit by hand."

# The exact datamodel-codegen command. Every option is spelled out (--ignore-pyproject), so the
# output depends only on this list, the pinned datamodel-code-generator and ruff, and the
# [tool.ruff] settings in pyproject.toml (ruff format reads them).
OPTIONS = [
    "--ignore-pyproject",
    "--input-file-type",
    "openapi",
    "--openapi-scopes",
    "schemas",
    "paths",
    "parameters",
    "--output-model-type",
    "pydantic_v2.BaseModel",
    "--target-python-version",
    "3.12",
    "--formatters",
    "ruff-format",
    # Enums become Literal types; small schemas become `type X = ...` aliases, not RootModels.
    "--enum-field-as-literal",
    "all",
    "--collapse-root-models",
    "--use-type-alias",
    # Inline objects are named after their parent (ClientInstallError), path bodies after their
    # operationId (AcknowledgeTosRequest).
    "--naming-strategy",
    "parent-prefixed",
    "--use-operation-id-as-name",
    "--use-standard-collections",
    "--use-union-operator",
    "--use-annotated",
    "--field-constraints",
    # Only `type: [x, 'null']` is nullable. Required nullable fields have no default, so a
    # response can't leave one out ("present and null, never left out").
    "--strict-nullable",
    "--output-datetime-class",
    "AwareDatetime",
    "--use-schema-description",
    "--use-field-description",
    "--use-double-quotes",
    "--disable-timestamp",
    "--custom-file-header",
    HEADER,
]


def command() -> list[str]:
    """The datamodel-codegen command line. It prints the models to stdout."""
    exe = Path(sys.executable).parent / "datamodel-codegen"
    return [str(exe), "--input", str(CONTRACT), *OPTIONS]


def generate() -> str:
    """Freshly generated models.py text.

    It runs in the controller folder, so ruff format finds pyproject.toml wherever the result goes.
    """
    result = subprocess.run(
        command(), check=True, cwd=CONTROLLER, capture_output=True, text=True, encoding="utf-8"
    )
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only check that models.py is current")
    args = parser.parse_args()
    fresh = generate()
    if args.check:
        if fresh != MODELS.read_text(encoding="utf-8"):
            print("models.py is out of date: run `uv run python scripts/gen_models.py`")
            return 1
        print("models.py is current")
        return 0
    MODELS.write_text(fresh, encoding="utf-8")
    print(f"wrote {MODELS.relative_to(CONTROLLER)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
