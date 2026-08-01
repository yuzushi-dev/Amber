# H4 Docker Root Storage Gate Design

## Problem

The H4 installer currently measures free space with `df` against the hardcoded
path `/var/lib/docker`. Production configures Docker with
`DockerRootDir=/opt/docker`, so the guard measured the root filesystem instead
of the filesystem that stores images and named volumes. The production install
failed closed before writing packages, but the false negative blocks the safe
rollout.

## Design

Keep the existing 20 GiB postflight floor, 4 GiB growth budget, and 24 GiB
preflight requirement unchanged. Replace only the source of the measured path.
A new `docker_root_dir` shell function asks the already-guarded local daemon for
`docker info --format '{{ .DockerRootDir }}'`. It accepts exactly one non-empty
line, requires an absolute path, rejects control characters, and requires the
directory to exist. Any invalid or unavailable value aborts before `df` or a
write to the candidate volume.

`free_bytes` calls this function and runs `df -B1 --output=avail --` against the
validated Docker root. This measures the filesystem consumed by Docker images,
temporary layers, and the candidate volume together. There is no environment,
CLI, or configuration override, so an operator cannot redirect the safety gate
to a filesystem with unrelated free space. The existing local socket/context
guard remains authoritative.

## Safety and testing

Static contract tests will require daemon-derived discovery and reject the old
hardcoded path or an override. Behavioral shell tests will use a fake `docker`
and `df` on `PATH` to prove that a custom absolute root is passed to `df`, while
relative, multiline, and nonexistent roots fail closed before `df`. Tests are
written and observed failing before implementation. Focused security tests and
the complete repository verification gate must pass before publication.

No production retry, volume write, preload, service start, datastore access, or
deployment is part of this code change.
