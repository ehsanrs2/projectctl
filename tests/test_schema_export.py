import json
from pathlib import Path

from projectctl.schema_export import PUBLIC_SCHEMAS, export_json_schemas


def test_schema_export(tmp_path: Path):
    paths = export_json_schemas(tmp_path)
    assert len(paths) == len(PUBLIC_SCHEMAS)
    assert [path.name for path in paths] == sorted(PUBLIC_SCHEMAS)
    assert {path.name for path in tmp_path.glob("*.schema.json")} == set(PUBLIC_SCHEMAS)
    for path in paths:
        data = json.loads(path.read_text())
        assert "$defs" in data or "properties" in data


def test_generated_schema_mirror_is_not_versioned():
    repository_root = Path(__file__).resolve().parents[1]
    assert not (repository_root / "schemas" / "generated").exists()
