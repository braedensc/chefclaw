"""export_openapi produces parseable, byte-stable JSON containing /api/health."""

import json
from pathlib import Path

from chefclaw.export_openapi import export, main


def test_export_writes_parseable_schema_with_health(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    assert main([str(out)]) == 0
    schema = json.loads(out.read_text(encoding="utf-8"))
    assert "/api/health" in schema["paths"]
    assert schema["info"]["title"] == "chefclaw"


def test_export_is_byte_stable(tmp_path: Path) -> None:
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    export(first)
    export(second)
    content = first.read_bytes()
    assert content == second.read_bytes()
    assert content.endswith(b"\n")


def test_main_usage_error() -> None:
    assert main([]) == 2
    assert main(["a", "b"]) == 2
