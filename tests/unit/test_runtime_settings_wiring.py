from src.core.generation.infrastructure.providers import factory as providers_factory


def test_api_configures_runtime_settings(monkeypatch):
    from src.api import main

    called = {}

    def fake_configure(settings):
        called["settings"] = settings

    monkeypatch.setattr(main, "configure_settings", fake_configure, raising=False)

    main._configure_runtime_settings()

    assert "settings" in called


def test_worker_init_calls_configure_settings(monkeypatch):
    from src.workers import celery_app

    called = {}

    def fake_configure(settings):
        called["settings"] = settings

    monkeypatch.setattr(celery_app, "configure_settings", fake_configure, raising=False)
    monkeypatch.setattr(providers_factory, "init_providers", lambda **_kwargs: None)

    celery_app.init_worker_process()

    assert "settings" in called
