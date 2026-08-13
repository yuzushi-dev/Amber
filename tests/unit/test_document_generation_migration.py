from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from src.core.ingestion.domain.chunk import Chunk
from src.core.ingestion.domain.document import Document

MIGRATION = (
    Path(__file__).parents[2]
    / "alembic/versions/20260813_1700_add_document_artifact_generations.py"
)


def _load_migration():
    spec = spec_from_file_location("document_generation_migration", MIGRATION)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generation_schema_is_additive_and_follows_current_head():
    migration = _load_migration()

    assert migration.revision == "20260813_1700"
    assert migration.down_revision == "20260812_1600"
    assert Document.__table__.c.active_generation_id.nullable
    assert Document.__table__.c.pending_generation_id.nullable
    assert Document.__table__.c.processing_attempt_id.nullable
    assert Chunk.__table__.c.generation_id.nullable


def test_downgrade_refuses_to_drop_nonempty_generation_schema(monkeypatch):
    migration = _load_migration()

    class _Connection:
        def execute(self, _statement):
            class _Result:
                @staticmethod
                def scalar_one():
                    return 1

            return _Result()

    monkeypatch.setattr(migration.op, "get_bind", _Connection)

    try:
        migration.downgrade()
    except RuntimeError as exc:
        assert "document generation data exists" in str(exc)
    else:
        raise AssertionError("downgrade must fail when generation data exists")
