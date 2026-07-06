"""Export the OpenAPI schema: ``python -m chefclaw.export_openapi <output-path>``.

Byte-stable output (sorted keys, 2-space indent, trailing newline) — the CI
drift check regenerates the typed TS client from this file and diffs it.
"""

import json
import sys
from pathlib import Path

from chefclaw.app import create_app


def export(output_path: Path) -> None:
    schema = create_app().openapi()
    serialized = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False)
    output_path.write_text(serialized + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m chefclaw.export_openapi <output-path>", file=sys.stderr)
        return 2
    export(Path(argv[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
