"""Static contracts for the H3 parser-stack package-volume rollout."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_VOLUME = "amber2_pip-packages-h3"
LEGACY_VOLUME = "amber2_pip-packages"


def _compose(path: str) -> dict:
    return yaml.safe_load((PROJECT_ROOT / path).read_text())


def _assert_active_mounts(compose: dict, services: tuple[str, ...]) -> None:
    for service_name in services:
        mounts = compose["services"][service_name]["volumes"]
        assert "pip-packages:/app/.packages" in mounts


def _assert_versioned_volume_contract(compose: dict) -> None:
    volumes = compose["volumes"]
    assert volumes["pip-packages"] == {
        "external": True,
        "name": "${PIP_PACKAGES_ACTIVE_VOLUME:-amber2_pip-packages-h3}",
    }
    assert volumes["pip-packages-rollback"] == {
        "external": True,
        "name": "${PIP_PACKAGES_ROLLBACK_VOLUME:-amber2_pip-packages}",
    }


def test_default_and_canary_compose_select_fresh_h3_volume_and_keep_rollback_reference():
    base_compose = _compose("docker-compose.yml")
    canary_compose = _compose("deploy/docker-compose.canary.yml")

    _assert_active_mounts(base_compose, ("api", "worker", "celery_beat"))
    _assert_active_mounts(canary_compose, ("api-canary", "worker-canary"))
    _assert_versioned_volume_contract(base_compose)
    _assert_versioned_volume_contract(canary_compose)


def test_h3_volume_helper_is_dry_run_by_default_and_never_copies_legacy_volume():
    helper = PROJECT_ROOT / "scripts" / "prepare_h3_pip_packages_volume.sh"
    result = subprocess.run(
        [
            "bash",
            str(helper),
            "--image",
            "amber2-api:h3",
            "--source-volume",
            LEGACY_VOLUME,
            "--target-volume",
            ACTIVE_VOLUME,
            "--features",
            "local_embeddings,reranking",
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "DRY RUN" in result.stdout
    assert LEGACY_VOLUME in result.stdout
    assert ACTIVE_VOLUME in result.stdout
    assert "No Docker mutation will run" in result.stdout
    assert "cp -a" not in helper.read_text()


def test_h3_rollout_document_requires_explicit_feature_restore_and_validation():
    runbook = (PROJECT_ROOT / "docs" / "H3_PARSER_STACK_ROLLOUT.md").read_text()

    assert "PIP_PACKAGES_ACTIVE_VOLUME" in runbook
    assert "PIP_PACKAGES_ROLLBACK_VOLUME" in runbook
    assert "--inventory" in runbook
    assert "--apply" in runbook
    assert "local_embeddings" in runbook
    assert "docker compose -f docker-compose.yml config" in runbook
    assert "rollback" in runbook.lower()
    assert "cp -a /from/. /to/" not in runbook
