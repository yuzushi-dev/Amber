"""Static validation for the immutable H4 ML runtime artifact."""

import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, cast

_REQUIRED_MINIMUMS = {
    "torch": (2, 13),
    "transformers": (5, 5),
    "onnx": (1, 22),
    "flashrank": (0, 0),
}
_CPU_WHEEL_SOURCE = "pytorch.org/whl/cpu"
_MIN_FREE_BYTES = 20 * 1024 * 1024 * 1024
_PEAK_BUDGET_BYTES = 4 * 1024 * 1024 * 1024
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


@dataclass(frozen=True)
class ArtifactProfile:
    python_version: str
    system: str
    machine: str


@dataclass(frozen=True)
class ValidationResult:
    packages: dict[str, str]
    errors: list[str]


def validate_requirements_lock(lock_text: str, profile: ArtifactProfile) -> ValidationResult:
    """Validate the H4 direct-package contract without invoking pip."""
    if (profile.python_version, profile.system, profile.machine) != ("3.11", "Linux", "x86_64"):
        return ValidationResult({}, ["artifact requires CPython 3.11 on Linux x86_64"])

    packages: dict[str, str] = {}
    hashes: dict[str, list[str]] = {}
    declared: set[str] = set()
    unpinned: set[str] = set()
    has_cpu_index = _CPU_WHEEL_SOURCE in lock_text

    active_package: str | None = None
    for raw_line in lock_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        hash_values = re.findall(r"--hash=sha256:([^\s\\]+)", line)
        if line.startswith("--hash=sha256:"):
            if active_package:
                hashes.setdefault(active_package, []).extend(hash_values)
            continue
        if line.startswith("--"):
            continue
        requirement = line.split()[0]
        name_match = re.match(r"[A-Za-z0-9_.-]+", requirement)
        if not name_match:
            continue
        name = name_match.group(0).lower()
        active_package = name
        declared.add(name)
        exact_match = re.fullmatch(r"[A-Za-z0-9_.-]+==([^=\s\\][^\s\\]*)", requirement)
        if exact_match:
            packages[name] = exact_match.group(1)
        else:
            unpinned.add(name)
        if hash_values:
            hashes.setdefault(name, []).extend(hash_values)

    errors: list[str] = []
    for package, minimum in _REQUIRED_MINIMUMS.items():
        version = packages.get(package)
        if version is None:
            if package not in declared:
                errors.append(f"missing required package: {package}")
            continue
        if not _is_at_least(version, minimum):
            errors.append(f"{package} must meet minimum version {_format_minimum(minimum)}")

    torch_version = packages.get("torch")
    if torch_version and not torch_version.endswith("+cpu"):
        errors.append("torch must use an explicit +cpu wheel build")
    if torch_version and not has_cpu_index:
        errors.append("torch requires the PyTorch CPU wheel index")
    for package in sorted(declared):
        if package in unpinned or package not in packages:
            errors.append(f"{package} must use an exact == pin")
        package_hashes = hashes.get(package, [])
        if not package_hashes:
            errors.append(f"{package} must include at least one sha256 hash")
        elif not all(_SHA256_HEX.fullmatch(value) for value in package_hashes):
            errors.append(f"{package} must include a valid sha256 hash")

    errors.extend(validate_nomic_policy(lock_text))
    return ValidationResult(packages, errors)


def validate_nomic_policy(lock_text: str, cache_paths: tuple[str, ...] = ()) -> list[str]:
    """Reject dense-local dependencies and caches from the Nomic/Ollama strategy."""
    errors: list[str] = []
    normalized_lock = lock_text.lower()
    if "sentence-transformers" in normalized_lock:
        errors.append("H4 Nomic policy forbids sentence-transformers")
    if "baai/bge-m3" in normalized_lock:
        errors.append("H4 Nomic policy forbids BAAI/bge-m3")

    normalized_paths = [path.lower() for path in cache_paths]
    if any("baai" in path or "bge-m3" in path for path in normalized_paths):
        errors.append("H4 Nomic policy forbids BAAI model cache paths")
    if any("sentence-transformers" in path for path in normalized_paths):
        errors.append("H4 Nomic policy forbids sentence-transformers cache paths")
    return errors


