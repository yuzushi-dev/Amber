"""Contract tests for the immutable, CPU-only H4 ML artifact."""

from pathlib import Path
import json
import subprocess

import pytest

from src.shared.ml_runtime_artifact import (
    ArtifactProfile,
    publish_preload_validation_proof,
    validate_nomic_policy,
    validate_preload_validation_proof,
    validate_requirements_lock,
)


VALID_LOCK = """\
--index-url https://pypi.org/simple
--find-links https://download-r2.pytorch.org/whl/cpu/torch-2.13.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl

torch==2.13.0+cpu --hash=sha256:torchhash
transformers==5.5.0 --hash=sha256:transformershash
onnx==1.22.0 --hash=sha256:onnxhash
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
            "flashrank==0.2.10 " + chr(92),
            "    --hash=sha256:flashrankhash",
        ]
    )

    result = validate_requirements_lock(multiline_lock, ArtifactProfile("3.11", "Linux", "x86_64"))

    assert result.errors == []


def test_accepts_numpy_2_for_the_2026_torch_2_13_cpu_wheel():
    compatible_lock = f"{VALID_LOCK}numpy==2.4.4 --hash=sha256:numpyhash\n"

    errors = validate_requirements_lock(compatible_lock, ArtifactProfile("3.11", "Linux", "x86_64")).errors

    assert errors == []


def test_repository_lock_satisfies_the_cpu_artifact_contract():
    root = Path(__file__).parents[2]
    lock_text = (root / "requirements-ml-h4-cpu.in").read_text() + "\n" + (
        root / "requirements-ml-h4-cpu.lock"
    ).read_text()

    result = validate_requirements_lock(lock_text, ArtifactProfile("3.11", "Linux", "x86_64"))

    assert result.errors == []
    assert result.packages["torch"] == "2.13.0+cpu"
    assert result.packages["numpy"].startswith("2.")
    assert "sentence-transformers" not in result.packages


def test_nomic_only_policy_rejects_baai_and_sentence_transformers_cache_paths():
    forbidden_lock = f"{VALID_LOCK}sentence-transformers==5.6.1 --hash=sha256:sentencehash\n# BAAI/bge-m3\n"

    errors = validate_nomic_policy(
        forbidden_lock,
        cache_paths=(
            "hf-cache/hub/models--naver--splade-cocondenser-ensembledistil",
            "hf-cache/sentence-transformers/models--BAAI--bge-m3",
        ),
    )

    assert "H4 Nomic policy forbids sentence-transformers" in errors
    assert "H4 Nomic policy forbids BAAI/bge-m3" in errors
    assert "H4 Nomic policy forbids BAAI model cache paths" in errors


def test_nomic_only_policy_accepts_sparse_and_rerank_caches():
    errors = validate_nomic_policy(
        VALID_LOCK,
        cache_paths=(
            "hf-cache/hub/models--naver--splade-cocondenser-ensembledistil",
            "flashrank-cache/ms-marco-MiniLM-L-12-v2",
        ),
    )

    assert errors == []


def test_accepts_complete_offline_post_preload_validation_proof():
    proof = {
        "schema": "h4-preload-validation/v1",
        "network_mode": "none",
        "offline": {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        },
        "lock_sha256": "expected-lock",
        "packages": {
            "torch": "2.13.0+cpu",
            "transformers": "5.14.1",
            "onnx": "1.22.0",
            "flashrank": "0.2.10",
        },
        "torch": {"cuda_available": False, "version_cuda": None},
        "nvidia_distributions": [],
        "nomic_policy_errors": [],
        "dense_local_distributions": [],
        "dense_local_cache_paths": [],
        "candidate_scan": {"root": "/app/.packages", "path_count": 1234},
        "storage": {
            "preflight_free_bytes": 30_000_000_000,
            "baseline_free_bytes": 29_000_000_000,
            "postflight_free_bytes": 30_000_000_000,
            "postflight_growth_bytes": -1_000_000_000,
        },
        "first_use": {"splade_sparse_terms": 4, "flashrank_results": 2},
    }

    errors = validate_preload_validation_proof(
        proof,
        expected_lock_sha256="expected-lock",
        expected_packages=proof["packages"],
    )

    assert errors == []


def test_rejects_incomplete_or_non_cpu_post_preload_validation_proof():
    proof = {
        "schema": "h4-preload-validation/v1",
        "network_mode": "bridge",
        "offline": {"HF_HUB_OFFLINE": "0", "TRANSFORMERS_OFFLINE": "1"},
        "lock_sha256": "wrong-lock",
        "packages": {"torch": "2.13.0"},
        "torch": {"cuda_available": True, "version_cuda": "12.4"},
        "nvidia_distributions": ["nvidia-cuda-runtime-cu12"],
        "nomic_policy_errors": ["H4 Nomic policy forbids BAAI/bge-m3"],
        "dense_local_distributions": ["sentence-transformers"],
        "dense_local_cache_paths": [".cache/models--BAAI--bge-m3"],
        "candidate_scan": {"root": "/app/.packages/hf-cache", "path_count": 1},
        "storage": {
            "preflight_free_bytes": 30_000_000_000,
            "baseline_free_bytes": 29_000_000_000,
            "postflight_free_bytes": 1,
            "postflight_growth_bytes": 4_294_967_297,
        },
        "first_use": {"splade_sparse_terms": 0, "flashrank_results": 0},
    }

    errors = validate_preload_validation_proof(
        proof,
        expected_lock_sha256="expected-lock",
        expected_packages={"torch": "2.13.0+cpu", "transformers": "5.14.1"},
    )

    assert "post-preload validation must run with --network none" in errors
    assert "post-preload validation requires HF_HUB_OFFLINE=1" in errors
    assert "post-preload validation lock hash mismatch" in errors
    assert "torch version mismatch: expected 2.13.0+cpu, got 2.13.0" in errors
    assert "transformers missing from post-preload validation" in errors
    assert "torch.cuda.is_available() must be false" in errors
    assert "torch.version.cuda must be null" in errors
    assert "NVIDIA/CUDA distributions are forbidden: nvidia-cuda-runtime-cu12" in errors
    assert "post-preload validation found Nomic policy errors" in errors
    assert "post-preload validation found dense-local distributions" in errors
    assert "post-preload validation found dense-local cache paths" in errors
    assert "post-preload validation did not scan the complete candidate tree" in errors
    assert "post-preload validation storage floor failed" in errors
    assert "post-preload validation storage budget exceeded" in errors
    assert "offline SPLADE first-use validation did not produce sparse terms" in errors
    assert "offline FlashRank first-use validation did not return two results" in errors


def test_atomic_proof_publication_never_leaves_a_canonical_file_after_write_failure(tmp_path):
    target = tmp_path / ".h4-preload-validation.json"

    def fail_after_partial_write(handle):
        handle.write('{"partial":')
        raise OSError("simulated proof write failure")

    with pytest.raises(OSError, match="simulated proof write failure"):
        publish_preload_validation_proof(
            target,
            {"schema": "h4-preload-validation/v1"},
            write_payload=fail_after_partial_write,
        )

    assert not target.exists()
    assert list(tmp_path.glob(".h4-preload-validation.json.*.tmp")) == []


def test_atomic_proof_publication_persists_only_complete_json(tmp_path):
    target = tmp_path / ".h4-preload-validation.json"
    proof = {"schema": "h4-preload-validation/v1", "storage": {"postflight": 1}}

    publish_preload_validation_proof(target, proof)

    assert json.loads(target.read_text()) == proof
    assert list(tmp_path.glob(".h4-preload-validation.json.*.tmp")) == []


def test_atomic_proof_publication_does_not_overwrite_an_existing_proof(tmp_path):
    target = tmp_path / ".h4-preload-validation.json"
    target.write_text('{"existing": true}\n')

    with pytest.raises(FileExistsError):
        publish_preload_validation_proof(target, {"schema": "replacement"})

    assert target.read_text() == '{"existing": true}\n'


def test_builder_is_scoped_to_the_single_labeled_candidate_volume():
    root = Path(__file__).parents[2]
    script = (root / "scripts/h4_ml_runtime_candidate.sh").read_text()

    assert "ambermirror_pip-packages-h4-cpu-nomic-20260730" in script
    assert "amber.h4.role" in script
    assert "amber.h4.profile" in script
    assert "amber.h4.strategy" in script
    assert "amber.h4.source" in script
    assert "--require-hashes" in script
    assert "--no-index" in script
    assert "--read-only" in script
    assert "--tmpfs /tmp:rw,noexec,nosuid,size=1g" in script
    assert "df -B1 --output=avail /var/lib/docker" in script
    assert 'df -B1 --output=avail "$1"' not in script
    assert '"$mountpoint/.' not in script
    assert "h4-install-${H4_ATTEMPT_ID}-download.log" in script
    assert "h4-install-${H4_ATTEMPT_ID}-install.log" in script
    assert "TMPDIR=/artifact/.h4-pip-tmp" in script
    assert "--no-compile" in script
    assert "test -f /artifact/.h4-storage-baseline" in script
    assert "H4_ATTEMPT_ID" in script
    assert "download_skipped=immutable-wheelhouse-reuse" in script
    assert "H4_WHEELHOUSE_MODE" in script
    assert "--authorize-preload" in script
    assert "--network none" in script
    assert "dst=/app/.packages,readonly" in script
    assert "packages_root.rglob(\"*\")" in script
    assert "HF_HUB_OFFLINE=1" in script
    assert "TRANSFORMERS_OFFLINE=1" in script
    assert "HF_DATASETS_OFFLINE=1" in script
    assert "local_files_only=True" in script
    assert ".h4-preload-validation.json" in script
    assert "validate_preload_validation_proof" in script
    assert "torch.cuda.is_available() is False" in script
    assert "torch.version.cuda is None" in script
    assert 'run_post_preload_validation\ncheck_postflight_space "preload" "$baseline_free"\nwrite_post_preload_proof' in script
    assert "publish_preload_validation_proof" in script
    assert "assert not target.exists()" not in script
    assert "SetupService" not in script
    assert "amber2_pip-packages" not in script


def test_rollout_requires_explicit_preload_authorization_and_offline_proof():
    root = Path(__file__).parents[2]
    rollout = (root / "docs/H4_ML_RUNTIME_ROLLOUT.md").read_text()

    assert "--authorize-preload" in rollout
    assert "direct user approval" in rollout
    assert "--network none" in rollout
    assert ".h4-preload-validation.json" in rollout
    assert "after the storage postflight succeeds" in rollout


def test_preload_refuses_to_reach_docker_without_the_explicit_guard():
    root = Path(__file__).parents[2]
    script = root / "scripts/h4_ml_runtime_candidate.sh"

    result = subprocess.run(
        [str(script), "preload", "--volume", "ambermirror_pip-packages-h4-cpu-nomic-20260730"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 1
    assert "preload requires --authorize-preload after direct user approval" in result.stderr
