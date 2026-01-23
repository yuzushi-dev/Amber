import pytest

from src.shared.kernel import runtime


class DummySettings:
    app_name = "amber"


def test_get_settings_raises_when_unconfigured():
    runtime._reset_for_tests()
    with pytest.raises(RuntimeError):
        runtime.get_settings()


def test_get_settings_returns_configured_instance():
    runtime._reset_for_tests()
    settings = DummySettings()
    runtime.configure_settings(settings)
    assert runtime.get_settings() is settings
