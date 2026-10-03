from projectctl.schema_export import PUBLIC_SCHEMAS


def test_m12a_capability_contracts_are_public():
    assert "worker-capabilities.v1.schema.json" in PUBLIC_SCHEMAS
    assert "worker-strategy-decision.v1.schema.json" in PUBLIC_SCHEMAS
