#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

CATEGORY_ORDER = {
    "ci": 0,
    "tooling": 1,
    "docs": 2,
    "package": 3,
    "app": 4,
    "test": 5,
    "misc": 6,
}

ROOT_TOOLING_FILES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "turbo.json",
    "nx.json",
    "lerna.json",
    "biome.json",
    "biome.jsonc",
}

ROOT_TOOLING_PREFIXES = (
    "tsconfig.",
    "eslint.config.",
    "prettier.config.",
    "vitest.config.",
    "jest.config.",
    "vite.config.",
    "rollup.config.",
    "webpack.config.",
    "babel.config.",
    "commitlint.config.",
)

ROOT_TOOLING_DOTFILE_PREFIXES = (
    ".eslintrc",
    ".prettierrc",
    ".editorconfig",
    ".gitignore",
    ".gitattributes",
    ".gitmodules",
    ".npmrc",
    ".nvmrc",
    ".yarnrc",
)

ROOT_DOC_FILENAMES = {
    "README",
    "CHANGELOG",
    "LICENSE",
    "CONTRIBUTING",
}

ROOT_DOC_SUFFIXES = {
    ".md",
    ".mdx",
    ".rst",
    ".txt",
}


@dataclass(frozen=True)
class StatusEntry:
    index_status: str
    worktree_status: str
    path: str
    pathspecs: tuple[str, ...]


@dataclass
class Group:
    domain_key: str
    scope_hint: str
    category: str
    paths: set[str] = field(default_factory=set)
    reasons: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, object]:
        return {
            "domain_key": self.domain_key,
            "scope_hint": self.scope_hint,
            "category": self.category,
            "paths": sorted(self.paths),
            "reason": "; ".join(sorted(self.reasons)),
        }


class PlannerError(RuntimeError):
    pass


