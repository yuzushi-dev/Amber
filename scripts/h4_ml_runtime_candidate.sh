#!/usr/bin/env bash
# Build the sole local H4 CPU runtime candidate. This never starts a service.

set -euo pipefail

readonly CANDIDATE_VOLUME="ambermirror_pip-packages-h4-cpu-20260730"
readonly CANDIDATE_ROLE="ml-runtime-candidate"
readonly CANDIDATE_PROFILE="cpu"
readonly PYTHON_IMAGE="python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93"
readonly TORCH_CPU_FIND_LINK="https://download-r2.pytorch.org/whl/cpu/torch/"

root_dir="$(cd "$(dirname "$BASH_SOURCE")/.." && pwd)"
requirements_input="$root_dir/requirements-ml-h4-cpu.in"
requirements_lock="$root_dir/requirements-ml-h4-cpu.lock"

die() {
    printf 'H4 candidate error: %s\n' "$*" >&2
    exit 1
}

usage() {
    printf 'Usage: h4_ml_runtime_candidate.sh install --volume %s\n' "$CANDIDATE_VOLUME" >&2
    exit 2
}

[[ $# -eq 3 && "$1" == "install" && "$2" == "--volume" ]] || usage
volume="$3"
[[ "$volume" == "$CANDIDATE_VOLUME" ]] || die "refusing volume $volume"

role="$(docker volume inspect --format '{{ index .Labels "amber.h4.role" }}' "$volume")"
profile="$(docker volume inspect --format '{{ index .Labels "amber.h4.profile" }}' "$volume")"
[[ "$role" == "$CANDIDATE_ROLE" ]] || die "candidate role label is not $CANDIDATE_ROLE"
[[ "$profile" == "$CANDIDATE_PROFILE" ]] || die "candidate profile label is not $CANDIDATE_PROFILE"

PYTHONPATH="$root_dir" python3 - "$requirements_input" "$requirements_lock" <<'PY'
from pathlib import Path
import sys

from src.shared.ml_runtime_artifact import ArtifactProfile, validate_requirements_lock

lock_text = Path(sys.argv[1]).read_text() + "\n" + Path(sys.argv[2]).read_text()
result = validate_requirements_lock(lock_text, ArtifactProfile("3.11", "Linux", "x86_64"))
if result.errors:
    raise SystemExit("invalid H4 artifact lock: " + "; ".join(result.errors))
PY

docker run --rm \
    --mount "type=volume,src=$volume,dst=/artifact" \
    "$PYTHON_IMAGE" \
    sh -ec '
        test ! -e /artifact/.h4-artifact.json
        for package_dir in torch transformers onnx sentence_transformers flashrank; do
            test ! -e "/artifact/$package_dir"
        done
    ' || die "candidate already contains an installed artifact"

lock_sha256="$(sha256sum "$requirements_lock" | awk '{print $1}')"
docker run --rm \
    --mount "type=volume,src=$volume,dst=/artifact" \
    --mount "type=bind,src=$root_dir,dst=/workspace,readonly" \
    -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
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

docker run --rm \
    --mount "type=volume,src=$volume,dst=/artifact" \
    -e H4_LOCK_SHA256="$lock_sha256" \
    -e H4_PYTHON_IMAGE="$PYTHON_IMAGE" \
    "$PYTHON_IMAGE" \
    sh -ec '
        PYTHONPATH=/artifact python - <<"PY"
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
        "sentence-transformers": version("sentence-transformers"),
        "torch": version("torch"),
        "transformers": version("transformers"),
    },
    "torch_cuda_available": torch.cuda.is_available(),
}
Path("/artifact/.h4-artifact.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
PY
    '

printf 'Installed H4 CPU artifact into %s (lock sha256 %s).\n' "$volume" "$lock_sha256"
