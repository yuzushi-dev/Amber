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

root_dir="$(cd "$(dirname "$BASH_SOURCE")/.." && pwd)"
requirements_input="$root_dir/requirements-ml-h4-cpu.in"
requirements_lock="$root_dir/requirements-ml-h4-cpu.lock"

die() {
    printf 'H4 Nomic candidate error: %s\n' "$*" >&2
    exit 1
}

usage() {
    printf 'Usage: h4_ml_runtime_candidate.sh <install|preload> --volume %s\n' "$CANDIDATE_VOLUME" >&2
    exit 2
}

free_bytes() {
    df -B1 --output=avail /var/lib/docker | tail -n 1 | tr -d '[:space:]'
}

check_preflight_space() {
    local phase="$1"
    local mountpoint="$2"
    local available
    available="$(free_bytes "$mountpoint")"
    printf 'storage_preflight phase=%s free_bytes=%s required_bytes=%s\n' \
        "$phase" "$available" "$REQUIRED_PREFLIGHT_FREE_BYTES"
    [[ "$available" -ge "$REQUIRED_PREFLIGHT_FREE_BYTES" ]] || die "storage gate failed before $phase"
}

check_postflight_space() {
    local phase="$1"
    local mountpoint="$2"
    local baseline="$3"
    local available
    local growth
    available="$(free_bytes "$mountpoint")"
    growth=$((baseline - available))
    printf 'storage_postflight phase=%s free_bytes=%s growth_bytes=%s budget_bytes=%s\n' \
        "$phase" "$available" "$growth" "$PEAK_BUDGET_BYTES"
    [[ "$available" -ge "$MIN_FREE_BYTES" ]] || die "minimum 20 GiB free-space floor failed after $phase"
    [[ "$growth" -le "$PEAK_BUDGET_BYTES" ]] || die "4 GiB storage budget exceeded after $phase"
}

[[ $# -eq 3 && ( "$1" == "install" || "$1" == "preload" ) && "$2" == "--volume" ]] || usage
phase="$1"
volume="$3"
[[ "$volume" == "$CANDIDATE_VOLUME" ]] || die "refusing volume $volume"

role="$(docker volume inspect --format '{{ index .Labels "amber.h4.role" }}' "$volume")"
profile="$(docker volume inspect --format '{{ index .Labels "amber.h4.profile" }}' "$volume")"
strategy="$(docker volume inspect --format '{{ index .Labels "amber.h4.strategy" }}' "$volume")"
source="$(docker volume inspect --format '{{ index .Labels "amber.h4.source" }}' "$volume")"
mountpoint="$(docker volume inspect --format '{{.Mountpoint}}' "$volume")"
[[ "$role" == "$CANDIDATE_ROLE" ]] || die "candidate role label is not $CANDIDATE_ROLE"
[[ "$profile" == "$CANDIDATE_PROFILE" ]] || die "candidate profile label is not $CANDIDATE_PROFILE"
[[ "$strategy" == "$CANDIDATE_STRATEGY" ]] || die "candidate strategy label is not $CANDIDATE_STRATEGY"
[[ "$source" == "$CANDIDATE_SOURCE" ]] || die "candidate source label is not $CANDIDATE_SOURCE"
check_preflight_space "$phase" "$mountpoint"

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
    docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=1g \
        --mount "type=volume,src=$volume,dst=/artifact" \
        "$PYTHON_IMAGE" \
        sh -ec '
            test ! -e /artifact/.h4-artifact.json
            test ! -e /artifact/.h4-models.json
            for package_dir in torch transformers onnx flashrank sentence_transformers; do
                test ! -e "/artifact/$package_dir"
            done
        ' || die "candidate already contains an installed artifact"

    baseline_free="$(free_bytes "$mountpoint")"
    printf '%s\n' "$baseline_free" > "$mountpoint/.h4-storage-baseline"
    lock_sha256="$(sha256sum "$requirements_lock" | awk '{print $1}')"
    docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=1g \
        --mount "type=volume,src=$volume,dst=/artifact" \
        --mount "type=bind,src=$root_dir,dst=/workspace,readonly" \
        -e HOME=/tmp \
        -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
        -e PIP_NO_CACHE_DIR=1 \
        "$PYTHON_IMAGE" \
        sh -ec '
            install -d /artifact/.h4-wheelhouse
            python -m pip download --isolated --only-binary=:all: --require-hashes \
                --dest /artifact/.h4-wheelhouse \
                --index-url https://pypi.org/simple \
                --find-links "'"$TORCH_CPU_FIND_LINK"'" \
                -r /workspace/requirements-ml-h4-cpu.lock
            python -m pip install --isolated --no-index --find-links /artifact/.h4-wheelhouse \
                --require-hashes --target /artifact \
                -r /workspace/requirements-ml-h4-cpu.lock
            cp /workspace/requirements-ml-h4-cpu.lock /artifact/.h4-requirements.lock
        '

    docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=1g \
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
    check_postflight_space "install" "$mountpoint" "$baseline_free"
    printf 'Installed H4 Nomic CPU artifact into %s (lock sha256 %s).\n' "$volume" "$lock_sha256"
    exit 0
fi

test -f "$mountpoint/.h4-artifact.json" || die "package artifact is missing"
test ! -f "$mountpoint/.h4-models.json" || die "candidate already contains model caches"
baseline_free="$(cat "$mountpoint/.h4-storage-baseline")"
docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=1g \
    --mount "type=volume,src=$volume,dst=/artifact" \
    -e PYTHONPATH=/artifact \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -e PIP_NO_INDEX=1 \
    -e HOME=/artifact/.home \
    -e XDG_CACHE_HOME=/artifact/.cache \
    -e HF_HOME=/artifact/hf-cache \
    -e HUGGINGFACE_HUB_CACHE=/artifact/hf-cache/hub \
    -e HF_HUB_DISABLE_TELEMETRY=1 \
    "$PYTHON_IMAGE" \
    sh -ec '
        PYTHONPATH=/artifact python - <<"PY"
import json
from pathlib import Path

from flashrank import Ranker, RerankRequest
from transformers import AutoModelForMaskedLM, AutoTokenizer

splade_model = "naver/splade-cocondenser-ensembledistil"
splade_revision = "49cf4c7b0db5b870a401ddf5e2669993ef3699c7"
flashrank_model = "ms-marco-MiniLM-L-12-v2"

print("preload=splade", flush=True)
tokenizer = AutoTokenizer.from_pretrained(
    splade_model, revision=splade_revision, trust_remote_code=False
)
model = AutoModelForMaskedLM.from_pretrained(
    splade_model, revision=splade_revision, trust_remote_code=False
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

manifest = {
    "flashrank": {"model": flashrank_model, "results": len(results)},
    "splade": {"model": splade_model, "revision": splade_revision},
}
Path("/artifact/.h4-models.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
print("preload=complete", flush=True)
PY
    '
check_postflight_space "preload" "$mountpoint" "$baseline_free"
printf 'Preloaded SPLADE and FlashRank into %s.\n' "$volume"
