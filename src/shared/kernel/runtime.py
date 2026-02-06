from src.shared.kernel.settings import SettingsProtocol

_settings: SettingsProtocol | None = None


def configure_settings(settings: SettingsProtocol) -> None:
    global _settings
    _settings = settings


def get_settings() -> SettingsProtocol:
    if _settings is None:
        raise RuntimeError("Settings not configured. Call configure_settings() at startup.")
    return _settings


def _reset_for_tests() -> None:
    global _settings
    _settings = None
