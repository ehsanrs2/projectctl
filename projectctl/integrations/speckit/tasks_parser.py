from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from projectctl.core.errors import TaskImportConflict

_PHASE_RE = re.compile(r"^##\s+(?:Phase\s+\d+\s*:\s*)?(?P<title>.+?)\s*$", re.IGNORECASE)
_TASK_RE = re.compile(
    r"^-\s*\[(?P<checked>[ xX])\]\s+"
    r"\[?(?P<id>T\d{3,})\]?\s+"
    r"(?P<parallel>\[P\]\s+)?"
    r"(?P<story>\[US\d+\]\s+)?"
    r"(?P<description>.+?)\s*$"
)


@dataclass(frozen=True)
class SpecKitTask:
    source_id: str
    description: str
    phase: str
    phase_index: int
    parallel: bool = False
    story: str | None = None
    checked: bool = False
    dependencies: tuple[str, ...] = field(default_factory=tuple)

    @property
    def title(self) -> str:
        return f"{self.source_id}: {self.description}"


@dataclass(frozen=True)
class ParsedSpecKitTasks:
    path: Path
    tasks: tuple[SpecKitTask, ...]


class SpecKitTasksParser:
    """Parse the strict Spec Kit checklist format and derive conservative execution edges.

    Dependency derivation mirrors Spec Kit's phase-by-phase execution rule: sequential
    tasks form barriers; consecutive [P] tasks share the same predecessor and the next
    sequential task waits for the entire parallel batch.
    """

    def parse(self, path: Path) -> ParsedSpecKitTasks:
        text = path.read_text(encoding="utf-8")
        phase = "Unphased"
        phase_index = 0
        raw_tasks: list[SpecKitTask] = []
        seen: set[str] = set()

        for line_no, line in enumerate(text.splitlines(), start=1):
            phase_match = _PHASE_RE.match(line)
            if phase_match:
                title = phase_match.group("title").strip()
                # Ignore documentation sections that are not task phases if no tasks follow;
                # phase boundaries are harmless and preserve source order.
                phase = title
                phase_index += 1
                continue

            match = _TASK_RE.match(line)
            if not match:
                continue
            source_id = match.group("id")
            if source_id in seen:
                raise TaskImportConflict(f"Duplicate Spec Kit task id {source_id} at line {line_no}.")
            seen.add(source_id)
            story_raw = match.group("story")
            story = story_raw.strip("[] ") if story_raw else None
            raw_tasks.append(
                SpecKitTask(
                    source_id=source_id,
                    description=match.group("description").strip(),
                    phase=phase,
                    phase_index=phase_index,
                    parallel=bool(match.group("parallel")),
                    story=story,
                    checked=match.group("checked").lower() == "x",
                )
            )

        if not raw_tasks:
            raise TaskImportConflict(f"No Spec Kit checklist tasks found in {path}.")

        return ParsedSpecKitTasks(path=path, tasks=tuple(self._derive_dependencies(raw_tasks)))

    @staticmethod
    def _derive_dependencies(tasks: list[SpecKitTask]) -> list[SpecKitTask]:
        result: list[SpecKitTask] = []
        frontier: set[str] = set()
        parallel_batch: set[str] = set()
        current_phase: int | None = None

        for task in tasks:
            if current_phase is None:
                current_phase = task.phase_index
            elif task.phase_index != current_phase:
                if parallel_batch:
                    frontier = set(parallel_batch)
                    parallel_batch.clear()
                current_phase = task.phase_index

            if task.parallel:
                deps = tuple(sorted(frontier))
                parallel_batch.add(task.source_id)
            else:
                deps = tuple(sorted(parallel_batch if parallel_batch else frontier))
                parallel_batch.clear()
                frontier = {task.source_id}

            result.append(
                SpecKitTask(
                    source_id=task.source_id,
                    description=task.description,
                    phase=task.phase,
                    phase_index=task.phase_index,
                    parallel=task.parallel,
                    story=task.story,
                    checked=task.checked,
                    dependencies=deps,
                )
            )

        return result
