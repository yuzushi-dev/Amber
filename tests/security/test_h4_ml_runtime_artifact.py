"""Contract tests for the immutable, CPU-only H4 ML artifact."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

import src.shared.ml_runtime_artifact as ml_runtime_artifact
from src.shared.ml_runtime_artifact import (
    ArtifactProfile,
    publish_preload_validation_proof,
    publish_staged_model_manifest,
    validate_nomic_policy,
    validate_preload_validation_proof,
    validate_requirements_lock,
)

VALID_SHA256 = "a" * 64


VALID_LOCK = f"""\
--index-url https://pypi.org/simple
--find-links https://download-r2.pytorch.org/whl/cpu/torch-2.13.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl

torch==2.13.0+cpu --hash=sha256:{VALID_SHA256}
transformers==5.5.0 --hash=sha256:{VALID_SHA256}
onnx==1.22.0 --hash=sha256:{VALID_SHA256}
flashrank==0.2.10 --hash=sha256:{VALID_SHA256}
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
        f"flashrank==0.2.10 --hash=sha256:{VALID_SHA256}", "flashrank>=0.2.10"
    )

    errors = validate_requirements_lock(
        invalid_lock, ArtifactProfile("3.11", "Linux", "x86_64")
    ).errors

    assert "flashrank must use an exact == pin" in errors
    assert "flashrank must include at least one sha256 hash" in errors


def test_rejects_torch_without_cpu_wheel_pin_and_index():
    invalid_lock = VALID_LOCK.replace("torch==2.13.0+cpu", "torch==2.13.0").replace(
        "--find-links https://download-r2.pytorch.org/whl/cpu/torch-2.13.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl\n",
        "",
    )

    errors = validate_requirements_lock(
        invalid_lock, ArtifactProfile("3.11", "Linux", "x86_64")
    ).errors

    assert "torch must use an explicit +cpu wheel build" in errors
    assert "torch requires the PyTorch CPU wheel index" in errors


def test_rejects_non_container_abi():
    errors = validate_requirements_lock(
        VALID_LOCK, ArtifactProfile("3.12", "Linux", "x86_64")
    ).errors

    assert errors == ["artifact requires CPython 3.11 on Linux x86_64"]


def test_rejects_unhashed_transitive_requirement():
    invalid_lock = f"{VALID_LOCK}filelock==3.20.0\n"

    errors = validate_requirements_lock(
        invalid_lock, ArtifactProfile("3.11", "Linux", "x86_64")
    ).errors

    assert "filelock must include at least one sha256 hash" in errors


def test_rejects_non_exact_or_invalidly_hashed_transitive_requirement():
    invalid_lock = f"{VALID_LOCK}filelock>=3 --hash=sha256:not-a-sha256\n"

    errors = validate_requirements_lock(
        invalid_lock, ArtifactProfile("3.11", "Linux", "x86_64")
    ).errors

    assert "filelock must use an exact == pin" in errors
    assert "filelock must include a valid sha256 hash" in errors


def test_rejects_a_transitive_requirement_with_any_malformed_sha256_hash():
    invalid_lock = (
        f"{VALID_LOCK}filelock==3.20.0 --hash=sha256:{VALID_SHA256} --hash=sha256:not-a-sha256\n"
    )

    errors = validate_requirements_lock(
        invalid_lock, ArtifactProfile("3.11", "Linux", "x86_64")
    ).errors

    assert "filelock must include a valid sha256 hash" in errors


def test_rejects_any_non_exact_declaration_even_if_the_package_is_pinned_later():
    invalid_lock = (
        f"{VALID_LOCK}filelock>=3 --hash=sha256:{VALID_SHA256}\n"
        f"filelock==3.20.0 --hash=sha256:{VALID_SHA256}\n"
    )

    errors = validate_requirements_lock(
        invalid_lock, ArtifactProfile("3.11", "Linux", "x86_64")
    ).errors

    assert "filelock must use an exact == pin" in errors


def test_accepts_hashes_on_pip_continuation_lines():
    multiline_lock = "\n".join(
        [
            "--index-url https://pypi.org/simple",
            "--find-links https://download-r2.pytorch.org/whl/cpu/torch-2.13.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl",
            "",
            "torch==2.13.0+cpu " + chr(92),
            f"    --hash=sha256:{VALID_SHA256}",
            "transformers==5.5.0 " + chr(92),
            f"    --hash=sha256:{VALID_SHA256}",
            "onnx==1.22.0 " + chr(92),
            f"    --hash=sha256:{VALID_SHA256}",
            "flashrank==0.2.10 " + chr(92),
            f"    --hash=sha256:{VALID_SHA256}",
        ]
    )

    result = validate_requirements_lock(multiline_lock, ArtifactProfile("3.11", "Linux", "x86_64"))

    assert result.errors == []


