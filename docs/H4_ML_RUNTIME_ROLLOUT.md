# H4 immutable ML runtime — CPU candidate runbook

## Scope and authority

This runbook is restricted to the local, disposable H4 CPU candidate. It does
not start a service, mount the legacy/H3 package volume, access a datastore,
create or migrate a collection, ingest content, route traffic, or use a GPU.

The single authorized local candidate is
`ambermirror_pip-packages-h4-cpu-20260730`. Its Docker labels are:

| Label | Value |
| --- | --- |
| `amber.h4.role` | `ml-runtime-candidate` |
| `amber.h4.profile` | `cpu` |
| `amber.h4.created` | `2026-07-30` |
| `amber.h4.source-ref` | `08d7a60a` |
| `amber.h4.disposal` | `direct-user-approval-required` |

The volume was created only after proving that exact name did not exist. It is
not to be removed, cleared, reused, or labeled disposable without a new direct
user approval. The initial resolver cache and resolver logs are retained; no
runtime package directory or model cache exists at this pre-install checkpoint.

## Immutable package artifact

The target ABI is **CPython 3.11 / Linux x86_64**. The builder image is pinned
to `python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93`.
The candidate input uses PyPI as its sole package index and the official CPU
find-link `https://download-r2.pytorch.org/whl/cpu/torch/`.

| File | SHA-256 |
| --- | --- |
| `requirements-ml-h4-cpu.in` | `04fc1227171244b7e441de10f7e16c32cc93411438357f1e3036d6bf0327eb1b` |
| `requirements-ml-h4-cpu.lock` | `26fef3ae045b9071265dce0a4de15628d31e654a90ed0ac3a2447158cec89e1c` |

The direct runtime versions are `torch==2.13.0+cpu`,
`numpy==1.26.4`, `transformers==5.14.1`, `onnx==1.22.0`,
`sentence-transformers==5.6.1`, and `flashrank==0.2.10`. NumPy is
intentionally constrained to 1.x because the selected Torch 2.13 binary ABI
cannot safely load NumPy 2.x.

The static validator requires exact pins and SHA-256 hashes for every direct
and transitive requirement, the CPU Torch build/source, and the target ABI. It
does not invoke `SetupService`, pip, or any dynamic package installer.

## Effective wheel inventory

The following was resolved by an isolated, non-installing CPython 3.11
`pip --dry-run --only-binary=:all: --require-hashes` report. Each row is the
effective Linux x86_64 wheel and verified SHA-256, not merely a broad
cross-platform lock hash. All rows are from PyPI's files host except the
explicit CPU Torch wheel. The inventory contains 49 packages and no package
whose name includes `cuda` or `nvidia`.

