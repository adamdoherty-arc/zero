"""
Tests for the tool-output compaction helpers.
"""

from __future__ import annotations


class TestGitDiff:
    def test_short_passthrough(self):
        from app.services.tool_output_helpers import compact_git_diff
        diff = "diff --git a/foo b/foo\n@@ -1 +1 @@\n-old\n+new\n"
        assert compact_git_diff(diff) == diff

    def test_long_strips_progress_bars(self):
        from app.services.tool_output_helpers import compact_git_diff
        # Pad with terminal noise to exceed 2k chars
        noise = "Progress: 5%\rProgress: 50%\rProgress: 100%\n"
        diff = noise * 200
        out = compact_git_diff(diff)
        assert len(out) < len(diff)
        assert "Progress: 5%" not in out


class TestTerminal:
    def test_ansi_stripped(self):
        from app.services.tool_output_helpers import compact_terminal_output
        text = ("\x1b[31mFAILED\x1b[0m: build error\n" * 200)
        out = compact_terminal_output(text)
        assert "\x1b[" not in out


class TestFileRead:
    def test_small_file_passthrough(self):
        from app.services.tool_output_helpers import compact_file_read
        body = "hello world"
        assert compact_file_read(body) == body

    def test_large_html_file_compacted(self):
        from app.services.tool_output_helpers import compact_file_read
        big_html = (
            "<html><body>" + "<script>x()</script>" * 200 + "<p>real content</p></body></html>"
        )
        out = compact_file_read(big_html)
        assert "x()" not in out
        assert "real content" in out
        assert len(out) < len(big_html)

    def test_min_size_override_runs_compaction(self):
        from app.services.tool_output_helpers import compact_file_read
        # Same content; just confirm min_size override actually invokes the
        # compactor rather than passing through. We assert by checking that
        # the compactor's auto-detect produced the same output (compactor
        # is a no-op on plain text) — but the telemetry counter advances.
        from app.services import tokenjuice_compactor as t
        t.reset_compaction_metrics()
        compact_file_read("short", min_size=2)
        assert t.get_compaction_metrics()["calls"] == 1


class TestTelemetryAdvances:
    def test_metrics_counter_increments(self, monkeypatch):
        from app.services import tokenjuice_compactor as t
        from app.services.tool_output_helpers import compact_terminal_output
        t.reset_compaction_metrics()
        text = "\x1b[31mERROR\x1b[0m" * 500
        compact_terminal_output(text)
        compact_terminal_output(text)
        m = t.get_compaction_metrics()
        assert m["calls"] == 2
        assert m["before_chars_total"] > 0
        assert m["after_chars_total"] > 0
