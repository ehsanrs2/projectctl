from datetime import datetime, timedelta, timezone

from projectctl.core.enums import (
    ApprovalPolicy,
    CapabilityState,
    ExecutionSandboxMode,
    WorkerMode,
)
from projectctl.schemas.capabilities import (
    CapabilitySupport,
    PermissionCapabilities,
    WorkerCapabilities,
    WorkerRuntimeDescriptor,
)
from projectctl.workers.capability_digest import effective_capability_digest

NOW = datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)


def support():
    return CapabilitySupport(
        runtime=CapabilityState.SUPPORTED,
        adapter=CapabilityState.SUPPORTED,
        note="human note",
    )


def caps(observed_at, probe_kind, note):
    return WorkerCapabilities(
        probe_kind=probe_kind,
        runtime=WorkerRuntimeDescriptor(
            provider="codex",
            sdk_name="openai-codex",
            sdk_version="0.160.0",
            runtime_name="openai-codex-cli-bin",
            runtime_version="0.160.0",
            adapter_name="projectctl.codex",
            adapter_version="0.9.0",
            observed_at=observed_at,
        ),
        modes={
            WorkerMode.DEFAULT: support(),
            WorkerMode.PLAN: CapabilitySupport(),
            WorkerMode.GOAL: CapabilitySupport(),
        },
        permissions=PermissionCapabilities(
            sandboxes={
                ExecutionSandboxMode.READ_ONLY: support(),
                ExecutionSandboxMode.WORKSPACE_WRITE: support(),
            },
            approvals={ApprovalPolicy.DENY_ALL: support()},
        ),
        notes=[note],
    )


def test_effective_capability_digest_ignores_observation_metadata():
    first = caps(NOW, "version_only", "one")
    second = caps(NOW + timedelta(minutes=5), "live_runtime", "two")
    assert effective_capability_digest(first) == effective_capability_digest(second)


def test_effective_capability_digest_changes_with_runtime_version():
    first = caps(NOW, "version_only", "one")
    second = caps(NOW, "version_only", "one")
    second.runtime.runtime_version = "0.161.0"
    assert effective_capability_digest(first) != effective_capability_digest(second)
