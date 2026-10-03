# Project workflow

Project intent lives in `docs/` and `specs/`.

`docs/PROJECT_STATE.yaml` is the human-managed structured source for the current goal and active milestone.
Beads is the canonical task tracker when `task_store.provider: beads`.
Generated files under `docs/generated/` must not be edited manually.
`projectctl.verification.yaml` is human-managed verification policy and workers must not modify it.
ProjectCTL owns `.projectctl/` operational state and scheduling metadata.
Do not create parallel task tracking systems.
Architecture changes require an ADR.
Do not modify requirements implicitly.
