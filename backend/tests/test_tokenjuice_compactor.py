"""
Tests for TokenJuice compaction.
"""

from __future__ import annotations

import json


class TestHtmlCompaction:
    def test_strips_scripts_and_styles(self):
        from app.services.tokenjuice_compactor import compact
        html = (
            "<html><head><style>body{}</style>"
            "<script>alert(1)</script></head>"
            "<body><h1>Hello</h1><p>World</p></body></html>"
        )
        out = compact(html, kind="html")
        assert "alert(1)" not in out
        assert "body{}" not in out
        assert "Hello" in out
        assert "World" in out

    def test_converts_headings(self):
        from app.services.tokenjuice_compactor import compact
        html = "<h1>Title</h1><h2>Sub</h2>"
        out = compact(html, kind="html")
        assert "# Title" in out
        assert "## Sub" in out

    def test_converts_links_to_markdown(self):
        from app.services.tokenjuice_compactor import compact
        html = '<a href="https://example.com/page">Click</a>'
        out = compact(html, kind="html")
        assert "[Click](https://example.com/page)" in out

    def test_converts_list_items(self):
        from app.services.tokenjuice_compactor import compact
        html = "<ul><li>One</li><li>Two</li></ul>"
        out = compact(html, kind="html")
        assert "- One" in out
        assert "- Two" in out

    def test_meaningful_savings_on_real_html(self):
        from app.services.tokenjuice_compactor import compact, estimate_savings
        big = (
            "<html><body>"
            + "<div class='wrap'><script>x()</script></div>" * 50
            + "<p>The actual content</p>"
            + "<div class='footer'><style>.x{}</style></div>" * 50
            + "</body></html>"
        )
        out = compact(big, kind="html")
        report = estimate_savings(big, out)
        assert report.savings_ratio >= 0.5
        assert "actual content" in out


class TestUrlShortening:
    def test_long_urls_become_markers(self):
        from app.services.tokenjuice_compactor import compact
        long_url = "https://example.com/" + "x" * 200
        out = compact(f"see {long_url} for details")
        body, _, footnote = out.partition("## Links")
        # Body has only the short marker, footnote has the real URL
        assert long_url not in body
        assert "example.com" in body
        assert long_url in footnote

    def test_short_urls_left_alone(self):
        from app.services.tokenjuice_compactor import compact
        out = compact("see https://example.com/x for details")
        assert "https://example.com/x" in out
        assert "## Links" not in out


class TestTerminalCompaction:
    def test_strips_ansi_escapes(self):
        from app.services.tokenjuice_compactor import compact
        text = "\x1b[31mERROR\x1b[0m: something broke"
        out = compact(text, kind="terminal")
        assert "\x1b[" not in out
        assert "ERROR" in out

    def test_collapses_progress_bars(self):
        from app.services.tokenjuice_compactor import compact
        text = "Step 1\rStep 2\rStep 3\rDone\nNext line"
        out = compact(text, kind="terminal")
        assert "Step 1" not in out
        assert "Done" in out
        assert "Next line" in out

    def test_dedup_runs(self):
        from app.services.tokenjuice_compactor import compact
        text = "same\nsame\nsame\nsame\ndifferent"
        out = compact(text, kind="text")
        assert "(x 4)" in out
        assert "different" in out


class TestJsonCompaction:
    def test_compacts_pretty_json(self):
        from app.services.tokenjuice_compactor import compact
        pretty = json.dumps({"a": 1, "b": [1, 2, 3]}, indent=2)
        out = compact(pretty, kind="json")
        assert "\n" not in out
        assert json.loads(out) == {"a": 1, "b": [1, 2, 3]}

    def test_invalid_json_left_alone(self):
        from app.services.tokenjuice_compactor import compact
        out = compact("{not actual json", kind="json")
        assert "{not actual json" in out


class TestOversizedTrim:
    def test_trims_with_head_tail_marker(self):
        from app.services.tokenjuice_compactor import compact
        text = "HEAD" + ("x" * 10000) + "TAIL"
        out = compact(text, kind="text", max_chars=4000)
        assert "HEAD" in out
        assert "TAIL" in out
        assert "trimmed" in out
        assert len(out) < len(text)


class TestAutoDetect:
    def test_html_detected(self):
        from app.services.tokenjuice_compactor import compact
        out = compact("<html><body><p>hi</p></body></html>")
        assert "<" not in out

    def test_terminal_detected(self):
        from app.services.tokenjuice_compactor import compact
        out = compact("\x1b[1mhi\x1b[0m\r" * 5)
        assert "\x1b" not in out

    def test_json_detected(self):
        from app.services.tokenjuice_compactor import compact
        pretty = json.dumps({"k": "v"}, indent=4)
        out = compact(pretty)
        # Should be re-emitted compact
        assert out == '{"k":"v"}'

    def test_plain_text_passthrough(self):
        from app.services.tokenjuice_compactor import compact
        out = compact("hello world")
        assert out == "hello world"


class TestEmpty:
    def test_empty_string(self):
        from app.services.tokenjuice_compactor import compact
        assert compact("") == ""
