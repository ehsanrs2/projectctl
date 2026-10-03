from typing import Protocol

from projectctl.schemas.capabilities import WorkerCapabilities


class WorkerCapabilityProbe(Protocol):
    def probe(self) -> WorkerCapabilities: ...
