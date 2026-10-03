from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.schemas.execution import WorkerCheckpoint, WorkerCheckpointV1


def test_m22_worker_checkpoint_schema_versions_are_exported():
    assert PUBLIC_SCHEMAS["worker-checkpoint.v1.schema.json"] is WorkerCheckpointV1
    assert PUBLIC_SCHEMAS["worker-checkpoint.v2.schema.json"] is WorkerCheckpoint
    assert WorkerCheckpointV1.model_fields["schema_version"].default == 1
    assert WorkerCheckpoint.model_fields["schema_version"].default == 2
