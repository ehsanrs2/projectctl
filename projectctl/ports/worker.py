from pathlib import Path
from typing import Protocol

from projectctl.schemas.capabilities import WorkerCapabilities
from projectctl.schemas.execution import WorkerCheckpoint, WorkerRequest, WorkerResult


class WorkerAdapter(Protocol):
    def probe(self) -> WorkerCapabilities: ...

    def start(self, request: WorkerRequest, *, workspace: Path) -> WorkerResult: ...

    def resume(self, checkpoint: WorkerCheckpoint, *, workspace: Path) -> WorkerResult: ...

    def cancel(self, run_id: str) -> None: ...
