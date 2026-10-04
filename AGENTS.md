# Project workflow

Project intent lives in `docs/` and `specs/`.

Read `docs/PROJECTCTL_BLUEPRINT.md` before architecture or roadmap work. It is the
human-managed source for the high-level product vision, architecture invariants, authority map,
and roadmap shape.
`docs/PROJECT_STATE.yaml` is the only structured source for the current goal and active milestone.
The configured `task_store` is the canonical task execution-state authority.
Generated files under `docs/generated/` must not be edited manually.
`projectctl.verification.yaml` is human-managed verification policy and workers must not modify it.
ProjectCTL owns `.projectctl/` operational state and scheduling metadata.
Do not create parallel task tracking systems.
Architecture changes require an ADR. If they change the high-level architecture or roadmap,
update `docs/PROJECTCTL_BLUEPRINT.md` in the same change.
Do not modify requirements implicitly.
