import inspect

import pytest

openai_codex = pytest.importorskip("openai_codex")

from openai_codex import (
    ApprovalMode,
    Codex,
    CodexConfig,
    ExternalMessage,
    Sandbox,
    Thread,
    TurnHandle,
)


def test_pinned_codex_public_surface_matches_adapter_contract():
    config = CodexConfig(
        cwd="/tmp",
        client_name="projectctl",
        client_title="ProjectCTL",
        client_version="0.9.0",
        experimental_api=True,
        config_overrides=("sandbox_workspace_write.network_access=false",),
    )
    assert config.client_name == "projectctl"
    assert ApprovalMode.deny_all is not None
    assert Sandbox.read_only is not None
    assert Sandbox.workspace_write is not None

    message = ExternalMessage(
        tool_name="projectctl_task",
        namespace="projectctl",
        content="task",
    )
    assert message.tool_name == "projectctl_task"

    start_params = set(inspect.signature(Codex.thread_start).parameters)
    assert {
        "approval_mode",
        "cwd",
        "developer_instructions",
        "ephemeral",
        "model",
        "sandbox",
        "config",
    } <= start_params

    run_params = set(inspect.signature(Thread.run).parameters)
    assert {
        "approval_mode",
        "cwd",
        "model",
        "output_schema",
        "sandbox",
    } <= run_params

    turn_params = set(inspect.signature(Thread.turn).parameters)
    assert {
        "approval_mode",
        "cwd",
        "model",
        "output_schema",
        "sandbox",
    } <= turn_params

    resume_params = set(inspect.signature(Codex.thread_resume).parameters)
    assert {
        "approval_mode",
        "cwd",
        "developer_instructions",
        "model",
        "sandbox",
        "config",
    } <= resume_params

    assert "self" in inspect.signature(TurnHandle.interrupt).parameters
