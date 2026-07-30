"""Security contracts for the native image-parser dependency surfaces."""

import tomllib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECURITY_FLOORS = {"pillow": (12, 3, 0), "pi-heif": (1, 3, 0)}
RETIRED_PARSER_LOCK_PACKAGES = {"marker-pdf", "surya-ocr"}


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split(".")[:3])


def _locked_package_versions() -> dict[str, str]:
    with (PROJECT_ROOT / "uv.lock").open("rb") as lock_file:
        lock = tomllib.load(lock_file)
    return {package["name"]: package["version"] for package in lock["package"]}


@pytest.mark.parametrize("package", sorted(SECURITY_FLOORS))
def test_lock_resolves_patched_native_parser_dependency(package: str):
    version = _locked_package_versions()[package]
    assert _version_tuple(version) >= SECURITY_FLOORS[package], (
        f"{package} must resolve to at least "
        f"{'.'.join(map(str, SECURITY_FLOORS[package]))}; got {version}"
    )


def test_lock_retired_parser_stack_is_absent_without_claiming_h4_optional_dependencies():
    locked_packages = _locked_package_versions()
    retired_packages = {
        package
        for package in locked_packages
        if package in RETIRED_PARSER_LOCK_PACKAGES
    }
    assert not retired_packages, f"retired parser packages remain locked: {retired_packages}"


def test_parser_owner_manifests_declare_security_floors_without_marker():
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text().lower()
    core_requirements = (PROJECT_ROOT / "requirements-core.txt").read_text()
    for package, minimum in SECURITY_FLOORS.items():
        requirement = f"{package}>={'.'.join(map(str, minimum))}"
        assert requirement in pyproject
        assert requirement in core_requirements.lower()

    assert "unstructured[all-docs]" not in pyproject
    assert "marker-pdf" not in pyproject
    assert not (PROJECT_ROOT / "requirements-ocr.txt").exists()


def test_api_image_has_no_marker_build_path():
    api_dockerfile = (PROJECT_ROOT / "docker" / "api.Dockerfile").read_text()

    assert "MARKER" not in api_dockerfile
    assert "requirements-ocr.txt" not in api_dockerfile
