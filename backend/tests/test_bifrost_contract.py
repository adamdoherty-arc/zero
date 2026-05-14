"""
Bifrost client contract.

Zero does not own the live Bifrost config. The deployed gateway is shared
infrastructure (currently ``C:\\code\\shared-infra\\bifrost\\config.json`` on
the host), so this repo only verifies the client behavior and that no runtime
YAML is accidentally treated as canonical inside Zero.
"""

from __future__ import annotations

from pathlib import Path


class TestBifrostConfigOwnership:
    def test_zero_repo_does_not_ship_runtime_bifrost_yaml(self):
        repo_root = Path(__file__).resolve().parents[2]
        assert not (repo_root / "shared-infra" / "bifrost" / "config.yaml").exists()


class TestBifrostClient:
    def test_unavailable_without_env(self, monkeypatch):
        monkeypatch.delenv("BIFROST_GATEWAY_URL", raising=False)
        from app.infrastructure.bifrost_client import BifrostClient

        client = BifrostClient()
        assert client.is_available() is False
        assert client.url is None

    def test_available_with_env(self, monkeypatch):
        monkeypatch.setenv("BIFROST_GATEWAY_URL", "http://bifrost:8080/")
        from app.infrastructure.bifrost_client import BifrostClient

        client = BifrostClient()
        assert client.is_available() is True
        assert client.url == "http://bifrost:8080"

    def test_headers_include_auth_token(self, monkeypatch):
        monkeypatch.setenv("BIFROST_GATEWAY_URL", "http://bifrost:8080")
        monkeypatch.setenv("BIFROST_TOKEN", "secret-token")
        from app.infrastructure.bifrost_client import BifrostClient

        client = BifrostClient()
        headers = client._headers()
        assert headers.get("Authorization") == "Bearer secret-token"

    def test_complete_raises_when_unavailable(self, monkeypatch):
        import asyncio

        monkeypatch.delenv("BIFROST_GATEWAY_URL", raising=False)
        from app.infrastructure.bifrost_client import BifrostClient

        client = BifrostClient()

        async def run():
            try:
                await client.complete(model="hint:summarize", messages=[])
                return False
            except RuntimeError:
                return True

        assert asyncio.run(run()) is True
