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

It does not start a service, mount an H3/legacy package volume, access a
datastore, create or migrate a collection, ingest content, reindex data, route
traffic, or use a GPU. The previous H4 candidate remains audit-only and is not
mounted, cleared, relabeled, or deleted by this procedure.

## Candidate and storage guard

The single active candidate is
`ambermirror_pip-packages-h4-cpu-nomic-20260730`.

| Label | Value |
| --- | --- |
| `amber.h4.role` | `ml-runtime-candidate` |
| `amber.h4.profile` | `cpu` |
| `amber.h4.strategy` | `nomic-ollama-remote` |
| `amber.h4.source` | `clean` |
| `amber.h4.created` | `2026-07-30` |
| `amber.h4.source-ref` | `08d7a60a` |
| `amber.h4.disposal` | `direct-user-approval-required` |

The candidate name was proven absent before creation. It is never to be
removed, cleared, or reused without direct user approval.

The host floor is **20 GiB free**. The conservative maximum growth for this
candidate is **4 GiB** (wheelhouse, installed package target, SPLADE,
FlashRank, resolver/log overhead, and atomic download headroom). Before
candidate creation, package install, and model preload, require at least
`25,769,803,776` bytes free (20 GiB + 4 GiB). Record the preflight and
postflight byte counts. The builder uses a read-only root filesystem and a
1 GiB tmpfs for ephemeral paths; persistent writes go only to the candidate
volume. Stop without cleanup if a preflight fails, the final 20 GiB floor is
breached, or observed candidate growth exceeds 4 GiB.

## Immutable CPU package artifact

The target ABI is **CPython 3.11 / Linux x86_64**. The builder image is pinned
to `python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93`.
PyPI is the sole package index; the official CPU Torch find-link is
`https://download-r2.pytorch.org/whl/cpu/torch/`.

| File | SHA-256 |
| --- | --- |
| `requirements-ml-h4-cpu.in` | `d05e423a467abd4f25034a8f591e1c889edb3cb74136f8fcd241a56256b527b5` |
| `requirements-ml-h4-cpu.lock` | `9cd303586d8bee32848f14457d28cdb46278df1acbde5ee04f1c2156e8f48456` |

Direct versions are:

| Package | Exact version | Source / selected CPU artifact |
| --- | --- | --- |
| Torch | `2.13.0+cpu` | `torch-2.13.0+cpu-cp311-cp311-manylinux_2_28_x86_64.whl`, SHA-256 `6746dbcbeb526eb61330b76b41ff1b4eb848951103a892eeb080dfa2b264667b` |
| Transformers | `5.14.1` | PyPI, SHA-256 in lock |
| NumPy | `2.4.6` | PyPI, SHA-256 in lock |
| ONNX | `1.22.0` | PyPI, SHA-256 in lock |
| FlashRank | `0.2.10` | PyPI, SHA-256 in lock |

The lock contains 43 exact, hash-verified packages: six fewer than the
abandoned candidate. It excludes the dense-local stack and its
SciPy/scikit-learn transitive packages. ONNX 1.22 selects NumPy 2.4.6 through
its current `ml-dtypes` dependency. The Torch wheel hash is explicit in both
the input and lock because the resolver does not emit a hash for the official
find-link wheel on its own.

`src.shared.ml_runtime_artifact.validate_nomic_policy` rejects any dense-local
package/model/cache path. The static validator also requires exact pins and
SHA-256 hashes for all lock entries, the CPU Torch build/source, and the target
ABI. It never invokes `SetupService` or any dynamic installer.

## Build and validation

```bash
rtk python3 -m pytest -q tests/security/test_h4_ml_runtime_artifact.py
rtk scripts/h4_ml_runtime_candidate.sh install \
  --volume ambermirror_pip-packages-h4-cpu-nomic-20260730
rtk scripts/h4_ml_runtime_candidate.sh preload \
  --volume ambermirror_pip-packages-h4-cpu-nomic-20260730 \
  --authorize-preload
```

The installer checks the candidate's exact labels and storage floor before it
downloads hash-verified binary wheels only to its own `.h4-wheelhouse`. It
installs strictly from that wheelhouse with `--no-index --require-hashes`.
The preload pins SPLADE to revision
`49cf4c7b0db5b870a401ddf5e2669993ef3699c7`, sets
`trust_remote_code=False`, and caches only SPLADE and FlashRank. It must stop
on an unexpected model/cache or remote-code requirement.
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
first-use download. A successful run persists the canonical proof as
`.h4-preload-validation.json`; it is never overwritten. The validator itself
reads the candidate package tree only as `/app/.packages:ro`, and only a
separate proof writer may add that single JSON file after the storage postflight succeeds. The proof records durable preflight, baseline, and
postflight storage values; a failed floor or budget check writes no proof.
The Nomic check is configuration only: a future deployment may
validate the configured remote Ollama endpoint/model through a read-only
health/configuration contract, but this H4 candidate never contacts it.

## Release gates and rollback

No Dependabot alert is closed by this work. H3 must be merged and `main`
rescanned/rebaselined before alert disposition.

For any future production decision:

1. Perform a read-only GPU probe for NVIDIA driver, runtime/toolkit, visible
   devices, memory, and Torch/CUDA ABI. This CPU candidate supplies no GPU
   evidence.
2. Preserve the normal H3 image and clean H3 package volume as rollback. Do
   not mount an H3/legacy volume into H4.
3. Require direct user approval for an H4 API/worker startup, any traffic
   change, collection work, ingestion, model configuration change, or
   candidate disposal.
4. Read collection metadata/dimensions before any change. Any blue/green
   collection must be distinct, backed up, dry-run, and separately approved;
   never invoke the destructive embedding migration endpoint or delete/reindex
   an existing collection automatically.
5. Roll back by restoring H3 configuration/traffic while preserving data and
   both package volumes.
