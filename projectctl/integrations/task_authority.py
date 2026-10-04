from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from projectctl.core.enums import CapabilityState
from projectctl.core.errors import ConfigurationError
from projectctl.integrations.beads.claim import BeadsTaskClaimer
from projectctl.integrations.beads.client import BeadsClient
from projectctl.integrations.beads.completion import BeadsTaskCompletionWriter
from projectctl.integrations.beads.task_store import BeadsTaskStore
from projectctl.integrations.github.claim import GitHubTaskClaimer
from projectctl.git.publication import GitRemotePublisher
from projectctl.integrations.github.client import GitHubIssuesClient
from projectctl.integrations.github.completion import GitHubTaskCompletionWriter
from projectctl.integrations.github.task_store import GitHubIssuesTaskStore
from projectctl.ports.publication import TaskPublisher
from projectctl.ports.task_store import (
    TaskClaimer,
    TaskCompletionWriter,
    TaskStoreReader,
)
from projectctl.project.loader import load_project_config
from projectctl.schemas.delivery import TaskDeliveryPolicy
from projectctl.schemas.task_authority import TaskAuthorityCapabilities


@dataclass(frozen=True)
class TaskAuthority:
    capabilities: TaskAuthorityCapabilities
    delivery_policy: TaskDeliveryPolicy
    reader: TaskStoreReader
    claimer: TaskClaimer | None = None
    completion_writer: TaskCompletionWriter | None = None
    publisher: TaskPublisher | None = None

    @property
    def provider(self) -> str:
        return self.capabilities.provider

    def require_claimer(self) -> TaskClaimer:
        if (
            self.claimer is None
            or self.capabilities.claim != CapabilityState.SUPPORTED
            or self.capabilities.release != CapabilityState.SUPPORTED
        ):
            raise ConfigurationError(
                f"Task authority {self.provider!r} does not provide a supported "
                "claim/release lifecycle."
            )
        return self.claimer

    def require_completion_writer(self) -> TaskCompletionWriter:
        if (
            self.completion_writer is None
            or self.capabilities.complete != CapabilityState.SUPPORTED
            or self.capabilities.block_for_decision != CapabilityState.SUPPORTED
        ):
            raise ConfigurationError(
                f"Task authority {self.provider!r} does not provide supported "
                "block/complete lifecycle writes."
            )
        return self.completion_writer

    def require_publisher(self) -> TaskPublisher:
        if not self.delivery_policy.publication_required:
            raise ConfigurationError(
                f"Task authority {self.provider!r} does not require remote publication."
            )
        if self.publisher is None:
            raise ConfigurationError(
                f"Task authority {self.provider!r} requires publication but has no publisher."
            )
        return self.publisher

    def require_execution_ready(self) -> None:
        required = {
            "read": self.capabilities.read,
            "claim": self.capabilities.claim,
            "release": self.capabilities.release,
            "block_for_decision": self.capabilities.block_for_decision,
            "complete": self.capabilities.complete,
        }
        unsupported = [
            name for name, state in required.items()
            if state != CapabilityState.SUPPORTED
        ]
        if unsupported:
            raise ConfigurationError(
                f"Task authority {self.provider!r} is not execution-ready. "
                "Unsupported lifecycle operations: " + ", ".join(unsupported) + "."
            )


def task_authority_capabilities_for_provider(
    provider: str,
) -> TaskAuthorityCapabilities:
    if provider == "beads":
        return TaskAuthorityCapabilities(
            provider="beads",
            read=CapabilityState.SUPPORTED,
            claim=CapabilityState.SUPPORTED,
            release=CapabilityState.SUPPORTED,
            block_for_decision=CapabilityState.SUPPORTED,
            complete=CapabilityState.SUPPORTED,
            notes=[
                "Beads is the current full local execution-state authority."
            ],
        )
    if provider == "github":
        return TaskAuthorityCapabilities(
            provider="github",
            read=CapabilityState.SUPPORTED,
            claim=CapabilityState.SUPPORTED,
            release=CapabilityState.SUPPORTED,
            block_for_decision=CapabilityState.SUPPORTED,
            complete=CapabilityState.SUPPORTED,
            notes=[
                "M3.0c adds additive GitHub decision/completion labels.",
                "Completion is gated on verified remote publication.",
            ],
        )
    raise ConfigurationError(
        f"Task authority provider {provider!r} is not implemented."
    )


