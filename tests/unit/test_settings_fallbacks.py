from src.api.config import Settings


def test_llm_fallback_settings_present():
    s = Settings()
    assert hasattr(s, "llm_fallback_economy")
    assert hasattr(s, "embedding_fallback_order")
