from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from projectctl.core.errors import ProviderUnavailableError, QuotaError
from projectctl.project.bootstrap import _global_init, projectctl_home
from projectctl.quota.codex_app_server import CodexAppServerQuotaProvider
from projectctl.quota.manual import ManualQuotaProvider
from projectctl.schemas.quota import QuotaSnapshot, QuotaWindow

SUPPORTED_QUOTA_PROVIDERS = {"manual", "codex_app_server"}


def _home(home: Path | None = None) -> Path:
    value = (home or projectctl_home()).resolve()
    _global_init(value)
    return value


def get_account_quota_provider(account: str, *, home: Path | None = None) -> str:
    root = _home(home)
    conn = sqlite3.connect(root / "state.sqlite")
    try:
        row = conn.execute(
            "SELECT provider FROM accounts WHERE account_id=?",
            (account,),
        ).fetchone()
    finally:
        conn.close()
    return str(row[0]) if row else "manual"


def set_account_quota_provider(
    account: str,
    provider: str,
    *,
    home: Path | None = None,
) -> str:
    if provider not in SUPPORTED_QUOTA_PROVIDERS:
        raise ProviderUnavailableError(
            f"Unsupported quota provider {provider!r}. "
            f"Choose one of: {', '.join(sorted(SUPPORTED_QUOTA_PROVIDERS))}."
        )
    root = _home(home)
    conn = sqlite3.connect(root / "state.sqlite")
    try:
        conn.execute(
            "INSERT OR IGNORE INTO accounts(account_id, provider, config_json) VALUES (?, ?, '{}')",
            (account, provider),
        )
        conn.execute(
            "UPDATE accounts SET provider=? WHERE account_id=?",
            (provider, account),
        )
        conn.commit()
    finally:
        conn.close()
    return provider


def resolve_quota_provider(account: str, *, home: Path | None = None):
    root = _home(home)
    provider = get_account_quota_provider(account, home=root)
    if provider == "manual":
        return ManualQuotaProvider(root)
    if provider == "codex_app_server":
        return CodexAppServerQuotaProvider(root)
    raise ProviderUnavailableError(f"Quota provider {provider!r} is not implemented.")


def unknown_quota_snapshot(account: str, provider: str) -> QuotaSnapshot:
    return QuotaSnapshot(
        provider=provider,
        account=account,
        observed_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
        five_hour=QuotaWindow(),
        weekly=QuotaWindow(),
    )


def read_current_quota(
    account: str,
    *,
    home: Path | None = None,
    fail_closed: bool = True,
) -> QuotaSnapshot:
    provider_name = get_account_quota_provider(account, home=home)
    try:
        return resolve_quota_provider(account, home=home).get_snapshot(account)
    except (ProviderUnavailableError, QuotaError):
        if not fail_closed:
            raise
        return unknown_quota_snapshot(account, provider_name)
