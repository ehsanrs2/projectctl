from projectctl.schema_export import PUBLIC_SCHEMAS


def test_m14_public_schemas_are_exported():
    assert "integration-manifest.v1.schema.json" in PUBLIC_SCHEMAS
    assert "recovery-report.v1.schema.json" in PUBLIC_SCHEMAS
