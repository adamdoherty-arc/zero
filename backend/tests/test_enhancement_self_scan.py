"""
The enhancement scanner must not file signals against its own machinery.

Its source describes how markers are routed, in comments that necessarily NAME
the markers, and the extractor could not distinguish prose-about-a-marker from a
real marker. Both such lines were filed as live signals and reached Legion as
tasks in sprint 13275 on 2026-08-01. Same reasoning as the `_archive` exclusion
shipped in Fix-160.

Fix-162 closed the next level of the same loop. THIS FILE was scanned: its
docstring quotes the markers and its fixtures pass them as string arguments. Four
signals were filed against it at security/critical/95 and fixme/high/100, two
converted to Legion tasks, and the executor rewrote the fixtures below -- leaving
a test that asserted nothing. Three defences now stand: markers are read from
real comment tokens only, test paths are skipped for every signal type, and this
file is named in the pipeline exclusion set.
"""

import pathlib

from app.services.enhancement_service import EnhancementService

PIPELINE_FILES = [
    "enhancement_service.py",
    "daily_improvement_service.py",
    "continuous_enhancement_service.py",
    "task_execution_service.py",
    "test_enhancement_self_scan.py",
]

# Built at runtime so this module's own source carries no bare marker for a
# future scan to trip over.
FIXME_MARKER = "# " + "FIXME" + " with good confidence -> auto-fix"
SECURITY_MARKER = "# " + "SECURITY" + " issues always get human review"
TODO_MARKER = "# " + "TODO" + ": wire the retry budget into the client"


def test_pipeline_source_is_not_scanned(tmp_path):
    svc = EnhancementService()
    services = tmp_path / "services"
    services.mkdir()

    # A real marker in ordinary code must still be picked up...
    (services / "some_feature.py").write_text(TODO_MARKER + "\n", encoding="utf-8")
    # ...while the same shape inside the pipeline's own files must not be.
    for name in PIPELINE_FILES:
        (services / name).write_text(
            FIXME_MARKER + "\n" + SECURITY_MARKER + "\n", encoding="utf-8"
        )

    signals = svc._scan_directories_sync([services], project_name="zero")
    files = {pathlib.Path(s.source_file).name for s in signals}

    assert "some_feature.py" in files, "ordinary markers must still be detected"
    for name in PIPELINE_FILES:
        assert name not in files, f"{name} is pipeline machinery and must be skipped"


def test_archive_exclusion_still_holds(tmp_path):
    """Guards the Fix-160 exclusion alongside the new one."""
    svc = EnhancementService()
    archived = tmp_path / "_archive"
    archived.mkdir()
    (archived / "old_tool.py").write_text(TODO_MARKER + "\n", encoding="utf-8")

    assert svc._scan_directories_sync([tmp_path], project_name="zero") == []


def test_markers_inside_docstrings_are_not_signals(tmp_path):
    """
    A `#` inside a string is not a comment.

    This is the Fix-162 headline: the marker that got filed at confidence 100 and
    executed against this repo sat on line 5 of a module docstring.
    """
    svc = EnhancementService()
    services = tmp_path / "services"
    services.mkdir()
    (services / "documented.py").write_text(
        '"""\n'
        "Routing rules, described in prose:\n"
        f'  {FIXME_MARKER}\n'
        f'  {SECURITY_MARKER}\n'
        '"""\n',
        encoding="utf-8",
    )

    signals = svc._scan_directories_sync([services], project_name="zero")
    assert signals == [], f"docstring prose must not be filed, got {[s.message for s in signals]}"


def test_markers_inside_string_literals_are_not_signals(tmp_path):
    """The other half of Fix-162: fixtures passing markers as arguments."""
    svc = EnhancementService()
    services = tmp_path / "services"
    services.mkdir()
    (services / "fixture_like.py").write_text(
        "def write_fixture(path):\n"
        f'    path.write_text("{FIXME_MARKER}\\n{SECURITY_MARKER}\\n")\n',
        encoding="utf-8",
    )

    signals = svc._scan_directories_sync([services], project_name="zero")
    assert signals == [], f"string literals must not be filed, got {[s.message for s in signals]}"


def test_real_comments_are_still_detected_alongside_strings(tmp_path):
    """The exclusion must not swallow genuine markers in the same file."""
    svc = EnhancementService()
    services = tmp_path / "services"
    services.mkdir()
    (services / "mixed.py").write_text(
        '"""Docstring mentioning ' + FIXME_MARKER + '."""\n'
        f'PROSE = "{SECURITY_MARKER}"\n'
        + TODO_MARKER
        + "\n",
        encoding="utf-8",
    )

    signals = svc._scan_directories_sync([services], project_name="zero")
    assert len(signals) == 1, f"expected only the real comment, got {[s.message for s in signals]}"
    assert "retry budget" in signals[0].message


def test_test_paths_are_skipped_for_every_signal_type(tmp_path):
    """
    fixme/high and security/critical walked past the old TODO-only test guard.

    Those were precisely the two types filed against this file.
    """
    svc = EnhancementService()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_something.py").write_text(
        FIXME_MARKER + "\n" + SECURITY_MARKER + "\n" + TODO_MARKER + "\n",
        encoding="utf-8",
    )

    signals = svc._scan_directories_sync([tests_dir], project_name="zero")
    assert signals == [], f"test paths must be skipped, got {[s.message for s in signals]}"


def test_unparseable_python_falls_back_to_line_scan(tmp_path):
    """A half-written file must not silently disable detection for that file."""
    svc = EnhancementService()
    services = tmp_path / "services"
    services.mkdir()
    (services / "broken.py").write_text(
        "def truncated(\n" + TODO_MARKER + "\n", encoding="utf-8"
    )

    signals = svc._scan_directories_sync([services], project_name="zero")
    assert len(signals) == 1, "unparseable source must fall back to scanning every line"
