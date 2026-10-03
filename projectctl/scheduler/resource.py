from projectctl.core.enums import ResourceClass, TaskType
from projectctl.schemas.task import NormalizedTask


def effective_resource_class(task: NormalizedTask) -> ResourceClass:
    if task.resource_class != ResourceClass.UNKNOWN:
        return task.resource_class
    if task.type in {TaskType.DOCS, TaskType.CHORE}:
        return ResourceClass.SMALL
    if task.type in {TaskType.ARCHITECTURE, TaskType.RESEARCH, TaskType.EXPERIMENT, TaskType.SECURITY}:
        return ResourceClass.LARGE
    if task.type in {TaskType.FEATURE, TaskType.BUG, TaskType.REFACTOR}:
        return ResourceClass.MEDIUM
    # Generic imported tasks are conservatively treated as medium. This inference is
    # explicit in the scheduler layer; the canonical task remains UNKNOWN.
    return ResourceClass.MEDIUM
