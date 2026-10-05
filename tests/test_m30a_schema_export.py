from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.schemas.onboarding import (
    AdoptionManifest,
    AdoptionManifestV1,
    AdoptionManifestV2,
    AdoptionManifestV3,
    AdoptionManifestV4,
    AdoptionManifestV5,
    AdoptionPlan,
    AdoptionPlanV1,
    AdoptionPlanV2,
    AdoptionPlanV3,
    AdoptionPlanV4,
    AdoptionPlanV5,
    ProjectInspection,
    ProjectInspectionV1,
    ProjectInspectionV2,
)


def test_m30a_onboarding_contracts_are_versioned_additively():
    assert PUBLIC_SCHEMAS["project-inspection.v1.schema.json"] is ProjectInspectionV1
    assert PUBLIC_SCHEMAS["project-inspection.v2.schema.json"] is ProjectInspectionV2
    assert PUBLIC_SCHEMAS["project-inspection.v3.schema.json"] is ProjectInspection
    assert PUBLIC_SCHEMAS["adoption-plan.v1.schema.json"] is AdoptionPlanV1
    assert PUBLIC_SCHEMAS["adoption-plan.v2.schema.json"] is AdoptionPlanV2
    assert PUBLIC_SCHEMAS["adoption-plan.v3.schema.json"] is AdoptionPlanV3
    assert PUBLIC_SCHEMAS["adoption-plan.v4.schema.json"] is AdoptionPlanV4
    assert PUBLIC_SCHEMAS["adoption-plan.v5.schema.json"] is AdoptionPlanV5
    assert PUBLIC_SCHEMAS["adoption-plan.v6.schema.json"] is AdoptionPlan
    assert PUBLIC_SCHEMAS["adoption-manifest.v1.schema.json"] is AdoptionManifestV1
    assert PUBLIC_SCHEMAS["adoption-manifest.v2.schema.json"] is AdoptionManifestV2
    assert PUBLIC_SCHEMAS["adoption-manifest.v3.schema.json"] is AdoptionManifestV3
    assert PUBLIC_SCHEMAS["adoption-manifest.v4.schema.json"] is AdoptionManifestV4
    assert PUBLIC_SCHEMAS["adoption-manifest.v5.schema.json"] is AdoptionManifestV5
    assert PUBLIC_SCHEMAS["adoption-manifest.v6.schema.json"] is AdoptionManifest

    assert ProjectInspectionV1.model_fields["schema_version"].default == 1
    assert ProjectInspectionV2.model_fields["schema_version"].default == 2
    assert ProjectInspection.model_fields["schema_version"].default == 3
    assert "github_repository" not in ProjectInspectionV1.model_fields
    assert "github_repository" in ProjectInspectionV2.model_fields
    assert "git_remote_identity" not in ProjectInspectionV2.model_fields
    assert "git_remote_identity" in ProjectInspection.model_fields

    assert "task_store_repository" not in AdoptionPlanV1.model_fields
    assert "task_store_repository" in AdoptionPlanV2.model_fields
    assert "task_store_team" not in AdoptionPlanV2.model_fields
    assert "task_store_team" in AdoptionPlanV3.model_fields
    assert "code_transport_mode" not in AdoptionPlanV3.model_fields
    assert "code_transport_mode" in AdoptionPlanV4.model_fields
    assert "code_delivery_mode" not in AdoptionPlanV4.model_fields
    assert "code_delivery_mode" in AdoptionPlanV5.model_fields
    assert "task_store_site" not in AdoptionPlanV5.model_fields
    assert "task_store_site" in AdoptionPlan.model_fields
    assert "task_store_project" in AdoptionPlan.model_fields
    assert "task_store_repository" not in AdoptionManifestV1.model_fields
    assert "task_store_repository" in AdoptionManifestV2.model_fields
    assert "task_store_team" not in AdoptionManifestV2.model_fields
    assert "task_store_team" in AdoptionManifestV3.model_fields
    assert "code_transport_mode" not in AdoptionManifestV3.model_fields
    assert "code_transport_mode" in AdoptionManifestV4.model_fields
    assert "code_delivery_mode" not in AdoptionManifestV4.model_fields
    assert "code_delivery_mode" in AdoptionManifestV5.model_fields
    assert "task_store_site" not in AdoptionManifestV5.model_fields
    assert "task_store_site" in AdoptionManifest.model_fields
    assert "task_store_project" in AdoptionManifest.model_fields
