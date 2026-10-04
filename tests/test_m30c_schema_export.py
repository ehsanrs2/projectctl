from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.schemas.delivery import (
    PublicationManifest,
    PublicationRequest,
    TaskDeliveryPolicy,
)
from projectctl.schemas.integration import IntegrationManifest, IntegrationManifestV1


def test_m30c_public_delivery_contracts_are_exported_additively():
    assert PUBLIC_SCHEMAS["task-delivery-policy.v1.schema.json"] is TaskDeliveryPolicy
    assert PUBLIC_SCHEMAS["publication-request.v1.schema.json"] is PublicationRequest
    assert PUBLIC_SCHEMAS["publication-manifest.v1.schema.json"] is PublicationManifest
    assert PUBLIC_SCHEMAS["integration-manifest.v1.schema.json"] is IntegrationManifestV1
    assert PUBLIC_SCHEMAS["integration-manifest.v2.schema.json"] is IntegrationManifest

    assert IntegrationManifestV1.model_fields["schema_version"].default == 1
    assert IntegrationManifest.model_fields["schema_version"].default == 2
    assert "publication_required" not in IntegrationManifestV1.model_fields
    assert "publication_required" in IntegrationManifest.model_fields
    assert "publication_digest" in IntegrationManifest.model_fields
