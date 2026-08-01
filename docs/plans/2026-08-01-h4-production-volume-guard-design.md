# H4 production volume guard design

## Problem

The merged H4 builder accepts only the mirror volume
`ambermirror_pip-packages-h4-cpu-nomic-da122dfb-38eb9c2d`. That is correct for
the validated mirror candidate, but it makes the production runbook impossible
to execute without editing the script on the host or reusing a mirror name.
Both alternatives break the exact-SHA and audit requirements.

## Decision

Keep the existing mirror path byte-for-byte compatible and add one explicit
production mode to the same builder. Production mode is enabled only by
`--authorize-production`; it does not create, delete, clear, copy, or relabel a
volume. The accepted production name is derived from the fixed H3 source ref
and the Git HEAD of the checked-out builder:

`amber2_pip-packages-h4-cpu-nomic-<h3-ref>-<current-head-short>`

The builder resolves the full current HEAD itself, requires a 40-hex commit,
and accepts only the exact derived name. It additionally requires the existing
volume label `amber.h4.candidate-ref` to equal that full HEAD. All existing
role/profile/strategy/source/source-ref, local-socket, storage, hash, offline,
CPU, immutability, serialization, and preload guards remain unchanged.

Production install syntax is:

```text
install --volume <exact-name> --authorize-production
```

Production preload syntax is:

```text
preload --volume <exact-name> --authorize-production --authorize-preload
```

The authorization flags are command guards, not substitutes for direct human
approval. Volume creation remains a separately shown and separately approved
production mutation, so a failed or malicious invocation of the builder
cannot create a persistent target.

## Alternatives rejected

- Hardcode the next production name: its merge SHA is unknown until after the
  change merges, creating another circular rollout blocker.
- Reuse the mirror name on production: loses environment provenance and
  violates the approved runbook.
- Patch or wrap the script on the production host: the executed code would no
  longer be the reviewed exact merge SHA.

## Verification

Tests must first demonstrate that production names are currently refused.
They then cover missing authorization, wrong name, exact dynamic name, required
candidate-ref label, unchanged mirror behavior, and documented two-step
approval. No test creates a Docker volume or contacts a remote Docker daemon.