def test_accepts_numpy_2_for_the_2026_torch_2_13_cpu_wheel():
    compatible_lock = f"{VALID_LOCK}numpy==2.4.4 --hash=sha256:{VALID_SHA256}\n"

    errors = validate_requirements_lock(
        compatible_lock, ArtifactProfile("3.11", "Linux", "x86_64")
    ).errors

    assert errors == []


def test_repository_lock_satisfies_the_cpu_artifact_contract():
    root = Path(__file__).parents[2]
    lock_text = (root / "requirements-ml-h4-cpu.lock").read_text()

    result = validate_requirements_lock(lock_text, ArtifactProfile("3.11", "Linux", "x86_64"))

    assert result.errors == []
    assert result.packages["torch"] == "2.13.0+cpu"
    assert result.packages["numpy"].startswith("2.")
    assert "sentence-transformers" not in result.packages


def test_repository_lock_does_not_downgrade_shared_application_runtime():
    root = Path(__file__).parents[2]
    lock_text = (root / "requirements-ml-h4-cpu.lock").read_text()

    packages = validate_requirements_lock(
        lock_text, ArtifactProfile("3.11", "Linux", "x86_64")
    ).packages

    assert packages["requests"] == "2.34.2"
    assert packages["urllib3"] == "2.7.0"
    assert packages["certifi"] == "2026.7.22"
    assert packages["charset-normalizer"] == "3.4.9"
    assert packages["idna"] == "3.18"
    assert packages["protobuf"] == "6.33.6"
    assert packages["setuptools"] == "78.1.1"
    assert packages["rich"] == "14.3.3"
    assert packages["tqdm"] == "4.70.0"


def test_nomic_only_policy_rejects_baai_and_sentence_transformers_cache_paths():
    forbidden_lock = (
        f"{VALID_LOCK}sentence-transformers==5.6.1 --hash=sha256:{VALID_SHA256}\n# BAAI/bge-m3\n"
    )

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
        "flashrank": {"model": "ms-marco-MiniLM-L-12-v2", "cache_sha256": VALID_SHA256},
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
        "flashrank": {"model": "ms-marco-MiniLM-L-12-v2", "cache_sha256": "not-a-hash"},
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
    assert "post-preload validation FlashRank cache sha256 is invalid" in errors
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


def test_staged_model_manifest_is_fsynced_before_exclusive_publication(tmp_path, monkeypatch):
    staged = tmp_path / ".h4-models-attempt.pending.json"
    target = tmp_path / ".h4-models.json"
    staged.write_text('{"flashrank": {}}\n')
    fsync_calls: list[int] = []

    monkeypatch.setattr(
        ml_runtime_artifact.os, "fsync", lambda descriptor: fsync_calls.append(descriptor)
    )

    publish_staged_model_manifest(staged, target)

    assert target.read_text() == '{"flashrank": {}}\n'
    assert len(fsync_calls) == 2


