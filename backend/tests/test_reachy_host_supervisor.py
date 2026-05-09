from types import MethodType

from host_agent.supervisor import (
    DaemonSupervisor,
    _daemon_blocker_from_status_data,
    _isolated_python_env,
    _select_reachy_python_candidate,
)


def _supervisor_with_log_lines(lines: list[str]) -> DaemonSupervisor:
    supervisor = DaemonSupervisor.__new__(DaemonSupervisor)

    def logs(self: DaemonSupervisor, tail: int = 100) -> dict:
        return {"lines": lines[-tail:]}

    supervisor.logs = MethodType(logs, supervisor)  # type: ignore[method-assign]
    return supervisor


def test_known_issues_reports_motor_power_before_clean_start():
    supervisor = _supervisor_with_log_lines([
        "Failed to start daemon: No motors detected. Check if the power supply is connected and turned on!",
    ])

    issues = supervisor._scan_known_issues()

    assert issues["count"] == 1
    assert issues["items"][0]["id"] == "motors_unpowered"


def test_known_issues_clears_motor_power_after_clean_start():
    supervisor = _supervisor_with_log_lines([
        "Failed to start daemon: No motors detected. Check if the power supply is connected and turned on!",
        "2026-05-06 13:13:02,485 INFO [reachy_mini.daemon.daemon] Daemon started successfully.",
    ])

    issues = supervisor._scan_known_issues()

    assert issues["count"] == 0
    assert issues["items"] == []


def test_daemon_status_error_reports_motor_power_blocker():
    blocker = _daemon_blocker_from_status_data({
        "state": "error",
        "error": "No motors detected. Check if the power supply is connected and turned on!",
    })

    assert blocker is not None
    assert blocker["id"] == "motors_unpowered"


def test_select_reachy_python_prefers_newest_sdk(tmp_path):
    old_python = tmp_path / "old" / "pythonw.exe"
    new_python = tmp_path / "new" / "pythonw.exe"
    old_python.parent.mkdir()
    new_python.parent.mkdir()
    old_python.touch()
    new_python.touch()

    selected = _select_reachy_python_candidate(
        [old_python, new_python],
        version_lookup=lambda path: {
            old_python: "1.6.4",
            new_python: "1.7.1",
        }[path],
    )

    assert selected == (new_python, "1.7.1")


def test_select_reachy_python_keeps_first_existing_when_version_unknown(tmp_path):
    first_python = tmp_path / "first" / "pythonw.exe"
    second_python = tmp_path / "second" / "pythonw.exe"
    first_python.parent.mkdir()
    second_python.parent.mkdir()
    first_python.touch()
    second_python.touch()

    selected = _select_reachy_python_candidate(
        [first_python, second_python],
        version_lookup=lambda _path: None,
    )

    assert selected == (first_python, None)


def test_isolated_python_env_removes_cross_venv_path(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "C:/code/zero/host_agent/.venv/Lib/site-packages")
    monkeypatch.setenv("VIRTUAL_ENV", "C:/code/zero/host_agent/.venv")
    monkeypatch.setenv("ZERO_REACHY_DAEMON_ARGS", "--no-preload --no-media")

    env = _isolated_python_env()

    assert "PYTHONPATH" not in env
    assert "VIRTUAL_ENV" not in env
    assert env["ZERO_REACHY_DAEMON_ARGS"] == "--no-preload --no-media"
