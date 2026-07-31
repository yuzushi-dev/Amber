"""Regression coverage for the retired Marker OCR feature."""

from pathlib import Path

import pytest

from src.api.services.setup_service import OPTIONAL_FEATURES
from src.core.ingestion.infrastructure.extraction.config import ExtractionSettings

PROJECT_ROOT = Path(__file__).resolve().parents[6]


def test_setup_wizard_does_not_offer_retired_marker_ocr():
    assert "ocr" not in OPTIONAL_FEATURES
    assert all(
        "marker-pdf" not in requirement
        for feature in OPTIONAL_FEATURES.values()
        for requirement in feature.packages
    )


def test_h3_keeps_h4_local_embedding_dependencies_outside_parser_scope():
    local_embeddings = OPTIONAL_FEATURES["local_embeddings"].packages
    requirements = (PROJECT_ROOT / "requirements.txt").read_text().lower()

    assert "torch" in local_embeddings
    assert any(package.startswith("transformers") for package in local_embeddings)
    assert "sentence-transformers>=2.7.0" in requirements
    assert "transformers==4.40.1" in requirements


@pytest.mark.parametrize("setting", ("marker_enabled", "hybrid_ocr_enabled"))
def test_retired_marker_settings_fail_explicitly(setting: str):
    with pytest.raises(ValueError, match="Marker OCR support has been retired"):
        ExtractionSettings(**{setting: True})


def test_unused_legacy_ocr_density_threshold_is_not_a_runtime_setting():
    assert "ocr_text_density_threshold" not in ExtractionSettings.model_fields


def test_admin_configuration_does_not_offer_retired_hybrid_ocr():
    admin_config = (PROJECT_ROOT / "src" / "api" / "routes" / "admin" / "config.py").read_text()
    tenant_defaults = (
        PROJECT_ROOT / "src" / "core" / "admin_ops" / "application" / "api_key_service.py"
    ).read_text()
    frontend_types = (PROJECT_ROOT / "frontend" / "src" / "lib" / "api-admin.ts").read_text()
    api_docs = (PROJECT_ROOT / "docs" / "API_ENDPOINTS.md").read_text()

    for retired_setting in ("hybrid_ocr_enabled", "ocr_text_density_threshold"):
        assert retired_setting not in admin_config
        assert retired_setting not in tenant_defaults
        assert retired_setting not in frontend_types
        assert retired_setting not in api_docs


def test_active_parser_docs_do_not_describe_retired_marker_fallbacks():
    readme = (PROJECT_ROOT / "README.md").read_text().lower()
    internals = (PROJECT_ROOT / "docs" / "INTERNALS.md").read_text().lower()

    assert "marker-pdf" not in readme
    assert "marker-pdf" not in internals
    assert "marker_pdf.convert" not in internals
