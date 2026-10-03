from __future__ import annotations

from pathlib import Path

from projectctl.core.digest import digest
from projectctl.core.enums import ImportAction
from projectctl.core.errors import DigestMismatchError, TaskImportConflict, TaskStoreError
from projectctl.core.paths import resolve_inside_repo
from projectctl.core.time import utc_now
from projectctl.project.state import load_project_state, semantic_project_state_digest
from projectctl.integrations.beads.client import BeadsClient
from projectctl.integrations.speckit.tasks_parser import ParsedSpecKitTasks, SpecKitTask, SpecKitTasksParser
from projectctl.schemas.importing import ImportItem, ImportPlan, ImportResult
from projectctl.storage.import_bindings import get_binding, upsert_binding


_SOURCE_TYPE = "speckit_tasks"


def _task_digest(task: SpecKitTask) -> str:
    return digest(
        {
            "source_id": task.source_id,
            "description": task.description,
            "phase": task.phase,
            "phase_index": task.phase_index,
            "parallel": task.parallel,
            "story": task.story,
            "checked": task.checked,
            "dependencies": list(task.dependencies),
        }
    )


def _description(source_path: str, task: SpecKitTask) -> str:
    lines = [
        "Imported from Spec Kit by ProjectCTL.",
        "",
        f"Source: {source_path}#{task.source_id}",
        f"Phase: {task.phase}",
        f"Parallel: {'yes' if task.parallel else 'no'}",
    ]
    if task.story:
        lines.append(f"Story: {task.story}")
    lines.extend(["", "Task:", task.description])
    return "\n".join(lines)


