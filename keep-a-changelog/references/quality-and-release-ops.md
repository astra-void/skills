# Quality and Release Operations

Use this reference when the request needs content-quality review, release-summary guidance, migration-note rules, fix grouping, or profile selection.

## Quality Review Heuristics

Warn on these cases by default:

- duplicate bullets in the same section
- empty category headings
- empty release sections
- reverse-order released versions
- large release sections with no summary prose
- removals or deprecations that likely require migration notes
- bullets that read like internal work, such as refactors, CI-only changes, lint cleanups, or test-only work
- bullets that are too terse to explain user impact
- long `Fixed` sections that would be easier to scan when grouped into themes

Treat these as blocking only when the user requests strict quality enforcement or `--strict-quality`.

## Notability Rules

Default to excluding low-signal groups from drafted changelog content:

- `ci`
- `tooling`
- `test`
- docs-only changes that do not affect product behavior, upgrade flow, or public usage

Review `area` and `misc` groups manually before including them.
Prefer `package` and `app` groups when the change is clearly user-visible.
If a build, CI, or tooling change belongs in the changelog, rewrite it around outcomes such as reliability, stability, compatibility, or upgrade behavior rather than listing implementation details.

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

## Fix Grouping

Prefer grouped fix bullets when a release contains many closely related fixes.

Instead of listing every interaction fix separately, compress them into a few themes such as:

- focus and keyboard behavior
- popup positioning and layering
- input sizing or measurement behavior

Keep individual bullets only when users would genuinely benefit from that level of detail.

## Generic Examples

- Package or app removal:
  `This release removes deprecated packages and narrows the supported surface to the maintained modules.`
- API removal with migration:
  `Migration notes:`
  `- Replace deprecated imports with the stable entrypoints before upgrading.`
- Build reliability improvement:
  `- Improve build reliability and incremental execution stability across the workspace.`
- Grouped fixes:
  `- Improve focus restoration and keyboard navigation across layered and composite components.`

## Profiles

- `generic`: default; broad grouping by repo shape without assuming one monorepo layout
- `lattice`: current explicit monorepo profile with `packages/`, `apps/`, and attached test-domain behavior

Prefer `generic` unless the repository clearly matches the `lattice` profile.
Profiles affect grouping only. Release-writing standards stay generic.
