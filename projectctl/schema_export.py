import json
from pathlib import Path

from projectctl.schemas.artifact import ArtifactMetadata
from projectctl.schemas.config import ProjectConfig
from projectctl.schemas.quota import QuotaSnapshot
from projectctl.schemas.run import ContextManifest, RunManifest
from projectctl.schemas.scheduler import SchedulerDecision
from projectctl.schemas.task import TaskSnapshot
from projectctl.schemas.onboarding import AdoptionManifest, AdoptionPlan, ProjectInspection

PUBLIC_SCHEMAS = {
    "project-config.v1.schema.json": ProjectConfig,
    "quota-snapshot.v1.schema.json": QuotaSnapshot,
    "task-snapshot.v1.schema.json": TaskSnapshot,
    "scheduler-decision.v1.schema.json": SchedulerDecision,
    "run-manifest.v1.schema.json": RunManifest,
    "context-manifest.v1.schema.json": ContextManifest,
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
