import sys
from types import SimpleNamespace

import pytest

from src.core.generation.infrastructure.providers import local


def _ready_h4_runtime(tmp_path):
    for name in (
        ".h4-artifact.json",
        ".h4-models.json",
        ".h4-preload-validation.json",
    ):
        (tmp_path / name).write_text("{}\n")
    (tmp_path / "hf-cache" / "hub").mkdir(parents=True)
    (tmp_path / "flashrank-cache").mkdir()
    return tmp_path


def test_h4_flashrank_loader_uses_validated_cache(tmp_path, monkeypatch):
    runtime_root = _ready_h4_runtime(tmp_path)
    monkeypatch.setenv("AMBER_H4_ML_RUNTIME_ROOT", str(runtime_root))
    calls = []

    def fake_ranker(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setitem(sys.modules, "flashrank", SimpleNamespace(Ranker=fake_ranker))
    local._flashrank_ranker_cache.clear()

    local.FlashRankReranker()._load_ranker("ms-marco-MiniLM-L-12-v2")

    assert calls == [
        {
            "model_name": "ms-marco-MiniLM-L-12-v2",
            "cache_dir": str(runtime_root / "flashrank-cache"),
        }
    ]


def test_h4_flashrank_loader_fails_closed_without_validation_proof(tmp_path, monkeypatch):
    monkeypatch.setenv("AMBER_H4_ML_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setitem(
        sys.modules,
        "flashrank",
        SimpleNamespace(Ranker=lambda **kwargs: object()),
    )
    local._flashrank_ranker_cache.clear()

    with pytest.raises(RuntimeError, match="validated H4 ML runtime"):
        local.FlashRankReranker()._load_ranker("ms-marco-MiniLM-L-12-v2")
