"""
Path-containment tests for TaskExecutionService (Fix-161).

The service runs unattended every two minutes (check_and_execute) and writes
LLM-planned file paths into repos that docker-compose.sprint.yml bind-mounts
read-write into zero-api (/projects/zero, /projects/legion, /vault). Before
Fix-161 the target was a bare `Path(project_path) / step.file_path`, which:

  * honoured absolute paths (pathlib drops the left side entirely),
  * honoured `..`,
  * joined the planner's "projects/<slug>/" echo ONTO project_path, and
  * mkdir(parents=True)'d whatever fell out of that.

The observed damage was a fabricated
`C:/code/zero/projects/zero/skills/_archive/hn/scripts/` tree plus an LLM
rewrite of an archived .js file. These tests pin every gate that closes it.
"""

import asyncio

import pytest

from app.services.task_execution_service import ExecutionStep, TaskExecutionService


def _step(action: str, file_path: str) -> ExecutionStep:
    return ExecutionStep(
        step_num=1,
        action=action,
        file_path=file_path,
        description="d",
        instructions="i",
    )


@pytest.fixture()
def svc() -> TaskExecutionService:
    return TaskExecutionService()


# ---------------------------------------------------------------- _resolve_target


def test_resolves_a_normal_relative_path(svc, tmp_path):
    target, rel, reason = svc._resolve_target(str(tmp_path), "backend/app/x.py")
    assert reason == ""
    assert rel == "backend/app/x.py"
    assert target == (tmp_path / "backend" / "app" / "x.py").resolve()


def test_absolute_posix_path_is_refused(svc, tmp_path):
    target, _, reason = svc._resolve_target(str(tmp_path), "/projects/legion/backend/app/x.py")
    assert target is None
    assert "absolute path refused" in reason


def test_absolute_windows_path_is_refused(svc, tmp_path):
    target, _, reason = svc._resolve_target(str(tmp_path), r"C:\code\Legion\backend\x.py")
    assert target is None
    assert "absolute path refused" in reason


def test_parent_traversal_is_refused(svc, tmp_path):
    target, _, reason = svc._resolve_target(str(tmp_path), "../legion/backend/app/x.py")
    assert target is None
    assert "parent traversal refused" in reason


def test_duplicate_project_prefix_is_stripped(svc, tmp_path):
    """The 2026-08-01 regression: signals carry /projects/zero/<rel>, so the
    planner echoes the prefix and it used to be joined a second time."""
    root = tmp_path / "zero"
    root.mkdir()
    target, rel, reason = svc._resolve_target(str(root), "projects/zero/backend/app/x.py")
    assert reason == ""
    assert rel == "backend/app/x.py"
    assert "projects" not in target.parts


def test_unrelated_projects_dir_is_preserved(svc, tmp_path):
    """Only a prefix naming THIS project is redundant; a real ./projects tree
    belonging to some other slug must still resolve normally."""
    root = tmp_path / "zero"
    root.mkdir()
    _, rel, reason = svc._resolve_target(str(root), "projects/other/x.py")
    assert reason == ""
    assert rel == "projects/other/x.py"


@pytest.mark.parametrize(
    "path",
    [
        "skills/_archive/intelligence-suite/scripts/scan.js",
        "attic/autostart-legacy/install.py",
        ".git/config",
        "frontend/node_modules/react/index.js",
        ".claude/rules/00-critical.md",
    ],
)
def test_never_write_directories_are_refused(svc, tmp_path, path):
    target, _, reason = svc._resolve_target(str(tmp_path), path)
    assert target is None
    assert "non-writable directory" in reason


def test_similarly_named_file_is_not_blocked(svc, tmp_path):
    """Segment matching, not substring matching — archive_service.py is fine."""
    _, rel, reason = svc._resolve_target(str(tmp_path), "backend/app/services/archive_service.py")
    assert reason == ""
    assert rel == "backend/app/services/archive_service.py"


def test_empty_path_is_refused(svc, tmp_path):
    target, _, reason = svc._resolve_target(str(tmp_path), "   ")
    assert target is None
    assert "empty file path" in reason


# ------------------------------------------------------------------ _execute_step


