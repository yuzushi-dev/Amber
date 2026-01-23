from types import SimpleNamespace

from src.core.database import session as core_session


def test_build_session_factory_uses_core_maker(monkeypatch):
    from src.amber_platform import composition_root

    sentinel = object()

    def fake_get_session_maker():
        return sentinel

    def raise_unexpected(*_args, **_kwargs):
        raise AssertionError("create_async_engine should not be called")

    monkeypatch.setattr(core_session, "get_session_maker", fake_get_session_maker)
    monkeypatch.setattr(
        composition_root,
        "get_settings_lazy",
        lambda: SimpleNamespace(
            db=SimpleNamespace(
                database_url="sqlite://",
                pool_size=1,
                max_overflow=1,
            )
        ),
    )

    import sqlalchemy.ext.asyncio as async_module
    monkeypatch.setattr(async_module, "create_async_engine", raise_unexpected)

    maker = composition_root.build_session_factory()

    assert maker is sentinel
