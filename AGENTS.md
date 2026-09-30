# Project workflow

Project intent lives in `docs/` and `specs/`.

Beads is the canonical task tracker when `task_store.provider: beads`.
Generated files under `docs/generated/` must not be edited manually.
ProjectCTL owns `.projectctl/` operational state and scheduling metadata.
Do not create parallel task tracking systems.
Architecture changes require an ADR.
Do not modify requirements implicitly.
