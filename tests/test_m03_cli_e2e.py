import json
import os
import stat
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from projectctl.cli.app import app

runner = CliRunner()


FAKE_BD = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path

root = Path.cwd()
state_path = root / ".fake-bd.json"
state = json.loads(state_path.read_text()) if state_path.exists() else {"issues": {}, "deps": [], "next": 1}

def save():
    state_path.write_text(json.dumps(state))

def issues():
    return list(state["issues"].values())

def arg(name, default=None):
    if name not in sys.argv: return default
    i = sys.argv.index(name)
    return sys.argv[i+1] if i+1 < len(sys.argv) else default

args = sys.argv[1:]
if args == ["--version"]:
    print("bd version 1.2.2")
    raise SystemExit(0)

cmd = args[0] if args else ""
if cmd == "create":
    issue_id = f"bd-{state['next']}"; state["next"] += 1
    title = args[1]
    state["issues"][issue_id] = {
        "id": issue_id, "title": title, "description": arg("--description", ""),
        "status": "open", "priority": int(arg("--priority", 2)), "issue_type": arg("--type", "task"),
        "created_at": "2026-09-30T10:00:00Z", "updated_at": "2026-09-30T10:00:00Z",
        "labels": [x for x in (arg("-l", "") or "").split(",") if x]
    }
    save(); print(json.dumps(state["issues"][issue_id])); raise SystemExit(0)
if cmd == "list":
    print(json.dumps(issues())); raise SystemExit(0)
if cmd == "ready":
    closed = {i for i,v in state["issues"].items() if v["status"] == "closed"}
    out=[]
    for item in issues():
        if item["status"] != "open": continue
        blockers=[d for c,d in state["deps"] if c == item["id"] and d not in closed]
        if not blockers: out.append(item)
    print(json.dumps(out)); raise SystemExit(0)
if cmd == "blocked":
    closed = {i for i,v in state["issues"].items() if v["status"] == "closed"}
    out=[]
    for item in issues():
        blockers=[d for c,d in state["deps"] if c == item["id"] and d not in closed]
        if item["status"] == "open" and blockers:
            value=dict(item); value["blocked_by"]=[{"id":b} for b in blockers]; out.append(value)
    print(json.dumps(out)); raise SystemExit(0)
if cmd == "show":
    issue_id=args[1]; value=state["issues"].get(issue_id)
    if not value: print("not found", file=sys.stderr); raise SystemExit(1)
    print(json.dumps([value])); raise SystemExit(0)
if cmd == "dep" and args[1] == "list":
    child=args[2]
    print(json.dumps([{"id":d,"dependency_type":"blocks"} for c,d in state["deps"] if c==child])); raise SystemExit(0)
if cmd == "dep" and args[1] == "add":
    edge=[args[2],args[3]]
    if edge not in state["deps"]: state["deps"].append(edge)
    save(); raise SystemExit(0)
if cmd == "close":
    issue_id=args[1]; state["issues"][issue_id]["status"]="closed"; save(); raise SystemExit(0)
print("unsupported fake bd command: " + " ".join(args), file=sys.stderr)
raise SystemExit(2)
'''


def test_import_then_tasks_end_to_end(tmp_path: Path, monkeypatch):
    repo = tmp_path / "demo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    assert runner.invoke(app, ["init", str(repo)]).exit_code == 0
    (repo / ".beads").mkdir()

    bin_dir = tmp_path / "bin"; bin_dir.mkdir()
    bd = bin_dir / "bd"; bd.write_text(FAKE_BD); bd.chmod(bd.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))

    feature = repo / "specs" / "001-auth"; feature.mkdir(parents=True)
    source = feature / "tasks.md"
    source.write_text(
        "## Phase 1: Setup\n"
        "- [ ] T001 Create auth package in src/auth/__init__.py\n"
        "- [ ] T002 [P] Create token model in src/auth/token.py\n"
        "- [ ] T003 [P] Create config in src/auth/config.py\n"
        "- [ ] T004 Wire auth in src/app.py\n"
    )

    imported = runner.invoke(app, ["import-tasks", str(source), "--project", str(repo), "--json"])
    assert imported.exit_code == 0, imported.output
    payload = json.loads(imported.output)
    assert len(payload["items"]) == 4

    ready = runner.invoke(app, ["tasks", "--project", str(repo), "--state", "ready", "--json"])
    assert ready.exit_code == 0, ready.output
    ready_payload = json.loads(ready.output)
    assert [t["title"].split(":", 1)[0] for t in ready_payload["tasks"]] == ["T001"]

    blocked = runner.invoke(app, ["tasks", "--project", str(repo), "--state", "blocked", "--json"])
    assert blocked.exit_code == 0, blocked.output
    blocked_payload = json.loads(blocked.output)
    assert len(blocked_payload["tasks"]) == 3
