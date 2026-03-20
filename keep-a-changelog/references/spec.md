# Keep a Changelog 1.1.0 Summary

Use this reference when the request needs exact structure, heading names, date formatting, or footer-link behavior.

## Core Structure

- Start with a human-readable title, usually `# Changelog`.
- Keep a top `## [Unreleased]` section.
- List released versions in reverse chronological order below `Unreleased`.
- Format release headings as `## [<version>] - YYYY-MM-DD`.
- Add ` [YANKED]` to a release heading only when the release was withdrawn.

## Canonical Change Headings

Use level-3 headings in this order:

1. `### Added`
2. `### Changed`
3. `### Deprecated`
4. `### Removed`
5. `### Fixed`
6. `### Security`

Use only the headings that are needed for the current section. Do not invent alternative names such as `Bug Fixes`, `Breaking`, or `Improvements`.

## Writing Guidance

- Write for humans, not commit tooling.
- Summarize notable changes, not every internal edit.
- Prefer concise bullets that describe the user-visible result.
- Keep the file in English for this skill.

## Compare Links

- Footer links are optional but common.
- Reuse existing footer-reference style when the file already has it.
- Update compare links only when the repository URL and tag pattern are safely derivable.
- If the tag pattern is ambiguous, keep the footer unchanged and report the omission.

## Safe Normalization Rules For This Skill

The writer script may create or repair these cases automatically:

- Missing root `CHANGELOG.md`
- Missing `## [Unreleased]`
- Missing canonical level-3 headings in the target section
- Missing footer links when the compare strategy is safely derivable

The writer script must stop instead of guessing when it sees:

- Duplicate `Unreleased` sections
- Duplicate version headings
- Unknown level-3 category headings inside a section it needs to rewrite
- Invalid release date formats on version headings
- Merge conflicts or partial staging in the repo state
