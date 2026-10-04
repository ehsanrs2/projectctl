from typing import Protocol

from projectctl.schemas.delivery import PublicationManifest, PublicationRequest


class TaskPublisher(Protocol):
    def publish(self, request: PublicationRequest) -> PublicationManifest: ...
    def reconcile(self, request: PublicationRequest) -> PublicationManifest: ...
