from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from projectctl.core.errors import ConfigurationError
from projectctl.git.publication import GitRemotePublisher
from projectctl.ports.publication import TaskPublisher
from projectctl.ports.review_delivery import ReviewDeliveryAdapter
from projectctl.project.loader import load_project_config
from projectctl.schemas.delivery import CodeDeliveryPolicy


@dataclass(frozen=True)
class CodeDelivery:
    policy: CodeDeliveryPolicy
    publisher: TaskPublisher | None = None
    reviewer: ReviewDeliveryAdapter | None = None


def _review_provider(remote_identity: str | None) -> str | None:
    identity = str(remote_identity or "").strip().casefold()
    if identity.startswith("github.com/"):
        return "github"
    if identity.startswith("gitlab.com/"):
        return "gitlab"
    return None


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
            review_provider=None,
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
            review_provider=None,
            notes=[
                "Verified candidate publication uses an exact-base Git ref lease.",
                "Remote write/branch policy is proven only by the real publication attempt.",
            ],
        )

    assert delivery.mode == "review_required"
    review_provider = _review_provider(transport.remote_identity)
    return CodeDeliveryPolicy(
        mode="review_required",
        supported=review_provider is not None,
        publication_required=True,
        completion_evidence="review_receipt",
        transport_mode="git_remote",
        remote_name=transport.remote_name,
        remote_identity=transport.remote_identity,
        review_provider=review_provider,
        notes=(
            [
                f"Review delivery uses the built-in {review_provider} adapter.",
                "ProjectCTL creates/reconciles review requests but never auto-merges them.",
                "Canonical task completion waits for an externally merged exact candidate.",
            ]
            if review_provider is not None
            else [
                "Review-required delivery has no built-in adapter for this Git host.",
                "Autonomous execution fails closed before claiming work.",
            ]
        ),
    )


def resolve_code_delivery(project_root: Path) -> CodeDelivery:
    root = project_root.resolve()
    policy = code_delivery_policy(root)
    if policy.mode == "local":
        return CodeDelivery(policy=policy)

    if policy.mode == "review_required":
        if not policy.supported or policy.review_provider is None:
            return CodeDelivery(policy=policy)
        assert policy.remote_name is not None
        assert policy.remote_identity is not None
        if policy.review_provider == "github":
            from projectctl.integrations.review.github import GitHubReviewDeliveryAdapter

            reviewer = GitHubReviewDeliveryAdapter(
                root,
                remote_name=policy.remote_name,
                remote_identity=policy.remote_identity,
            )
        elif policy.review_provider == "gitlab":
            from projectctl.integrations.review.gitlab import GitLabReviewDeliveryAdapter

            reviewer = GitLabReviewDeliveryAdapter(
                root,
                remote_name=policy.remote_name,
                remote_identity=policy.remote_identity,
            )
        else:
            raise ConfigurationError(
                f"Unsupported review delivery provider {policy.review_provider!r}."
            )
        return CodeDelivery(policy=policy, reviewer=reviewer)

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
    delivery = resolve_code_delivery(project_root)
    policy = delivery.policy
    if not policy.supported:
        raise ConfigurationError(
            f"Code delivery mode {policy.mode!r} is not execution-ready for "
            f"remote {policy.remote_identity or 'local'}."
        )
    if policy.mode == "review_required" and delivery.reviewer is None:
        raise ConfigurationError(
            "Review-required delivery has no runtime review adapter."
        )
