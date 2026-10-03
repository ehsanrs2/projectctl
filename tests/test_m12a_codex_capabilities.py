from projectctl.core.enums import (
    ApprovalPolicy,
    CapabilityState,
    ExecutionSandboxMode,
    WorkerMode,
)
from projectctl.workers.codex.capabilities import (
    CodexAdapterSurface,
    CodexCapabilityProbe,
)


def test_codex_probe_separates_runtime_and_adapter_support(monkeypatch):
    versions = {
        "openai-codex": "0.160.0",
        "openai-codex-cli-bin": "0.160.0",
    }
    monkeypatch.setattr(
        "projectctl.workers.codex.capabilities._package_version",
        lambda name: versions.get(name),
    )
    monkeypatch.setattr(
        "projectctl.workers.codex.capabilities._codex_cli_version",
        lambda: None,
    )

    caps = CodexCapabilityProbe().probe()

    assert caps.probe_kind == "version_only"
    assert caps.runtime.sdk_version == "0.160.0"
    assert caps.runtime.runtime_version == "0.160.0"
    assert caps.modes[WorkerMode.DEFAULT].runtime == CapabilityState.SUPPORTED
    assert caps.modes[WorkerMode.DEFAULT].adapter == CapabilityState.UNSUPPORTED
    assert caps.modes[WorkerMode.PLAN].runtime == CapabilityState.UNKNOWN
    assert caps.modes[WorkerMode.GOAL].runtime == CapabilityState.SUPPORTED
    assert (
        caps.permissions.approvals[ApprovalPolicy.EXPLICIT].runtime
        == CapabilityState.UNSUPPORTED
    )
    assert (
        caps.permissions.sandboxes[ExecutionSandboxMode.WORKSPACE_WRITE].adapter
        == CapabilityState.UNSUPPORTED
    )


def test_codex_probe_can_declare_adapter_surface_without_conflating_plan(monkeypatch):
    versions = {
        "openai-codex": "0.160.0",
        "openai-codex-cli-bin": "0.160.0",
    }
    monkeypatch.setattr(
        "projectctl.workers.codex.capabilities._package_version",
        lambda name: versions.get(name),
    )
    monkeypatch.setattr(
        "projectctl.workers.codex.capabilities._codex_cli_version",
        lambda: None,
    )

    caps = CodexCapabilityProbe(
        CodexAdapterSurface(
            default_mode=True,
            goal_mode=True,
            sandbox_read_only=True,
            sandbox_workspace_write=True,
            approval_deny_all=True,
            thread_resume=True,
            goal_pause_resume=True,
            structured_output=True,
        )
    ).probe()

    assert caps.modes[WorkerMode.DEFAULT].usable is True
    assert caps.modes[WorkerMode.GOAL].usable is True
    # Adapter declaration alone is insufficient: version-only probing cannot
    # verify the experimental collaboration-mode surface.
    assert caps.modes[WorkerMode.PLAN].usable is False


def test_goal_runtime_support_has_explicit_minimum_version(monkeypatch):
    versions = {
        "openai-codex": "0.127.0",
        "openai-codex-cli-bin": "0.127.0",
    }
    monkeypatch.setattr(
        "projectctl.workers.codex.capabilities._package_version",
        lambda name: versions.get(name),
    )
    monkeypatch.setattr(
        "projectctl.workers.codex.capabilities._codex_cli_version",
        lambda: None,
    )

    caps = CodexCapabilityProbe(
        CodexAdapterSurface(goal_mode=True)
    ).probe()
    assert caps.modes[WorkerMode.GOAL].runtime == CapabilityState.UNSUPPORTED
    assert caps.modes[WorkerMode.GOAL].usable is False


def test_missing_codex_install_is_reported_not_crashed(monkeypatch):
    monkeypatch.setattr(
        "projectctl.workers.codex.capabilities._package_version",
        lambda name: None,
    )
    monkeypatch.setattr(
        "projectctl.workers.codex.capabilities._codex_cli_version",
        lambda: None,
    )
    caps = CodexCapabilityProbe().probe()
    assert caps.runtime.sdk_version is None
    assert caps.runtime.runtime_version is None
    assert caps.modes[WorkerMode.DEFAULT].runtime == CapabilityState.UNSUPPORTED
