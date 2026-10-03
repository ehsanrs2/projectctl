import json

from typer.testing import CliRunner

from projectctl.cli.entry import app

runner = CliRunner()


def test_worker_capabilities_command_is_available_without_codex_extra():
    result = runner.invoke(app, ["worker", "capabilities", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_kind"] == "projectctl.worker_capabilities"
    assert payload["runtime"]["provider"] == "codex"
    assert "default" in payload["modes"]
    assert "plan" in payload["modes"]
    assert "goal" in payload["modes"]
