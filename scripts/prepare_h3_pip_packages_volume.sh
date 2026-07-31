#!/usr/bin/env bash
# Prepare the fresh H3 optional-package volume without copying the legacy one.
#
# This helper is intentionally dry-run by default. `--apply` is the only mode
# that creates a volume, and it refuses to reuse an existing target. Use it only
# after the production operator has approved the named target volume.

set -euo pipefail

readonly DEFAULT_SOURCE_VOLUME="amber2_pip-packages"
readonly DEFAULT_TARGET_VOLUME="amber2_pip-packages-h3"
readonly SUPPORTED_FEATURES=(local_embeddings reranking community_detection ragas)

source_volume="$DEFAULT_SOURCE_VOLUME"
target_volume="$DEFAULT_TARGET_VOLUME"
image=""
features_csv=""
mode="dry-run"

usage() {
  cat <<'EOF'
Usage:
  scripts/prepare_h3_pip_packages_volume.sh [options]

Modes (dry-run is the default):
  --inventory             Read-only inventory of managed optional features in the legacy volume.
  --apply                 Create a fresh target volume, reinstall selected non-parser features, and verify it.
  --verify                Read-only validation of an already prepared target volume.
  --dry-run               Print the selected plan; never run Docker (default).

Required for --inventory, --apply and --verify:
  --image IMAGE           H3 API image containing src.api.services.setup_service.

Required for --apply:
  --features IDS          Comma-separated managed non-parser IDs: local_embeddings,
                          reranking, community_detection, ragas.

Options:
  --source-volume NAME    Legacy rollback volume (default: amber2_pip-packages).
  --target-volume NAME    Fresh H3 active volume (default: amber2_pip-packages-h3).
  -h, --help              Show this help.

The helper never copies the legacy volume. `document_processing` is supplied by
the H3 image requirements-core.txt and is intentionally not restored here.
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 2
}

contains_supported_feature() {
  local requested="$1"
  local supported
  for supported in "${SUPPORTED_FEATURES[@]}"; do
    [[ "$requested" == "$supported" ]] && return 0
  done
  return 1
}

parse_features() {
  local raw_feature
  IFS=',' read -r -a selected_features <<<"$features_csv"
  [[ ${#selected_features[@]} -gt 0 && -n "${selected_features[0]}" ]] || \
    die "--features must name at least one managed non-parser feature"

  for raw_feature in "${selected_features[@]}"; do
    contains_supported_feature "$raw_feature" || \
      die "unsupported feature '$raw_feature'; choose: ${SUPPORTED_FEATURES[*]}"
  done
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --inventory)
      mode="inventory"
      ;;
    --apply)
      mode="apply"
      ;;
    --verify)
      mode="verify"
      ;;
    --dry-run)
      mode="dry-run"
      ;;
    --image)
      image="${2:-}"
      shift
      ;;
    --source-volume)
      source_volume="${2:-}"
      shift
      ;;
    --target-volume)
      target_volume="${2:-}"
      shift
      ;;
    --features)
      features_csv="${2:-}"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      die "unknown option '$1'"
      ;;
  esac
  shift
done

[[ -n "$source_volume" && -n "$target_volume" ]] || die "volume names cannot be empty"
[[ "$source_volume" != "$target_volume" ]] || \
  die "target volume must be fresh and must not equal the legacy rollback volume"

if [[ -n "$features_csv" ]]; then
  parse_features
else
  selected_features=()
fi

print_plan() {
  cat <<EOF
H3 parser package-volume plan
  legacy rollback volume: $source_volume (read-only; never copied or changed)
  fresh active volume:    $target_volume
  H3 API image:           ${image:-<required for execution>}
  selected non-parser features: ${features_csv:-<none selected>}
EOF
}

