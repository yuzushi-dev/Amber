# H3 Parser Stack: Versioned Optional-Package Volume Rollout

## Purpose and boundary

H3 removes the Marker OCR parser stack from the API and worker images. API,
worker, Celery beat and canary containers also mount `/app/.packages`; a legacy
`amber2_pip-packages` volume would take precedence over the rebuilt image and
could reintroduce old parser packages. Therefore the default active volume is
the fresh external `amber2_pip-packages-h3` (or the explicitly supplied
`PIP_PACKAGES_ACTIVE_VOLUME`).

The legacy `PIP_PACKAGES_ROLLBACK_VOLUME` remains external and inactive. Do not
delete, alter, mount into H3, or copy it into the fresh volume. This runbook
does not change production by itself: production commands require the operator's
direct approval after the read-only steps below.

## 1. Read-only preflight

Set the exact built H3 API image reference. Do not use an image that predates
the H3 parser commit.

```bash
export H3_API_IMAGE=amber2-api:<h3-image-tag-or-digest>
export PIP_PACKAGES_ACTIVE_VOLUME=amber2_pip-packages-h3
export PIP_PACKAGES_ROLLBACK_VOLUME=amber2_pip-packages

# Resolve Compose without starting services or creating volumes.
docker compose -f docker-compose.yml config --no-interpolate

# Inventory the old volume read-only. Record exactly which managed features are true.
bash scripts/prepare_h3_pip_packages_volume.sh --inventory \
  --image "$H3_API_IMAGE" \
  --source-volume "$PIP_PACKAGES_ROLLBACK_VOLUME"
```

The inventory covers the managed non-parser setup features: `local_embeddings`,
`reranking`, `community_detection`, and `ragas`. `local_embeddings` deliberately
contains Torch/Transformers and remains H4-owned; H3 neither removes nor
asserts their global absence. `document_processing` is already supplied by the
H3 image’s `requirements-core.txt`, so it is not copied from the legacy volume.
`requirements-optional.txt` is a reference list; only IDs implemented by
`SetupService` have a managed runtime restoration path.

## 2. Preview and approve the fresh-volume preparation

Choose precisely the feature IDs observed as required in the inventory. This
example preserves local embeddings and reranking; it is only a preview and does
not call Docker:

```bash
bash scripts/prepare_h3_pip_packages_volume.sh \
  --image "$H3_API_IMAGE" \
  --source-volume "$PIP_PACKAGES_ROLLBACK_VOLUME" \
  --target-volume "$PIP_PACKAGES_ACTIVE_VOLUME" \
  --features local_embeddings,reranking
```

After a human has explicitly approved creating the new named volume, run the
same command with `--apply`. The helper refuses to reuse an existing target,
creates only the fresh target volume, reinstalls selected features through
`SetupService`, imports each selected feature, and verifies Marker/Surya modules
are absent. It never copies or modifies the old volume.

```bash
bash scripts/prepare_h3_pip_packages_volume.sh --apply \
  --image "$H3_API_IMAGE" \
  --source-volume "$PIP_PACKAGES_ROLLBACK_VOLUME" \
  --target-volume "$PIP_PACKAGES_ACTIVE_VOLUME" \
  --features local_embeddings,reranking
```

Before changing traffic, repeat validation without mutation:

```bash
bash scripts/prepare_h3_pip_packages_volume.sh --verify \
  --image "$H3_API_IMAGE" \
  --target-volume "$PIP_PACKAGES_ACTIVE_VOLUME" \
  --features local_embeddings,reranking
docker compose -f docker-compose.yml config
```

Compose declares the active volume as `external: true`, so an unprepared target
causes a pre-start failure instead of silently starting with an empty volume and
losing optional features.

## 3. Activation and normal rollback

Only after the prepare/verify steps and normal deployment approval, deploy using
the H3 image with `PIP_PACKAGES_ACTIVE_VOLUME` set to the fresh target. Validate
the required feature(s) with real application health/query checks before traffic
cutover. The API, worker, beat and canary all select the same active volume.

The package volume is not a normal rollback lever. For a normal H3 rollback,
keep the clean prepared `PIP_PACKAGES_ACTIVE_VOLUME` in place and roll back only
the application/traffic change to the previous known-good H3 image or release.
If the fresh volume itself must be replaced, prepare a new clean versioned target
(for example `amber2_pip-packages-h3-r2`) with the same inventory/apply/verify
procedure; do not use the legacy volume.

```bash
# Normal rollback retains the clean H3 volume.
export PIP_PACKAGES_ACTIVE_VOLUME=amber2_pip-packages-h3
docker compose -f docker-compose.yml config
```

Perform any subsequent service restart or traffic action only with direct human
approval. Do not delete either volume during the rollback window.

## 4. Legacy-volume emergency exception

Mounting `PIP_PACKAGES_ROLLBACK_VOLUME` with an H3 image is a documented
**security regression**: it may restore Marker or a vulnerable Pillow/pi-heif
decoder ahead of the secure image packages. It is never a normal rollback.

Use the legacy mount only during a declared incident and only after **direct user approval**.
The exception must be **time-bounded**, recorded with an owner and
end time, and have **compensating monitoring**: capture the effective
`PIL.__version__`, `pi_heif.__version__`, and absence/presence of Marker/Surya
before traffic is restored; alert on parser/import errors for the whole window.
The incident plan must include a **return to the fresh volume** using the
inventory/apply/verify procedure above.

```bash
# Emergency exception only: this intentionally reintroduces legacy package risk.
export PIP_PACKAGES_ACTIVE_VOLUME="$PIP_PACKAGES_ROLLBACK_VOLUME"
docker compose -f docker-compose.yml config
```

Do not delete either volume during the incident window. Revert the environment
selection to a verified clean H3 volume as soon as the emergency condition ends.
