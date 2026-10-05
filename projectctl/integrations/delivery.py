from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from projectctl.core.errors import ConfigurationError
from projectctl.git.publication import GitRemotePublisher
from projectctl.ports.publication import TaskPublisher
from projectctl.project.loader import load_project_config
from projectctl.schemas.delivery import CodeDeliveryPolicy


@dataclass(frozen=True)
class CodeDelivery:
    policy: CodeDeliveryPolicy
    publisher: TaskPublisher | None = None


def code_delivery_policy(project_root: Path) -> CodeDeliveryPolicy:
    root = project_root.resolve()
    config = load_project_config(root)
    delivery = config.code_delivery
    transport = config.code_transport

    if delivery.mode == "local":
        return CodeDeliveryPolicy(
            mode="local",
            supported=True,
            publication_required=False,
            completion_evidence="evidence_manifest",
            transport_mode=transport.mode,
            remote_name=transport.remote_name,
            remote_identity=transport.remote_identity,
            notes=[
                "Verified code is integrated only into the local Git target.",
                "No network publication is required before canonical task completion.",
            ],
        )

    if transport.mode != "git_remote":
        raise ConfigurationError(
            f"{delivery.mode} delivery requires code_transport.mode='git_remote'."
        )
    if not transport.remote_name or not transport.remote_identity:
        raise ConfigurationError(
            f"{delivery.mode} delivery requires a configured Git remote identity."
        )

    if delivery.mode == "direct_git":
        return CodeDeliveryPolicy(
            mode="direct_git",
            supported=True,
            publication_required=True,
            completion_evidence="publication_manifest",
            transport_mode="git_remote",
            remote_name=transport.remote_name,
            remote_identity=transport.remote_identity,
            notes=[
                "Verified candidate publication uses an exact-base Git ref lease.",
                "Remote write/branch policy is proven only by the real publication attempt.",
            ],
        )

    assert delivery.mode == "review_required"
    return CodeDeliveryPolicy(
        mode="review_required",
        supported=False,
        publication_required=True,
        completion_evidence="review_receipt",
        transport_mode="git_remote",
        remote_name=transport.remote_name,
        remote_identity=transport.remote_identity,
        notes=[
            "Review-required delivery is modeled but no PR/MR adapter is implemented yet.",
            "Autonomous execution therefore fails closed before claiming work.",
        ],
    )


def resolve_code_delivery(project_root: Path) -> CodeDelivery:
    root = project_root.resolve()
    policy = code_delivery_policy(root)
    if policy.mode == "local":
        return CodeDelivery(policy=policy)

    if policy.mode == "review_required":
        return CodeDelivery(policy=policy)

    assert policy.mode == "direct_git"
    assert policy.remote_name is not None
    assert policy.remote_identity is not None
    return CodeDelivery(
        policy=policy,
        publisher=GitRemotePublisher(
            root,
            remote_name=policy.remote_name,
            remote_identity=policy.remote_identity,
        ),
    )


def require_code_delivery_execution_ready(project_root: Path) -> None:
    policy = code_delivery_policy(project_root)
    if not policy.supported:
        raise ConfigurationError(
            f"Code delivery mode {policy.mode!r} is not execution-ready. "
            "A review delivery adapter is required before autonomous execution."
        )
