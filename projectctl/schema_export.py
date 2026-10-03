import json
from pathlib import Path

from projectctl.schemas.artifact import ArtifactMetadata
from projectctl.schemas.capabilities import WorkerCapabilities, WorkerStrategyDecision
from projectctl.schemas.config import ProjectConfig
from projectctl.schemas.evidence import EvidenceManifest, EvidenceManifestV1
from projectctl.schemas.execution import (ExecutionPlan, ExecutionPlanV1, WorkerCheckpoint, WorkerRequest, WorkerRequestV1, WorkerResult)
from projectctl.schemas.onboarding import AdoptionManifest, AdoptionPlan, ProjectInspection
from projectctl.schemas.project_state import ProjectState
from projectctl.schemas.quota import QuotaSnapshot
from projectctl.schemas.run import ContextManifest, ContextManifestV1, RunManifest, RunManifestV1
from projectctl.schemas.scheduler import SchedulerDecision, SchedulerDecisionV1
from projectctl.schemas.status import ProjectStatus
from projectctl.schemas.task import TaskSnapshot
from projectctl.schemas.verification import VerificationCatalog, VerificationManifest, VerificationManifestV1

PUBLIC_SCHEMAS = {
    "project-config.v1.schema.json": ProjectConfig,
    "worker-capabilities.v1.schema.json": WorkerCapabilities,
    "worker-strategy-decision.v1.schema.json": WorkerStrategyDecision,
    "quota-snapshot.v1.schema.json": QuotaSnapshot,
    "task-snapshot.v1.schema.json": TaskSnapshot,
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
    "worker-checkpoint.v1.schema.json": WorkerCheckpoint,
    "verification-catalog.v1.schema.json": VerificationCatalog,
    "verification-manifest.v1.schema.json": VerificationManifestV1,
    "verification-manifest.v2.schema.json": VerificationManifest,
    "evidence-manifest.v1.schema.json": EvidenceManifestV1,
    "evidence-manifest.v2.schema.json": EvidenceManifest,
    "artifact-metadata.v1.schema.json": ArtifactMetadata,
    "project-inspection.v1.schema.json": ProjectInspection,
    "adoption-plan.v1.schema.json": AdoptionPlan,
    "adoption-manifest.v1.schema.json": AdoptionManifest,
}


def export_json_schemas(destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, model in PUBLIC_SCHEMAS.items():
        path = destination / filename
        path.write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written
