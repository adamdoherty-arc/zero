"""
The enhancement scanner must not file signals against its own machinery.

Its source describes how markers are routed, in comments that necessarily NAME
the markers: "# FIXME with good confidence -> auto-fix", "# Security issues
always get human review". The extractor cannot distinguish prose-about-a-marker
from a real marker, so both lines were filed as live signals and reached Legion
as tasks in sprint 13275 on 2026-08-01. Same reasoning as the `_archive`
exclusion shipped in Fix-160.
"""

import pathlib

from app.services.enhancement_service import EnhancementService

PIPELINE_FILES = [
    "enhancement_service.py",
    "daily_improvement_service.py",
    "continuous_enhancement_service.py",
    "task_execution_service.py",
]


def test_pipeline_source_is_not_scanned(tmp_path):
    svc = EnhancementService()
    services = tmp_path / "services"
    services.mkdir()

    # A real marker in ordinary code must still be picked up...
    (services / "some_feature.py").write_text(
        "# TODO: wire the retry budget into the client\n", encoding="utf-8"
    )
    # ...while the same shape inside the pipeline's own files must not be.
    for name in PIPELINE_FILES:
        (services / name).write_text(
            "# FIXME with good confidence -> auto-fix\n"
            "# Security issues always get human review\n",
            encoding="utf-8",
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
    (archived / "old_tool.py").write_text("# TODO: revive this someday\n", encoding="utf-8")

    assert svc._scan_directories_sync([tmp_path], project_name="zero") == []
