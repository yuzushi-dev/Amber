# H4 Nomic/Ollama immutable CPU runtime

## Scope and authority

Amber's only supported dense-embedding path is Nomic through a remote Ollama
configuration. This H4 package artifact does not install, download, cache, or
call a dense-embedding model. It does not start an Ollama service or change an
Ollama model/cache.

The current local candidate is strictly for CPU sparse retrieval and reranking:

- SPLADE sparse retrieval: `naver/splade-cocondenser-ensembledistil`;
- FlashRank reranking: `ms-marco-MiniLM-L-12-v2`;
- Nomic: remote Ollama configuration contract only.

It does not start a service, alter or copy an H3/legacy package volume, access
a datastore, create or migrate a collection, ingest content, reindex data,
route traffic, or use a GPU. The previous H4 candidate remains audit-only and
is not mounted, cleared, relabeled, or deleted by this procedure.

## Candidate and storage guard

The single active candidate is
`ambermirror_pip-packages-h4-cpu-nomic-da122dfb-38eb9c2d`.

| Label | Value |
| --- | --- |
| `amber.h4.role` | `ml-runtime-candidate` |
| `amber.h4.profile` | `cpu` |
| `amber.h4.strategy` | `nomic-ollama-remote` |
| `amber.h4.source` | `clean` |
| `amber.h4.created` | `2026-07-31` |
| `amber.h4.source-ref` | `da122dfb` |
| `amber.h4.disposal` | `direct-user-approval-required` |

The candidate name was proven absent before creation. It is never to be
removed, cleared, or reused without direct user approval.

### Production exact-SHA candidate

The mirror name above remains the only accepted default. On production, the
builder accepts exactly one separately authorized name derived from the Git
HEAD that contains the builder itself:

`amber2_pip-packages-h4-cpu-nomic-da122dfb-<current-head-short>`

The target must be absent before a separately approved `docker volume create`.
The production volume uses the same labels as the mirror candidate and adds
`amber.h4.candidate-ref=<current-full-head>`. Resolve and show `candidate_ref`,
`production_volume`, the complete create command, and free space to the user
before requesting direct approval. The approved form is:

```bash
candidate_ref="$(git rev-parse --verify 'HEAD^{commit}')"
production_volume="amber2_pip-packages-h4-cpu-nomic-da122dfb-${candidate_ref:0:8}"

docker volume create \
  --label amber.h4.role=ml-runtime-candidate \
  --label amber.h4.profile=cpu \
  --label amber.h4.strategy=nomic-ollama-remote \
  --label amber.h4.source=clean \
  --label amber.h4.source-ref=da122dfb \
  --label "amber.h4.candidate-ref=$candidate_ref" \
  --label amber.h4.disposal=direct-user-approval-required \
  "$production_volume"
```

The builder never creates, deletes, clears, copies, or relabels a volume. It
requires `--authorize-production`, recomputes the current full HEAD, derives
the only accepted production name, and verifies the candidate-ref label before
install or preload. The flag is a command guard and does not replace direct
approval for any production mutation.

The host floor is **20 GiB free**. The conservative maximum growth for this
candidate is **4 GiB** (wheelhouse, installed package target, SPLADE,
FlashRank, resolver/log overhead, and atomic download headroom). Before
candidate creation, package install, and model preload, require at least
`25,769,803,776` bytes free (20 GiB + 4 GiB). Record the preflight and
postflight byte counts. The builder uses a read-only root filesystem and a
1 GiB tmpfs for ephemeral paths; persistent writes go only to the candidate
volume. Stop without cleanup if a preflight fails, the final 20 GiB floor is
breached, or observed candidate growth exceeds 4 GiB.

Free space is measured on the filesystem that backs the guarded local daemon's
`DockerRootDir`, resolved from `docker info`; it is not assumed to be
`/var/lib/docker`. The builder accepts only one existing absolute path without
control characters and fails closed before `df` if discovery or validation
fails. There is deliberately no environment or CLI override for this path.

## Immutable CPU package artifact

