"""
Contract test: the Bifrost gateway YAML and the in-process LLM router
taxonomy must stay aligned. PRs that add a hint or a preset must touch both.
"""

from __future__ import annotations

from pathlib import Path


CONFIG_PATH = Path(__file__).resolve().parents[2] / "shared-infra" / "bifrost" / "config.yaml"


def _load_yaml():
    import yaml
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestVirtualModelsMatchHints:
    def test_every_hint_has_a_virtual_model(self):
        from app.infrastructure.llm_hints import HINT_TO_TASK_TYPE
        cfg = _load_yaml()
        gateway_hints = {
            k.replace("hint:", "")
            for k in cfg["virtual_models"].keys()
            if k.startswith("hint:")
        }
        missing = set(HINT_TO_TASK_TYPE.keys()) - gateway_hints
        assert not missing, (
            f"Gateway config is missing hints: {missing}. "
            f"Update shared-infra/bifrost/config.yaml when adding hints."
        )

    def test_no_extra_hints_in_gateway(self):
        from app.infrastructure.llm_hints import HINT_TO_TASK_TYPE
        cfg = _load_yaml()
        gateway_hints = {
            k.replace("hint:", "")
            for k in cfg["virtual_models"].keys()
            if k.startswith("hint:")
        }
        extra = gateway_hints - set(HINT_TO_TASK_TYPE.keys())
        assert not extra, (
            f"Gateway has hints not in the in-process taxonomy: {extra}"
        )

    def test_every_virtual_model_has_primary(self):
        cfg = _load_yaml()
        for name, vm in cfg["virtual_models"].items():
            assert vm.get("primary"), f"{name} missing 'primary'"


class TestPresetsMatchTaxonomy:
    def test_all_in_process_presets_present(self):
        from app.infrastructure.llm_hints import all_presets
        cfg = _load_yaml()
        gateway_presets = set(cfg.get("presets", {}).keys())
        for p in all_presets():
            assert p in gateway_presets, f"Preset '{p}' missing from gateway yaml"

    def test_preset_keys_are_hint_strings(self):
        cfg = _load_yaml()
        for name, mapping in cfg["presets"].items():
            if not mapping:
                continue
            for hint_key in mapping.keys():
                assert hint_key.startswith("hint:"), (
                    f"Preset '{name}' key '{hint_key}' should be a hint:* string"
                )


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
        # Trailing slash stripped
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
