"""
Tests for the skill manifest spec + validator + legacy migration.
"""

from __future__ import annotations

import json
from pathlib import Path


class TestValidate:
    def test_minimal_valid(self):
        from app.services.skill_manifest import validate
        result = validate({
            "slug": "test-skill",
            "name": "Test",
            "version": "1.0.0",
        })
        assert result.ok is True
        assert result.errors == []

    def test_missing_required(self):
        from app.services.skill_manifest import validate
        result = validate({})
        assert result.ok is False
        assert any("slug" in e for e in result.errors)
        assert any("name" in e for e in result.errors)
        assert any("version" in e for e in result.errors)

    def test_bad_slug(self):
        from app.services.skill_manifest import validate
        result = validate({"slug": "bad/slash", "name": "x", "version": "1"})
        assert result.ok is False
        assert any("illegal characters" in e for e in result.errors)

    def test_unknown_auth_scope_is_warning(self):
        from app.services.skill_manifest import validate
        result = validate({
            "slug": "ok", "name": "x", "version": "1",
            "auth": ["fs_read", "wat"],
        })
        assert result.ok is True
        assert any("wat" in w for w in result.warnings)

    def test_invalid_sandbox_timeout(self):
        from app.services.skill_manifest import validate
        result = validate({
            "slug": "ok", "name": "x", "version": "1",
            "sandbox": {"timeout_s": -1, "memory_mb": 256},
        })
        assert result.ok is False
        assert any("timeout_s" in e for e in result.errors)

    def test_unknown_platform_is_warning(self):
        from app.services.skill_manifest import validate
        result = validate({
            "slug": "ok", "name": "x", "version": "1",
            "platforms": ["windows", "atari"],
        })
        assert result.ok is True
        assert any("atari" in w for w in result.warnings)


class TestMigrateLegacy:
    def test_basic_migration(self):
        from app.services.skill_manifest import migrate_legacy
        meta = {"slug": "debug-pro", "version": "1.0.0", "ownerId": "kn748"}
        out = migrate_legacy(meta, slug="debug-pro", skill_md="# debug-pro\n\nSystematic debugging.")
        assert out["slug"] == "debug-pro"
        assert out["name"] == "debug-pro"
        assert "Systematic debugging" in out["description"]
        assert out["author"] == "kn748"
        assert out["auth"] == []
        assert out["platforms"] == ["any"]


class TestLoadFromDir:
    def test_loads_extended_manifest(self, tmp_path):
        from app.services.skill_manifest import load_from_dir
        d = tmp_path / "my-skill"
        d.mkdir()
        (d / "skill.json").write_text(json.dumps({
            "slug": "my-skill",
            "name": "My Skill",
            "version": "0.1.0",
            "auth": ["fs_read"],
            "platforms": ["linux"],
            "tools": ["search"],
        }), encoding="utf-8")
        manifest, validation = load_from_dir(d)
        assert validation.ok
        assert manifest is not None
        assert manifest.slug == "my-skill"
        assert "fs_read" in manifest.auth
        assert "linux" in manifest.platforms

    def test_falls_back_to_legacy_meta(self, tmp_path):
        from app.services.skill_manifest import load_from_dir
        d = tmp_path / "legacy-skill"
        d.mkdir()
        (d / "_meta.json").write_text(
            json.dumps({"slug": "legacy-skill", "version": "1.0.0", "ownerId": "xx"}),
            encoding="utf-8",
        )
        (d / "SKILL.md").write_text("# Legacy Skill\n\nA legacy thing.")
        manifest, validation = load_from_dir(d)
        assert validation.ok
        assert manifest is not None
        assert manifest.name == "Legacy Skill"

    def test_missing_manifests(self, tmp_path):
        from app.services.skill_manifest import load_from_dir
        d = tmp_path / "empty-skill"
        d.mkdir()
        manifest, validation = load_from_dir(d)
        assert manifest is None
        assert validation.ok is False


class TestDiscoverSkills:
    def test_discovers_all_legacy_skills(self):
        """Confirm Zero's existing skills/ tree loads without errors."""
        from app.services.skill_manifest import discover_skills
        roots = [Path(__file__).resolve().parents[2] / "skills"]
        results = discover_skills(roots)
        assert len(results) >= 1
        # Every result has a valid manifest
        for manifest, validation in results:
            assert manifest is not None
            assert validation.ok, f"{manifest.slug}: {validation.errors}"


class TestThirdPartyRegistry:
    def test_registry_is_valid_json(self):
        registry_path = (
            Path(__file__).resolve().parents[2] / "skills" / "third-party-skills.json"
        )
        if not registry_path.exists():
            return
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        for entry in data:
            assert "slug" in entry
            assert "repository" in entry
