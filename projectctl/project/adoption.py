from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from projectctl import __version__
from projectctl.core.errors import DigestMismatchError, RepositoryContractError, TaskStoreError
from projectctl.core.paths import resolve_inside_repo
from projectctl.core.time import utc_now
from projectctl.integrations.github.repository import normalize_github_repository
from projectctl.integrations.linear.team import normalize_linear_team_id
from projectctl.project.bootstrap import _global_init, _slug, projectctl_home
from projectctl.project.inspection import inspect_repository
from projectctl.project.state import PROJECT_STATE_PATH, initial_project_state, write_project_state
from projectctl.schemas.config import (
    CodeTransportConfig,
    KnowledgeConfig,
    KnowledgeRoleBinding,
    ProjectConfig,
    ProjectIdentity,
    TaskStoreConfig,
)
from projectctl.schemas.onboarding import AdoptionManifest, AdoptionPlan, KnowledgeBinding, ProjectInspection
from projectctl.storage.sqlite import initialize_project_state_db, initialize_telemetry_db


@dataclass
class AdoptionResult:
    project_root: Path
    created: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)
    unresolved_decisions: list[str] = field(default_factory=list)


@contextmanager
def _adoption_lock(root: Path):
    lock_dir = Path(tempfile.gettempdir()) / "projectctl-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:24]
    lock = lock_dir / f"adopt-{key}.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RepositoryContractError(f"Another ProjectCTL adoption appears to be running for {root}") from exc
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _remove_created_dir(path: Path, *, stop_at: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    parent = path.parent
    while parent != stop_at and parent.is_relative_to(stop_at):
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def _binding_map(bindings: list[KnowledgeBinding]) -> dict[str, list[str]]:
    return {b.role: list(b.sources) for b in bindings}


def plan_adoption(
    inspection: ProjectInspection,
    *,
    task_store_provider: str | None = None,
    task_store_repository: str | None = None,
    task_store_team: str | None = None,
) -> AdoptionPlan:
    if inspection.classification != "existing_unmanaged":
        raise RepositoryContractError(
            f"Adoption requires an existing unmanaged project; found `{inspection.classification}`."
        )
    if inspection.conflicts:
        raise RepositoryContractError("Adoption cannot proceed while inspection conflicts exist: " + ", ".join(inspection.conflicts))

    detected = inspection.detected_task_systems
    provider = task_store_provider
    if provider is None and len(detected) == 1:
        provider = detected[0]

    if provider != "github" and task_store_repository is not None:
        raise RepositoryContractError(
            "task_store_repository is only supported with the GitHub task store."
        )
    if provider != "linear" and task_store_team is not None:
        raise RepositoryContractError(
            "task_store_team is only supported with the Linear task store."
        )

    repository = None
    if provider == "github":
        raw_repository = task_store_repository or inspection.github_repository
        if raw_repository is not None:
            repository = normalize_github_repository(raw_repository)
            if repository is None:
                raise RepositoryContractError(
                    "GitHub task repository must use the owner/repository form."
                )

    team = None
    if provider == "linear":
        try:
            team = normalize_linear_team_id(task_store_team)
        except TaskStoreError as exc:
            raise RepositoryContractError(str(exc)) from exc

    unresolved = [d for d in inspection.unresolved_decisions if not d.startswith("task_store")]
    if provider is None:
        unresolved.append("task_store")
    if provider == "github" and not repository:
        unresolved.append("task_store_repository")
    if provider == "linear" and not team:
        unresolved.append("task_store_team")

    root = Path(inspection.project_root)
    preserve_set = {a.path for a in inspection.assets}
    create = [
        ".projectctl/config.yaml",
        ".projectctl/state.sqlite",
        ".projectctl/telemetry.sqlite",
        ".projectctl/adoption.yaml",
    ]
    state_path = resolve_inside_repo(root, PROJECT_STATE_PATH, must_exist=False)
    if state_path.exists():
        preserve_set.add(PROJECT_STATE_PATH)
    else:
        create.append(PROJECT_STATE_PATH)

    for rel in ["docs/generated", "evidence"]:
        path = resolve_inside_repo(root, rel, must_exist=False)
        if path.exists():
            preserve_set.add(rel)
        else:
            create.append(rel)
    preserve = sorted(preserve_set)

    return AdoptionPlan(
        project_root=inspection.project_root,
        created_at=utc_now(),
        baseline_commit=inspection.baseline_commit,
        repository_fingerprint=inspection.repository_fingerprint,
        dirty=inspection.dirty,
        preserve=preserve,
        create=create,
        knowledge_bindings=inspection.suggested_bindings,
        task_store_provider=provider,
        task_store_repository=repository,
        task_store_team=team,
        unresolved_decisions=sorted(set(unresolved)),
        conflicts=list(inspection.conflicts),
    )


def _knowledge_from_plan(plan: AdoptionPlan) -> KnowledgeConfig:
    values = _binding_map(plan.knowledge_bindings)
    return KnowledgeConfig(
        project_overview=KnowledgeRoleBinding(sources=values.get("project_overview", [])),
        roadmap=KnowledgeRoleBinding(sources=values.get("roadmap", [])),
        constraints=KnowledgeRoleBinding(sources=values.get("constraints", [])),
        architecture=KnowledgeRoleBinding(sources=values.get("architecture", [])),
        decisions=KnowledgeRoleBinding(sources=values.get("decisions", [])),
    )


def _register_global(root: Path, project_id: str, instance_id: str) -> None:
    _global_init(projectctl_home())
    conn = sqlite3.connect(projectctl_home() / "state.sqlite")
    try:
        now = utc_now().isoformat()
        conn.execute(
            """
            INSERT INTO project_registry(project_instance_id, project_id, project_root, registered_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_instance_id) DO UPDATE SET
              project_id=excluded.project_id,
              project_root=excluded.project_root,
              last_seen_at=excluded.last_seen_at
            """,
            (instance_id, project_id, str(root), now, now),
        )
        conn.commit()
    finally:
        conn.close()


def apply_adoption(plan: AdoptionPlan, *, allow_dirty: bool = False) -> AdoptionResult:
    root = Path(plan.project_root).resolve()
    with _adoption_lock(root):
        current = inspect_repository(root)
        if current.repository_fingerprint != plan.repository_fingerprint:
            raise DigestMismatchError("Repository changed after adoption plan was created; inspect again.")
        if current.dirty and not allow_dirty:
            raise RepositoryContractError(
                "Working tree contains uncommitted changes. Re-run with --allow-dirty only after reviewing the dry-run plan."
            )
        if plan.unresolved_decisions:
            raise RepositoryContractError(
                "Adoption plan has unresolved decisions: " + ", ".join(plan.unresolved_decisions)
            )
        if (root / ".projectctl").exists():
            raise RepositoryContractError(".projectctl already exists; refusing brownfield adoption over managed state.")

        result = AdoptionResult(project_root=root, preserved=list(plan.preserve))
        staging_parent = root / ".projectctl-adopt-staging"
        if staging_parent.exists():
            raise RepositoryContractError(f"Staging path already exists and will not be overwritten: {staging_parent}")
        staging_parent.mkdir()
        created_dirs: list[Path] = []
        created_files: list[Path] = []
        committed_ctl = False

        try:
            staged_ctl = staging_parent / ".projectctl"
            staged_ctl.mkdir()
            for name in ["runs", "cache", "locks"]:
                (staged_ctl / name).mkdir()

            provider = plan.task_store_provider or "unresolved"
            if provider == "github" and plan.task_store_repository:
                code_transport = CodeTransportConfig(
                    mode="git_remote",
                    remote_name="origin",
                    remote_identity=f"github.com/{plan.task_store_repository}",
                )
            else:
                code_transport = CodeTransportConfig(mode="local")

            config = ProjectConfig(
                project=ProjectIdentity(id=_slug(root.name), name=root.name),
                task_store=TaskStoreConfig(
                    provider=provider,
                    repository=plan.task_store_repository,
                    team=plan.task_store_team,
                ),
                code_transport=code_transport,
                knowledge=_knowledge_from_plan(plan),
            )
            (staged_ctl / "config.yaml").write_text(
                yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
            )
            initialize_project_state_db(staged_ctl / "state.sqlite")
            initialize_telemetry_db(staged_ctl / "telemetry.sqlite")

            instance_id = str(uuid.uuid4())
            conn = sqlite3.connect(staged_ctl / "state.sqlite")
            try:
                conn.execute("INSERT INTO project_metadata(key, value) VALUES (?, ?)", ("project_instance_id", instance_id))
                conn.execute("INSERT INTO project_metadata(key, value) VALUES (?, ?)", ("projectctl_version", __version__))
                conn.commit()
            finally:
                conn.close()

            manifest = AdoptionManifest(
                adopted_at=utc_now(),
                baseline_commit=plan.baseline_commit,
                repository_fingerprint=plan.repository_fingerprint,
                preserved=plan.preserve,
                created=plan.create,
                knowledge_bindings=plan.knowledge_bindings,
                task_store_provider=plan.task_store_provider,
                task_store_repository=plan.task_store_repository,
                task_store_team=plan.task_store_team,
                unresolved_decisions=plan.unresolved_decisions,
            )
            (staged_ctl / "adoption.yaml").write_text(
                yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
            )

            # Commit point: no pre-existing repository content is changed.
            staged_ctl.rename(root / ".projectctl")
            committed_ctl = True
            result.created.extend([
                ".projectctl/config.yaml", ".projectctl/state.sqlite",
                ".projectctl/telemetry.sqlite", ".projectctl/adoption.yaml",
            ])

            state_path = resolve_inside_repo(root, PROJECT_STATE_PATH, must_exist=False)
            if not state_path.exists():
                write_project_state(root, initial_project_state(config.project.id))
                created_files.append(state_path)
                result.created.append(PROJECT_STATE_PATH)

            for rel in ["docs/generated", "evidence"]:
                path = resolve_inside_repo(root, rel, must_exist=False)
                if not path.exists():
                    path.mkdir(parents=True)
                    created_dirs.append(path)
                    result.created.append(rel)

            # Global registration happens last. A failure rolls back only ProjectCTL-created local artifacts.
            _register_global(root, config.project.id, instance_id)
            result.unresolved_decisions = list(plan.unresolved_decisions)
            return result
        except Exception:
            if committed_ctl and (root / ".projectctl").exists():
                shutil.rmtree(root / ".projectctl", ignore_errors=True)
            for path in reversed(created_files):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            for path in reversed(created_dirs):
                _remove_created_dir(path, stop_at=root)
            raise
        finally:
            shutil.rmtree(staging_parent, ignore_errors=True)

