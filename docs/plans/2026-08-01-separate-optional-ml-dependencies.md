# Separate Optional ML Dependencies Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the vulnerable, internally incompatible local-ML stack from the general manifest while preserving it as a coherent optional installation.

**Architecture:** Production core images remain based on `requirements-core.txt`, and H4 remains based on its immutable lock. The setup service owns the optional local-embedding dependency set installed into `/app/.packages`; documentation and regression tests enforce the boundary.

**Tech Stack:** Python 3.11, pytest, pip dependency resolver, Ruff, mypy, import-linter.

---

### Task 1: Add failing dependency-boundary tests

**Files:**
- Modify: `tests/unit/core/ingestion/infrastructure/extraction/test_marker_retirement.py`

**Step 1: Write the failing tests**

Replace the legacy exact-version assertions with tests equivalent to:

```python
def test_general_requirements_exclude_optional_local_embedding_stack():
    requirements = (PROJECT_ROOT / "requirements.txt").read_text().lower().splitlines()
    names = {line.split("==")[0].split(">=")[0] for line in requirements if line and not line.startswith("#")}
    assert names.isdisjoint({"sentence-transformers", "transformers", "huggingface-hub"})


def test_local_embeddings_use_validated_compatible_versions():
    packages = set(OPTIONAL_FEATURES["local_embeddings"].packages)
    assert {
        "torch==2.13.0+cpu",
        "sentence-transformers==5.6.1",
        "transformers==5.14.1",
        "huggingface-hub==1.25.1",
        "tokenizers==0.22.2",
    } <= packages


def test_optional_requirements_document_validated_local_embedding_versions():
    optional = (PROJECT_ROOT / "requirements-optional.txt").read_text()
    for package in OPTIONAL_FEATURES["local_embeddings"].packages:
        assert package in optional
```

**Step 2: Run tests and verify RED**

Run:

```bash
/home/daniele/Amber/.venv/bin/python -m pytest tests/unit/core/ingestion/infrastructure/extraction/test_marker_retirement.py -q
```

Expected: failures because the general manifest still contains the legacy
packages and the setup/docs still use unpinned legacy constraints.

**Step 3: Commit the RED tests**

```bash
git add tests/unit/core/ingestion/infrastructure/extraction/test_marker_retirement.py
git commit -m "test: enforce optional ML dependency boundary"
```

### Task 2: Apply the minimal manifest separation

**Files:**
- Modify: `requirements.txt`
- Modify: `requirements-optional.txt`
- Modify: `src/api/services/setup_service.py`

**Step 1: Remove the legacy stack from the general manifest**

Delete only these declarations from `requirements.txt`:

```text
sentence-transformers>=2.7.0
transformers==4.40.1
huggingface-hub==0.23.0
```

**Step 2: Pin the optional feature coherently**

Set the `local_embeddings` package list to:

```python
packages=[
    "torch==2.13.0+cpu",
    "sentence-transformers==5.6.1",
    "transformers==5.14.1",
    "huggingface-hub==1.25.1",
    "tokenizers==0.22.2",
    OPTIONAL_PROTOBUF_PIN,
]
```

**Step 3: Synchronize operator documentation**

Update the local-embedding section in `requirements-optional.txt` to show the
same five exact ML package pins and retain the CPU PyTorch index instruction.

**Step 4: Run tests and verify GREEN**

Run the Task 1 pytest command. Expected: all tests pass.

**Step 5: Commit the implementation**

```bash
git add requirements.txt requirements-optional.txt src/api/services/setup_service.py
git commit -m "fix: separate optional ML dependencies"
```

### Task 3: Resolve and verify the complete change

**Files:**
- Verify only; no production or datastore files.

**Step 1: Dry-run dependency resolution**

Run `pip install --dry-run --ignore-installed` for the five pinned optional ML
packages with the PyTorch CPU extra index. Expected: resolver success without
installing or changing the environment.

**Step 2: Run focused safety tests**

Run the marker-retirement test module, H4 runtime artifact tests, setup-service
tests, and parser-stack volume tests. Expected: all pass.

**Step 3: Run static gates**

Run Ruff over `src` and `tests`, mypy over `src`, and all import-linter
contracts. Expected: zero failures.

**Step 4: Run the full quality gate**

Run `bash scripts/verify.sh`. Expected: backend and frontend gates pass. Record
any demonstrably pre-existing environment-only failure without masking it.

**Step 5: Audit the diff**

Run `git diff --check`, confirm no Dockerfile, Compose, migration, datastore,
or production file changed, and secret-scan every changed file.

**Step 6: Final commit if verification documentation changed**

Stage only explicitly modified files. Do not push, merge, deploy, or open a
pull request without a separate decision after review.
