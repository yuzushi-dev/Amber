"""Version-aware contracts for optional package volumes."""

import asyncio
import importlib
from importlib import metadata

import pytest

from src.api.services.setup_service import OPTIONAL_FEATURES, Feature, FeatureStatus, SetupService


def _local_embeddings_service(tmp_path) -> SetupService:
    service = object.__new__(SetupService)
    feature = OPTIONAL_FEATURES["local_embeddings"]
    service._features = {"local_embeddings": Feature(**{**feature.__dict__})}
    service._installation_lock = asyncio.Lock()
    service.PACKAGES_DIR = str(tmp_path)
    return service


def test_local_embeddings_rejects_importable_legacy_transformers(monkeypatch, tmp_path):
    service = _local_embeddings_service(tmp_path)
    versions = {
        "torch": "2.13.0+cpu",
        "sentence-transformers": "5.6.1",
        "transformers": "4.40.1",
        "huggingface-hub": "1.25.1",
        "tokenizers": "0.22.2",
        "protobuf": "6.33.6",
    }
    monkeypatch.setattr(importlib, "import_module", lambda _name: object())
    monkeypatch.setattr(metadata, "version", versions.__getitem__)

    assert service._check_feature_installed("local_embeddings") is False


@pytest.mark.asyncio
async def test_non_streaming_install_upgrades_existing_optional_packages(monkeypatch, tmp_path):
    service = _local_embeddings_service(tmp_path)
    captured_command: tuple[str, ...] = ()

    class SuccessfulProcess:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def create_process(*command, **_kwargs):
        nonlocal captured_command
        captured_command = command
        return SuccessfulProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(service, "_check_feature_installed", lambda _feature_id: True)

    result = await service.install_feature("local_embeddings")

    assert result["success"] is True
    assert service._features["local_embeddings"].status == FeatureStatus.INSTALLED
    assert "--upgrade" in captured_command
