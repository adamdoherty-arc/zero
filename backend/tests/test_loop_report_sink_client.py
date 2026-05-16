"""Tests for Zero -> Legion loop sink client."""

from app.services.loop_report_sink_client import LoopReportSinkClient


def test_loop_sink_sends_zero_gateway_token(monkeypatch):
    monkeypatch.delenv("ZERO_LEGION_SINK_TOKEN", raising=False)
    monkeypatch.setenv("ZERO_GATEWAY_TOKEN", "gateway-token")
    client = LoopReportSinkClient()

    assert client._headers() == {"Authorization": "Bearer gateway-token"}


def test_loop_sink_prefers_dedicated_legion_sink_token(monkeypatch):
    monkeypatch.setenv("ZERO_GATEWAY_TOKEN", "gateway-token")
    monkeypatch.setenv("ZERO_LEGION_SINK_TOKEN", "legion-token")
    client = LoopReportSinkClient()

    assert client._headers() == {"Authorization": "Bearer legion-token"}
