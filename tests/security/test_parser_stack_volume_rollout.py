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


def _assert_active_mounts(
    compose: dict, services: tuple[str, ...], *, read_only: bool = False
) -> None:
    expected_mount = "pip-packages:/app/.packages:ro" if read_only else "pip-packages:/app/.packages"
    for service_name in services:
        mounts = compose["services"][service_name]["volumes"]
        assert expected_mount in mounts


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
    _assert_active_mounts(canary_compose, ("api-canary", "worker-canary"), read_only=True)
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


def test_verify_target_has_ephemeral_tmp_for_imports_in_read_only_container():
    helper = (PROJECT_ROOT / "scripts" / "prepare_h3_pip_packages_volume.sh").read_text()
    verify_body = helper.split("verify_target() {", 1)[1].split("\n}\n\ncase", 1)[0]

    assert "--read-only" in verify_body
    assert "--tmpfs /tmp:rw,noexec,nosuid,size=64m" in verify_body


@pytest.mark.parametrize("dockerfile", ["docker/api.Dockerfile", "docker/worker.Dockerfile"])
def test_runtime_images_create_writable_user_cache_before_switching_user(dockerfile: str):
    build = (PROJECT_ROOT / dockerfile).read_text()
    root_build, separator, _ = build.partition("USER appuser")

    assert separator, f"{dockerfile} must switch to appuser"
    assert (
        "install -d -o appuser -g appuser "
        "/home/appuser/.cache /home/appuser/.cache/huggingface" in root_build
    ), (
        f"{dockerfile} must own the Hugging Face cache parent before Compose bind-mounts "
        "its child path; otherwise Kreuzberg silently drops the Tesseract backend"
    )


@pytest.mark.parametrize("feature_id", ["local_embeddings", "reranking", "ragas"])
def test_optional_ml_features_pin_protobuf_compatible_with_opentelemetry(feature_id: str):
    from src.api.services.setup_service import OPTIONAL_FEATURES

    assert "protobuf==6.33.6" in OPTIONAL_FEATURES[feature_id].packages


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