def task_delivery_policy_for_provider(provider: str) -> TaskDeliveryPolicy:
    if provider == "beads":
        return TaskDeliveryPolicy(
            provider="beads",
            publication_required=False,
            remote_name=None,
            release_claim_after_completion=False,
            release_claim_after_decision_block=False,
        )
    if provider == "github":
        return TaskDeliveryPolicy(
            provider="github",
            publication_required=True,
            remote_name="origin",
            release_claim_after_completion=True,
            release_claim_after_decision_block=True,
        )
    raise ConfigurationError(
        f"Task authority provider {provider!r} is not implemented."
    )


def task_delivery_policy(project_root: Path) -> TaskDeliveryPolicy:
    provider = load_project_config(project_root.resolve()).task_store.provider
    return task_delivery_policy_for_provider(provider)


def task_authority_capabilities(project_root: Path) -> TaskAuthorityCapabilities:
    provider = load_project_config(project_root.resolve()).task_store.provider
    return task_authority_capabilities_for_provider(provider)


def require_task_authority_execution_ready(project_root: Path) -> None:
    capabilities = task_authority_capabilities(project_root)
    required = {
        "read": capabilities.read,
        "claim": capabilities.claim,
        "release": capabilities.release,
        "block_for_decision": capabilities.block_for_decision,
        "complete": capabilities.complete,
    }
    unsupported = [
        name for name, state in required.items()
        if state != CapabilityState.SUPPORTED
    ]
    if unsupported:
        raise ConfigurationError(
            f"Task authority {capabilities.provider!r} is not execution-ready. "
            "Unsupported lifecycle operations: " + ", ".join(unsupported) + "."
        )


def resolve_task_authority(
    project_root: Path,
    *,
    read_cache_max_age_seconds: float | None = None,
) -> TaskAuthority:
    root = project_root.resolve()
    config = load_project_config(root)
    provider = config.task_store.provider
    capabilities = task_authority_capabilities_for_provider(provider)
    delivery_policy = task_delivery_policy_for_provider(provider)

    if provider == "beads":
        client = BeadsClient(root)
        return TaskAuthority(
            capabilities=capabilities,
            delivery_policy=delivery_policy,
            reader=BeadsTaskStore(root, client=client),
            claimer=BeadsTaskClaimer(root, client=client),
            completion_writer=BeadsTaskCompletionWriter(root, client=client),
        )

    if provider == "github":
        client = GitHubIssuesClient(
            root,
            repository=config.task_store.repository,
            cache_max_age_seconds=(
                config.task_store.cache_max_age_seconds
                if read_cache_max_age_seconds is None
                else read_cache_max_age_seconds
            ),
        )
        repository = config.task_store.repository
        if repository is None:
            raise ConfigurationError(
                "GitHub task authority requires task_store.repository."
            )
        return TaskAuthority(
            capabilities=capabilities,
            delivery_policy=delivery_policy,
            reader=GitHubIssuesTaskStore(
                root,
                repository=repository,
                client=client,
            ),
            claimer=GitHubTaskClaimer(
                root,
                repository=repository,
            ),
            completion_writer=GitHubTaskCompletionWriter(
                root,
                repository=repository,
                client=client,
            ),
            publisher=GitRemotePublisher(
                root,
                repository=repository,
                remote_name=delivery_policy.remote_name or "origin",
            ),
        )

    raise ConfigurationError(
        f"Task authority provider {provider!r} is not implemented."
    )
