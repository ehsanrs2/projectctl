from __future__ import annotations

from uuid import UUID

from projectctl.core.errors import TaskStoreError


def normalize_linear_team_id(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return str(UUID(raw))
    except (ValueError, AttributeError) as exc:
        raise TaskStoreError(
            "Linear team identity must be a canonical UUID."
        ) from exc
