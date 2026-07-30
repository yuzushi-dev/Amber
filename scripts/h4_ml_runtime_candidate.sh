#!/usr/bin/env bash
# Build the sole local H4 Nomic/Ollama CPU runtime candidate. Never starts a service.

set -euo pipefail

readonly CANDIDATE_VOLUME="ambermirror_pip-packages-h4-cpu-nomic-20260730"
readonly CANDIDATE_ROLE="ml-runtime-candidate"
readonly CANDIDATE_PROFILE="cpu"
readonly CANDIDATE_STRATEGY="nomic-ollama-remote"
readonly CANDIDATE_SOURCE="clean"
readonly MIN_FREE_BYTES=21474836480
readonly PEAK_BUDGET_BYTES=4294967296
readonly REQUIRED_PREFLIGHT_FREE_BYTES=25769803776
readonly PYTHON_IMAGE="python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93"
readonly TORCH_CPU_FIND_LINK="https://download-r2.pytorch.org/whl/cpu/torch/"
readonly H4_RUN_LOCK_PATH="/tmp/amber-h4-ml-runtime-candidate.lock"

PRECHECK_FREE_BYTES=""
POSTFLIGHT_FREE_BYTES=""
POSTFLIGHT_GROWTH_BYTES=""
VALIDATION_PROOF=""
H4_RUN_LOCK_FD=""

root_dir="$(cd "$(dirname "$BASH_SOURCE")/.." && pwd)"
requirements_input="$root_dir/requirements-ml-h4-cpu.in"
requirements_lock="$root_dir/requirements-ml-h4-cpu.lock"

die() {
    printf 'H4 Nomic candidate error: %s\n' "$*" >&2
    exit 1
}

usage() {
    printf '%s\n' "Usage: h4_ml_runtime_candidate.sh install --volume $CANDIDATE_VOLUME" >&2
    printf '%s\n' "       h4_ml_runtime_candidate.sh preload --volume $CANDIDATE_VOLUME --authorize-preload" >&2
    exit 2
}

ensure_local_docker() {
    local context_name

    [[ -z "${DOCKER_HOST:-}" ]] || die "DOCKER_HOST must be unset for the local H4 candidate"
    [[ "${DOCKER_CONTEXT:-default}" == "default" ]] \
        || die "DOCKER_CONTEXT must be default for the local H4 candidate"
    [[ -S /var/run/docker.sock ]] || die "local Docker socket is unavailable"
    context_name="$(env -u DOCKER_HOST -u DOCKER_CONTEXT docker context show)"
    [[ "$context_name" == "default" ]] || die "active Docker context must be default"
}

docker_local() {
    ensure_local_docker
    env -u DOCKER_HOST -u DOCKER_CONTEXT docker --host unix:///var/run/docker.sock "$@"
}

acquire_run_lock() {
    command -v flock >/dev/null 2>&1 || die "flock is required for the H4 candidate lock"
    umask 077
    exec {H4_RUN_LOCK_FD}>"$H4_RUN_LOCK_PATH"
    flock -n "$H4_RUN_LOCK_FD" \
        || die "another install or preload already holds the H4 candidate lock"
}

free_bytes() {
    df -B1 --output=avail /var/lib/docker | tail -n 1 | tr -d '[:space:]'
}

check_preflight_space() {
    local phase="$1"
    local available
    available="$(free_bytes)"
    PRECHECK_FREE_BYTES="$available"
    printf 'storage_preflight phase=%s free_bytes=%s required_bytes=%s\n' \
        "$phase" "$available" "$REQUIRED_PREFLIGHT_FREE_BYTES"
    [[ "$available" -ge "$REQUIRED_PREFLIGHT_FREE_BYTES" ]] || die "storage gate failed before $phase"
}

check_postflight_space() {
    local phase="$1"
    local baseline="$2"
    local available
    local growth
    available="$(free_bytes)"
    growth=$((baseline - available))
    POSTFLIGHT_FREE_BYTES="$available"
    POSTFLIGHT_GROWTH_BYTES="$growth"
    printf 'storage_postflight phase=%s free_bytes=%s growth_bytes=%s budget_bytes=%s\n' \
        "$phase" "$available" "$growth" "$PEAK_BUDGET_BYTES"
    [[ "$available" -ge "$MIN_FREE_BYTES" ]] || die "minimum 20 GiB free-space floor failed after $phase"
    [[ "$growth" -le "$PEAK_BUDGET_BYTES" ]] || die "4 GiB storage budget exceeded after $phase"
}