The target ABI is **CPython 3.11 / Linux x86_64**. The builder image is pinned
to `python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93`.
PyPI is the sole package index; the official CPU Torch find-link is
`https://download-r2.pytorch.org/whl/cpu/torch/`.

| File | SHA-256 |
| --- | --- |
| `requirements-ml-h4-cpu.in` | `316a6fbe2e33d9fc2f727c9ff729c5c58a44e2e5d2ab2e857a1539538900e646` |
| `requirements-ml-h4-cpu.lock` | `977398e821f80e1303d3ed598d2c30c1f2f2b9d723d34f19b31fe6f38cf9829d` |

Direct versions are:

| Package | Exact version | Source / selected CPU artifact |
| --- | --- | --- |
| Torch | `2.13.0+cpu` | `torch-2.13.0+cpu-cp311-cp311-manylinux_2_28_x86_64.whl`, SHA-256 `6746dbcbeb526eb61330b76b41ff1b4eb848951103a892eeb080dfa2b264667b` |
| Transformers | `5.14.1` | PyPI, SHA-256 in lock |
| NumPy | `2.4.6` | PyPI, SHA-256 in lock |
| ONNX | `1.22.0` | PyPI, SHA-256 in lock |
| FlashRank | `0.2.10` | PyPI, SHA-256 in lock |

The standalone lock contains the PyPI index and official CPU Torch find-link,
so installation and validation never reconstruct source directives from the
input file or shell arguments. It contains 43 exact, hash-verified packages: six fewer than the
abandoned candidate. It excludes the dense-local stack and its
SciPy/scikit-learn transitive packages. ONNX 1.22 selects NumPy 2.4.6 through
its current `ml-dtypes` dependency. The Torch wheel hash is explicit in both
the input and lock because the resolver does not emit a hash for the official
find-link wheel on its own.

`src.shared.ml_runtime_artifact.validate_nomic_policy` rejects any dense-local
package/model/cache path. The static validator also requires exact pins and
valid 64-hex SHA-256 hashes for all lock entries (including transitives), the
CPU Torch build/source, and the target ABI. It never invokes `SetupService` or
any dynamic installer.

## Build and validation

```bash
rtk python3 -m pytest -q tests/security/test_h4_ml_runtime_artifact.py
rtk scripts/h4_ml_runtime_candidate.sh install \
  --volume ambermirror_pip-packages-h4-cpu-nomic-da122dfb-38eb9c2d
rtk scripts/h4_ml_runtime_candidate.sh preload \
  --volume ambermirror_pip-packages-h4-cpu-nomic-da122dfb-38eb9c2d \
  --authorize-preload
```

After the production volume has been separately approved and created, the
production forms are:

```bash
rtk scripts/h4_ml_runtime_candidate.sh install \
  --volume "$production_volume" \
  --authorize-production
rtk scripts/h4_ml_runtime_candidate.sh preload \
  --volume "$production_volume" \
  --authorize-production \
  --authorize-preload
```

Install and preload are distinct production mutations. Show each resolved
command and request direct approval at its checkpoint; approval for volume
creation does not authorize preload.

The installer checks the candidate's exact labels and storage floor before it
downloads hash-verified binary wheels only to its own `.h4-wheelhouse`. It
installs strictly from that wheelhouse with `--no-index --require-hashes`.
It refuses `DOCKER_HOST`, requires the `default` Docker context and the local
`/var/run/docker.sock`, and invokes Docker with that explicit Unix socket; it
therefore cannot inspect or mutate a remote candidate with the same name. A
non-blocking host `flock` serializes an authorized install or preload, without
cleaning shared cache, wheelhouse, manifest, or model state.
The preload pins SPLADE to revision
`49cf4c7b0db5b870a401ddf5e2669993ef3699c7`, sets
`trust_remote_code=False`, and uses the single Hugging Face hub root
`hf-cache/hub` for both preload and offline validation. It caches only SPLADE
and FlashRank. It must stop on an unexpected model/cache or remote-code
requirement.
`--authorize-preload` is a deliberate command guard, not a substitute for
direct user approval: use it only after that approval has been given for this
specific candidate and preload.