def test_builder_is_scoped_to_the_single_labeled_candidate_volume():
    root = Path(__file__).parents[2]
    script = (root / "scripts/h4_ml_runtime_candidate.sh").read_text()

    assert "ambermirror_pip-packages-h4-cpu-nomic-da122dfb-38eb9c2d" in script
    assert 'PRODUCTION_VOLUME_PREFIX="amber2_pip-packages-h4-cpu-nomic-da122dfb-"' in script
    assert "amber.h4.role" in script
    assert "amber.h4.profile" in script
    assert "amber.h4.strategy" in script
    assert "amber.h4.source" in script
    assert "amber.h4.source-ref" in script
    assert 'CANDIDATE_SOURCE_REF="da122dfb"' in script
    assert "--require-hashes" in script
    assert "--no-index" in script
    assert "--read-only" in script
    assert "--tmpfs /tmp:rw,noexec,nosuid,size=1g" in script
    assert "docker_local info --format '{{ .DockerRootDir }}'" in script
    assert 'df -B1 --output=avail -- "$docker_root"' in script
    assert "/var/lib/docker" not in script
    assert "H4_DOCKER_ROOT" not in script
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
    assert "--authorize-production" in script
    assert "git -C \"$root_dir\" rev-parse --verify 'HEAD^{commit}'" in script
    assert "amber.h4.candidate-ref" in script
    assert "--network none" in script
    assert "dst=/app/.packages,readonly" in script
    assert 'packages_root.rglob("*")' in script
    assert "HF_HUB_OFFLINE=1" in script
    assert "TRANSFORMERS_OFFLINE=1" in script
    assert "HF_DATASETS_OFFLINE=1" in script
    assert "local_files_only=True" in script
    assert ".h4-preload-validation.json" in script
    assert "validate_preload_validation_proof" in script
    assert "torch.cuda.is_available() is False" in script
    assert "torch.version.cuda is None" in script
    assert (
        'run_post_preload_validation "$staged_models"\ncheck_postflight_space "preload" "$baseline_free"\nwrite_post_preload_proof'
        in script
    )
    assert "publish_preload_validation_proof" in script
    assert "assert not target.exists()" not in script
    assert "SetupService" not in script
    assert "docker_local volume create" not in script
    assert "docker_local volume rm" not in script


