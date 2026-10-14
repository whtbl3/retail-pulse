## What changed

<!-- Before: ... / After: ... (what a reader will notice) -->

## Why

<!-- Link to the spec, an issue or specs/NNN-name/ if any -->

## Definition of Done (Project-Spec §16)

- [ ] Behavior matches `docs/Project-Spec.md` and the existing architecture
- [ ] Tests cover the normal case and the important failure cases
- [ ] `make check` is green (ruff + pytest); for dbt changes, `make dbt-parse` succeeds
- [ ] New commands and configuration are documented (`docs/phases/`, `docs/design/`, `make help`)
- [ ] No secrets or runtime files committed (`.env`, keys, `dbt/target/`...)
- [ ] If a Final decision changed, the decision log (§17) is updated in the same PR

## How it was tested

<!-- Commands run and their results -->