After preload, validation runs in a non-service container with:

- the candidate mounted as `/app/.packages:ro`;
- `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and `--network none`;
- candidate-first `PYTHONPATH`;
- only synthetic SPLADE sparse and FlashRank rerank inputs.

It must prove exact installed versions, no CUDA/NVIDIA distribution, no local
dense package/cache anywhere in the candidate tree (including `.cache`,
`.home`, and any future path), `torch.cuda.is_available() is False`, and no
first-use download. FlashRank 0.2.10 exposes a model name and cache directory,
but no revision parameter: the authorized preload therefore records a
path-and-content SHA-256 of its complete cache tree. The network-isolated
first use recomputes and compares that digest before constructing `Ranker`; a
cache changed from the approved preload cannot be accepted, and `--network
none` prevents an upstream fallback.

The model manifest is first written as an attempt-specific pending file. The
offline validator reads that staged file, and only after validation plus the
storage postflight does the writer link it into canonical
`.h4-models.json` after fsyncing its contents. Thus a download, cache, offline-validation, or storage
failure leaves no canonical model manifest and does not block a new authorized
retry; no cache cleanup is attempted. If a proof publication fails after the
model manifest link, the retry resumes network-isolated validation from that
canonical manifest and publishes only the missing proof. A successful run
persists the canonical proof as
`.h4-preload-validation.json`; it is never overwritten. The validator itself
reads the candidate package tree only as `/app/.packages:ro`, and only a
separate proof writer may add that single JSON file after the storage postflight succeeds. The proof records durable preflight, baseline, and
postflight storage values; a failed floor or budget check writes no proof.
Publication is exclusive and atomic on the candidate filesystem: a fsynced
temporary file is linked into place only if the canonical path does not yet
exist, then the directory is fsynced. A failed write can leave only a
best-effort-cleaned temporary file, never a partial canonical proof.
The Nomic check is configuration only: a future deployment may
validate the configured remote Ollama endpoint/model through a read-only
health/configuration contract, but this H4 candidate never contacts it.

## Canary overlay

The canary Compose file keeps the H3 feature volume mounted at
`/app/.packages` and mounts the validated H4 candidate separately and
read-only at `/app/.packages-h4`. Set
`H4_ML_RUNTIME_VOLUME=ambermirror_pip-packages-h4-cpu-nomic-da122dfb-38eb9c2d`;
API and worker then receive:

- `AMBER_H4_ML_RUNTIME_ROOT=/app/.packages-h4`;
- H4 before H3 on `PYTHONPATH`, without replacing or copying either volume;
- the pinned SPLADE revision with `local_files_only=True` and
  `hf-cache/hub`;
- the validated FlashRank cache directory.

`api-canary` starts Uvicorn directly instead of the standard image entrypoint.
This prevents canary startup from running migrations or `init_resources`
against the shared backing services. Treat any such startup action as NO-GO.

When H4 is enabled, missing proof/manifests/cache directories fail closed.
Before starting services, test the actual API and worker application
components in non-service containers with both volumes mounted read-only and
`--network none`.

## Release gates and rollback

No Dependabot alert is closed by this work. H3 must be merged and `main`
rescanned/rebaselined before alert disposition.

For any future production decision:

1. Perform a read-only GPU probe for NVIDIA driver, runtime/toolkit, visible
   devices, memory, and Torch/CUDA ABI. This CPU candidate supplies no GPU
   evidence.
2. Preserve the normal H3 image and clean H3 package volume as rollback. H4 is
   a separate read-only overlay; never copy, mutate, or replace the H3 volume.
3. Require direct user approval for an H4 API/worker startup, any traffic
   change, collection work, ingestion, model configuration change, or
   candidate disposal.
4. Read collection metadata/dimensions before any change. Any blue/green
   collection must be distinct, backed up, dry-run, and separately approved;
   never invoke the destructive embedding migration endpoint or delete/reindex
   an existing collection automatically.
5. Roll back by restoring H3 configuration/traffic while preserving data and
   both package volumes.