run_post_preload_validation() {
    local lock_sha256
    local staged_models="$1"

    lock_sha256="$(sha256sum "$requirements_lock" | awk '{print $1}')"
    VALIDATION_PROOF="$(docker_local run --rm --read-only --network none --tmpfs /tmp:rw,noexec,nosuid,size=1g \
        --mount "type=volume,src=$volume,dst=/app/.packages,readonly" \
        --mount "type=bind,src=$root_dir,dst=/workspace,readonly" \
        -e H4_LOCK_SHA256="$lock_sha256" \
        -e H4_MODELS_STAGED_FILE="$staged_models" \
        -e PYTHONPATH=/app/.packages:/workspace \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -e PIP_NO_INDEX=1 \
        -e HOME=/tmp \
        -e XDG_CACHE_HOME=/tmp \
        -e HF_HOME=/app/.packages/hf-cache \
        -e HUGGINGFACE_HUB_CACHE=/app/.packages/hf-cache/hub \
        -e HF_HUB_OFFLINE=1 \
        -e TRANSFORMERS_OFFLINE=1 \
        -e HF_DATASETS_OFFLINE=1 \
        -e HF_HUB_DISABLE_TELEMETRY=1 \
        "$PYTHON_IMAGE" \
        sh -ec '
            test -f /app/.packages/.h4-artifact.json
            test -f "/app/.packages/$H4_MODELS_STAGED_FILE"
            test ! -e /app/.packages/.h4-preload-validation.json
            python - <<"PY"
import hashlib
import json
import os
import re
from importlib.metadata import distributions, version
from pathlib import Path

import torch
from flashrank import Ranker, RerankRequest
from transformers import AutoModelForMaskedLM, AutoTokenizer
from transformers.utils import logging as transformers_logging

from src.shared.ml_runtime_artifact import (
    validate_nomic_policy,
    validate_preload_validation_proof,
)

transformers_logging.set_verbosity_error()
packages_root = Path("/app/.packages")
lock_path = packages_root / ".h4-requirements.lock"
lock_text = lock_path.read_text()
lock_sha256 = hashlib.sha256(lock_path.read_bytes()).hexdigest()
assert lock_sha256 == os.environ["H4_LOCK_SHA256"]

expected_packages = {}
for raw_line in lock_text.splitlines():
    match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", raw_line.strip())
    if match:
        expected_packages[match.group(1).lower()] = match.group(2)
installed_packages = {
    name: version(name)
    for name in expected_packages
}

artifact = json.loads((packages_root / ".h4-artifact.json").read_text())
assert artifact["lock_sha256"] == lock_sha256
assert artifact["torch_cuda_available"] is False
assert torch.cuda.is_available() is False
assert torch.version.cuda is None

installed_distribution_names = sorted(
    {
        distribution.metadata["Name"].lower()
        for distribution in distributions()
        if distribution.metadata.get("Name")
    }
)
nvidia_distributions = [
    name
    for name in installed_distribution_names
    if name.startswith("nvidia-") or "cuda" in name
]
dense_local_distributions = [
    name
    for name in installed_distribution_names
    if name == "sentence-transformers"
]

candidate_paths = [str(path.relative_to(packages_root)) for path in packages_root.rglob("*")]
nomic_policy_errors = validate_nomic_policy(lock_text, tuple(candidate_paths))
dense_local_cache_paths = [
    path
    for path in candidate_paths
    if "baai" in path.lower()
    or "bge-m3" in path.lower()
    or "sentence-transformers" in path.lower()
    or "sentence_transformers" in path.lower()
]

splade_model = "naver/splade-cocondenser-ensembledistil"
splade_revision = "49cf4c7b0db5b870a401ddf5e2669993ef3699c7"
flashrank_model = "ms-marco-MiniLM-L-12-v2"
models_manifest = json.loads(
    (packages_root / os.environ["H4_MODELS_STAGED_FILE"]).read_text()
)
flashrank_manifest = models_manifest["flashrank"]
assert flashrank_manifest["model"] == flashrank_model
expected_flashrank_cache_sha256 = flashrank_manifest["cache_sha256"]
assert re.fullmatch(r"[0-9a-f]{64}", expected_flashrank_cache_sha256, re.IGNORECASE)


def cache_tree_sha256(cache_root: Path) -> str:
    assert cache_root.is_dir()
    digest = hashlib.sha256()
    for path in sorted(cache_root.rglob("*"), key=lambda item: item.relative_to(cache_root).as_posix()):
        assert not path.is_symlink()
        if path.is_dir():
            continue
        assert path.is_file()
        digest.update(path.relative_to(cache_root).as_posix().encode() + b"\0")
        with path.open("rb") as cache_file:
            for chunk in iter(lambda: cache_file.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


tokenizer = AutoTokenizer.from_pretrained(
    splade_model,
    revision=splade_revision,
    trust_remote_code=False,
    local_files_only=True,
    cache_dir=str(packages_root / "hf-cache" / "hub"),
)
model = AutoModelForMaskedLM.from_pretrained(
    splade_model,
    revision=splade_revision,
    trust_remote_code=False,
    local_files_only=True,
    cache_dir=str(packages_root / "hf-cache" / "hub"),
)
with torch.inference_mode():
    inputs = tokenizer("offline sparse validation", return_tensors="pt")
    activations = torch.log1p(torch.relu(model(**inputs).logits)).amax(dim=1).squeeze(0)
splade_sparse_terms = int(torch.count_nonzero(activations).item())

flashrank_cache_sha256 = cache_tree_sha256(packages_root / "flashrank-cache")
assert flashrank_cache_sha256 == expected_flashrank_cache_sha256
ranker = Ranker(model_name=flashrank_model, cache_dir=str(packages_root / "flashrank-cache"))
results = ranker.rerank(
    RerankRequest(
        query="offline H4 validation",
        passages=[
            {"id": "a", "text": "immutable CPU candidate"},
            {"id": "b", "text": "unrelated document"},
        ],
    )
)

proof = {
    "schema": "h4-preload-validation/v1",
    "network_mode": "none",
    "offline": {
        "HF_HUB_OFFLINE": os.environ["HF_HUB_OFFLINE"],
        "TRANSFORMERS_OFFLINE": os.environ["TRANSFORMERS_OFFLINE"],
    },
    "lock_sha256": lock_sha256,
    "packages": installed_packages,
    "torch": {
        "cuda_available": torch.cuda.is_available(),
        "version_cuda": torch.version.cuda,
    },
    "nvidia_distributions": nvidia_distributions,
    "nomic_policy_errors": nomic_policy_errors,
    "dense_local_distributions": dense_local_distributions,
    "dense_local_cache_paths": dense_local_cache_paths,
    "candidate_scan": {
        "root": "/app/.packages",
        "path_count": len(candidate_paths),
    },
    "flashrank": {
        "model": flashrank_model,
        "cache_sha256": flashrank_cache_sha256,
    },
    "first_use": {
        "splade_sparse_terms": splade_sparse_terms,
        "flashrank_results": len(results),
    },
}
errors = validate_preload_validation_proof(
    proof,
    expected_lock_sha256=lock_sha256,
    expected_packages=expected_packages,
    require_storage=False,
)
assert not errors, "; ".join(errors)
print(json.dumps(proof, indent=2, sort_keys=True))
PY
        ')"
}

write_post_preload_proof() {
    local validation_proof="$1"
    local baseline_free="$2"
    local staged_models="$3"

    printf '%s\n' "$validation_proof" | docker_local run --rm -i --read-only --network none --tmpfs /tmp:rw,noexec,nosuid,size=1g \
        --mount "type=volume,src=$volume,dst=/artifact" \
        --mount "type=bind,src=$root_dir,dst=/workspace,readonly" \
        -e PYTHONPATH=/workspace \
        -e H4_PREFLIGHT_FREE_BYTES="$PRECHECK_FREE_BYTES" \
        -e H4_BASELINE_FREE_BYTES="$baseline_free" \
        -e H4_POSTFLIGHT_FREE_BYTES="$POSTFLIGHT_FREE_BYTES" \
        -e H4_POSTFLIGHT_GROWTH_BYTES="$POSTFLIGHT_GROWTH_BYTES" \
        -e H4_MODELS_STAGED_FILE="$staged_models" \
        "$PYTHON_IMAGE" \
        python -c '
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from src.shared.ml_runtime_artifact import (
    publish_preload_validation_proof,
    publish_staged_model_manifest,
    validate_preload_validation_proof,
)

proof = json.load(sys.stdin)
lock_path = Path("/artifact/.h4-requirements.lock")
lock_text = lock_path.read_text()
expected_packages = {}
for raw_line in lock_text.splitlines():
    match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", raw_line.strip())
    if match:
        expected_packages[match.group(1).lower()] = match.group(2)
proof["storage"] = {
    "preflight_free_bytes": int(os.environ["H4_PREFLIGHT_FREE_BYTES"]),
    "baseline_free_bytes": int(os.environ["H4_BASELINE_FREE_BYTES"]),
    "postflight_free_bytes": int(os.environ["H4_POSTFLIGHT_FREE_BYTES"]),
    "postflight_growth_bytes": int(os.environ["H4_POSTFLIGHT_GROWTH_BYTES"]),
}
errors = validate_preload_validation_proof(
    proof,
    expected_lock_sha256=hashlib.sha256(lock_path.read_bytes()).hexdigest(),
    expected_packages=expected_packages,
)
assert not errors, "; ".join(errors)
staged_models = Path("/artifact") / os.environ["H4_MODELS_STAGED_FILE"]
models_target = Path("/artifact/.h4-models.json")
if staged_models == models_target:
    assert models_target.is_file()
else:
    assert staged_models.is_file()
    assert not models_target.exists()
    publish_staged_model_manifest(staged_models, models_target)
target = Path("/artifact/.h4-preload-validation.json")
publish_preload_validation_proof(target, proof)
'
}

[[ $# -ge 1 ]] || usage
phase="$1"
case "$phase" in
    install)
        [[ $# -eq 3 && "$2" == "--volume" ]] || usage
        volume="$3"
        ;;
    preload)
        [[ $# -eq 4 && "$2" == "--volume" && "$4" == "--authorize-preload" ]] \
            || die "preload requires --authorize-preload after direct user approval"
        volume="$3"
        ;;
    *)
        usage
        ;;
esac
[[ "$volume" == "$CANDIDATE_VOLUME" ]] || die "refusing volume $volume"
acquire_run_lock
ensure_local_docker

role="$(docker_local volume inspect --format '{{ index .Labels "amber.h4.role" }}' "$volume")"
profile="$(docker_local volume inspect --format '{{ index .Labels "amber.h4.profile" }}' "$volume")"
strategy="$(docker_local volume inspect --format '{{ index .Labels "amber.h4.strategy" }}' "$volume")"
source="$(docker_local volume inspect --format '{{ index .Labels "amber.h4.source" }}' "$volume")"
[[ "$role" == "$CANDIDATE_ROLE" ]] || die "candidate role label is not $CANDIDATE_ROLE"
[[ "$profile" == "$CANDIDATE_PROFILE" ]] || die "candidate profile label is not $CANDIDATE_PROFILE"
[[ "$strategy" == "$CANDIDATE_STRATEGY" ]] || die "candidate strategy label is not $CANDIDATE_STRATEGY"
[[ "$source" == "$CANDIDATE_SOURCE" ]] || die "candidate source label is not $CANDIDATE_SOURCE"
check_preflight_space "$phase"

PYTHONPATH="$root_dir" python3 - "$requirements_input" "$requirements_lock" <<'PY'
from pathlib import Path
import sys

from src.shared.ml_runtime_artifact import ArtifactProfile, validate_requirements_lock

lock_text = Path(sys.argv[1]).read_text() + "\n" + Path(sys.argv[2]).read_text()
result = validate_requirements_lock(lock_text, ArtifactProfile("3.11", "Linux", "x86_64"))
if result.errors:
    raise SystemExit("invalid H4 Nomic artifact lock: " + "; ".join(result.errors))
PY

if [[ "$phase" == "install" ]]; then
    docker_local run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=1g \
        --mount "type=volume,src=$volume,dst=/artifact" \
        "$PYTHON_IMAGE" \
        sh -ec '
            test ! -e /artifact/.h4-artifact.json
            test ! -e /artifact/.h4-models.json
            for package_dir in torch transformers onnx flashrank sentence_transformers; do
                test ! -e "/artifact/$package_dir"
            done
        ' || die "candidate already contains an installed artifact"

    observed_free="$(free_bytes)"
    baseline_free="$(docker_local run --rm --read-only \
        --mount "type=volume,src=$volume,dst=/artifact,readonly" \
        alpine:3.21 \
        sh -ec 'if test -f /artifact/.h4-storage-baseline; then cat /artifact/.h4-storage-baseline; fi')"
    if [[ -z "$baseline_free" ]]; then
        baseline_free="$observed_free"
        docker_local run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=1g \
            --mount "type=volume,src=$volume,dst=/artifact" \
            -e H4_STORAGE_BASELINE="$baseline_free" \
            alpine:3.21 \
            sh -ec 'test ! -e /artifact/.h4-storage-baseline; printf "%s\n" "$H4_STORAGE_BASELINE" > /artifact/.h4-storage-baseline'
    fi
    [[ "$baseline_free" =~ ^[0-9]+$ ]] || die "candidate storage baseline is invalid"
    wheelhouse_mode="$(docker_local run --rm --read-only \
        --mount "type=volume,src=$volume,dst=/artifact,readonly" \
        alpine:3.21 \
        sh -ec 'if test -d /artifact/.h4-wheelhouse && find /artifact/.h4-wheelhouse -type f -name "*.whl" -print -quit | grep -q .; then printf reuse; else printf fresh; fi')"
    [[ "$wheelhouse_mode" == "fresh" || "$wheelhouse_mode" == "reuse" ]] || die "candidate wheelhouse state is invalid"
    attempt_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
    lock_sha256="$(sha256sum "$requirements_lock" | awk '{print $1}')"
    docker_local run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=1g \
        --mount "type=volume,src=$volume,dst=/artifact" \
        --mount "type=bind,src=$root_dir,dst=/workspace,readonly" \
        -e HOME=/tmp \
        -e H4_ATTEMPT_ID="$attempt_id" \
        -e H4_WHEELHOUSE_MODE="$wheelhouse_mode" \
        -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
        -e PIP_NO_CACHE_DIR=1 \
        "$PYTHON_IMAGE" \
        sh -ec '
            install -d /artifact/.h4-wheelhouse /artifact/.h4-pip-tmp
            download_log="/artifact/h4-install-${H4_ATTEMPT_ID}-download.log"
            install_log="/artifact/h4-install-${H4_ATTEMPT_ID}-install.log"
            test ! -e "$download_log"
            test ! -e "$install_log"
            if [ "$H4_WHEELHOUSE_MODE" = fresh ]; then
                python -m pip download --isolated --only-binary=:all: --require-hashes \
                    --dest /artifact/.h4-wheelhouse \
                    --index-url https://pypi.org/simple \
                    --find-links "'"$TORCH_CPU_FIND_LINK"'" \
                    -r /workspace/requirements-ml-h4-cpu.lock \
                    > "$download_log" 2>&1 || {
                        tail -n 80 "$download_log" >&2
                        exit 1
                    }
            else
                printf "download_skipped=immutable-wheelhouse-reuse\\n" > "$download_log"
            fi
            TMPDIR=/artifact/.h4-pip-tmp python -m pip install \
                --isolated --no-index --find-links /artifact/.h4-wheelhouse \
                --require-hashes --no-compile --target /artifact \
                -r /workspace/requirements-ml-h4-cpu.lock \
                > "$install_log" 2>&1 || {
                    tail -n 80 "$install_log" >&2
                    exit 1
                }
            cp /workspace/requirements-ml-h4-cpu.lock /artifact/.h4-requirements.lock
        '

    docker_local run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=1g \
        --mount "type=volume,src=$volume,dst=/artifact" \
        -e H4_LOCK_SHA256="$lock_sha256" \
        -e H4_PYTHON_IMAGE="$PYTHON_IMAGE" \
        "$PYTHON_IMAGE" \
        sh -ec '
            PYTHONPATH=/artifact PYTHONDONTWRITEBYTECODE=1 python - <<"PY"
import json
import os
from importlib.metadata import version
from pathlib import Path

import torch

metadata = {
    "abi": "CPython 3.11 Linux x86_64",
    "lock_sha256": os.environ["H4_LOCK_SHA256"],
    "python_image": os.environ["H4_PYTHON_IMAGE"],
    "packages": {
        "flashrank": version("FlashRank"),
        "onnx": version("onnx"),
        "torch": version("torch"),
        "transformers": version("transformers"),
    },
    "strategy": "nomic-ollama-remote",
    "torch_cuda_available": torch.cuda.is_available(),
}
Path("/artifact/.h4-artifact.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
PY
        '
    check_postflight_space "install" "$baseline_free"
    printf 'Installed H4 Nomic CPU artifact into %s (lock sha256 %s).\n' "$volume" "$lock_sha256"
    exit 0
fi

preload_state="$(docker_local run --rm --read-only \
    --mount "type=volume,src=$volume,dst=/artifact,readonly" \
    alpine:3.21 \
    sh -ec '
        test -f /artifact/.h4-artifact.json
        test ! -f /artifact/.h4-preload-validation.json
        if test -f /artifact/.h4-models.json; then
            printf resume
        else
            printf fresh
        fi
        printf " "
        cat /artifact/.h4-storage-baseline
    ')"
read -r preload_mode baseline_free <<< "$preload_state"
[[ "$preload_mode" == "fresh" || "$preload_mode" == "resume" ]] || die "candidate preload state is invalid"
[[ "$baseline_free" =~ ^[0-9]+$ ]] || die "candidate storage baseline is invalid"
if [[ "$preload_mode" == "fresh" ]]; then
    H4_PRELOAD_ATTEMPT_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
    staged_models=".h4-models-${H4_PRELOAD_ATTEMPT_ID}.pending.json"
    docker_local run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=1g \
    --mount "type=volume,src=$volume,dst=/artifact" \
    -e PYTHONPATH=/artifact \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -e PIP_NO_INDEX=1 \
    -e HOME=/artifact/.home \
    -e XDG_CACHE_HOME=/artifact/.cache \
    -e HF_HOME=/artifact/hf-cache \
    -e HUGGINGFACE_HUB_CACHE=/artifact/hf-cache/hub \
    -e H4_MODELS_STAGED_FILE="$staged_models" \
    -e HF_HUB_DISABLE_TELEMETRY=1 \
    "$PYTHON_IMAGE" \
    sh -ec '
        PYTHONPATH=/artifact python - <<"PY"
import hashlib
import json
import os
from pathlib import Path

from flashrank import Ranker, RerankRequest
from transformers import AutoModelForMaskedLM, AutoTokenizer

splade_model = "naver/splade-cocondenser-ensembledistil"
splade_revision = "49cf4c7b0db5b870a401ddf5e2669993ef3699c7"
flashrank_model = "ms-marco-MiniLM-L-12-v2"

print("preload=splade", flush=True)
tokenizer = AutoTokenizer.from_pretrained(
    splade_model,
    revision=splade_revision,
    trust_remote_code=False,
    cache_dir="/artifact/hf-cache/hub",
)
model = AutoModelForMaskedLM.from_pretrained(
    splade_model,
    revision=splade_revision,
    trust_remote_code=False,
    cache_dir="/artifact/hf-cache/hub",
)
assert tokenizer is not None
assert model.config.model_type

print("preload=flashrank", flush=True)
ranker = Ranker(model_name=flashrank_model, cache_dir="/artifact/flashrank-cache")
results = ranker.rerank(
    RerankRequest(
        query="H4 CPU artifact",
        passages=[
            {"id": "a", "text": "immutable CPU candidate"},
            {"id": "b", "text": "unrelated document"},
        ],
    )
)
assert len(results) == 2, results


def cache_tree_sha256(cache_root: Path) -> str:
    assert cache_root.is_dir()
    digest = hashlib.sha256()
    for path in sorted(cache_root.rglob("*"), key=lambda item: item.relative_to(cache_root).as_posix()):
        assert not path.is_symlink()
        if path.is_dir():
            continue
        assert path.is_file()
        digest.update(path.relative_to(cache_root).as_posix().encode() + b"\0")
        with path.open("rb") as cache_file:
            for chunk in iter(lambda: cache_file.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


staged_models_name = os.environ["H4_MODELS_STAGED_FILE"]
assert staged_models_name.startswith(".h4-models-")
assert staged_models_name.endswith(".pending.json")
assert "/" not in staged_models_name
staged_models_path = Path("/artifact") / staged_models_name
assert not staged_models_path.exists()
manifest = {
    "flashrank": {
        "cache_sha256": cache_tree_sha256(Path("/artifact/flashrank-cache")),
        "model": flashrank_model,
        "results": len(results),
    },
    "splade": {"model": splade_model, "revision": splade_revision},
}
staged_models_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
print("preload=complete", flush=True)
PY
    '
else
    staged_models=".h4-models.json"
fi
run_post_preload_validation "$staged_models"
check_postflight_space "preload" "$baseline_free"
write_post_preload_proof "$VALIDATION_PROOF" "$baseline_free" "$staged_models"
printf 'Preloaded and offline-validated SPLADE and FlashRank into %s.\n' "$volume"
