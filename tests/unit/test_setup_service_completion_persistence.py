"""Cross-replica persistence of the setup-complete flag (issue #93)."""

from src.api.services.setup_service import OPTIONAL_FEATURES, Feature, SetupService


class FakeRedis:
    """Minimal sync-redis stand-in: get/set only, byte-encoded values."""

    def __init__(self):
        self.store: dict[str, bytes] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value.encode() if isinstance(value, str) else value


def _bare_service() -> SetupService:
    """Construct a SetupService without running __init__'s filesystem/Redis
    probing, matching the existing test_setup_service_optional_versions.py
    pattern."""
    service = object.__new__(SetupService)
    feature = OPTIONAL_FEATURES["local_embeddings"]
    service._features = {"local_embeddings": Feature(**{**feature.__dict__})}
    service._redis_url = None
    service._redis_client_cache = None
    service._redis_unavailable = False
    service._setup_complete = False
    return service


def test_mark_setup_complete_writes_through_to_redis(monkeypatch):
    service = _bare_service()
    fake_redis = FakeRedis()
    monkeypatch.setattr(service, "_redis_client", lambda: fake_redis)

    service.mark_setup_complete()

    assert service._setup_complete is True
    assert fake_redis.store[SetupService._SETUP_COMPLETE_REDIS_KEY] == b"true"


def test_get_setup_status_picks_up_completion_from_another_replica(monkeypatch):
    """Simulates api-canary-1 seeing api-1's mark_setup_complete() without a
    restart -- the exact cross-replica divergence from issue #93."""
    service = _bare_service()
    fake_redis = FakeRedis()
    fake_redis.store[SetupService._SETUP_COMPLETE_REDIS_KEY] = b"true"
    monkeypatch.setattr(service, "_redis_client", lambda: fake_redis)

    assert service._setup_complete is False  # this replica never marked it itself

    status = service.get_setup_status()

    assert status["setup_complete"] is True
    assert service._setup_complete is True


def test_get_setup_status_does_not_regress_when_redis_says_false():
    """If this replica already knows setup is complete, a stale/empty Redis
    key must not un-complete it (fail open to the more-complete state)."""
    service = _bare_service()
    service._setup_complete = True
    fake_redis = FakeRedis()
    service._redis_client = lambda: fake_redis  # no key set -> get() returns None

    status = service.get_setup_status()

    assert status["setup_complete"] is True


def test_redis_unavailable_falls_back_to_in_memory_flag_without_raising():
    service = _bare_service()
    service._setup_complete = True

    def _raise():
        raise ConnectionError("redis unreachable")

    service._redis_client = _raise  # simulate a hard failure in the accessor

    status = service.get_setup_status()

    assert status["setup_complete"] is True


def test_mark_setup_complete_survives_redis_set_failure():
    service = _bare_service()

    class RaisingRedis:
        def get(self, _key):
            raise ConnectionError("redis unreachable")

        def set(self, _key, _value):
            raise ConnectionError("redis unreachable")

    service._redis_client = RaisingRedis

    service.mark_setup_complete()  # must not raise

    assert service._setup_complete is True


def test_get_setup_service_uses_settings_db_redis_url(monkeypatch):
    import src.api.services.setup_service as setup_module
    from src.api.config import settings

    monkeypatch.setattr(setup_module, "_setup_service", None)
    svc = setup_module.get_setup_service()
    assert svc._redis_url == settings.db.redis_url
    monkeypatch.setattr(setup_module, "_setup_service", None)
