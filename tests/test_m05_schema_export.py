from projectctl.schema_export import PUBLIC_SCHEMAS


def test_m05_public_schema_versions_are_explicit():
    assert "project-state.v1.schema.json" in PUBLIC_SCHEMAS
    assert "project-status.v1.schema.json" in PUBLIC_SCHEMAS
    assert "scheduler-decision.v2.schema.json" in PUBLIC_SCHEMAS
    assert "scheduler-decision.v1.schema.json" in PUBLIC_SCHEMAS  # legacy readable contract\n