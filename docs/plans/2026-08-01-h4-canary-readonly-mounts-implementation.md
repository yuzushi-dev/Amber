# H4 canary read-only shared mounts: implementation plan

1. Add a failing security contract test that requires the uploads, H3 packages, Hugging Face cache, and H4 candidate mounts to be read-only for both canary services.
2. Run the focused test and record that the current Compose overlay violates the new contract.
3. Add `:ro` to the three currently writable shared mounts in both canary services.
4. Re-run the focused test, H4 security suite, shell/lock checks, and the complete repository verification gate.
5. Review the diff for scope and whitespace errors, then open a PR. Do not merge or mutate production without a separate direct confirmation.
