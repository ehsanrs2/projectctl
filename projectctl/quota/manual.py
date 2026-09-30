from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from projectctl.core.enums import ConfidenceLevel, QuotaSource
from projectctl.core.errors import QuotaError
from projectctl.core.time import utc_now
from projectctl.project.bootstrap import _global_init, projectctl_home
from projectctl.schemas.quota import QuotaSnapshot, QuotaWindow


class ManualQuotaProvider:
    """Global, account-scoped quota provider backed by ~/.projectctl/state.sqlite."""

    provider = "manual"

    def __init__(self, home: Path | None = None):
        self.home = (home or projectctl_home()).resolve()
        _global_init(self.home)
        self.db_path = self.home / "state.sqlite"

    def set_snapshot(
        self,
        *,
        account: str,
        five_hour: float | None,
        weekly: float | None,
        five_hour_reset_at: datetime | None = None,
        weekly_reset_at: datetime | None = None,
        observed_at: datetime | None = None,
    ) -> QuotaSnapshot:
        observed_at = observed_at or utc_now()
        snapshot = QuotaSnapshot(
            provider=self.provider,
            account=account,
            observed_at=observed_at,
            five_hour=QuotaWindow(
                remaining_ratio=five_hour,
                reset_at=five_hour_reset_at,
                source=QuotaSource.MANUAL if five_hour is not None else QuotaSource.UNKNOWN,
                confidence=ConfidenceLevel.MEDIUM if five_hour is not None else ConfidenceLevel.UNKNOWN,
            ),
            weekly=QuotaWindow(
                remaining_ratio=weekly,
                reset_at=weekly_reset_at,
                source=QuotaSource.MANUAL if weekly is not None else QuotaSource.UNKNOWN,
                confidence=ConfidenceLevel.MEDIUM if weekly is not None else ConfidenceLevel.UNKNOWN,
            ),
        )
        payload = json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO accounts(account_id, provider, config_json) VALUES (?, ?, '{}')",
                (account, self.provider),
            )
            conn.execute(
                "UPDATE accounts SET provider=? WHERE account_id=?",
                (self.provider, account),
            )
            conn.execute(
                "INSERT INTO quota_observations(account_id, observed_at, snapshot_json) VALUES (?, ?, ?)",
                (account, observed_at.isoformat(), payload),
            )
            conn.commit()
        finally:
            conn.close()
        return snapshot

    def get_snapshot(self, account: str) -> QuotaSnapshot:
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT snapshot_json FROM quota_observations WHERE account_id=? ORDER BY id DESC LIMIT 1",
                (account,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return QuotaSnapshot(
                provider=self.provider,
                account=account,
                observed_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
                five_hour=QuotaWindow(),
                weekly=QuotaWindow(),
            )
        try:
            return QuotaSnapshot.model_validate(json.loads(row[0]))
        except Exception as exc:  # corrupt persistent state must fail loudly
            raise QuotaError(f"Invalid stored quota snapshot for account {account}: {exc}") from exc