| Package | Version | Source | Effective wheel | SHA-256 |
| --- | --- | --- | --- | --- |
| annotated-doc | 0.0.5 | files.pythonhosted.org | `annotated_doc-0.0.5-py3-none-any.whl` | `117bac03a25ede5df5440e855b32d556049ca169ead221505badf432fed4b101` |
| anyio | 4.14.2 | files.pythonhosted.org | `anyio-4.14.2-py3-none-any.whl` | `9f505dda5ac9f0c8309b5e8bd445a8c2bf7246f3ce950121e45ea15bc41d1494` |
| certifi | 2022.12.7 | files.pythonhosted.org | `certifi-2022.12.7-py3-none-any.whl` | `4ad3232f5e926d6718ec31cfc1fcadfde020920e278684144551c91769c7bc18` |
| charset-normalizer | 2.1.1 | files.pythonhosted.org | `charset_normalizer-2.1.1-py3-none-any.whl` | `83e9a75d1911279afd89352c68b45348559d1fc0506b054b346651b5e7fee29f` |
| click | 8.4.2 | files.pythonhosted.org | `click-8.4.2-py3-none-any.whl` | `e6f9f66136c816745b9d65817da91d61d957fb16e02e4dcd0552553c5a197b76` |
| filelock | 3.29.0 | files.pythonhosted.org | `filelock-3.29.0-py3-none-any.whl` | `96f5f6344709aa1572bbf631c640e4ebeeb519e08da902c39a001882f30ac258` |
| flashrank | 0.2.10 | files.pythonhosted.org | `FlashRank-0.2.10-py3-none-any.whl` | `5d3272ae657d793c132d1e7917ed9e2adf49e0e1c60735583a67b051c6f0434a` |
| flatbuffers | 25.12.19 | files.pythonhosted.org | `flatbuffers-25.12.19-py2.py3-none-any.whl` | `7634f50c427838bb021c2d66a3d1168e9d199b0607e6329399f04846d42e20b4` |
| fsspec | 2026.4.0 | files.pythonhosted.org | `fsspec-2026.4.0-py3-none-any.whl` | `11ef7bb35dab8a394fde6e608221d5cf3e8499401c249bebaeaad760a1a8dec2` |
| h11 | 0.16.0 | files.pythonhosted.org | `h11-0.16.0-py3-none-any.whl` | `63cf8bbe7522de3bf65932fda1d9c2772064ffb3dae62d55932da54b31cb6c86` |
| hf-xet | 1.5.2 | files.pythonhosted.org | `hf_xet-1.5.2-cp38-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` | `db78c39c83d6279daddc98e2238f373ab8980685556d42472b4ec51abcf03e8c` |
| httpcore | 1.0.9 | files.pythonhosted.org | `httpcore-1.0.9-py3-none-any.whl` | `2d400746a40668fc9dec9810239072b40b4484b640a8c38fd654a024c7a1bf55` |
| httpx | 0.28.1 | files.pythonhosted.org | `httpx-0.28.1-py3-none-any.whl` | `d909fcccc110f8c7faf814ca82a9a4d816bc5a6dbfea25d6591d6985b8ba59ad` |
| huggingface_hub | 1.25.1 | files.pythonhosted.org | `huggingface_hub-1.25.1-py3-none-any.whl` | `004d4e70350517e24c68a7dbb7dc5e40b2b6aefef8f94bf7a85f6f9835102ea5` |
| idna | 3.4 | files.pythonhosted.org | `idna-3.4-py3-none-any.whl` | `90b77e79eaa3eba6de819a0c442c0b4ceefc341a7a2ab77d7562bf49f425c5c2` |
| jinja2 | 3.1.6 | files.pythonhosted.org | `jinja2-3.1.6-py3-none-any.whl` | `85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67` |
| joblib | 1.5.3 | files.pythonhosted.org | `joblib-1.5.3-py3-none-any.whl` | `5fc3c5039fc5ca8c0276333a188bbd59d6b7ab37fe6632daa76bc7f9ec18e713` |
| markdown-it-py | 4.2.0 | files.pythonhosted.org | `markdown_it_py-4.2.0-py3-none-any.whl` | `9f7ebbcd14fe59494226453aed97c1070d83f8d24b6fc3a3bcf9a38092641c4a` |
| markupsafe | 3.0.3 | files.pythonhosted.org | `markupsafe-3.0.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl` | `0bf2a864d67e76e5c9a34dc26ec616a66b9888e25e7b9460e1c76d3293bd9dbf` |
| mdurl | 0.1.2 | files.pythonhosted.org | `mdurl-0.1.2-py3-none-any.whl` | `84008a41e51615a49fc9966191ff91509e3c40b939176e643fd50a5c2196b8f8` |
| ml_dtypes | 0.5.4 | files.pythonhosted.org | `ml_dtypes-0.5.4-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl` | `19b9a53598f21e453ea2fbda8aa783c20faff8e1eeb0d7ab899309a0053f1483` |
| mpmath | 1.3.0 | files.pythonhosted.org | `mpmath-1.3.0-py3-none-any.whl` | `a0b2b9fe80bbcd81a6647ff13108738cfb482d481d826cc0e02f5b35e5c88d2c` |
| narwhals | 2.24.0 | files.pythonhosted.org | `narwhals-2.24.0-py3-none-any.whl` | `42fdedf44e5b2ca7505630d45b4ac3058f38d8485cba9fe1652ca23152df7489` |
| networkx | 3.6.1 | files.pythonhosted.org | `networkx-3.6.1-py3-none-any.whl` | `d47fbf302e7d9cbbb9e2555a0d267983d2aa476bac30e90dfbe5669bd57f3762` |
| numpy | 1.26.4 | files.pythonhosted.org | `numpy-1.26.4-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` | `666dbfb6ec68962c033a450943ded891bed2d54e6755e35e5835d63f4f6931d5` |
| onnx | 1.22.0 | files.pythonhosted.org | `onnx-1.22.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl` | `1d0a2bdb15eb2b3cb65c438f3423d9620d14fdce32f92380e6bb1b2e09568ef5` |
| onnxruntime | 1.28.0 | files.pythonhosted.org | `onnxruntime-1.28.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl` | `a166b78ee04f3a37fa1ef82034b6a3ce96d9684e582d4d30b296de83e9998bb5` |
| packaging | 24.1 | files.pythonhosted.org | `packaging-24.1-py3-none-any.whl` | `5b8f2217dbdbd2f7f384c41c628544e6d52f2d0f53c6d0c3ea61aa5d1d7ff124` |
| protobuf | 7.35.1 | files.pythonhosted.org | `protobuf-7.35.1-cp310-abi3-manylinux2014_x86_64.whl` | `74758715c53d7158fb76caf4f0cfdacc5329a4b1bb994f865d6cf302d413a1c4` |
| pygments | 2.20.0 | files.pythonhosted.org | `pygments-2.20.0-py3-none-any.whl` | `81a9e26dd42fd28a23a2d169d86d7ac03b46e2f8b59ed4698fb4785f946d0176` |
| pyyaml | 6.0.3 | files.pythonhosted.org | `pyyaml-6.0.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl` | `b8bb0864c5a28024fac8a632c443c87c5aa6f215c0b126c449ae1a150412f31d` |
| regex | 2026.7.19 | files.pythonhosted.org | `regex-2026.7.19-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl` | `09f3e5287f94f17b709dc9a9e70865855feee835c861613be144218ce4ca82cc` |
| requests | 2.28.1 | files.pythonhosted.org | `requests-2.28.1-py3-none-any.whl` | `8fefa2a1a1365bf5520aac41836fbee479da67864514bdb821f31ce07ce65349` |
| rich | 15.0.0 | files.pythonhosted.org | `rich-15.0.0-py3-none-any.whl` | `33bd4ef74232fb73fe9279a257718407f169c09b78a87ad3d296f548e27de0bb` |
| safetensors | 0.8.0 | files.pythonhosted.org | `safetensors-0.8.0-cp310-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` | `fd6f3f93c9a0a7cc2788ee63fb763353d4bd2e89b0751bc78fcf7dda00bea774` |
| scikit-learn | 1.9.0 | files.pythonhosted.org | `scikit_learn-1.9.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl` | `f7e254636164090da847715a27f8e5478feb98c40a9e0ee90cbd277de9e5ceb8` |
| scipy | 1.17.1 | files.pythonhosted.org | `scipy-1.17.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl` | `43af8d1f3bea642559019edfe64e9b11192a8978efbd1539d7bc2aaa23d92de4` |
| sentence-transformers | 5.6.1 | files.pythonhosted.org | `sentence_transformers-5.6.1-py3-none-any.whl` | `cefbb17b6325a982a4732c8c49fb013375392687049d1de3d435c4b04060680b` |
| setuptools | 78.1.0 | files.pythonhosted.org | `setuptools-78.1.0-py3-none-any.whl` | `3e386e96793c8702ae83d17b853fb93d3e09ef82ec62722e61da5cd22376dcd8` |
| shellingham | 1.5.4 | files.pythonhosted.org | `shellingham-1.5.4-py2.py3-none-any.whl` | `7ecfff8f2fd72616f7481040475a65b2bf8af90a56c89140852d1120324e8686` |
| sympy | 1.14.0 | files.pythonhosted.org | `sympy-1.14.0-py3-none-any.whl` | `e091cc3e99d2141a0ba2847328f5479b05d94a6635cb96148ccb3f34671bd8f5` |
| threadpoolctl | 3.6.0 | files.pythonhosted.org | `threadpoolctl-3.6.0-py3-none-any.whl` | `43a0b8fd5a2928500110039e43a5eed8480b918967083ea48dc3ab9f13c4a7fb` |
| tokenizers | 0.22.2 | files.pythonhosted.org | `tokenizers-0.22.2-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` | `369cc9fc8cc10cb24143873a0d95438bb8ee257bb80c71989e3ee290e8d72c67` |
| torch | 2.13.0+cpu | download-r2.pytorch.org | `torch-2.13.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl` | `6746dbcbeb526eb61330b76b41ff1b4eb848951103a892eeb080dfa2b264667b` |
| tqdm | 4.66.5 | files.pythonhosted.org | `tqdm-4.66.5-py3-none-any.whl` | `90279a3770753eafc9194a0364852159802111925aa30eb3f9d85b0e805ac7cd` |
| transformers | 5.14.1 | files.pythonhosted.org | `transformers-5.14.1-py3-none-any.whl` | `9db974c4079ede2d1a3ea7ca5a240df33f2cc26fc2b36ba64c5f2a4f43b6e725` |
| typer | 0.27.0 | files.pythonhosted.org | `typer-0.27.0-py3-none-any.whl` | `6f4b27631e47f077871b7dc30e933ec0131c1390fbe0e387ea5574b5bac9ccf1` |
| typing_extensions | 4.15.0 | files.pythonhosted.org | `typing_extensions-4.15.0-py3-none-any.whl` | `f0fa19c6845758ab08074a0cfa8b7aecb71c999ca73d62883bc25cc018c4e548` |
| urllib3 | 1.26.13 | files.pythonhosted.org | `urllib3-1.26.13-py2.py3-none-any.whl` | `47cc05d99aaa09c9e72ed5809b60e7ba354e64b59c9c173ac3018642d8bb41fc` |