def _run_builder_free_bytes(tmp_path: Path, docker_root: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    root = Path(__file__).parents[2]
    script = (root / "scripts/h4_ml_runtime_candidate.sh").read_text()
    function_prefix = script.split("[[ $# -ge 1 ]] || usage", maxsplit=1)[0]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    df_args = tmp_path / "df-args"
    fake_df = fake_bin / "df"
    fake_df.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$@" > "$DF_ARGS_LOG"\n'
        "printf 'Avail\\n30000000000\\n'\n"
    )
    fake_df.chmod(0o755)
    harness = (
        function_prefix
        + "\ndocker_local() { printf '%s\\n' \"$TEST_DOCKER_ROOT\"; }\n"
        + "free_bytes\n"
    )
    harness_path = tmp_path / "free-bytes-harness.sh"
    harness_path.write_text(harness)
    environment = {
        **os.environ,
        "DF_ARGS_LOG": str(df_args),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "TEST_DOCKER_ROOT": docker_root,
    }

    result = subprocess.run(
        ["bash", str(harness_path)],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    return result, df_args


def test_storage_gate_measures_the_daemon_docker_root(tmp_path):
    docker_root = tmp_path / "custom docker root"
    docker_root.mkdir()

    result, df_args = _run_builder_free_bytes(tmp_path, str(docker_root))

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "30000000000"
    assert df_args.read_text().splitlines() == [
        "-B1",
        "--output=avail",
        "--",
        str(docker_root),
    ]


@pytest.mark.parametrize(
    "docker_root",
    [
        "relative/docker",
        "/opt/docker\n/other",
        "/opt/docker\tother",
    ],
)
def test_storage_gate_rejects_invalid_daemon_docker_root_before_df(tmp_path, docker_root):
    result, df_args = _run_builder_free_bytes(tmp_path, docker_root)

    assert result.returncode == 1
    assert "Docker root" in result.stderr
    assert not df_args.exists()


def test_storage_gate_rejects_a_missing_daemon_docker_root_before_df(tmp_path):
    result, df_args = _run_builder_free_bytes(tmp_path, str(tmp_path / "missing"))

    assert result.returncode == 1
    assert "Docker root" in result.stderr
    assert not df_args.exists()


def test_builder_installs_and_validates_the_standalone_lock():
    root = Path(__file__).parents[2]
    script = (root / "scripts/h4_ml_runtime_candidate.sh").read_text()

    assert "TORCH_CPU_FIND_LINK" not in script
    assert 'Path(sys.argv[1]).read_text() + "\\n" + Path(sys.argv[2]).read_text()' not in script
    assert 'python3 - "$requirements_lock"' in script
    assert "--index-url https://pypi.org/simple" not in script
    assert '--find-links "\'"' not in script


def test_canary_uses_a_separate_read_only_h4_overlay():
    root = Path(__file__).parents[2]
    canary = (root / "deploy/docker-compose.canary.yml").read_text()

    assert 'entrypoint: ["/usr/local/bin/uvicorn"]' in canary
    assert 'command: ["src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]' in canary
    assert "AMBER_H4_ML_RUNTIME_ROOT=/app/.packages-h4" in canary
    assert "PYTHONPATH=/app/.packages-h4:/app:/app/src:/app/.packages" in canary
    assert canary.count("h4-ml-runtime:/app/.packages-h4:ro") == 2
    assert "H4_ML_RUNTIME_VOLUME" in canary
    assert "h4-ml-runtime:" in canary


def test_canary_compose_uses_the_live_project_identity_from_any_worktree():
    root = Path(__file__).parents[2]
    canary_path = root / "deploy/docker-compose.canary.yml"
    canary_text = canary_path.read_text()
    canary = yaml.safe_load(canary_text)

    assert canary["name"] == "amber2"
    assert canary_text.count("docker compose --project-name amber2") == 2
    assert "up -d --no-deps --no-build --pull never api-canary worker-canary" in canary_text


def test_resolved_canary_compose_reuses_live_datastore_volume_names():
    root = Path(__file__).parents[2]
    environment = os.environ | {
        "H4_ML_RUNTIME_VOLUME": "amber2_h4_candidate",
        "PIP_PACKAGES_ACTIVE_VOLUME": "amber2_h3_active",
        "PIP_PACKAGES_ROLLBACK_VOLUME": "amber2_h3_rollback",
    }
    try:
        compose_version = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        pytest.skip("Docker CLI is not installed")

    if compose_version.returncode != 0:
        pytest.skip("Docker Compose plugin is not available")

    command = [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "-f",
        "deploy/docker-compose.canary.yml",
        "config",
        "--format",
        "json",
    ]

    result = subprocess.run(
        command,
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    resolved = json.loads(result.stdout)
    assert resolved["name"] == "amber2"
    assert resolved["volumes"]["graphrag-postgres"]["name"] == "amber2_graphrag-postgres"
    assert resolved["volumes"]["graphrag-redis"]["name"] == "amber2_graphrag-redis"
    assert resolved["volumes"]["graphrag-neo4j"]["name"] == "amber2_graphrag-neo4j"
    assert resolved["volumes"]["graphrag-milvus"]["name"] == "amber2_graphrag-milvus"
    assert resolved["volumes"]["graphrag-etcd"]["name"] == "amber2_graphrag-etcd"
    assert resolved["volumes"]["graphrag-minio-data"]["name"] == "amber2_graphrag-minio-data"


def test_canary_explicitly_propagates_ollama_cloud_api_keys_once_per_service():
    root = Path(__file__).parents[2]
    canary = yaml.safe_load((root / "deploy/docker-compose.canary.yml").read_text())
    expected = "OLLAMA_CLOUD_API_KEYS=${OLLAMA_CLOUD_API_KEYS:-}"

    for service_name in ("api-canary", "worker-canary"):
        environment = canary["services"][service_name]["environment"]
        variable_names = [entry.partition("=")[0] for entry in environment]

        assert variable_names.count("OLLAMA_CLOUD_API_KEYS") == 1
        assert expected in environment


def test_resolved_canary_propagates_ollama_cloud_api_keys():
    root = Path(__file__).parents[2]
    sentinel = "canary-key-sentinel-a,canary-key-sentinel-b"
    environment = os.environ | {
        "H4_ML_RUNTIME_VOLUME": "amber2_h4_candidate",
        "PIP_PACKAGES_ACTIVE_VOLUME": "amber2_h3_active",
        "PIP_PACKAGES_ROLLBACK_VOLUME": "amber2_h3_rollback",
        "OLLAMA_CLOUD_API_KEYS": sentinel,
    }
    try:
        compose_version = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        pytest.skip("Docker CLI is not installed")

    if compose_version.returncode != 0:
        pytest.skip("Docker Compose plugin is not available")

    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "deploy/docker-compose.canary.yml",
            "config",
            "--format",
            "json",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    resolved = json.loads(result.stdout)
    for service_name in ("api-canary", "worker-canary"):
        assert resolved["services"][service_name]["environment"]["OLLAMA_CLOUD_API_KEYS"] == sentinel


def test_canary_mounts_every_shared_production_path_read_only():
    root = Path(__file__).parents[2]
    canary_path = root / "deploy/docker-compose.canary.yml"
    canary = yaml.safe_load(canary_path.read_text())

    shared_read_only_mounts = (
        "graphrag-uploads:/app/uploads:ro",
        "pip-packages:/app/.packages:ro",
        "h4-ml-runtime:/app/.packages-h4:ro",
    )

    for service_name in ("api-canary", "worker-canary"):
        service_mounts = canary["services"][service_name]["volumes"]
        mount_targets = [mount.split(":")[1] for mount in service_mounts]

        for mount in shared_read_only_mounts:
            assert service_mounts.count(mount) == 1
            assert mount_targets.count(mount.split(":")[1]) == 1


def test_canary_uses_the_read_only_h4_artifact_cache_without_a_host_bind():
    root = Path(__file__).parents[2]
    canary = yaml.safe_load((root / "deploy/docker-compose.canary.yml").read_text())

    expected_cache_environment = {
        "HF_HOME=/app/.packages-h4/hf-cache",
        "HUGGINGFACE_HUB_CACHE=/app/.packages-h4/hf-cache/hub",
    }

    for service_name in ("api-canary", "worker-canary"):
        service = canary["services"][service_name]
        environment = service["environment"]
        environment_keys = [entry.split("=", 1)[0] for entry in environment]
        mount_targets = [mount.split(":")[1] for mount in service["volumes"]]

        for entry in expected_cache_environment:
            assert environment.count(entry) == 1
            assert environment_keys.count(entry.split("=", 1)[0]) == 1

        assert "/home/appuser/.cache/huggingface" not in mount_targets


def test_builder_enforces_a_local_docker_socket_before_candidate_access():
    root = Path(__file__).parents[2]
    script = (root / "scripts/h4_ml_runtime_candidate.sh").read_text()

    first_candidate_access = script.index('role="$(docker_local volume inspect --format')
    guard_invocation = script.index("acquire_run_lock\nensure_local_docker")
    assert "ensure_local_docker" in script
    assert guard_invocation < first_candidate_access
    assert '[[ -z "${DOCKER_HOST:-}" ]]' in script
    assert '[[ "${DOCKER_CONTEXT:-default}" == "default" ]]' in script
    assert "[[ -S /var/run/docker.sock ]]" in script
    assert (
        "env -u DOCKER_HOST -u DOCKER_CONTEXT docker --host unix:///var/run/docker.sock" in script
    )


def test_builder_refuses_a_remote_docker_host_without_reaching_a_candidate():
    root = Path(__file__).parents[2]
    script = root / "scripts/h4_ml_runtime_candidate.sh"
    environment = {**os.environ, "DOCKER_HOST": "tcp://192.0.2.1:2375"}

    result = subprocess.run(
        [
            str(script),
            "install",
            "--volume",
            "ambermirror_pip-packages-h4-cpu-nomic-da122dfb-38eb9c2d",
        ],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert result.returncode == 1
    assert "DOCKER_HOST must be unset for the local H4 candidate" in result.stderr


def test_builder_requires_explicit_production_authorization_before_docker_access():
    root = Path(__file__).parents[2]
    script = root / "scripts/h4_ml_runtime_candidate.sh"
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    volume = f"amber2_pip-packages-h4-cpu-nomic-da122dfb-{head[:8]}"
    environment = {**os.environ, "DOCKER_HOST": "tcp://192.0.2.1:2375"}

    result = subprocess.run(
        [str(script), "install", "--volume", volume],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert result.returncode == 1
    assert "production volume requires --authorize-production" in result.stderr


def test_builder_accepts_only_the_current_head_production_name_with_authorization():
    root = Path(__file__).parents[2]
    script = root / "scripts/h4_ml_runtime_candidate.sh"
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    volume = f"amber2_pip-packages-h4-cpu-nomic-da122dfb-{head[:8]}"
    environment = {**os.environ, "DOCKER_HOST": "tcp://192.0.2.1:2375"}

    result = subprocess.run(
        [str(script), "install", "--volume", volume, "--authorize-production"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert result.returncode == 1
    assert "DOCKER_HOST must be unset for the local H4 candidate" in result.stderr


def test_builder_refuses_an_authorized_production_name_not_derived_from_head():
    root = Path(__file__).parents[2]
    script = root / "scripts/h4_ml_runtime_candidate.sh"
    environment = {**os.environ, "DOCKER_HOST": "tcp://192.0.2.1:2375"}

    result = subprocess.run(
        [
            str(script),
            "install",
            "--volume",
            "amber2_pip-packages-h4-cpu-nomic-da122dfb-deadbeef",
            "--authorize-production",
        ],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert result.returncode == 1
    assert "refusing production volume" in result.stderr


def test_builder_serializes_install_and_preload_before_candidate_access():
    root = Path(__file__).parents[2]
    script = (root / "scripts/h4_ml_runtime_candidate.sh").read_text()

    first_candidate_access = script.index('role="$(docker_local volume inspect --format')
    lock_invocation = script.index("acquire_run_lock\nensure_local_docker")
    assert "acquire_run_lock" in script
    assert lock_invocation < first_candidate_access
    assert 'flock -n "$H4_RUN_LOCK_FD"' in script
    assert "another install or preload already holds the H4 candidate lock" in script


def test_preload_uses_one_huggingface_cache_root_and_stages_the_model_manifest():
    root = Path(__file__).parents[2]
    script = (root / "scripts/h4_ml_runtime_candidate.sh").read_text()

    assert 'cache_dir="/artifact/hf-cache/hub"' in script
    assert 'cache_dir=str(packages_root / "hf-cache" / "hub")' in script
    assert "H4_MODELS_STAGED_FILE" in script
    assert ".h4-models-${H4_PRELOAD_ATTEMPT_ID}.pending.json" in script
    assert "publish_staged_model_manifest" in script
    assert "flashrank_cache_sha256" in script
    assert "cache_sha256" in script


def test_failed_preload_publication_can_resume_offline_without_replacing_the_manifest():
    root = Path(__file__).parents[2]
    script = (root / "scripts/h4_ml_runtime_candidate.sh").read_text()

    assert "test ! -f /artifact/.h4-preload-validation.json" in script
    assert "            printf resume\n" in script
    assert 'staged_models=".h4-models.json"' in script
    assert "if staged_models == models_target:" in script
    assert "assert models_target.is_file()" in script


def test_rollout_requires_explicit_preload_authorization_and_offline_proof():
    root = Path(__file__).parents[2]
    rollout = (root / "docs/H4_ML_RUNTIME_ROLLOUT.md").read_text()

    assert "--authorize-preload" in rollout
    assert "direct user approval" in rollout
    assert "--network none" in rollout
    assert ".h4-preload-validation.json" in rollout
    assert "after the storage postflight succeeds" in rollout
    assert "ambermirror_pip-packages-h4-cpu-nomic-da122dfb-38eb9c2d" in rollout
    assert "amber2_pip-packages-h4-cpu-nomic-da122dfb-<current-head-short>" in rollout
    assert "amber.h4.candidate-ref" in rollout
    assert "--authorize-production" in rollout
    assert "`da122dfb`" in rollout


def test_preload_refuses_to_reach_docker_without_the_explicit_guard():
    root = Path(__file__).parents[2]
    script = root / "scripts/h4_ml_runtime_candidate.sh"

    result = subprocess.run(
        [
            str(script),
            "preload",
            "--volume",
            "ambermirror_pip-packages-h4-cpu-nomic-da122dfb-38eb9c2d",
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 1
    assert "preload requires --authorize-preload after direct user approval" in result.stderr


def test_h4_live_worker_overlay_declares_safe_blue_green_replicas():
    root = Path(__file__).parents[2]
    overlay = yaml.safe_load((root / "deploy/docker-compose.worker-h4-live.yml").read_text())
    expected_services = {f"worker-h4-live-{index}" for index in range(1, 4)}

    assert set(overlay["services"]) == expected_services

    live_queues = {"high_priority", "celery", "evaluation", "low_priority"}
    for index in range(1, 4):
        service_name = f"worker-h4-live-{index}"
        service = overlay["services"][service_name]
        command = service["command"].split()
        queue_names = set(command[command.index("-Q") + 1].split(","))

        assert service["extends"] == {
            "file": "docker-compose.yml",
            "service": "worker",
        }
        assert service["container_name"] == f"amber2-worker-h4-live-{index}"
        assert queue_names == live_queues | {f"h4_promotion_{index}"}
        assert f"--hostname=h4-live-{index}@%h" in command
        assert "--concurrency=${CELERY_CONCURRENCY:-2}" in command
        assert service["restart"] == "unless-stopped"
        assert service["stop_grace_period"] == "300s"


def test_resolved_h4_live_workers_inherit_production_canary_safety():
    root = Path(__file__).parents[2]
    sentinel = "h4-live-key-sentinel-a,h4-live-key-sentinel-b"
    environment = os.environ | {
        "H4_ML_RUNTIME_VOLUME": "amber2_h4_candidate",
        "PIP_PACKAGES_ACTIVE_VOLUME": "amber2_h3_active",
        "PIP_PACKAGES_ROLLBACK_VOLUME": "amber2_h3_rollback",
        "APP_DATABASE_URL": "postgresql+asyncpg://app-role-sentinel@postgres/graphrag",
        "OLLAMA_CLOUD_API_KEYS": sentinel,
        "DEFAULT_LLM_PROVIDER": "ollama_cloud",
        "DEFAULT_LLM_MODEL": "gemma4:31b-cloud",
        "SECRET_KEY": "compose-contract-secret",
        "DEV_API_KEY": "compose-contract-api-key",
        "GRAPHRAG_APP_PASSWORD": "compose-contract-password",
        "POSTGRES_PASSWORD": "compose-contract-password",
        "NEO4J_PASSWORD": "compose-contract-password",
        "OBJECT_STORAGE_ACCESS_KEY": "compose-contract-access-key",
        "OBJECT_STORAGE_SECRET_KEY": "compose-contract-secret-key",
    }
    base_command = [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "-f",
        "deploy/docker-compose.canary.yml",
    ]

    try:
        compose_version = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        pytest.skip("Docker CLI is not installed")

    if compose_version.returncode != 0:
        pytest.skip("Docker Compose plugin is not available")

    baseline_result = subprocess.run(
        [*base_command, "config", "--format", "json"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    result = subprocess.run(
        [
            *base_command,
            "-f",
            "deploy/docker-compose.worker-h4-live.yml",
            "config",
            "--format",
            "json",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert baseline_result.returncode == 0, baseline_result.stderr
    assert result.returncode == 0, result.stderr
    baseline = json.loads(baseline_result.stdout)
    resolved = json.loads(result.stdout)
    assert resolved["name"] == "amber2"
    assert resolved["volumes"] == baseline["volumes"]
    live_environment = baseline["services"]["worker"]["environment"]
    intentional_h4_overrides = {"HF_HOME", "PYTHONPATH"}

    expected_targets = {
        "/app/src",
        "/app/config",
        "/app/alembic",
        "/app/uploads",
        "/app/.packages",
        "/app/.packages-h4",
    }
    for index in range(1, 4):
        service = resolved["services"][f"worker-h4-live-{index}"]
        mounts = {mount["target"]: mount for mount in service["volumes"]}

        for name, value in live_environment.items():
            if name not in intentional_h4_overrides:
                assert service["environment"][name] == value
        assert service["environment"]["APP_DATABASE_URL"] == (
            "postgresql+asyncpg://app-role-sentinel@postgres/graphrag"
        )
        assert service["environment"]["OLLAMA_CLOUD_API_KEYS"] == sentinel
        assert service["environment"]["AMBER_CANARY"] == "true"
        assert service["environment"]["DEFAULT_LLM_PROVIDER"] == "ollama_cloud"
        assert service["environment"]["DEFAULT_LLM_MODEL"] == "gemma4:31b-cloud"
        assert expected_targets <= mounts.keys()
        assert all(mounts[target]["read_only"] is True for target in expected_targets)
        assert mounts["/app/.packages"]["source"] == "pip-packages"
        assert mounts["/app/.packages-h4"]["source"] == "h4-ml-runtime"
        assert service["deploy"]["replicas"] == 1
        assert service["deploy"]["resources"]["limits"]["memory"] == "2147483648"


def test_h4_worker_handover_runbook_is_fail_closed_and_non_destructive():
    root = Path(__file__).parents[2]
    runbook = (
        root / "docs/runbooks/h4-worker-blue-green-handover.md"
    ).read_text()

    required_fragments = {
        "docker-compose.yml",
        "deploy/docker-compose.canary.yml",
        "deploy/docker-compose.worker-h4-live.yml",
        "--dry-run",
        "--no-deps",
        "--no-build",
        "--pull never",
        "src.workers.tasks.health_check",
        "h4_promotion_1",
        "cancel_consumer",
        "inspect active",
        "inspect reserved",
        "inspect scheduled",
        "docker stop --time 300",
        "conferma diretta",
        "Rollback",
    }
    forbidden_fragments = {
        "docker rm",
        "compose down",
        "down -v",
        "docker volume rm",
        "docker system prune",
        "docker volume prune",
        "rm -rf",
    }

    missing_required = {
        fragment for fragment in required_fragments if fragment not in runbook
    }
    present_forbidden = {
        fragment for fragment in forbidden_fragments if fragment in runbook
    }

    assert not missing_required
    assert not present_forbidden
