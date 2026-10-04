from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.schemas.onboarding import (
    AdoptionManifest,
    AdoptionManifestV1,
    AdoptionManifestV2,
    AdoptionPlan,
    AdoptionPlanV1,
    AdoptionPlanV2,
    ProjectInspection,
    ProjectInspectionV1,
)


def test_m30a_onboarding_contracts_are_versioned_additively():
    assert PUBLIC_SCHEMAS["project-inspection.v1.schema.json"] is ProjectInspectionV1
    assert PUBLIC_SCHEMAS["project-inspection.v2.schema.json"] is ProjectInspection
    assert PUBLIC_SCHEMAS["adoption-plan.v1.schema.json"] is AdoptionPlanV1
    assert PUBLIC_SCHEMAS["adoption-plan.v2.schema.json"] is AdoptionPlanV2
    assert PUBLIC_SCHEMAS["adoption-plan.v3.schema.json"] is AdoptionPlan
    assert PUBLIC_SCHEMAS["adoption-manifest.v1.schema.json"] is AdoptionManifestV1
    assert PUBLIC_SCHEMAS["adoption-manifest.v2.schema.json"] is AdoptionManifestV2
    assert PUBLIC_SCHEMAS["adoption-manifest.v3.schema.json"] is AdoptionManifest

    assert ProjectInspectionV1.model_fields["schema_version"].default == 1
    assert ProjectInspection.model_fields["schema_version"].default == 2
    assert "github_repository" not in ProjectInspectionV1.model_fields
    assert "github_repository" in ProjectInspection.model_fields

    assert "task_store_repository" not in AdoptionPlanV1.model_fields
    assert "task_store_repository" in AdoptionPlanV2.model_fields
    assert "task_store_team" not in AdoptionPlanV2.model_fields
    assert "task_store_team" in AdoptionPlan.model_fields
    assert "task_store_repository" not in AdoptionManifestV1.model_fields
    assert "task_store_repository" in AdoptionManifestV2.model_fields
    assert "task_store_team" not in AdoptionManifestV2.model_fields
    assert "task_store_team" in AdoptionManifest.model_fields
