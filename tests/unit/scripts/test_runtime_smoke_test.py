from __future__ import annotations

import json
from pathlib import Path

from scripts.nvidia.runtime_smoke_test import load_json


def test_load_json_accepts_utf8_bom(
    tmp_path: Path,
) -> None:
    path = tmp_path / "manifest.json"

    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
            }
        ),
        encoding="utf-8-sig",
    )

    document = load_json(path)

    assert document == {
        "schema_version": 1,
    }
