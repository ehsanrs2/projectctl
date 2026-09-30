from pathlib import Path

from projectctl.integrations.speckit.tasks_parser import SpecKitTasksParser


def test_parser_derives_parallel_batches_and_phase_barriers(tmp_path: Path):
    source = tmp_path / "tasks.md"
    source.write_text(
        "# Tasks\n\n"
        "## Phase 1: Setup\n"
        "- [ ] T001 Create structure in src/\n"
        "- [ ] T002 [P] Add config in src/config.py\n"
        "- [ ] T003 [P] Add logging in src/logging.py\n"
        "- [ ] T004 Wire setup in src/app.py\n\n"
        "## Phase 2: User Story 1\n"
        "- [ ] T005 [US1] Implement endpoint in src/api.py\n"
        "- [ ] T006 [P] [US1] Add API tests in tests/test_api.py\n"
        "- [ ] T007 [US1] Finish integration in src/app.py\n",
        encoding="utf-8",
    )

    parsed = SpecKitTasksParser().parse(source)
    tasks = {task.source_id: task for task in parsed.tasks}

    assert tasks["T001"].dependencies == ()
    assert tasks["T002"].dependencies == ("T001",)
    assert tasks["T003"].dependencies == ("T001",)
    assert tasks["T004"].dependencies == ("T002", "T003")
    assert tasks["T005"].dependencies == ("T004",)
    assert tasks["T006"].dependencies == ("T005",)
    assert tasks["T007"].dependencies == ("T006",)
    assert tasks["T005"].story == "US1"


def test_parser_accepts_bracketed_task_id(tmp_path: Path):
    source = tmp_path / "tasks.md"
    source.write_text("## Phase 1: Setup\n- [ ] [T001] Do the thing in src/x.py\n", encoding="utf-8")
    parsed = SpecKitTasksParser().parse(source)
    assert parsed.tasks[0].source_id == "T001"
