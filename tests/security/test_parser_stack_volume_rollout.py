"""Static contracts for the H3 parser-stack package-volume rollout."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
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


def test_normal_rollback_keeps_clean_h3_volume_and_legacy_use_is_an_emergency_exception():
    runbook = (PROJECT_ROOT / "docs" / "H3_PARSER_STACK_ROLLOUT.md").read_text()
    normal_rollback, emergency_heading, emergency_exception = runbook.partition(
        "## 4. Legacy-volume emergency exception"
    )

    assert emergency_heading
    assert 'PIP_PACKAGES_ACTIVE_VOLUME="$PIP_PACKAGES_ROLLBACK_VOLUME"' not in normal_rollback
    assert 'PIP_PACKAGES_ACTIVE_VOLUME="$PIP_PACKAGES_ROLLBACK_VOLUME"' in emergency_exception
    for required_safeguard in (
        "direct user approval",
        "time-bounded",
        "compensating monitoring",
        "return to the fresh volume",
    ):
        assert required_safeguard in runbook.lower()


def _write_distribution_metadata(target: Path, name: str, version: str) -> None:
    metadata_dir = target / f"{name}-{version}.dist-info"
    metadata_dir.mkdir()
    (metadata_dir / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")


def _write_decoder_module(target: Path, package: str, version: str) -> None:
    module_dir = target / package
    module_dir.mkdir()
    (module_dir / "__init__.py").write_text(f'__version__ = "{version}"\n')


def _verify_target_python() -> str:
    helper = (PROJECT_ROOT / "scripts" / "prepare_h3_pip_packages_volume.sh").read_text()
    verify_body = helper.split("verify_target() {", 1)[1].split("\n}\n\ncase", 1)[0]
    match = re.search(r"<<'PY'\n(?P<python>.*?)\nPY", verify_body, flags=re.DOTALL)
    assert match, "verify_target must pass a Python verifier to the mounted target volume"
    return match.group("python")


@pytest.mark.parametrize(
    ("pillow", "pi_heif", "rejected_distribution"),
    [
        ("10.4.0", "1.4.0", "Pillow"),
        ("12.3.0", "1.2.0", "pi-heif"),
    ],
)
def test_verify_target_rejects_outdated_native_decoder_in_mounted_target(
    tmp_path: Path, pillow: str, pi_heif: str, rejected_distribution: str
):
    target = tmp_path / "packages"
    target.mkdir()
    _write_distribution_metadata(target, "Pillow", pillow)
    _write_distribution_metadata(target, "pi-heif", pi_heif)
    _write_decoder_module(target, "PIL", pillow)
    _write_decoder_module(target, "pi_heif", pi_heif)

    environment = os.environ | {
        "PACKAGES_DIR": str(target),
        "PYTHONPATH": f"{target}{os.pathsep}{PROJECT_ROOT}",
    }
    result = subprocess.run(
        [sys.executable, "-c", _verify_target_python()],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert result.returncode != 0
    assert rejected_distribution in f"{result.stdout}\n{result.stderr}"