## Build and local validation

Before the initial installation, run the focused static contract tests and
inspect the candidate labels. The install command is deliberately hard-coded
to the one labeled candidate and refuses a volume that already has an artifact:

```bash
rtk python3 -m pytest -q tests/security/test_h4_ml_runtime_artifact.py
rtk scripts/h4_ml_runtime_candidate.sh install \
  --volume ambermirror_pip-packages-h4-cpu-20260730
```

It uses an ephemeral, non-service container, downloads hash-verified wheels
only into that candidate's `.h4-wheelhouse`, then installs strictly with
`--no-index --require-hashes`. It has no reference to `SetupService` or a
legacy/H3 volume.

After package installation, pre-load only into the candidate cache:

- SPLADE: `naver/splade-cocondenser-ensembledistil` at revision
  `49cf4c7b0db5b870a401ddf5e2669993ef3699c7`;
- local dense embedding: `BAAI/bge-m3` at revision
  `5617a9f61b028005a4858fdac845db406aefb181`;
- FlashRank: `ms-marco-MiniLM-L-12-v2`, with the resulting cached files
  inventoried by SHA-256 before offline use.

Preload must use `trust_remote_code=False`. If any preload requests remote
code, requires a missing package, tries to access a datastore, or downloads
differing/unexpected artifacts, stop and report rather than retrying against a
different volume. The validation container must then mount the candidate as
`/app/.packages:ro`, set `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1`, use `--network none`, and exercise synthetic
SPLADE, BGE-M3 encoding, and FlashRank reranking only.

