from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from projectctl.core.time import utc_now


def record_event(project_root: Path, event_type: str, payload: Any) -> None:
    db = project_root / ".projectctl" / "telemetry.sqlite"
    if not db.exists():
        return
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json")
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO events(created_at, event_type, payload_json) VALUES (?, ?, ?)",
            (utc_now().isoformat(), event_type, json.dumps(payload, sort_keys=True, separators=(",", ":"))),
        )
        conn.commit()
    finally:
        conn.close()
