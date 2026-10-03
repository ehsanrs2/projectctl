from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from importlib import metadata

from projectctl import __version__
from projectctl.core.enums import (
    ApprovalPolicy,
    CapabilityState,
    ExecutionSandboxMode,
    WorkerMode,
)
from projectctl.core.time import utc_now
from projectctl.schemas.capabilities import (
    CapabilitySupport,
    PermissionCapabilities,
    WorkerCapabilities,
    WorkerRuntimeDescriptor,
)


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _numeric_version(value: str | None) -> tuple[int, ...] | None:
    if value is None:
        return None
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _codex_cli_version() -> str | None:
    binary = shutil.which("codex")
    if binary is None:
        return None
    result = subprocess.run(
        [binary, "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    if result.returncode != 0:
        return None
    output = (result.stdout or result.stderr).strip()
    match = re.search(r"(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?)", output)
    return match.group(1) if match else None


def _state(condition: bool | None) -> CapabilityState:
    if condition is True:
        return CapabilityState.SUPPORTED
    if condition is False:
        return CapabilityState.UNSUPPORTED
    return CapabilityState.UNKNOWN


@dataclass(frozen=True)
class CodexAdapterSurface:
    default_mode: bool = False
    plan_mode: bool = False
    goal_mode: bool = False
    sandbox_read_only: bool = False
    sandbox_workspace_write: bool = False
    sandbox_full_access: bool = False
    approval_deny_all: bool = False
    approval_auto_review: bool = False
    thread_resume: bool = False
    thread_fork: bool = False
    thread_compact: bool = False
    structured_output: bool = False
    skills: bool = False
    goal_pause_resume: bool = False


class CodexCapabilityProbe:
    """Version-only Codex capability probe.

    M1.2a deliberately does not start app-server. Runtime features that require
    live protocol discovery remain UNKNOWN until a later adapter performs a live
    probe. Adapter support is declared separately so provider capability is
    never mistaken for ProjectCTL capability.
    """

    def __init__(self, adapter: CodexAdapterSurface | None = None):
        self.adapter = adapter or CodexAdapterSurface()

    def probe(self) -> WorkerCapabilities:
        sdk_version = _package_version("openai-codex")
        runtime_pkg_version = _package_version("openai-codex-cli-bin")
        runtime_version = runtime_pkg_version or _codex_cli_version()

        runtime_present = runtime_version is not None
        sdk_present = sdk_version is not None
        parsed_runtime = _numeric_version(runtime_version)

        goal_runtime: bool | None
        if parsed_runtime is None:
            goal_runtime = None
        else:
            goal_runtime = parsed_runtime >= (0, 128, 0)

        def support(
            runtime: bool | None,
            adapter: bool,
            *,
            experimental: bool = False,
            note: str | None = None,
        ) -> CapabilitySupport:
            return CapabilitySupport(
                runtime=_state(runtime),
                adapter=_state(adapter),
                experimental=experimental,
                note=note,
            )

        permissions = PermissionCapabilities(
            sandboxes={
                ExecutionSandboxMode.READ_ONLY: support(
                    runtime_present and sdk_present,
                    self.adapter.sandbox_read_only,
                    note="Maps to Codex Sandbox.read_only.",
                ),
                ExecutionSandboxMode.WORKSPACE_WRITE: support(
                    runtime_present and sdk_present,
                    self.adapter.sandbox_workspace_write,
                    note="Maps to Codex Sandbox.workspace_write.",
                ),
                ExecutionSandboxMode.DANGER_FULL_ACCESS: support(
                    runtime_present and sdk_present,
                    self.adapter.sandbox_full_access,
                    note="Maps to Codex Sandbox.full_access.",
                ),
            },
            approvals={
                ApprovalPolicy.DENY_ALL: support(
                    sdk_present,
                    self.adapter.approval_deny_all,
                    note="Maps to public Python SDK ApprovalMode.deny_all.",
                ),
                ApprovalPolicy.AUTO_REVIEW: support(
                    sdk_present,
                    self.adapter.approval_auto_review,
                    note="Maps to public Python SDK ApprovalMode.auto_review.",
                ),
                ApprovalPolicy.EXPLICIT: support(
                    False if sdk_present else None,
                    False,
                    note=(
                        "ProjectCTL EXPLICIT has no implicit mapping in the current "
                        "public high-level Python SDK approval enum."
                    ),
                ),
            },
            scoped_network_requests=support(
                None,
                False,
                experimental=True,
                note="Requires live permission-capability probing before adapter enablement.",
            ),
            scoped_filesystem_read_requests=support(
                None,
                False,
                experimental=True,
                note="Requires live permission-capability probing before adapter enablement.",
            ),
            scoped_filesystem_write_requests=support(
                None,
                False,
                experimental=True,
                note="Requires live permission-capability probing before adapter enablement.",
            ),
        )

        return WorkerCapabilities(
            probe_kind="version_only",
            runtime=WorkerRuntimeDescriptor(
                provider="codex",
                sdk_name="openai-codex",
                sdk_version=sdk_version,
                runtime_name="openai-codex-cli-bin" if runtime_pkg_version else "codex",
                runtime_version=runtime_version,
                adapter_name="projectctl.codex",
                adapter_version=__version__,
                observed_at=utc_now(),
            ),
            modes={
                WorkerMode.DEFAULT: support(
                    runtime_present and sdk_present,
                    self.adapter.default_mode,
                    note="Default turns are part of the public Python SDK surface.",
                ),
                WorkerMode.PLAN: support(
                    None,
                    self.adapter.plan_mode,
                    experimental=True,
                    note=(
                        "Codex app-server has an experimental collaborationMode protocol, "
                        "but this version-only probe does not start app-server to verify "
                        "Plan availability in the installed runtime."
                    ),
                ),
                WorkerMode.GOAL: support(
                    goal_runtime,
                    self.adapter.goal_mode,
                    note=(
                        "Goals require Codex runtime 0.128.0 or newer. "
                        "ProjectCTL adapter support is declared independently."
                    ),
                ),
            },
            permissions=permissions,
            thread_resume=support(
                sdk_present,
                self.adapter.thread_resume,
                note="thread_resume is present in the public Python SDK.",
            ),
            thread_fork=support(
                runtime_present,
                self.adapter.thread_fork,
                experimental=True,
                note="Runtime protocol supports thread fork; adapter support is separate.",
            ),
            thread_compact=support(
                runtime_present,
                self.adapter.thread_compact,
                experimental=True,
                note="Runtime protocol supports thread compact; adapter support is separate.",
            ),
            structured_output=support(
                sdk_present,
                self.adapter.structured_output,
                note="Turn output_schema is supported by the Python SDK.",
            ),
            skills=support(
                sdk_present,
                self.adapter.skills,
                note="SkillInput is exported by the public Python SDK.",
            ),
            goal_pause_resume=support(
                goal_runtime,
                self.adapter.goal_pause_resume,
                experimental=True,
                note="Goal lifecycle exists in the current runtime/low-level SDK surface.",
            ),
            notes=[
                "Public Python SDK approvals are deny_all and auto_review; ProjectCTL EXPLICIT is not mapped implicitly.",
                "Codex thread_start defaults to auto_review, but ProjectCTL execution policy remains deny_all unless explicitly changed.",
                "Plan mode is never treated as a security boundary; ProjectCTL also requires read_only sandbox for planning.",
                "Provider runtime support and ProjectCTL adapter support are separate signals.",
            ],
        )