class SpecKitBeadsImporter:
    def __init__(self, project_root: Path, client: BeadsClient | None = None):
        self.project_root = project_root.resolve()
        self._client = client
        self.parser = SpecKitTasksParser()

    @property
    def client(self) -> BeadsClient:
        if self._client is None:
            self._client = BeadsClient(self.project_root)
        return self._client

    def _relative_source(self, source: str | Path) -> tuple[Path, str]:
        raw = Path(source)
        if raw.is_absolute():
            resolved = raw.resolve()
            try:
                rel = resolved.relative_to(self.project_root).as_posix()
            except ValueError as exc:
                raise TaskImportConflict("Spec Kit tasks source must be inside the project repository.") from exc
            source_path = resolved
        else:
            rel = raw.as_posix()
            source_path = resolve_inside_repo(self.project_root, rel, must_exist=True)
        if not source_path.is_file():
            raise TaskImportConflict(f"Spec Kit tasks source is not a file: {source_path}")
        return source_path, rel

    def _parse(self, source: str | Path) -> tuple[ParsedSpecKitTasks, str, str]:
        path, rel = self._relative_source(source)
        parsed = self.parser.parse(path)
        source_digest = digest(path.read_text(encoding="utf-8"))
        return parsed, rel, source_digest

    def preview(self, source: str) -> ImportPlan:
        parsed, rel, source_digest = self._parse(source)
        project_state = load_project_state(self.project_root, allow_missing=True)
        context_digest = semantic_project_state_digest(project_state)
        milestone = project_state.active_milestone.id if project_state.active_milestone else None
        items: list[ImportItem] = []
        for task in parsed.tasks:
            task_digest = _task_digest(task)
            binding = get_binding(self.project_root, _SOURCE_TYPE, rel, task.source_id)
            if binding is None:
                action = ImportAction.CREATE
                target_id = None
                reason = None
            elif binding.task_store_provider != "beads":
                action = ImportAction.CONFLICT
                target_id = binding.external_task_id
                reason = f"Existing binding belongs to provider {binding.task_store_provider}."
            elif binding.source_digest == task_digest:
                action = ImportAction.UNCHANGED
                target_id = binding.external_task_id
                reason = None
            else:
                # M0.3 deliberately fails closed rather than silently editing a task whose
                # dependency semantics may have changed. Reconciliation is a later slice.
                action = ImportAction.CONFLICT
                target_id = binding.external_task_id
                reason = "Source task changed since its last import; update reconciliation is not enabled in M0.3."
            items.append(ImportItem(source_id=task.source_id, target_id=target_id, action=action, reason=reason))
        return ImportPlan(
            source_type=_SOURCE_TYPE,
            source_path=rel,
            source_digest=source_digest,
            context_digest=context_digest,
            milestone=milestone,
            items=items,
        )

    def apply(self, plan: ImportPlan) -> ImportResult:
        if plan.source_type != _SOURCE_TYPE:
            raise TaskImportConflict(f"Unsupported import source type: {plan.source_type}")
        parsed, rel, current_digest = self._parse(plan.source_path)
        if rel != plan.source_path or current_digest != plan.source_digest:
            raise DigestMismatchError("Spec Kit tasks source changed after import preview; run preview again.")
        current_state = load_project_state(self.project_root, allow_missing=True)
        current_context_digest = semantic_project_state_digest(current_state)
        if plan.context_digest is not None and current_context_digest != plan.context_digest:
            raise DigestMismatchError(
                "Project state changed after import preview; run preview again before assigning milestone metadata."
            )
        conflicts = [item for item in plan.items if item.action == ImportAction.CONFLICT]
        if conflicts:
            ids = ", ".join(item.source_id for item in conflicts)
            raise TaskImportConflict(f"Import contains conflicts: {ids}")

        tasks = {task.source_id: task for task in parsed.tasks}
        target_ids: dict[str, str] = {}
        result_items: list[ImportItem] = []

        for item in plan.items:
            task = tasks.get(item.source_id)
            if task is None:
                raise DigestMismatchError(f"Task {item.source_id} disappeared after preview.")
            task_digest = _task_digest(task)
            binding = get_binding(self.project_root, _SOURCE_TYPE, rel, task.source_id)

            if item.action == ImportAction.UNCHANGED:
                if binding is None or binding.source_digest != task_digest:
                    raise DigestMismatchError(f"Import binding for {task.source_id} changed after preview.")
                target_id = binding.external_task_id
                try:
                    self.client.show(target_id)
                except TaskStoreError as exc:
                    raise TaskImportConflict(
                        f"Imported task {task.source_id} is bound to missing/unreadable Beads issue {target_id}."
                    ) from exc
            elif item.action == ImportAction.CREATE:
                if binding is not None:
                    # Crash-safe resume: another partial apply may already have created it.
                    target_id = binding.external_task_id
                else:
                    labels = [f"milestone:{plan.milestone}"] if plan.milestone else []
                    target_id = self.client.create_issue(
                        title=task.title,
                        description=_description(rel, task),
                        issue_type="task",
                        priority=2,
                        labels=labels,
                    )
                    upsert_binding(
                        self.project_root,
                        source_type=_SOURCE_TYPE,
                        source_path=rel,
                        source_task_id=task.source_id,
                        provider="beads",
                        external_task_id=target_id,
                        source_digest=task_digest,
                    )
            else:
                raise TaskImportConflict(f"Unsupported import action in apply: {item.action}")

            if task.checked:
                current = self.client.show(target_id)
                if str(current.get("status") or "").lower() not in {"closed", "done", "completed"}:
                    self.client.close_issue(target_id, "Imported as completed from Spec Kit tasks.md")

            target_ids[task.source_id] = target_id
            result_items.append(
                ImportItem(source_id=task.source_id, target_id=target_id, action=item.action, reason=item.reason)
            )

        # Reconcile desired blocking dependencies on every apply. This makes an interrupted
        # import resumable even when issue creation succeeded before dependency creation.
        for task in parsed.tasks:
            child_id = target_ids[task.source_id]
            for source_dep in task.dependencies:
                dep_id = target_ids.get(source_dep)
                if not dep_id:
                    raise TaskImportConflict(f"Missing imported target for dependency {source_dep} of {task.source_id}.")
                self.client.ensure_blocking_dependency(child_id, dep_id)

        return ImportResult(
            source_type=_SOURCE_TYPE,
            source_path=rel,
            source_digest=plan.source_digest,
            context_digest=plan.context_digest,
            milestone=plan.milestone,
            applied_at=utc_now(),
            items=result_items,
        )
