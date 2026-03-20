# Quality and Release Operations

Use this reference when the request needs content-quality review, release-summary guidance, migration-note rules, or profile selection.

## Quality Review Heuristics

Warn on these cases by default:

- duplicate bullets in the same section
- empty category headings
- empty release sections
- reverse-order released versions
- bullets that read like internal work, such as refactors, CI-only changes, lint cleanups, or test-only work
- bullets that are too terse to explain user impact

Treat these as blocking only when the user requests strict quality enforcement or `--strict-quality`.

## Notability Rules

Default to excluding low-signal groups from drafted changelog content:

- `ci`
- `tooling`
- `test`
- docs-only changes that do not affect product behavior, upgrade flow, or public usage

Review `area` and `misc` groups manually before including them.
Prefer `package` and `app` groups when the change is clearly user-visible.

## Release-Level Prose

Use summary prose before category headings when:

- the release changes the package surface
- the release removes or narrows supported scope
- the release combines many related bullets that need one framing sentence
- the release is large enough that users need a fast overview

Use migration notes when:

- public APIs are removed or renamed
- packages are removed, split, or consolidated
- the upgrade requires behavior changes or follow-up steps

## Profiles

- `generic`: default; broad grouping by repo shape without assuming one monorepo layout
- `lattice`: current explicit monorepo profile with `packages/`, `apps/`, and attached test-domain behavior

Prefer `generic` unless the repository clearly matches the `lattice` profile.
