"""
Regression coverage for the seed-sample-data environment guard.

`/admin/seed-sample-data` was mounted unconditionally (src/api/main.py) and
protected only by tenant-scoped authentication (no role check) — reachable
in production by any authenticated user of a tenant. It seeds demo content
(Wikipedia-derived sample docs), so it's dev/demo-only functionality, not a
legitimate production admin operation. It's now gated on `settings.debug`,
matching the existing dev-only convention in `src/api/main.py` (CORS
wildcard fallback, dev-secret guardrail).
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from src.api.routes import seed as seed_module


def test_ensure_dev_environment_blocks_when_not_debug():
    with patch.object(seed_module.settings, "debug", False):
        with pytest.raises(HTTPException) as exc:
            seed_module._ensure_dev_environment()

    assert exc.value.status_code == 403


def test_ensure_dev_environment_allows_when_debug():
    with patch.object(seed_module.settings, "debug", True):
        seed_module._ensure_dev_environment()  # must not raise
