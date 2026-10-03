from projectctl.core.enums import Ownership

DEFAULT_OWNERSHIP = {
    "docs/PROJECT.md": Ownership.HUMAN,
    "docs/ROADMAP.md": Ownership.HUMAN,
    "docs/CONSTRAINTS.md": Ownership.HUMAN,
    "docs/PROJECT_STATE.yaml": Ownership.HUMAN,
    "AGENTS.md": Ownership.HUMAN,
    "docs/generated/STATUS.md": Ownership.GENERATED,
    "docs/generated/BUDGET.md": Ownership.GENERATED,
    "docs/generated/TASKBOARD.md": Ownership.GENERATED,
}
