from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from projectctl.core.enums import CapabilityState
from projectctl.core.errors import ConfigurationError
from projectctl.git.task_claim import GitRemoteTaskClaimer
from projectctl.integrations.delivery import (
    code_delivery_policy,
    require_code_delivery_execution_ready,
)
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


def execution_ownership_policy(project_root: Path) -> ExecutionOwnershipPolicy:
    """Resolve ownership intent without touching provider/runtime dependencies."""
    root = project_root.resolve()
    config = load_project_config(root)
    provider = config.task_store.provider
    transport = config.code_transport

    if provider == "beads":
        return ExecutionOwnershipPolicy(
            task_provider=provider,
            strategy="task_native",
            scope="local",
            transport_mode=transport.mode,
            remote_name=transport.remote_name,
            remote_identity=transport.remote_identity,
            notes=["Beads task ownership remains task-native and local."],
        )

    if transport.mode == "local":
        return ExecutionOwnershipPolicy(
            task_provider=provider,
            strategy="local_lock",
            scope="local",
            transport_mode="local",
            notes=[
                "Ownership is serialized only through the ProjectCTL project filesystem.",
                "This is not a cross-machine distributed claim.",
            ],
        )

    if not transport.remote_name or not transport.remote_identity:
        raise ConfigurationError(
            "git_remote execution ownership requires remote_name and remote_identity."
        )
    return ExecutionOwnershipPolicy(
        task_provider=provider,
        strategy="git_ref_lease",
        scope="distributed",
        transport_mode="git_remote",
        remote_name=transport.remote_name,
        remote_identity=transport.remote_identity,
        notes=[
            "Ownership uses an exact Git remote-ref lease independent of task provider."
        ],
    )


def resolve_execution_ownership(
    project_root: Path,
    *,
    task_authority=None,
) -> ExecutionOwnership:
    root = project_root.resolve()
    config = load_project_config(root)
    provider = config.task_store.provider
    transport = config.code_transport
    policy = execution_ownership_policy(root)

    # Beads has a task-native local claim protocol. Code publication transport
    # does not replace that canonical task ownership primitive.
    if provider == "beads":
        authority = task_authority or resolve_task_authority(root)
        return ExecutionOwnership(
            policy=policy,
            claimer=authority.require_claimer(),
        )

    if transport.mode == "local":
        return ExecutionOwnership(
            policy=policy,
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
        authority = task_authority or resolve_task_authority(root)
        claimer: TaskClaimer = authority.require_claimer()
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
        policy=policy.model_copy(update={"notes": [note]}),
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

    # Policy resolution validates ownership intent without requiring the
    # provider runtime. The actual claimer is resolved only when a claim is
    # attempted.
    execution_ownership_policy(root)
    require_code_delivery_execution_ready(root)

    delivery = code_delivery_policy(root)
    if capabilities.provider == "github" and delivery.mode not in {
        "direct_git",
        "review_required",
    }:
        raise ConfigurationError(
            "GitHub task completion requires remote-visible delivery evidence: "
            "use code_delivery.mode='direct_git' or 'review_required'."
        )