def publish_preload_validation_proof(
    target: Path,
    proof: Mapping[str, object],
    *,
    write_payload: Callable[[TextIO], None] | None = None,
) -> None:
    """Atomically publish a proof without replacing an existing canonical file."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f"{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            if write_payload is None:
                json.dump(proof, temporary_file, indent=2, sort_keys=True)
                temporary_file.write("\n")
            else:
                write_payload(cast(TextIO, temporary_file.file))
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.link(temporary_path, target)
        _fsync_directory(target.parent)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
            else:
                try:
                    _fsync_directory(target.parent)
                except OSError:
                    pass


def _fsync_directory(directory: Path) -> None:
    directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def publish_staged_model_manifest(staged: Path, target: Path) -> None:
    """Atomically publish a validated staged model manifest without replacing one."""
    staged_fd = os.open(staged, os.O_RDONLY)
    try:
        os.fsync(staged_fd)
    finally:
        os.close(staged_fd)
    os.link(staged, target)
    _fsync_directory(target.parent)


def validate_preload_validation_proof(
    proof: Mapping[str, object],
    *,
    expected_lock_sha256: str,
    expected_packages: Mapping[str, str],
    require_storage: bool = True,
) -> list[str]:
    """Validate durable evidence from the network-isolated post-preload check."""
    errors: list[str] = []
    if proof.get("schema") != "h4-preload-validation/v1":
        errors.append("post-preload validation proof schema is invalid")
    if proof.get("network_mode") != "none":
        errors.append("post-preload validation must run with --network none")

    offline = proof.get("offline")
    if not isinstance(offline, Mapping):
        offline = {}
    for variable in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        if offline.get(variable) != "1":
            errors.append(f"post-preload validation requires {variable}=1")

    if proof.get("lock_sha256") != expected_lock_sha256:
        errors.append("post-preload validation lock hash mismatch")

    packages = proof.get("packages")
    if not isinstance(packages, Mapping):
        packages = {}
    for name, expected_version in sorted(expected_packages.items()):
        actual_version = packages.get(name)
        if actual_version is None:
            errors.append(f"{name} missing from post-preload validation")
        elif actual_version != expected_version:
            errors.append(
                f"{name} version mismatch: expected {expected_version}, got {actual_version}"
            )

    torch = proof.get("torch")
    if not isinstance(torch, Mapping):
        torch = {}
    if torch.get("cuda_available") is not False:
        errors.append("torch.cuda.is_available() must be false")
    if torch.get("version_cuda") is not None:
        errors.append("torch.version.cuda must be null")

    nvidia_distributions = proof.get("nvidia_distributions")
    if not isinstance(nvidia_distributions, list):
        nvidia_distributions = ["invalid-proof-value"]
    if nvidia_distributions:
        errors.append(
            "NVIDIA/CUDA distributions are forbidden: "
            + ", ".join(sorted(str(name) for name in nvidia_distributions))
        )

    if proof.get("nomic_policy_errors") != []:
        errors.append("post-preload validation found Nomic policy errors")
    if proof.get("dense_local_distributions") != []:
        errors.append("post-preload validation found dense-local distributions")
    if proof.get("dense_local_cache_paths") != []:
        errors.append("post-preload validation found dense-local cache paths")

    candidate_scan = proof.get("candidate_scan")
    if (
        not isinstance(candidate_scan, Mapping)
        or candidate_scan.get("root") != "/app/.packages"
        or not isinstance(candidate_scan.get("path_count"), int)
        or candidate_scan["path_count"] <= 0
    ):
        errors.append("post-preload validation did not scan the complete candidate tree")

    flashrank = proof.get("flashrank")
    if (
        not isinstance(flashrank, Mapping)
        or not isinstance(flashrank.get("model"), str)
        or not flashrank["model"]
        or not isinstance(flashrank.get("cache_sha256"), str)
        or not _SHA256_HEX.fullmatch(flashrank["cache_sha256"])
    ):
        errors.append("post-preload validation FlashRank cache sha256 is invalid")

    if require_storage:
        storage = proof.get("storage")
        if not isinstance(storage, Mapping):
            errors.append("post-preload validation storage evidence is missing")
        else:
            preflight_free = storage.get("preflight_free_bytes")
            baseline_free = storage.get("baseline_free_bytes")
            postflight_free = storage.get("postflight_free_bytes")
            postflight_growth = storage.get("postflight_growth_bytes")
            if not (
                isinstance(preflight_free, int)
                and preflight_free >= 0
                and isinstance(baseline_free, int)
                and baseline_free >= 0
                and isinstance(postflight_free, int)
                and postflight_free >= 0
                and isinstance(postflight_growth, int)
            ):
                errors.append("post-preload validation storage evidence is invalid")
            else:
                if postflight_free < _MIN_FREE_BYTES:
                    errors.append("post-preload validation storage floor failed")
                if postflight_growth > _PEAK_BUDGET_BYTES:
                    errors.append("post-preload validation storage budget exceeded")

    first_use = proof.get("first_use")
    if not isinstance(first_use, Mapping):
        first_use = {}
    if (
        not isinstance(first_use.get("splade_sparse_terms"), int)
        or first_use["splade_sparse_terms"] <= 0
    ):
        errors.append("offline SPLADE first-use validation did not produce sparse terms")
    if first_use.get("flashrank_results") != 2:
        errors.append("offline FlashRank first-use validation did not return two results")

    return errors


def _is_at_least(version: str, minimum: tuple[int, int]) -> bool:
    match = re.match(r"(\d+)\.(\d+)", version)
    if not match:
        return False
    return (int(match.group(1)), int(match.group(2))) >= minimum


def _format_minimum(minimum: tuple[int, int]) -> str:
    return f"{minimum[0]}.{minimum[1]}"