inventory_legacy() {
  docker volume inspect "$source_volume" >/dev/null
  docker run --rm -i --read-only \
    -v "$source_volume:/app/.packages:ro" \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -e PYTHONPATH=/app:/app/.packages \
    --entrypoint python "$image" - <<'PY'
import importlib.util
import json

modules = {
    "local_embeddings": "sentence_transformers",
    "reranking": "flashrank",
    "community_detection": "leidenalg",
    "ragas": "ragas",
}
print(json.dumps({name: importlib.util.find_spec(module) is not None for name, module in modules.items()}))
PY
}

install_features() {
  docker volume inspect "$source_volume" >/dev/null
  if docker volume inspect "$target_volume" >/dev/null 2>&1; then
    die "refusing to reuse existing target '$target_volume'; choose a new versioned volume"
  fi

  docker volume create "$target_volume" >/dev/null
  docker run --rm --user root \
    -v "$target_volume:/app/.packages" \
    --entrypoint sh "$image" \
    -c 'chown -R "$(id -u appuser):$(id -g appuser)" /app/.packages'
  docker run --rm -i \
    -v "$target_volume:/app/.packages" \
    -e PACKAGES_DIR=/app/.packages \
    -e PYTHONPATH=/app:/app/.packages \
    --entrypoint python "$image" - "${selected_features[@]}" <<'PY'
import asyncio
import json
import sys

from src.api.services.setup_service import SetupService


async def main() -> None:
    service = SetupService()
    results = await service.install_features_batch(sys.argv[1:])
    print(json.dumps(results, sort_keys=True))
    if not all(result.get("success") for result in results.values()):
        raise SystemExit("one or more optional feature installs failed")


asyncio.run(main())
PY
}

verify_target() {
  docker volume inspect "$target_volume" >/dev/null
  docker run --rm -i --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    -v "$target_volume:/app/.packages:ro" \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -e PYTHONPATH=/app/.packages:/app \
    --entrypoint python "$image" - "${selected_features[@]}" <<'PY'
import importlib
import importlib.util
import sys

from packaging.version import InvalidVersion, Version
from PIL import __version__ as pillow_version
from pi_heif import __version__ as pi_heif_version

from src.api.services.setup_service import OPTIONAL_FEATURES


def require_effective_floor(distribution: str, version: str, minimum: str) -> None:
    try:
        installed = Version(version)
        required = Version(minimum)
    except InvalidVersion as exc:
        raise SystemExit(f"{distribution} has an invalid effective version {version!r}: {exc}")
    if installed < required:
        raise SystemExit(
            f"{distribution} effective version {installed} is below required floor {required}"
        )
    print(f"verified effective native parser dependency: {distribution} {installed}")


# The target volume is first on PYTHONPATH. These imports therefore fail if a
# stale volume shadows the secure image packages with an old native decoder.
require_effective_floor("Pillow", pillow_version, "12.3.0")
require_effective_floor("pi-heif", pi_heif_version, "1.3.0")

for feature_id in sys.argv[1:]:
    module = OPTIONAL_FEATURES[feature_id].check_import
    importlib.import_module(module)
    print(f"verified optional feature: {feature_id}")

retired_modules = [
    module
    for module in ("marker", "marker_pdf", "surya")
    if importlib.util.find_spec(module) is not None
]
if retired_modules:
    raise SystemExit(f"retired parser modules present: {retired_modules}")
print("verified retired parser modules are absent")
PY
}

case "$mode" in
  dry-run)
    print_plan
    printf 'DRY RUN: No Docker mutation will run. Use --inventory, --apply, or --verify explicitly.\n'
    ;;
  inventory)
    [[ -n "$image" ]] || die "--image is required for --inventory"
    inventory_legacy
    ;;
  apply)
    [[ -n "$image" ]] || die "--image is required for --apply"
    [[ -n "$features_csv" ]] || die "--features is required for --apply"
    print_plan
    install_features
    verify_target
    ;;
  verify)
    [[ -n "$image" ]] || die "--image is required for --verify"
    [[ -n "$features_csv" ]] || die "--features is required for --verify"
    verify_target
    ;;
esac
