from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from projectctl.core.enums import CapabilityState
from projectctl.core.errors import ConfigurationError
from projectctl.git.task_claim import GitRemoteTaskClaimer
from projectctl.integrations.beads.claim import BeadsTaskClaimer
from projectctl.integrations.beads.client import BeadsClient
from projectctl.integrations.github.claim import GitHubTaskClaimer
from projectctl.integrations.local_claim import LocalTaskClaimer
from projectctl.integrations.task_authority import (
    resolve_task_authority,
    task_authority_capabilities,
)
from projectctl.ports.task_store import TaskClaimer
from projectctl.project.loader import load_project_config
from projectctl.schemas.ownership import ExecutionOwnershipPolicy


@dataclass(frozen=True)
class ExecutionOwnership:
    policy: ExecutionOwnershipPolicy
    claimer: TaskClaimer


def resolve_execution_ownership(project_root: Path) -> ExecutionOwnership:
    root = project_root.resolve()
    config = load_project_config(root)
    provider = config.task_store.provider
    transport = config.code_transport

    # Beads has a task-native local claim protocol. Code publication transport
    # does not replace that canonical task ownership primitive.
    if provider == "beads":
        client = BeadsClient(root)
        return ExecutionOwnership(
            policy=ExecutionOwnershipPolicy(
                task_provider=provider,
                strategy="task_native",
                scope="local",
                transport_mode=transport.mode,
                remote_name=transport.remote_name,
                remote_identity=transport.remote_identity,
                notes=[
                    "Beads task ownership remains task-native and local.",
                ],
            ),
            claimer=BeadsTaskClaimer(root, client=client),
        )

    if transport.mode == "local":
        return ExecutionOwnership(
            policy=ExecutionOwnershipPolicy(
                task_provider=provider,
                strategy="local_lock",
                scope="local",
                transport_mode="local",
                notes=[
                    "Ownership is serialized only through the ProjectCTL project filesystem.",
                    "This is not a cross-machine distributed claim.",
                ],
            ),
            claimer=LocalTaskClaimer(root, provider=provider),
        )

    assert transport.mode == "git_remote"
    remote_name = transport.remote_name
    remote_identity = transport.remote_identity
    if not remote_name or not remote_identity:
        raise ConfigurationError(
            "git_remote execution ownership requires remote_name and remote_identity."
        )

    # Preserve the historical GitHub implementation when code/task repository
    # identities coincide, including its old durable recovery behavior.
    if (
        provider == "github"
        and config.task_store.repository
        and remote_identity == f"github.com/{config.task_store.repository}"
    ):
        claimer: TaskClaimer = GitHubTaskClaimer(
            root,
            repository=config.task_store.repository,
            remote_name=remote_name,
        )
        note = "Historical GitHub claim namespace retained for compatibility."
    else:
        claimer = GitRemoteTaskClaimer(
            root,
            provider=provider,
            remote_name=remote_name,
            remote_identity=remote_identity,
        )
        note = (
            "Task ownership uses a generic exact Git remote-ref lease independent "
            "of the task authority provider or Git hosting vendor."
        )

    return ExecutionOwnership(
        policy=ExecutionOwnershipPolicy(
            task_provider=provider,
            strategy="git_ref_lease",
            scope="distributed",
            transport_mode="git_remote",
            remote_name=remote_name,
            remote_identity=remote_identity,
            notes=[note],
        ),
        claimer=claimer,
    )


def require_project_execution_ready(project_root: Path) -> None:
    """Require task lifecycle semantics plus an independent ownership strategy."""
    root = project_root.resolve()
    capabilities = task_authority_capabilities(root)
    required_task_ops = {
        "read": capabilities.read,
        "block_for_decision": capabilities.block_for_decision,
        "complete": capabilities.complete,
    }
    unsupported = [
        name for name, state in required_task_ops.items()
        if state != CapabilityState.SUPPORTED
    ]
    if unsupported:
        raise ConfigurationError(
            f"Task authority {capabilities.provider!r} is not execution-ready. "
            "Unsupported canonical task operations: "
            + ", ".join(unsupported)
            + "."
        )

    # Resolution itself validates the configured ownership transport.
    resolve_execution_ownership(root)

    config = load_project_config(root)
    if capabilities.provider == "github" and config.code_transport.mode != "git_remote":
        raise ConfigurationError(
            "GitHub task completion currently requires a git_remote code transport "
            "because completion is gated on remote-visible publication."
        )
