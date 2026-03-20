---
name: keep-a-changelog
description: Draft, review, split, and optionally update Keep a Changelog style CHANGELOG.md files using the Keep a Changelog 1.1.0 format. Use when Codex needs to inspect the current git diff, review changelog quality, propose changelog bullets, group repo changes by changelog relevance, or safely manage Unreleased, release, subset-release, or yanked version sections in a repository changelog.
---

# Keep a Changelog

Use this skill for draft-only changelog requests, changelog review requests, and changelog release operations.

Read [references/spec.md](references/spec.md) for the format rules, canonical headings, compare-link expectations, and safe normalization boundaries.
Read [references/quality-and-release-ops.md](references/quality-and-release-ops.md) when the request needs notability rules, migration-note guidance, release-summary guidance, or profile selection details.

## Workflow

1. Inspect the real repository state first.
   Start with `scripts/plan_changelog.py --repo <cwd> --format json`.
   Default to `--profile generic`.
   Use `--profile lattice` only when the repository clearly matches the current monorepo conventions.

2. Enforce safety gates before automatic writes.
   Stop if `has_partial_staging` is true.
   Stop if `has_merge_conflicts` is true.
   Stop if `structure.errors` is non-empty.
   Treat `quality_warnings` as warnings by default.
   Stop on `quality_warnings` only when the user asks for strict enforcement or when `--strict-quality` is enabled.

3. Draft changelog content from grouped repo changes.
   Use the planner output as the source of truth for groups, notability hints, release support, and quality warnings.
   Read only the diff for one group before drafting bullets for that group.
   Omit `ci`, `tooling`, `test`, and low-signal docs work unless the change is clearly user-visible or release-relevant.
   Keep all generated prose in English.

4. Review both structure and content quality.
   Check for `## [Unreleased]`.
   Check level-2 version headings for `YYYY-MM-DD` dates.
   Check level-3 category headings against the canonical set.
   Warn on duplicate bullets, empty headings, empty sections, reverse-order release sections, internal-only wording, and weak user-facing phrasing.
   For large or breaking releases, require explicit release summary and migration-note coverage.

5. Execute changelog writes only when the user explicitly asks for an update.
   For unreleased updates:
   `scripts/apply_changelog.py --repo <cwd> --mode unreleased --payload <file-or->`
   For full release promotion:
   `scripts/apply_changelog.py --repo <cwd> --mode release --payload <file-or->`
   For selective release promotion:
   `scripts/apply_changelog.py --repo <cwd> --mode release-subset --payload <file-or->`
   For yank and unyank:
   `scripts/apply_changelog.py --repo <cwd> --mode yank --payload <file-or->`
   `scripts/apply_changelog.py --repo <cwd> --mode unyank --payload <file-or->`

6. Handle compare links conservatively.
   Repair or create footer links only when the planner reports a safe compare strategy.
   Prefer warnings over guessed link rewrites.

7. Keep Changesets out of scope for writes.
   Mention `.changeset` only as adjacent release metadata when the repository uses it.
   Do not create or edit changeset files.

## Profile Rules

- `generic`: default profile; group by broad repo shape without assuming `packages/` or `apps/`
- `lattice`: explicit profile for the current monorepo conventions and package/app test attachment behavior

## Message Policy

- Prefer user-visible behavior over implementation detail.
- Keep bullets concise, specific, and action-oriented.
- Summarize notable changes, not every internal edit.
- Prefer these headings in canonical order: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.
- Use release-level summary prose when the release materially changes scope, package surface, or migration requirements.
- Add migration notes for breaking behavior, package removals, or required follow-up work.
- Mention `YANKED` only when the changelog already uses it or the user explicitly asks for it.
- Keep all skill output and generated changelog text in English.

## Output Contract

- Draft from diff:
  1. print a short grouped plan when more than one domain is involved
  2. show each group with notability hints
  3. print proposed changelog bullets only for notable groups by default
- Review existing changelog:
  1. report whether the file conforms structurally
  2. list exact structural issues
  3. list `quality_warnings`
  4. provide corrected headings, bullets, summaries, or migration notes only when useful
- Split recommendation without execution:
  1. print the planner summary
  2. print the proposed category-to-bullets payload
  3. print any proposed `summary` and `migration_notes`
- Auto-update request:
  1. run `plan_changelog.py`
  2. stop on any safety gate
  3. draft the payload in canonical heading order
  4. run `apply_changelog.py`
  5. report the updated section, any quality warnings, and any skipped compare-link update

Use these response shapes:

- Draft from diff:
  `## [Unreleased]`
  `### Added`
  `- Add keyboard navigation for the menu trigger.`
- Large release:
  `## [0.4.0] - 2026-03-20`
  `This release narrows the published package surface and removes preview-only packages.`
  `Migration notes:`
  `- Replace preview imports with the stable package entrypoints.`
- Review existing changelog:
  `Non-conforming: missing ## [Unreleased] section.`
  `Quality warning: [1.2.0] bullet under Changed looks internal or low-signal: - Refactor build scripts.`
