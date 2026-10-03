from projectctl.schema_export import PUBLIC_SCHEMAS


def test_m12b_execution_contract_versions_are_explicit():
    assert "execution-plan.v1.schema.json" in PUBLIC_SCHEMAS
    assert "execution-plan.v2.schema.json" in PUBLIC_SCHEMAS
    assert "worker-request.v1.schema.json" in PUBLIC_SCHEMAS
    assert "worker-request.v2.schema.json" in PUBLIC_SCHEMAS
