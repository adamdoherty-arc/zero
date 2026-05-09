import pytest


@pytest.mark.asyncio
async def test_ambient_vision_tick_skips_when_disabled(monkeypatch):
    from app.infrastructure.config import Settings
    from app.services.ambient_vision_service import ambient_vision_tick

    settings = Settings(ambient_vision_enabled=False)
    monkeypatch.setattr("app.infrastructure.config.get_settings", lambda: settings)

    result = await ambient_vision_tick()

    assert result == {"status": "skipped_disabled"}


@pytest.mark.asyncio
async def test_ambient_vision_tick_reads_provider_when_enabled(monkeypatch):
    from app.infrastructure.config import Settings
    from app.services.ambient_vision_service import ambient_vision_tick

    settings = Settings(ambient_vision_enabled=True)
    monkeypatch.setattr("app.infrastructure.config.get_settings", lambda: settings)

    class Registry:
        def get_active(self):
            return None

    monkeypatch.setattr("app.services.sight.get_sight_registry", lambda: Registry())

    result = await ambient_vision_tick()

    assert result == {"status": "skipped_no_provider"}
