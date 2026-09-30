import json
from pathlib import Path

from projectctl.schema_export import PUBLIC_SCHEMAS, export_json_schemas


def test_schema_export(tmp_path: Path):
    paths = export_json_schemas(tmp_path)
    assert len(paths) == len(PUBLIC_SCHEMAS)
    for path in paths:
        data = json.loads(path.read_text())
        assert "$defs" in data or "properties" in data
