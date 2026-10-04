from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.schemas.task_claim import TaskClaim, TaskClaimRequest


def test_task_claim_contracts_are_public_v1_schemas():
    assert PUBLIC_SCHEMAS["task-claim-request.v1.schema.json"] is TaskClaimRequest
    assert PUBLIC_SCHEMAS["task-claim.v1.schema.json"] is TaskClaim
    assert TaskClaimRequest.model_fields["schema_version"].default == 1
    assert TaskClaim.model_fields["schema_version"].default == 1