## Future blue/green release gates

This candidate is not a service canary. A future production decision requires
all of the following first:

1. Read-only GPU probe: driver/`nvidia-smi`, Docker NVIDIA runtime and
   container toolkit, visible devices, GPU memory, and Torch/CUDA/driver ABI.
   This CPU candidate supplies no evidence for GPU availability.
2. Keep the normal H3 image plus clean H3 package volume untouched as the
   normal rollback point. Do not alter a legacy volume.
3. Start any H4 API/worker only after direct user approval, using a distinct
   H4 package volume and a blue/green configuration. Never run an H4 canary
   through the application's migration/initialization entrypoint casually.
4. Read current collection names, dimensions, and embedding-model metadata
   without mutation. If vectors are incompatible, create a distinct candidate
   collection only after backup, dry-run, and direct approval. Re-ingestion
   must be a separately approved operation; do not call the destructive
   embedding migration endpoint and do not delete/reindex an existing
   collection.
5. Compare synthetic and sampled read-only query behavior before an explicit
   traffic/configuration switch. Keep the old collection and H3 traffic path
   intact for rollback; rollback is a configuration/traffic reversal, not a
   data deletion.

No Dependabot alert is closed by this candidate. H3 must be merged and
`main` rescanned/rebaselined before alert disposition is considered.
