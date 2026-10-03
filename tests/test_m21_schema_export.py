from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.schemas.quota import QuotaSnapshot, QuotaSnapshotV1


def test_m21_quota_schema_versions_are_exported_separately():
    assert PUBLIC_SCHEMAS["quota-snapshot.v1.schema.json"] is QuotaSnapshotV1
    assert PUBLIC_SCHEMAS["quota-snapshot.v2.schema.json"] is QuotaSnapshot
    assert QuotaSnapshotV1.model_fields["schema_version"].default == 1
    assert QuotaSnapshot.model_fields["schema_version"].default == 2
