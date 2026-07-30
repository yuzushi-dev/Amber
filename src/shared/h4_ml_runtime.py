"""Validated paths for the optional, immutable H4 ML runtime overlay."""

import os
from pathlib import Path

H4_RUNTIME_ROOT_ENV = "AMBER_H4_ML_RUNTIME_ROOT"
SPLADE_MODEL = "naver/splade-cocondenser-ensembledistil"
SPLADE_REVISION = "49cf4c7b0db5b870a401ddf5e2669993ef3699c7"
_REQUIRED_EVIDENCE = (
    ".h4-artifact.json",
    ".h4-models.json",
    ".h4-preload-validation.json",
)


def validated_h4_runtime_root() -> Path | None:
    """Return the enabled H4 root, failing closed unless its proof is complete."""
    configured_root = os.getenv(H4_RUNTIME_ROOT_ENV)
    if not configured_root:
        return None

    root = Path(configured_root)
    missing = [name for name in _REQUIRED_EVIDENCE if not (root / name).is_file()]
    cache_directories = (root / "hf-cache" / "hub", root / "flashrank-cache")
    if missing or not all(path.is_dir() for path in cache_directories):
        raise RuntimeError(f"{H4_RUNTIME_ROOT_ENV} does not reference a validated H4 ML runtime")
    return root