def run_git(repo: Path, *args: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=text,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if text else result.stderr.decode(errors="replace").strip()
        raise PlannerError(f"git {' '.join(args)} failed: {stderr}")
    return result.stdout


def resolve_repo(path_arg: str | None) -> Path:
    repo = Path(path_arg or Path.cwd()).resolve()
    if repo.is_file():
        repo = repo.parent
    top_level = run_git(repo, "rev-parse", "--show-toplevel").strip()
    return Path(top_level)


def parse_status_entries(repo: Path) -> list[StatusEntry]:
    raw = run_git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", text=False)
    chunks = raw.split(b"\0")
    entries: list[StatusEntry] = []
    index = 0

    while index < len(chunks):
        chunk = chunks[index]
        index += 1
        if not chunk:
            continue
        if len(chunk) < 3:
            raise PlannerError("unexpected porcelain entry")

        index_status = chr(chunk[0])
        worktree_status = chr(chunk[1])
        path = os.fsdecode(chunk[3:])
        pathspecs = [path]

        if index_status in {"R", "C"} or worktree_status in {"R", "C"}:
            if index >= len(chunks):
                raise PlannerError("rename/copy entry missing source path")
            source_chunk = chunks[index]
            index += 1
            if source_chunk:
                source_path = os.fsdecode(source_chunk)
                pathspecs = [source_path, path]

        entries.append(
            StatusEntry(
                index_status=index_status,
                worktree_status=worktree_status,
                path=path,
                pathspecs=tuple(pathspecs),
            )
        )

    return entries


def is_root_tooling_file(path: str) -> bool:
    name = Path(path).name
    return (
        name in ROOT_TOOLING_FILES
        or name.startswith(ROOT_TOOLING_PREFIXES)
        or name.startswith(ROOT_TOOLING_DOTFILE_PREFIXES)
    )


def is_root_doc_file(path: str) -> bool:
    file_path = Path(path)
    stem = file_path.stem.upper()
    suffix = file_path.suffix.lower()
    return stem in ROOT_DOC_FILENAMES or suffix in ROOT_DOC_SUFFIXES


def known_package_names(repo: Path) -> set[str]:
    packages_dir = repo / "packages"
    if not packages_dir.is_dir():
        return set()
    return {child.name for child in packages_dir.iterdir() if child.is_dir()}


def known_app_names(repo: Path) -> set[str]:
    apps_dir = repo / "apps"
    if not apps_dir.is_dir():
        return set()
    return {child.name for child in apps_dir.iterdir() if child.is_dir()}


def classify_test_domain(
    test_name: str,
    package_names: set[str],
    app_names: set[str],
    source_reason: str,
) -> tuple[str, str, str, str]:
    if test_name in package_names:
        return test_name, test_name, "package", f"{source_reason} attached to packages/{test_name}"
    if test_name in app_names:
        return test_name, test_name, "app", f"{source_reason} attached to apps/{test_name}"
    return "test", "test", "test", f"{source_reason} without a matching package or app"


def classify_path(
    repo: Path,
    path: str,
    package_names: set[str],
    app_names: set[str],
) -> tuple[str, str, str, str]:
    parts = Path(path).parts
    if not parts:
        return "misc", "misc", "misc", "fallback group for unmatched paths"

    top = parts[0]

    if top == "packages" and len(parts) >= 2:
        name = parts[1]
        return name, name, "package", f"paths under packages/{name}"

    if top == "apps" and len(parts) >= 2:
        if len(parts) >= 5 and parts[1] == "test-harness" and parts[2] == "src" and parts[3] == "tests":
            return classify_test_domain(parts[4], package_names, app_names, "test-harness paths")
        name = parts[1]
        return name, name, "app", f"paths under apps/{name}"

    if top == ".github":
        return "ci", "ci", "ci", "CI workflow and automation paths"

    if top == "docs":
        return "docs", "docs", "docs", "paths under docs/"

    if top == "tests" and len(parts) >= 3 and parts[1] == "vitest":
        return classify_test_domain(parts[2], package_names, app_names, "vitest paths")

    if len(parts) == 1:
        if is_root_tooling_file(path):
            return "tooling", "tooling", "tooling", "root tooling and config files"
        if is_root_doc_file(path):
            return "docs", "docs", "docs", "root documentation files"

    return "misc", "misc", "misc", f"fallback group for unmatched path {path}"


def build_plan(repo: Path) -> dict[str, object]:
    entries = parse_status_entries(repo)
    package_names = known_package_names(repo)
    app_names = known_app_names(repo)

    has_staged_changes = any(entry.index_status not in {" ", "?", "!"} for entry in entries)
    has_partial_staging = any(
        entry.index_status not in {" ", "?", "!"} and entry.worktree_status not in {" ", "?", "!"}
        for entry in entries
    )

    groups_by_key: dict[tuple[str, str], Group] = {}
    warnings: set[str] = set()

    for entry in entries:
        if entry.index_status == "!" and entry.worktree_status == "!":
            continue

        if "U" in {entry.index_status, entry.worktree_status}:
            warnings.add("Merge-conflict entries detected; resolve conflicts before auto-committing.")

        domain_key, scope_hint, category, reason = classify_path(repo, entry.path, package_names, app_names)
        key = (category, domain_key)
        group = groups_by_key.setdefault(
            key,
            Group(domain_key=domain_key, scope_hint=scope_hint, category=category),
        )
        group.paths.update(entry.pathspecs)
        group.reasons.add(reason)

        if category == "misc":
            warnings.add(f"Unmatched path grouped under misc: {entry.path}")

    groups = [group.to_dict() for group in groups_by_key.values()]
    groups.sort(key=lambda group: (CATEGORY_ORDER.get(str(group["category"]), 99), str(group["domain_key"])))

    return {
        "repo_root": str(repo),
        "has_staged_changes": has_staged_changes,
        "has_partial_staging": has_partial_staging,
        "groups": groups,
        "warnings": sorted(warnings),
    }


def format_text(plan: dict[str, object]) -> str:
    lines = [
        f"repo_root: {plan['repo_root']}",
        f"has_staged_changes: {str(plan['has_staged_changes']).lower()}",
        f"has_partial_staging: {str(plan['has_partial_staging']).lower()}",
        "warnings:",
    ]

    warnings = plan["warnings"]
    if warnings:
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- none")

    lines.append("groups:")
    groups = plan["groups"]
    if not groups:
        lines.append("- none")
        return "\n".join(lines)

    for group in groups:
        lines.append(
            f"- {group['category']} {group['domain_key']} ({group['scope_hint']}): {group['reason']}"
        )
        for path in group["paths"]:
            lines.append(f"  - {path}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan domain-based Conventional Commit groups from the current git worktree.")
    parser.add_argument("--repo", help="Path to the target repository. Defaults to the current working directory.")
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format. Defaults to json.",
    )
    args = parser.parse_args()

    try:
        repo = resolve_repo(args.repo)
        plan = build_plan(repo)
    except PlannerError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(plan, indent=2, sort_keys=False))
    else:
        print(format_text(plan))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
