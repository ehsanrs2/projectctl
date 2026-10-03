from projectctl.schema_export import PUBLIC_SCHEMAS


def test_m20_public_schemas_are_exported():
    assert "auto-run-policy.v1.schema.json" in PUBLIC_SCHEMAS
    assert "auto-run-report.v1.schema.json" in PUBLIC_SCHEMAS
