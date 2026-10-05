import json
from pathlib import Path

from projectctl.schemas.artifact import ArtifactMetadata
from projectctl.schemas.auto import AutoRunPolicy, AutoRunReport
from projectctl.schemas.capabilities import WorkerCapabilities, WorkerStrategyDecision
from projectctl.schemas.config import ProjectConfig, ProjectConfigV1, ProjectConfigV2, ProjectConfigV3, ProjectConfigV4, ProjectConfigV5, ProjectConfigV6
from projectctl.schemas.ownership import ExecutionOwnershipPolicy
from projectctl.schemas.delivery import (
    CodeDeliveryPolicy,
    CodeDeliveryPolicyV1,
    PublicationManifest,
    PublicationRequest,
    ReviewReceipt,
    ReviewRequest,
    TaskDeliveryPolicy,
)
from projectctl.schemas.evidence import EvidenceManifest, EvidenceManifestV1
from projectctl.schemas.github_cache import GitHubCacheEntry, GitHubCacheRequest
from projectctl.schemas.execution import (ExecutionPlan, ExecutionPlanV1, WorkerCheckpoint, WorkerCheckpointV1, WorkerRequest, WorkerRequestV1, WorkerResult)
from projectctl.schemas.integration import (
    IntegrationManifest,
    IntegrationManifestV1,
    IntegrationManifestV2,
    RecoveryReport,
)
from projectctl.schemas.onboarding import (
    AdoptionManifest,
    AdoptionManifestV1,
    AdoptionManifestV2,
    AdoptionManifestV3,
    AdoptionManifestV4,
    AdoptionPlan,
    AdoptionPlanV1,
    AdoptionPlanV2,
    AdoptionPlanV3,
    AdoptionPlanV4,
    ProjectInspection,
    ProjectInspectionV1,
    ProjectInspectionV2,
)
from projectctl.schemas.project_state import ProjectState
from projectctl.schemas.quota import QuotaSnapshot, QuotaSnapshotV1
from projectctl.schemas.run import ContextManifest, ContextManifestV1, RunManifest, RunManifestV1
from projectctl.schemas.scheduler import SchedulerDecision, SchedulerDecisionV1
from projectctl.schemas.status import ProjectStatus
from projectctl.schemas.task import TaskSnapshot, TaskSnapshotV1, TaskSnapshotV2
from projectctl.schemas.task_authority import TaskAuthorityCapabilities
from projectctl.schemas.task_claim import TaskClaim, TaskClaimRequest
from projectctl.schemas.verification import VerificationCatalog, VerificationManifest, VerificationManifestV1

PUBLIC_SCHEMAS = {
    "project-config.v1.schema.json": ProjectConfigV1,
    "project-config.v2.schema.json": ProjectConfigV2,
    "project-config.v3.schema.json": ProjectConfigV3,
    "project-config.v4.schema.json": ProjectConfigV4,
    "project-config.v5.schema.json": ProjectConfigV5,
    "project-config.v6.schema.json": ProjectConfigV6,
    "project-config.v7.schema.json": ProjectConfig,
    "worker-capabilities.v1.schema.json": WorkerCapabilities,
    "worker-strategy-decision.v1.schema.json": WorkerStrategyDecision,
    "quota-snapshot.v1.schema.json": QuotaSnapshotV1,
    "quota-snapshot.v2.schema.json": QuotaSnapshot,
    "task-snapshot.v1.schema.json": TaskSnapshotV1,
    "task-snapshot.v2.schema.json": TaskSnapshotV2,
    "task-snapshot.v3.schema.json": TaskSnapshot,
    "task-authority-capabilities.v1.schema.json": TaskAuthorityCapabilities,
    "execution-ownership-policy.v1.schema.json": ExecutionOwnershipPolicy,
    "task-delivery-policy.v1.schema.json": TaskDeliveryPolicy,
    "code-delivery-policy.v1.schema.json": CodeDeliveryPolicyV1,
    "code-delivery-policy.v2.schema.json": CodeDeliveryPolicy,
    "review-request.v1.schema.json": ReviewRequest,
    "review-receipt.v1.schema.json": ReviewReceipt,
    "publication-request.v1.schema.json": PublicationRequest,
    "publication-manifest.v1.schema.json": PublicationManifest,
    "task-claim-request.v1.schema.json": TaskClaimRequest,
    "task-claim.v1.schema.json": TaskClaim,
    "scheduler-decision.v1.schema.json": SchedulerDecisionV1,
    "scheduler-decision.v2.schema.json": SchedulerDecision,
    "project-state.v1.schema.json": ProjectState,
    "project-status.v1.schema.json": ProjectStatus,
    "run-manifest.v1.schema.json": RunManifestV1,
    "run-manifest.v2.schema.json": RunManifest,
    "context-manifest.v1.schema.json": ContextManifestV1,
    "context-manifest.v2.schema.json": ContextManifest,
    "execution-plan.v1.schema.json": ExecutionPlanV1,
    "execution-plan.v2.schema.json": ExecutionPlan,
    "worker-request.v1.schema.json": WorkerRequestV1,
    "worker-request.v2.schema.json": WorkerRequest,
    "worker-result.v1.schema.json": WorkerResult,
    "worker-checkpoint.v1.schema.json": WorkerCheckpointV1,
    "worker-checkpoint.v2.schema.json": WorkerCheckpoint,
    "verification-catalog.v1.schema.json": VerificationCatalog,
    "verification-manifest.v1.schema.json": VerificationManifestV1,
    "verification-manifest.v2.schema.json": VerificationManifest,
    "evidence-manifest.v1.schema.json": EvidenceManifestV1,
    "evidence-manifest.v2.schema.json": EvidenceManifest,
    "github-cache-request.v1.schema.json": GitHubCacheRequest,
    "github-cache-entry.v1.schema.json": GitHubCacheEntry,
    "artifact-metadata.v1.schema.json": ArtifactMetadata,
    "auto-run-policy.v1.schema.json": AutoRunPolicy,
    "auto-run-report.v1.schema.json": AutoRunReport,
    "integration-manifest.v1.schema.json": IntegrationManifestV1,
    "integration-manifest.v2.schema.json": IntegrationManifestV2,
    "integration-manifest.v3.schema.json": IntegrationManifest,
    "recovery-report.v1.schema.json": RecoveryReport,
    "project-inspection.v1.schema.json": ProjectInspectionV1,
    "project-inspection.v2.schema.json": ProjectInspectionV2,
    "project-inspection.v3.schema.json": ProjectInspection,
    "adoption-plan.v1.schema.json": AdoptionPlanV1,
    "adoption-plan.v2.schema.json": AdoptionPlanV2,
    "adoption-plan.v3.schema.json": AdoptionPlanV3,
    "adoption-plan.v4.schema.json": AdoptionPlanV4,
    "adoption-plan.v5.schema.json": AdoptionPlan,
    "adoption-manifest.v1.schema.json": AdoptionManifestV1,
    "adoption-manifest.v2.schema.json": AdoptionManifestV2,
    "adoption-manifest.v3.schema.json": AdoptionManifestV3,
    "adoption-manifest.v4.schema.json": AdoptionManifestV4,
    "adoption-manifest.v5.schema.json": AdoptionManifest,
}


def export_json_schemas(destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    written = []
    for filename in sorted(PUBLIC_SCHEMAS):
        model = PUBLIC_SCHEMAS[filename]
        path = destination / filename
        path.write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written
