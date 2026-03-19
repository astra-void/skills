---
name: conventional-commits
description: Draft, rewrite, review, split, and optionally execute Conventional Commits using the Conventional Commits 1.0.0 specification. Use when Codex needs to propose or validate commit messages, split the current git diff by domain, print a commit plan, or safely run git add/git commit for each domain group.
---

# Conventional Commits

Use this skill for both message-only requests and domain-based auto-commit requests.

Read [references/spec.md](references/spec.md) when you need the rule summary, exact breaking-change behavior, or canonical examples.

## Workflow

1. Inspect the real change set.
   For repository-backed tasks, start with `scripts/plan_domain_commits.py --repo <cwd> --format json`.
   Use the staged diff, full diff, or a user-provided summary only when a real git worktree is unavailable.

2. Enforce safety gates before automatic commit execution.
   Stop if `has_staged_changes` is true.
   Stop if `has_partial_staging` is true.
   Do not try to preserve or reconstruct the existing index.
   Explain the blocking condition and stop instead of guessing.
   Keep draft and review requests available even when the index is not clean.

3. Apply deterministic domain grouping.
   Use the helper script output as the source of truth.
   Treat each group as exactly one commit.
   Do not split hunks inside a file.
   Treat unmatched paths as a `misc` fallback group and mention the warning.

4. Draft one Conventional Commit subject per group.
   Read only the diff for that group before writing the subject.
   Choose the type before the summary.
   Add a scope only when it helps.
   Prefer the group scope hint when it is clean and specific.

5. Print a short commit plan before execution.
   If there are two or more groups, show one line per group with the domain key, category, dominant paths, and proposed subject.

6. Execute only when the user explicitly asks to commit or auto-commit.
   Sort groups by category order `ci`, `tooling`, `docs`, `package`, `app`, `test`, `misc`, then by `domain_key`.
   For each group, run:
   `git add -A -- <paths>`
   `git commit -m "<subject>"`
   Keep the default commit message to a subject line only.

7. Handle breaking changes explicitly.
   Add `!` only when the group breaks public behavior or API compatibility.
   Add a `BREAKING CHANGE:` footer only when the migration note is necessary and obvious from the diff.

## Grouping Rules

- `packages/<name>/**` -> domain `<name>`, scope hint `<name>`, category `package`
- `apps/<name>/**` -> domain `<name>`, scope hint `<name>`, category `app`
- `.github/**` -> domain `ci`, scope hint `ci`, category `ci`
- Root tooling/config files such as `package.json`, lockfiles, `eslint.config.*`, `tsconfig.*`, `vite.config.*`, `vitest.config.*`, `jest.config.*` -> domain `tooling`, scope hint `tooling`, category `tooling`
- Root docs and `docs/**` -> domain `docs`, scope hint `docs`, category `docs`
- `tests/vitest/<name>/**` -> attach to `<name>` when `packages/<name>` or `apps/<name>` exists, otherwise group under domain `test`
- `apps/test-harness/src/tests/<name>/**` -> attach to `<name>` when `packages/<name>` or `apps/<name>` exists, otherwise group under domain `test`
- Any unmatched path -> domain `misc`, scope hint `misc`, category `misc`, plus a warning

## Message Policy

- Prefer the user-visible or consumer-visible effect over the implementation detail.
- Use lowercase commit types unless the repository clearly uses a different convention.
- Keep the subject concise, specific, and action-oriented.
- Avoid trailing periods in the subject unless the repository history clearly prefers them.
- Treat `feat` and `fix` as the only types with SemVer meaning by default.
- Keep the default output to the subject line only unless a breaking-change footer is required.
- When a repository uses Changesets, remind the user to add a changeset when public packages changed and release impact still needs to be recorded.

## Output Contract

- Draft from diff: return one best subject for one logical group.
- Review existing message: report whether it conforms, state the exact problem, and provide a corrected subject.
- Split recommendation without execution:
  1. print a short commit plan
  2. print one proposed Conventional Commit subject per group
- Auto-commit request:
  1. run `plan_domain_commits.py`
  2. stop on any safety gate
  3. print the commit plan when there is more than one group
  4. stage and commit each group in deterministic order
  5. report the created subjects in order

Use these response shapes:

- Draft from diff:
  `fix(radio-group): remove stale forceMount lint path`
- Draft with breaking change:
  `feat(core)!: drop deprecated theme token aliases`

  `BREAKING CHANGE: remove the deprecated aliases from the public theme API.`
- Review existing message:
  `Non-conforming: missing Conventional Commit type prefix.`
  `Suggested: ci: update GitHub Actions versions`