def test_execute_step_refuses_escaping_path_without_calling_llm(svc, tmp_path, monkeypatch):
    async def _boom(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("LLM must not be called for a refused path")

    monkeypatch.setattr(svc, "_call_ollama", _boom)

    result = asyncio.run(
        svc._execute_step(
            _step("create_file", "/projects/legion/backend/app/x.py"),
            {"project_path": str(tmp_path)},
        )
    )
    assert result["file_written"] is False
    assert "absolute path refused" in result["message"]


def test_protected_patterns_match_the_resolved_path(svc, tmp_path):
    """A protected pattern must still bite after the project-prefix strip."""
    root = tmp_path / "zero"
    root.mkdir()
    result = asyncio.run(
        svc._execute_step(
            _step("create_file", "projects/zero/backend/alembic/versions/060_x.py"),
            {"project_path": str(root)},
        )
    )
    assert result["file_written"] is False
    assert "protected path: alembic/" in result["message"]


# ------------------------------------------------------------------- _modify_file


def test_modify_missing_file_does_not_create_it(svc, tmp_path):
    missing = tmp_path / "skills" / "hn" / "hn.py"
    result = asyncio.run(svc._modify_file(missing, _step("modify_file", "skills/hn/hn.py")))
    assert result["file_written"] is False
    assert "does not exist" in result["message"]
    assert not missing.exists()
    assert not missing.parent.exists()


# ------------------------------------------------------------------- _create_file


def test_create_file_refuses_to_fabricate_a_nested_tree(svc, tmp_path, monkeypatch):
    async def _code(*_a, **_kw):
        return "x = 1\n"

    monkeypatch.setattr(svc, "_call_ollama", _code)

    deep = tmp_path / "a" / "b" / "c" / "x.py"
    with pytest.raises(Exception, match="Refusing to create nested directories"):
        asyncio.run(svc._create_file(deep, _step("create_file", "a/b/c/x.py")))
    assert not (tmp_path / "a").exists()


def test_create_file_allows_one_new_directory_level(svc, tmp_path, monkeypatch):
    async def _code(*_a, **_kw):
        return "x = 1\n"

    monkeypatch.setattr(svc, "_call_ollama", _code)

    target = tmp_path / "newdir" / "x.py"
    result = asyncio.run(svc._create_file(target, _step("create_file", "newdir/x.py")))
    assert result["file_written"] is True
    # _clean_code_response strips surrounding whitespace, so compare stripped.
    assert target.read_text(encoding="utf-8").strip() == "x = 1"


# ------------------------------------------------------------------ _validate_code


def test_validate_rejects_broken_json(svc):
    with pytest.raises(Exception, match="JSON syntax error"):
        svc._validate_code('{"a": 1,,}', "config/settings.json")


def test_validate_accepts_good_json(svc):
    svc._validate_code('{"a": 1}', "config/settings.json")


def test_validate_rejects_broken_yaml(svc):
    pytest.importorskip("yaml")
    with pytest.raises(Exception, match="YAML syntax error"):
        svc._validate_code("a: [1, 2\nb: }", "config/settings.yaml")


def test_validate_rejects_broken_python(svc):
    with pytest.raises(Exception, match="Python syntax error"):
        svc._validate_code("def f(:\n", "app/x.py")


# ------------------------------------------------------- _reclaim_orphaned_tasks


def test_orphaned_running_tasks_are_reclaimed(svc, monkeypatch):
    """A `running` row left by a dead process is invisible to check_and_execute
    (which picks only `queued`), so it must be failed out of the queue."""
    moved = []

    async def _capture(task):
        moved.append(task)

    monkeypatch.setattr(svc, "_move_to_history", _capture)

    queue = [
        {"task_id": "a", "status": "running", "title": "[legion] stranded"},
        {"task_id": "b", "status": "queued", "title": "[zero] pending"},
    ]
    changed = asyncio.run(svc._reclaim_orphaned_tasks(queue))

    assert changed is True
    assert [t["task_id"] for t in queue] == ["b"]
    assert moved[0]["status"] == "failed"
    assert "orphaned" in moved[0]["result"]["error"]


def test_reclaim_is_a_noop_without_orphans(svc):
    queue = [{"task_id": "b", "status": "queued"}]
    assert asyncio.run(svc._reclaim_orphaned_tasks(queue)) is False
    assert len(queue) == 1


def test_reclaim_leaves_the_live_current_task_alone(svc, monkeypatch):
    async def _capture(task):  # pragma: no cover - must never run
        raise AssertionError("the in-flight task must not be reclaimed")

    monkeypatch.setattr(svc, "_move_to_history", _capture)
    svc._current_task = {"task_id": "live"}

    queue = [{"task_id": "live", "status": "running"}]
    assert asyncio.run(svc._reclaim_orphaned_tasks(queue)) is False
    assert len(queue) == 1
