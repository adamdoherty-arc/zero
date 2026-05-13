"""
Tests for SOUL.md parsing and rendering.
"""

from __future__ import annotations

from pathlib import Path


class TestParseSoulMd:
    def test_empty_returns_empty_doc(self):
        from app.services.soul_md import parse_soul_md
        doc = parse_soul_md("")
        assert doc.title is None
        assert doc.preamble == ""
        assert doc.sections == []

    def test_h1_title(self):
        from app.services.soul_md import parse_soul_md
        doc = parse_soul_md("# Buddy the Robot\n\nA companion.")
        assert doc.title == "Buddy the Robot"
        assert "companion" in doc.preamble

    def test_no_sections_treats_as_preamble(self):
        from app.services.soul_md import parse_soul_md
        text = "# Buddy\nA companion that plays games."
        doc = parse_soul_md(text)
        assert doc.title == "Buddy"
        assert "plays games" in doc.preamble
        assert doc.sections == []

    def test_sections_in_order(self):
        from app.services.soul_md import parse_soul_md
        text = (
            "# Title\n\npreamble here\n\n"
            "## Personality\nplayful\n\n"
            "## Voice & Tone\nwarm\n\n"
            "## Safety Rules\n1. don't run\n"
        )
        doc = parse_soul_md(text)
        names = [n for n, _ in doc.sections]
        assert names == ["Personality", "Voice & Tone", "Safety Rules"]
        assert "playful" in doc.sections[0][1]


class TestRenderPrompt:
    def test_canonical_order(self):
        from app.services.soul_md import parse_soul_md
        # Source order intentionally jumbled
        text = (
            "## Safety Rules\n1. stop\n\n"
            "## Personality\nplayful\n\n"
            "## Voice & Tone\nwarm\n"
        )
        prompt = parse_soul_md(text).to_prompt()
        i_pers = prompt.find("Personality")
        i_voice = prompt.find("Voice & Tone")
        i_safety = prompt.find("Safety Rules")
        assert 0 <= i_pers < i_voice < i_safety, prompt

    def test_unknown_sections_after_canonical(self):
        from app.services.soul_md import parse_soul_md
        text = (
            "## Personality\np\n\n"
            "## Hobbies\nguitar\n\n"
            "## Safety Rules\nstop\n"
        )
        prompt = parse_soul_md(text).to_prompt()
        # Canonical Personality first, Safety Rules second; Hobbies after.
        assert prompt.find("Personality") < prompt.find("Safety Rules")
        assert prompt.find("Safety Rules") < prompt.find("Hobbies")

    def test_preamble_first(self):
        from app.services.soul_md import parse_soul_md
        text = "You are Buddy.\n\n## Personality\nplayful\n"
        prompt = parse_soul_md(text).to_prompt()
        assert prompt.startswith("You are Buddy.")


class TestLoadSoulMd:
    def test_returns_none_when_missing(self, tmp_path):
        from app.services.soul_md import load_soul_md
        assert load_soul_md(tmp_path) is None

    def test_loads_and_renders(self, tmp_path):
        from app.services.soul_md import load_soul_md
        (tmp_path / "SOUL.md").write_text(
            "# Buddy\n\nA companion.\n\n## Personality\nplayful\n"
        )
        out = load_soul_md(tmp_path)
        assert out
        assert "companion" in out
        assert "Personality" in out


class TestSafetyRulesExtraction:
    def test_extracts_numbered_rules(self):
        from app.services.soul_md import parse_soul_md, safety_rules_from_soul
        text = (
            "## Safety Rules\n"
            "1. never run at the child\n"
            "2. stop on 'stop'\n"
            "3. stay 1m away\n"
        )
        doc = parse_soul_md(text)
        rules = safety_rules_from_soul(doc)
        assert len(rules) == 3
        assert "never run" in rules[0]

    def test_extracts_bullet_rules(self):
        from app.services.soul_md import parse_soul_md, safety_rules_from_soul
        text = (
            "## Safety\n- stay calm\n- alert an adult\n"
        )
        rules = safety_rules_from_soul(parse_soul_md(text))
        assert rules == ["stay calm", "alert an adult"]

    def test_no_safety_section_returns_empty(self):
        from app.services.soul_md import parse_soul_md, safety_rules_from_soul
        rules = safety_rules_from_soul(parse_soul_md("## Personality\nplayful"))
        assert rules == []


class TestBuddyShipsCorrectly:
    def test_buddy_persona_loads(self):
        """The bundled Buddy persona SOUL.md should parse and emit non-empty prompt."""
        from app.services.soul_md import load_soul_md
        buddy_dir = (
            Path(__file__).resolve().parents[1]
            / "app" / "data" / "reachy_profiles" / "buddy"
        )
        prompt = load_soul_md(buddy_dir)
        assert prompt is not None
        assert "Buddy" in prompt
        assert "Safety Rules" in prompt
        assert "Personality" in prompt
