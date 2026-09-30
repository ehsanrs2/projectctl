from typing import Protocol

from projectctl.schemas.quota import QuotaSnapshot


class QuotaProvider(Protocol):
    def get_snapshot(self, account: str) -> QuotaSnapshot: ...
