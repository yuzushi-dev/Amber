"""Static validation for the immutable H4 ML runtime artifact."""

from dataclasses import dataclass
import re


_REQUIRED_MINIMUMS = {
    "torch": (2, 13),
    "transformers": (5, 5),
    "onnx": (1, 22),
    "flashrank": (0, 0),
}
_CPU_WHEEL_SOURCE = "pytorch.org/whl/cpu"


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
    hashes: set[str] = set()
    declared: set[str] = set()
    has_cpu_index = _CPU_WHEEL_SOURCE in lock_text

    active_package: str | None = None
    for raw_line in lock_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("--hash=sha256:"):
            if active_package:
                hashes.add(active_package)
            continue
        if line.startswith("--"):
            continue
        requirement = line.split()[0]
        match = re.match(r"([A-Za-z0-9-]+)(==(.+))?", requirement)
        if not match:
            continue
        name = match.group(1).lower()
        active_package = name
        declared.add(name)
        if match.group(2):
            packages[name] = match.group(3)
        if "--hash=sha256:" in line:
            hashes.add(name)

    errors: list[str] = []
    for package, minimum in _REQUIRED_MINIMUMS.items():
        version = packages.get(package)
        if version is None:
            if package not in declared:
                errors.append(f"missing required package: {package}")
            else:
                errors.append(f"{package} must use an exact == pin")
                if package not in hashes:
                    errors.append(f"{package} must include at least one sha256 hash")
            continue
        if package not in hashes:
            errors.append(f"{package} must include at least one sha256 hash")
        if not _is_at_least(version, minimum):
            errors.append(f"{package} must meet minimum version {_format_minimum(minimum)}")

    torch_version = packages.get("torch")
    if torch_version and not torch_version.endswith("+cpu"):
        errors.append("torch must use an explicit +cpu wheel build")
    if torch_version and not has_cpu_index:
        errors.append("torch requires the PyTorch CPU wheel index")
    for package in sorted(declared):
        error = f"{package} must include at least one sha256 hash"
        if package not in hashes and error not in errors:
            errors.append(error)

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


def _is_at_least(version: str, minimum: tuple[int, int]) -> bool:
    match = re.match(r"(\d+)\.(\d+)", version)
    if not match:
        return False
    return (int(match.group(1)), int(match.group(2))) >= minimum


def _format_minimum(minimum: tuple[int, int]) -> str:
    return f"{minimum[0]}.{minimum[1]}"
