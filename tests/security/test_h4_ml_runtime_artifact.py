"""Contract tests for the immutable, CPU-only H4 ML artifact."""

from pathlib import Path

from src.shared.ml_runtime_artifact import ArtifactProfile, validate_requirements_lock


VALID_LOCK = """\
--index-url https://pypi.org/simple
--find-links https://download-r2.pytorch.org/whl/cpu/torch-2.13.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl

torch==2.13.0+cpu --hash=sha256:torchhash
transformers==5.5.0 --hash=sha256:transformershash
onnx==1.22.0 --hash=sha256:onnxhash
sentence-transformers==5.1.0 --hash=sha256:sentencehash
flashrank==0.2.10 --hash=sha256:flashrankhash
"""


def test_accepts_exact_cpu_lock_for_container_abi():
    profile = ArtifactProfile(python_version="3.11", system="Linux", machine="x86_64")

    result = validate_requirements_lock(VALID_LOCK, profile)

    assert result.errors == []
    assert result.packages["torch"] == "2.13.0+cpu"
    assert result.packages["transformers"] == "5.5.0"
    assert result.packages["onnx"] == "1.22.0"


def test_rejects_unpinned_or_unhashed_requirement():
    invalid_lock = VALID_LOCK.replace(
        "flashrank==0.2.10 --hash=sha256:flashrankhash", "flashrank>=0.2.10"
    )

    errors = validate_requirements_lock(invalid_lock, ArtifactProfile("3.11", "Linux", "x86_64")).errors

    assert "flashrank must use an exact == pin" in errors
    assert "flashrank must include at least one sha256 hash" in errors


def test_rejects_torch_without_cpu_wheel_pin_and_index():
    invalid_lock = VALID_LOCK.replace("torch==2.13.0+cpu", "torch==2.13.0").replace(
        "--find-links https://download-r2.pytorch.org/whl/cpu/torch-2.13.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl\n",
        "",
    )

    errors = validate_requirements_lock(invalid_lock, ArtifactProfile("3.11", "Linux", "x86_64")).errors

    assert "torch must use an explicit +cpu wheel build" in errors
    assert "torch requires the PyTorch CPU wheel index" in errors


def test_rejects_non_container_abi():
    errors = validate_requirements_lock(VALID_LOCK, ArtifactProfile("3.12", "Linux", "x86_64")).errors

    assert errors == ["artifact requires CPython 3.11 on Linux x86_64"]


def test_rejects_unhashed_transitive_requirement():
    invalid_lock = f"{VALID_LOCK}filelock==3.20.0\n"

    errors = validate_requirements_lock(invalid_lock, ArtifactProfile("3.11", "Linux", "x86_64")).errors

    assert "filelock must include at least one sha256 hash" in errors


def test_accepts_hashes_on_pip_continuation_lines():
    multiline_lock = "\n".join(
        [
            "--index-url https://pypi.org/simple",
            "--find-links https://download-r2.pytorch.org/whl/cpu/torch-2.13.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl",
            "",
            "torch==2.13.0+cpu " + chr(92),
            "    --hash=sha256:torchhash",
            "transformers==5.5.0 " + chr(92),
            "    --hash=sha256:transformershash",
            "onnx==1.22.0 " + chr(92),
            "    --hash=sha256:onnxhash",
            "sentence-transformers==5.1.0 " + chr(92),
            "    --hash=sha256:sentencehash",
            "flashrank==0.2.10 " + chr(92),
            "    --hash=sha256:flashrankhash",
        ]
    )

    result = validate_requirements_lock(multiline_lock, ArtifactProfile("3.11", "Linux", "x86_64"))

    assert result.errors == []


def test_rejects_numpy_2_for_torch_2_13_abi():
    invalid_lock = f"{VALID_LOCK}numpy==2.4.4 --hash=sha256:numpyhash\n"

    errors = validate_requirements_lock(invalid_lock, ArtifactProfile("3.11", "Linux", "x86_64")).errors

    assert "torch 2.13 requires NumPy 1.x for binary ABI compatibility" in errors


def test_repository_lock_satisfies_the_cpu_artifact_contract():
    root = Path(__file__).parents[2]
    lock_text = (root / "requirements-ml-h4-cpu.in").read_text() + "\n" + (
        root / "requirements-ml-h4-cpu.lock"
    ).read_text()

    result = validate_requirements_lock(lock_text, ArtifactProfile("3.11", "Linux", "x86_64"))

    assert result.errors == []


def test_builder_is_scoped_to_the_single_labeled_candidate_volume():
    root = Path(__file__).parents[2]
    script = (root / "scripts/h4_ml_runtime_candidate.sh").read_text()

    assert "ambermirror_pip-packages-h4-cpu-20260730" in script
    assert "amber.h4.role" in script
    assert "amber.h4.profile" in script
    assert "--require-hashes" in script
    assert "--no-index" in script
    assert "SetupService" not in script
    assert "amber2_pip-packages" not in script
