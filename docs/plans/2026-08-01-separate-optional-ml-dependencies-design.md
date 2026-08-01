# Separate Optional ML Dependencies Design

## Context

The general `requirements.txt` still declares a legacy local-embedding stack:
Sentence Transformers 2.x, Transformers 4.40.1, and Hugging Face Hub 0.23.0.
Two High Dependabot alerts require Transformers 5.5.0 or newer. Updating only
Transformers is not valid: Transformers 5.5.0 requires Hugging Face Hub 1.5.0
or newer, while Sentence Transformers 2.7.0 constrains Transformers below 5.

Production API and worker images install `requirements-core.txt`, which does
not contain this stack. Production H4 inference instead uses the separately
validated immutable H4 lock and read-only runtime volume. The vulnerable
general manifest is therefore neither the production core contract nor the H4
artifact contract.

## Decision

Remove `sentence-transformers`, `transformers`, and `huggingface-hub` from the
general manifest. Preserve local embeddings as an explicit optional feature
installed into `/app/.packages`, with a coherent fully pinned set aligned with
the validated H4 versions where packages overlap:

- Torch `2.13.0+cpu`
- Sentence Transformers `5.6.1`
- Transformers `5.14.1`
- Hugging Face Hub `1.25.1`
- Tokenizers `0.22.2`

Keep the H4 lock, Dockerfiles, Compose files, and production runtime unchanged.
Update `requirements-optional.txt` so operator documentation matches the setup
service exactly.

## Safety and failure behavior

The base API and worker continue to boot from `requirements-core.txt`. Local
embedding imports remain lazy and explicitly unavailable until the optional
feature is installed. Installation remains isolated in the packages volume;
an installation failure must not mutate the core environment. No migration,
datastore action, Compose action, or production operation is part of this
change.

## Verification

Regression tests must prove the three legacy ML packages are absent from the
general manifest, the optional feature exposes the exact coherent pins, and
the operator documentation matches. TDD requires observing these tests fail
against the current files before implementation. Then run dependency resolver
dry-run, targeted tests, Ruff, mypy, import contracts, and the complete project
quality gate. Do not push or open a pull request until every relevant gate is
green and the diff has passed review and secret scanning.
