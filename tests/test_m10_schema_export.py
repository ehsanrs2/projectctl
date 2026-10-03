from projectctl.schema_export import PUBLIC_SCHEMAS


def test_m10_public_contracts_are_versioned_and_legacy_readable():
    expected = {
        "run-manifest.v1.schema.json",
        "run-manifest.v2.schema.json",
        "context-manifest.v1.schema.json",
        "context-manifest.v2.schema.json",
        "execution-plan.v1.schema.json",
        "worker-request.v1.schema.json",
        "worker-result.v1.schema.json",
        "worker-checkpoint.v1.schema.json",
        "verification-manifest.v1.schema.json",
        "evidence-manifest.v1.schema.json",
    }
    assert expected <= set(PUBLIC_SCHEMAS)
