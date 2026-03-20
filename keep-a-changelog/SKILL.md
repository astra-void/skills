---
name: keep-a-changelog
description: Draft, review, split, and optionally update Keep a Changelog style CHANGELOG.md files using the Keep a Changelog 1.1.0 format. Use when Codex needs to inspect the current git diff, propose changelog bullets, validate changelog structure, group changes by domain, or safely update an Unreleased or release section in a repository changelog.
---

# Keep a Changelog

Use this skill for draft-only changelog requests, changelog review requests, and automatic `CHANGELOG.md` updates.

Read [references/spec.md](references/spec.md) when you need the rule summary, canonical section order, `YANKED` handling, or compare-link guidance.

## Workflow

1. Inspect the real repository state first.
   Start with `scripts/plan_changelog.py --repo <cwd> --format json`.
   Use a user-provided path only when the changelog is not the repository-root `CHANGELOG.md`.

2. Enforce safety gates before automatic writes.
   Stop if `has_partial_staging` is true.
   Stop if `has_merge_conflicts` is true.
   Stop if `structure.errors` is non-empty.
   Keep draft and review requests available even when execution is blocked.

3. Draft changelog bullets from grouped repo changes.
   Use the planner output as the source of truth for domains and warnings.
   Read only the diff for one group before drafting bullets for that group.
   Choose one Keep a Changelog category per bullet unless the diff clearly spans multiple user-visible changes.
   Keep all generated prose in English.

4. Review changelog files against the format.
   Check for `## [Unreleased]`.
   Check level-2 version headings for `YYYY-MM-DD` dates.
   Check level-3 category headings against the canonical set.
   Report exact structural problems before suggesting rewritten text.

5. Execute changelog writes only when the user explicitly asks for an update.
   For unreleased updates, build a payload and run:
   `scripts/apply_changelog.py --repo <cwd> --mode unreleased --payload <file-or->`
   For release updates, include `version` and `date` in the payload and run:
   `scripts/apply_changelog.py --repo <cwd> --mode release --payload <file-or->`

6. Handle compare links conservatively.
   Update footer links only when the planner reports compare-link support from existing footer refs or a safe GitHub tag pattern.
   If link generation is ambiguous, leave the footer unchanged and report the warning instead of guessing.

7. Keep Changesets out of scope for writes.
   Mention `.changeset` only as adjacent release metadata when the repository uses it.
   Do not create or edit changeset files.

## Grouping Rules

- `packages/<name>/**` -> domain `<name>`, category `package`
- `apps/<name>/**` -> domain `<name>`, category `app`
- `.github/**` -> domain `ci`, category `ci`
- Root tooling/config files such as `package.json`, lockfiles, `eslint.config.*`, `tsconfig.*`, `vite.config.*`, `vitest.config.*`, `jest.config.*` -> domain `tooling`, category `tooling`
- Root docs and `docs/**` -> domain `docs`, category `docs`
- `tests/vitest/<name>/**` -> attach to `<name>` when `packages/<name>` or `apps/<name>` exists, otherwise group under `test`
- `apps/test-harness/src/tests/<name>/**` -> attach to `<name>` when `packages/<name>` or `apps/<name>` exists, otherwise group under `test`
- Any unmatched path -> domain `misc`, category `misc`, plus a warning

## Message Policy

- Prefer user-visible behavior over implementation detail.
- Keep bullets concise, specific, and action-oriented.
- Use one bullet per notable change unless the diff clearly contains two separate user-visible outcomes.
- Prefer these headings in canonical order: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.
- Mention `YANKED` only when the changelog already uses it or the user explicitly asks for it.
- Keep all skill output and generated changelog text in English.

## Output Contract

- Draft from diff:
  1. print a short grouped plan when more than one domain is involved
  2. print one or more proposed changelog bullets grouped under canonical headings
- Review existing changelog:
  1. report whether the file conforms
  2. list exact structural issues
  3. provide corrected headings or bullets only when useful
- Split recommendation without execution:
  1. print the planner summary
  2. print the proposed category-to-bullets payload
- Auto-update request:
  1. run `plan_changelog.py`
  2. stop on any safety gate
  3. draft the payload in canonical heading order
  4. run `apply_changelog.py`
  5. report the updated section and any skipped compare-link update

Use these response shapes:

- Draft from diff:
  `## [Unreleased]`
  `### Added`
  `- Add keyboard navigation for the menu trigger.`
- Review existing changelog:
  `Non-conforming: missing ## [Unreleased] section.`
  `Suggested heading: ## [1.4.0] - 2026-03-20`
