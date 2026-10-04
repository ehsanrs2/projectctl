from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.core.enums import ResourceClass, RiskLevel, TaskStatus, TaskType
from projectctl.schemas.base import Priority, ProjectCtlModel, Signal5
from projectctl.schemas.config import RepoRelativePath


class TaskSource(ProjectCtlModel):
    provider: str
    external_id: str
    revision: str | None = None
    external_url: str | None = None
    observed_at: AwareDatetime | None = None


class TaskReferences(ProjectCtlModel):
    specs: list[RepoRelativePath] = Field(default_factory=list)
    plans: list[RepoRelativePath] = Field(default_factory=list)
    decisions: list[RepoRelativePath] = Field(default_factory=list)
    research: list[RepoRelativePath] = Field(default_factory=list)


class TaskHierarchy(ProjectCtlModel):
    parent: str | None = None
    sub_issues: list[str] = Field(default_factory=list)


class TaskMilestoneMetadata(ProjectCtlModel):
    number: int | None = None
    title: str
    state: str | None = None
    due_on: AwareDatetime | None = None
    external_url: str | None = None
    open_issues: int | None = None
    closed_issues: int | None = None


class TaskIssueField(ProjectCtlModel):
    field_id: str
    name: str
    data_type: str
    value: str | int | float | bool | list[str] | None = None


class TaskTeamMetadata(ProjectCtlModel):
    assignees: list[str] = Field(default_factory=list)
    issue_type: str | None = None
    milestone: TaskMilestoneMetadata | None = None
    issue_fields: list[TaskIssueField] = Field(default_factory=list)


class NormalizedTaskV1(ProjectCtlModel):
    id: str
    title: str
    source: TaskSource
    type: TaskType = TaskType.UNKNOWN
    status: TaskStatus
    priority: Priority = 5
    milestone: str | None = None
    created_at: AwareDatetime | None = None
    ready_since: AwareDatetime | None = None
    due_at: AwareDatetime | None = None
    dependencies: list[str] = Field(default_factory=list)
    blocks: list[str] = Field(default_factory=list)
    risk: RiskLevel = RiskLevel.UNKNOWN
    resource_class: ResourceClass = ResourceClass.UNKNOWN
    information_gain: Signal5 = 0
    human_decision_required: bool = False
    references: TaskReferences = Field(default_factory=TaskReferences)
    tags: list[str] = Field(default_factory=list)
    normalization_notes: list[str] = Field(default_factory=list)


class NormalizedTaskV2(ProjectCtlModel):
    id: str
    title: str
    source: TaskSource
    type: TaskType = TaskType.UNKNOWN
    status: TaskStatus
    priority: Priority = 5
    milestone: str | None = None
    created_at: AwareDatetime | None = None
    ready_since: AwareDatetime | None = None
    due_at: AwareDatetime | None = None
    dependencies: list[str] = Field(default_factory=list)
    blocks: list[str] = Field(default_factory=list)
    hierarchy: TaskHierarchy = Field(default_factory=TaskHierarchy)
    risk: RiskLevel = RiskLevel.UNKNOWN
    resource_class: ResourceClass = ResourceClass.UNKNOWN
    information_gain: Signal5 = 0
    human_decision_required: bool = False
    references: TaskReferences = Field(default_factory=TaskReferences)
    tags: list[str] = Field(default_factory=list)
    normalization_notes: list[str] = Field(default_factory=list)


class NormalizedTask(ProjectCtlModel):
    id: str
    title: str
    source: TaskSource
    type: TaskType = TaskType.UNKNOWN
    status: TaskStatus
    priority: Priority = 5
    milestone: str | None = None
    created_at: AwareDatetime | None = None
    ready_since: AwareDatetime | None = None
    due_at: AwareDatetime | None = None
    dependencies: list[str] = Field(default_factory=list)
    blocks: list[str] = Field(default_factory=list)
    hierarchy: TaskHierarchy = Field(default_factory=TaskHierarchy)
    team: TaskTeamMetadata = Field(default_factory=TaskTeamMetadata)
    risk: RiskLevel = RiskLevel.UNKNOWN
    resource_class: ResourceClass = ResourceClass.UNKNOWN
    information_gain: Signal5 = 0
    human_decision_required: bool = False
    references: TaskReferences = Field(default_factory=TaskReferences)
    tags: list[str] = Field(default_factory=list)
    normalization_notes: list[str] = Field(default_factory=list)


class TaskSnapshotV1(ProjectCtlModel):
    schema_kind: Literal["projectctl.task_snapshot"] = "projectctl.task_snapshot"
    schema_version: Literal[1] = 1
    provider: str
    captured_at: AwareDatetime
    source_revision: str | None = None
    tasks: list[NormalizedTaskV1] = Field(default_factory=list)


class TaskSnapshotV2(ProjectCtlModel):
    schema_kind: Literal["projectctl.task_snapshot"] = "projectctl.task_snapshot"
    schema_version: Literal[2] = 2
    provider: str
    captured_at: AwareDatetime
    source_revision: str | None = None
    tasks: list[NormalizedTaskV2] = Field(default_factory=list)


class TaskSnapshot(ProjectCtlModel):
    schema_kind: Literal["projectctl.task_snapshot"] = "projectctl.task_snapshot"
    schema_version: Literal[3] = 3
    provider: str
    captured_at: AwareDatetime
    source_revision: str | None = None
    tasks: list[NormalizedTask] = Field(default_factory=list)
