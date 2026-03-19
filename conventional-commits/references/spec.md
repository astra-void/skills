# Conventional Commits 1.0.0 Summary

Use this file when you need the rule summary without reopening the public specification.

## Header Shape

Write commit subjects in this general form:

`<type>[optional scope][optional !]: <description>`

- `type` is required.
- `scope` is optional and should be a short noun in parentheses.
- `!` is optional and marks a breaking change.
- `description` is required and starts after the colon and space.

## Required Semantics

- Use `feat` for a new feature.
- Use `fix` for a bug fix.
- Use `!` or a `BREAKING CHANGE:` footer for incompatible changes.
- If you use `BREAKING CHANGE`, keep it uppercase.

## Body And Footers

- Add a body after one blank line when extra context helps.
- Add footers after one blank line.
- Footers use a token plus a separator, such as `Refs: #123`.
- Footer tokens normally replace spaces with hyphens.
- `BREAKING CHANGE` is the special exception that may contain a space.

## Other Types

The spec allows types beyond `feat` and `fix`. Common examples used by tooling and teams include:

- `docs`
- `refactor`
- `perf`
- `test`
- `build`
- `ci`
- `chore`
- `style`
- `revert`

These extra types do not imply SemVer behavior on their own.

## Breaking Change Guidance

Use `!` when the commit itself should immediately signal incompatibility.

Add a `BREAKING CHANGE:` footer when you need to explain the migration impact, for example:

`feat(api)!: remove legacy token endpoints`

`BREAKING CHANGE: clients must use the v2 token endpoints instead.`

## Monorepo Scope Guidance

In a monorepo, prefer scopes that help readers find the affected area quickly:

- package name: `feat(checkbox): add indeterminate icon slot`
- app or docs area: `docs(site): add installation guide`
- tooling area: `ci: cache pnpm store in workflow`

If the change spans many packages, omit the scope unless one area is clearly dominant.
