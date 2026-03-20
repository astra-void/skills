#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

STANDARD_CATEGORIES = (
    "Added",
    "Changed",
    "Deprecated",
    "Removed",
    "Fixed",
    "Security",
)

CATEGORY_ORDER = {
    "ci": 0,
    "tooling": 1,
    "docs": 2,
    "package": 3,
    "app": 4,
    "area": 5,
    "test": 6,
    "misc": 7,
}

LOW_NOTABILITY_CATEGORIES = {"ci", "tooling", "test"}
MEDIUM_NOTABILITY_CATEGORIES = {"docs", "area", "misc"}
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
    "Makefile",
    "Dockerfile",
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
ROOT_DOC_FILENAMES = {"README", "CHANGELOG", "LICENSE", "CONTRIBUTING"}
ROOT_DOC_SUFFIXES = {".md", ".mdx", ".rst", ".txt"}
GENERIC_DOC_DIRS = {"docs", "doc", "documentation"}
GENERIC_TEST_DIRS = {"tests", "test", "spec", "specs"}
GENERIC_PACKAGE_DIRS = {"packages", "package", "libs", "lib", "modules", "crates", "components", "plugins"}
GENERIC_APP_DIRS = {"apps", "app", "examples", "example", "demos", "demo", "sites", "site"}
LOW_SIGNAL_BULLET_PATTERNS = (
    "refactor",
    "internal",
    "cleanup",
    "clean up",
    "lint",
    "format",
    "test only",
    "ci",
    "tooling",
    "rename",
    "reorganize",
    "reorganise",
    "chore",
)
LOW_SIGNAL_DOC_PATTERNS = (
    "readme",
    "docs",
    "documentation",
    "comment",
)

SECTION_RE = re.compile(
    r"^## \[(?P<title>[^\]]+)\](?: - (?P<date>\d{4}-\d{2}-\d{2}))?(?P<yanked> \[YANKED\])?$"
)
CATEGORY_RE = re.compile(r"^### (?P<name>.+?)\s*$")
LINK_RE = re.compile(r"^\[(?P<label>[^\]]+)\]:\s*(?P<url>\S+)\s*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GITHUB_HTTPS_RE = re.compile(r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$")
GITHUB_SSH_RE = re.compile(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$")
COMPARE_RE = re.compile(
    r"^(?P<base>https://github\.com/[^/]+/[^/]+/compare)/(?P<left>[^.]+)\.\.\.(?P<right>\S+)$"
)


class PlannerError(RuntimeError):
    pass


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
    notability: str
    default_include: bool
    paths: set[str] = field(default_factory=set)
    reasons: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, object]:
        return {
            "domain_key": self.domain_key,
            "scope_hint": self.scope_hint,
            "category": self.category,
            "notability": self.notability,
            "default_include": self.default_include,
            "paths": sorted(self.paths),
            "reason": "; ".join(sorted(self.reasons)),
        }


@dataclass
class Section:
    title: str
    date: str | None
    yanked: bool
    heading_line: str
    body_lines: list[str]
    intro_lines: list[str] = field(default_factory=list)
    categories: OrderedDict[str, list[str]] = field(default_factory=OrderedDict)
    modified: bool = False

    def summary(self) -> dict[str, object]:
        return {
            "title": self.title,
            "date": self.date,
            "yanked": self.yanked,
            "categories": list(self.categories.keys()),
        }


@dataclass
class ChangelogDocument:
    preamble_lines: list[str]
    sections: list[Section]
    footer_links: OrderedDict[str, str]
    errors: list[str]
    warnings: list[str]

    def get_section(self, title: str) -> Section | None:
        for section in self.sections:
            if section.title == title:
                return section
        return None

    def to_summary(self) -> dict[str, object]:
        version_sections = [section.title for section in self.sections if section.title != "Unreleased"]
        return {
            "has_unreleased": self.get_section("Unreleased") is not None,
            "section_count": len(self.sections),
            "version_sections": version_sections,
            "footer_link_labels": list(self.footer_links.keys()),
            "errors": self.errors,
            "warnings": self.warnings,
            "sections": [section.summary() for section in self.sections],
        }


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


def classify_path_lattice(
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


def classify_path_generic(path: str) -> tuple[str, str, str, str]:
    parts = Path(path).parts
    if not parts:
        return "misc", "misc", "misc", "fallback group for unmatched paths"

    top = parts[0]
    name = Path(path).name.lower()

    if top == ".github":
        return "ci", "ci", "ci", "CI workflow and automation paths"

    if len(parts) == 1:
        if is_root_tooling_file(path):
            return "tooling", "tooling", "tooling", "root tooling and config files"
        if is_root_doc_file(path):
            return "docs", "docs", "docs", "root documentation files"

    if top.lower() in GENERIC_DOC_DIRS:
        return "docs", "docs", "docs", f"paths under {top}/"

    if top.lower() in GENERIC_TEST_DIRS or "__tests__" in parts or name.endswith(".spec.ts") or name.endswith(".test.ts"):
        return "test", "test", "test", f"paths under test-oriented tree {top}"

    if top.lower() in GENERIC_PACKAGE_DIRS and len(parts) >= 2:
        return parts[1], parts[1], "package", f"paths under {top}/{parts[1]}"

    if top.lower() in GENERIC_APP_DIRS and len(parts) >= 2:
        return parts[1], parts[1], "app", f"paths under {top}/{parts[1]}"

    if top.startswith("."):
        return "misc", "misc", "misc", f"fallback group for hidden path {path}"

    if len(parts) >= 2:
        return top, top, "area", f"paths under {top}/"

    return "misc", "misc", "misc", f"fallback group for unmatched path {path}"


def classify_path(
    profile: str,
    path: str,
    package_names: set[str],
    app_names: set[str],
) -> tuple[str, str, str, str]:
    if profile == "lattice":
        return classify_path_lattice(path, package_names, app_names)
    return classify_path_generic(path)


def compute_notability(category: str) -> tuple[str, bool]:
    if category in LOW_NOTABILITY_CATEGORIES:
        return "low", False
    if category in MEDIUM_NOTABILITY_CATEGORIES:
        return "medium", category == "area"
    return "high", True


def split_footer_links(lines: list[str]) -> tuple[list[str], OrderedDict[str, str]]:
    if not lines:
        return lines, OrderedDict()

    index = len(lines)
    while index > 0 and not lines[index - 1].strip():
        index -= 1

    start = index
    saw_link = False
    while start > 0:
        line = lines[start - 1]
        if not line.strip():
            start -= 1
            continue
        if LINK_RE.match(line):
            saw_link = True
            start -= 1
            continue
        break

    candidate = lines[start:index]
    if not saw_link:
        return lines, OrderedDict()

    footer_links: OrderedDict[str, str] = OrderedDict()
    for line in candidate:
        if not line.strip():
            continue
        match = LINK_RE.match(line)
        if not match:
            return lines, OrderedDict()
        footer_links[match.group("label")] = match.group("url")

    kept = lines[:start]
    while kept and not kept[-1].strip():
        kept.pop()
    return kept, footer_links


def parse_section_body(section: Section, errors: list[str]) -> None:
    current_category: str | None = None
    intro_lines: list[str] = []
    categories: OrderedDict[str, list[str]] = OrderedDict()

    for line in section.body_lines:
        category_match = CATEGORY_RE.match(line)
        if category_match:
            category_name = category_match.group("name")
            if category_name not in STANDARD_CATEGORIES:
                errors.append(f"Unsupported category heading in [{section.title}]: {category_name}")
            if category_name in categories:
                errors.append(f"Duplicate category heading in [{section.title}]: {category_name}")
            categories.setdefault(category_name, [])
            current_category = category_name
            continue

        if current_category is None:
            intro_lines.append(line)
        else:
            categories[current_category].append(line)

    section.intro_lines = intro_lines
    section.categories = categories


def normalize_bullet_text(line: str) -> str:
    text = line.strip()
    if text.startswith("- "):
        text = text[2:]
    return " ".join(text.lower().split())


def is_blank_lines(lines: list[str]) -> bool:
    return not any(line.strip() for line in lines)


def analyze_bullet_quality(section: Section, category: str, line: str) -> list[str]:
    bullet = normalize_bullet_text(line)
    if not bullet:
        return []

    warnings: list[str] = []
    if any(token in bullet for token in LOW_SIGNAL_BULLET_PATTERNS):
        warnings.append(
            f"[{section.title}] bullet under {category} looks internal or low-signal: {line.strip()}"
        )
    if any(token in bullet for token in LOW_SIGNAL_DOC_PATTERNS) and category != "Security":
        warnings.append(
            f"[{section.title}] bullet under {category} may document docs-only work: {line.strip()}"
        )
    if len(bullet.split()) <= 3:
        warnings.append(f"[{section.title}] bullet under {category} is too terse to explain user impact: {line.strip()}")
    return warnings


def collect_quality_warnings(document: ChangelogDocument) -> list[str]:
    warnings: list[str] = []

    for section in document.sections:
        has_intro = not is_blank_lines(section.intro_lines)
        non_empty_categories = 0
        seen_bullets: Counter[str] = Counter()

        for category, items in section.categories.items():
            bullet_lines = [item for item in items if item.strip()]
            if not bullet_lines:
                warnings.append(f"[{section.title}] category {category} is empty.")
                continue

            non_empty_categories += 1
            for line in bullet_lines:
                normalized = normalize_bullet_text(line)
                if normalized:
                    seen_bullets[normalized] += 1
                warnings.extend(analyze_bullet_quality(section, category, line))

        for bullet, count in seen_bullets.items():
            if count > 1:
                warnings.append(f"[{section.title}] contains duplicate bullet text: {bullet}")

        if section.title == "Unreleased":
            if not has_intro and non_empty_categories == 0:
                warnings.append("[Unreleased] is empty.")
        else:
            if not has_intro and non_empty_categories == 0:
                warnings.append(f"[{section.title}] is an empty release section.")

    return warnings


def parse_changelog_document(text: str) -> ChangelogDocument:
    lines = text.splitlines()
    section_indices: list[int] = []
    for index, line in enumerate(lines):
        if line.startswith("## "):
            section_indices.append(index)

    if not section_indices:
        return ChangelogDocument(
            preamble_lines=lines,
            sections=[],
            footer_links=OrderedDict(),
            errors=[],
            warnings=[],
        )

    preamble_lines = lines[: section_indices[0]]
    sections: list[Section] = []
    errors: list[str] = []
    warnings: list[str] = []
    seen_titles: set[str] = set()

    for idx, start in enumerate(section_indices):
        end = section_indices[idx + 1] if idx + 1 < len(section_indices) else len(lines)
        heading_line = lines[start]
        body_lines = lines[start + 1 : end]
        match = SECTION_RE.match(heading_line)
        if not match:
            errors.append(f"Unsupported level-2 heading: {heading_line}")
            title = heading_line.removeprefix("## ").strip()
            section = Section(title=title, date=None, yanked=False, heading_line=heading_line, body_lines=body_lines)
            sections.append(section)
            continue

        title = match.group("title")
        date = match.group("date")
        yanked = bool(match.group("yanked"))

        if title == "Unreleased" and date:
            errors.append("Unreleased heading must not contain a release date.")
        if title != "Unreleased" and not date:
            errors.append(f"Release heading [{title}] is missing a YYYY-MM-DD date.")
        if date and not DATE_RE.match(date):
            errors.append(f"Release heading [{title}] has an invalid date: {date}")
        if title in seen_titles:
            errors.append(f"Duplicate changelog section: [{title}]")
        seen_titles.add(title)

        section = Section(
            title=title,
            date=date,
            yanked=yanked,
            heading_line=heading_line,
            body_lines=body_lines,
        )
        parse_section_body(section, errors)
        sections.append(section)

    if sections:
        last_body, footer_links = split_footer_links(sections[-1].body_lines)
        if footer_links:
            sections[-1].body_lines = last_body
            sections[-1].intro_lines = []
            sections[-1].categories = OrderedDict()
            parse_section_body(sections[-1], errors)
        else:
            footer_links = OrderedDict()
    else:
        footer_links = OrderedDict()

    version_dates = [
        (section.title, section.date)
        for section in sections
        if section.title != "Unreleased" and section.date is not None
    ]
    for index in range(len(version_dates) - 1):
        current_title, current_date = version_dates[index]
        next_title, next_date = version_dates[index + 1]
        if current_date < next_date:
            warnings.append(
                f"Release sections are not in reverse chronological order: [{current_title}] precedes [{next_title}]."
            )

    if not any(section.title == "Unreleased" for section in sections):
        warnings.append("Missing [Unreleased] section.")

    return ChangelogDocument(
        preamble_lines=preamble_lines,
        sections=sections,
        footer_links=footer_links,
        errors=errors,
        warnings=warnings,
    )


def render_section(section: Section) -> list[str]:
    if not section.modified:
        return [section.heading_line, *section.body_lines]

    heading = f"## [{section.title}]"
    if section.title != "Unreleased" and section.date:
        heading += f" - {section.date}"
    if section.yanked:
        heading += " [YANKED]"

    lines = [heading]
    body: list[str] = list(section.intro_lines)
    while body and not body[-1].strip():
        body.pop()

    category_lines: list[str] = []
    for category in STANDARD_CATEGORIES:
        items = section.categories.get(category)
        if not items:
            continue
        content = [item for item in items if item.strip()]
        if not content:
            continue
        if category_lines:
            category_lines.append("")
        category_lines.append(f"### {category}")
        category_lines.extend(content)

    if body:
        lines.append("")
        lines.extend(body)
    if category_lines:
        lines.append("")
        lines.extend(category_lines)
    return lines


def render_changelog_document(document: ChangelogDocument) -> str:
    lines: list[str] = list(document.preamble_lines)
    while lines and not lines[-1].strip():
        lines.pop()

    for section in document.sections:
        if lines:
            lines.append("")
        lines.extend(render_section(section))

    if document.footer_links:
        if lines:
            lines.append("")
        for label, url in document.footer_links.items():
            lines.append(f"[{label}]: {url}")

    return "\n".join(lines).rstrip() + "\n"


def github_repo_url_from_remote(remote: str | None) -> str | None:
    if not remote:
        return None
    remote = remote.strip()
    for regex in (GITHUB_HTTPS_RE, GITHUB_SSH_RE):
        match = regex.match(remote)
        if match:
            owner = match.group("owner")
            repo = match.group("repo")
            return f"https://github.com/{owner}/{repo}"
    return None


def get_origin_remote(repo: Path) -> str | None:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    remote = result.stdout.strip()
    return remote or None


def get_tags(repo: Path) -> list[str]:
    try:
        raw = run_git(repo, "tag", "--list")
    except PlannerError:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def infer_compare_links(repo: Path, document: ChangelogDocument) -> dict[str, object]:
    remote_url = github_repo_url_from_remote(get_origin_remote(repo))
    compare_base = f"{remote_url}/compare" if remote_url else None
    version_titles = [section.title for section in document.sections if section.title != "Unreleased"]

    footer_matches: list[tuple[str, str, str]] = []
    for label, url in document.footer_links.items():
        match = COMPARE_RE.match(url)
        if not match:
            continue
        footer_matches.append((label, match.group("left"), match.group("right")))

    if footer_matches:
        prefixes: set[str] = set()
        footer_base = COMPARE_RE.match(next(iter(document.footer_links.values()), ""))
        derived_compare_base = footer_base.group("base") if footer_base else compare_base
        consistent = True
        for label, _, right in footer_matches:
            if label == "Unreleased":
                continue
            if right == label:
                prefixes.add("")
            elif right == f"v{label}":
                prefixes.add("v")
            else:
                consistent = False
                break
        if consistent and len(prefixes) <= 1 and derived_compare_base:
            return {
                "feasible": True,
                "source": "footer_links",
                "compare_base_url": derived_compare_base,
                "tag_prefix": next(iter(prefixes), ""),
            }

    if not compare_base or not version_titles:
        return {
            "feasible": False,
            "source": "none",
            "compare_base_url": compare_base,
            "tag_prefix": None,
        }

    tags = set(get_tags(repo))
    empty_match = all(title in tags for title in version_titles)
    v_match = all(f"v{title}" in tags for title in version_titles)
    if empty_match == v_match:
        return {
            "feasible": False,
            "source": "none",
            "compare_base_url": compare_base,
            "tag_prefix": None,
        }

    return {
        "feasible": True,
        "source": "git_tags",
        "compare_base_url": compare_base,
        "tag_prefix": "" if empty_match else "v",
    }


def build_release_support(document: ChangelogDocument, compare_links: dict[str, object]) -> dict[str, object]:
    versions = [section.title for section in document.sections if section.title != "Unreleased"]
    return {
        "available_versions": versions,
        "has_unreleased": document.get_section("Unreleased") is not None,
        "can_release": document.get_section("Unreleased") is not None and not document.errors,
        "can_release_subset": document.get_section("Unreleased") is not None and not document.errors,
        "supports_yank": bool(versions),
        "compare_links": compare_links,
    }


def build_plan(
    repo: Path,
    changelog_arg: str | None = None,
    *,
    profile: str = "generic",
    strict_quality: bool = False,
) -> dict[str, object]:
    changelog_path = Path(changelog_arg or "CHANGELOG.md")
    if not changelog_path.is_absolute():
        changelog_path = repo / changelog_path
    changelog_rel = changelog_path.relative_to(repo)

    entries = parse_status_entries(repo)
    package_names = known_package_names(repo)
    app_names = known_app_names(repo)

    has_staged_changes = any(entry.index_status not in {" ", "?", "!"} for entry in entries)
    has_partial_staging = any(
        entry.index_status not in {" ", "?", "!"} and entry.worktree_status not in {" ", "?", "!"}
        for entry in entries
    )
    has_merge_conflicts = any("U" in {entry.index_status, entry.worktree_status} for entry in entries)

    groups_by_key: dict[tuple[str, str], Group] = {}
    warnings: set[str] = set()
    changelog_modified = False

    for entry in entries:
        if entry.index_status == "!" and entry.worktree_status == "!":
            continue

        if "U" in {entry.index_status, entry.worktree_status}:
            warnings.add("Merge-conflict entries detected; resolve conflicts before auto-updating the changelog.")

        path_set = set(entry.pathspecs)
        if str(changelog_rel) in path_set:
            changelog_modified = True
            continue

        domain_key, scope_hint, category, reason = classify_path(profile, entry.path, package_names, app_names)
        notability, default_include = compute_notability(category)
        key = (category, domain_key)
        group = groups_by_key.setdefault(
            key,
            Group(
                domain_key=domain_key,
                scope_hint=scope_hint,
                category=category,
                notability=notability,
                default_include=default_include,
            ),
        )
        group.paths.update(path_set)
        group.reasons.add(reason)

        if category == "misc":
            warnings.add(f"Unmatched path grouped under misc: {entry.path}")

    if changelog_modified:
        warnings.add(f"{changelog_rel} is already modified and was excluded from diff grouping.")

    if changelog_path.exists():
        changelog_text = changelog_path.read_text()
        document = parse_changelog_document(changelog_text)
    else:
        document = ChangelogDocument([], [], OrderedDict(), [], ["Missing [Unreleased] section."])

    compare_links = infer_compare_links(repo, document)
    quality_warnings = sorted(set(collect_quality_warnings(document)))
    groups = [group.to_dict() for group in groups_by_key.values()]
    groups.sort(key=lambda group: (CATEGORY_ORDER.get(str(group["category"]), 99), str(group["domain_key"])))
    warnings.update(document.warnings)

    return {
        "repo_root": str(repo),
        "profile": profile,
        "strict_quality": strict_quality,
        "changelog_path": str(changelog_path),
        "changelog_exists": changelog_path.exists(),
        "has_staged_changes": has_staged_changes,
        "has_partial_staging": has_partial_staging,
        "has_merge_conflicts": has_merge_conflicts,
        "groups": groups,
        "warnings": sorted(warnings),
        "quality_warnings": quality_warnings,
        "quality_blocking": bool(strict_quality and quality_warnings),
        "structure": document.to_summary(),
        "compare_links": compare_links,
        "release_support": build_release_support(document, compare_links),
    }


def format_text(plan: dict[str, object]) -> str:
    lines = [
        f"repo_root: {plan['repo_root']}",
        f"profile: {plan['profile']}",
        f"strict_quality: {str(plan['strict_quality']).lower()}",
        f"changelog_path: {plan['changelog_path']}",
        f"changelog_exists: {str(plan['changelog_exists']).lower()}",
        f"has_staged_changes: {str(plan['has_staged_changes']).lower()}",
        f"has_partial_staging: {str(plan['has_partial_staging']).lower()}",
        f"has_merge_conflicts: {str(plan['has_merge_conflicts']).lower()}",
        "warnings:",
    ]

    warnings = plan["warnings"]
    if warnings:
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- none")

    quality_warnings = plan["quality_warnings"]
    lines.append("quality_warnings:")
    if quality_warnings:
        for warning in quality_warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- none")
    lines.append(f"quality_blocking: {str(plan['quality_blocking']).lower()}")

    structure = plan["structure"]
    lines.extend(
        [
            "structure:",
            f"- has_unreleased: {str(structure['has_unreleased']).lower()}",
            f"- version_sections: {', '.join(structure['version_sections']) or 'none'}",
            f"- footer_link_labels: {', '.join(structure['footer_link_labels']) or 'none'}",
        ]
    )
    if structure["errors"]:
        lines.append("- errors:")
        for error in structure["errors"]:
            lines.append(f"  - {error}")
    else:
        lines.append("- errors: none")

    compare_links = plan["compare_links"]
    lines.extend(
        [
            "compare_links:",
            f"- feasible: {str(compare_links['feasible']).lower()}",
            f"- source: {compare_links['source']}",
            f"- compare_base_url: {compare_links['compare_base_url'] or 'none'}",
            f"- tag_prefix: {compare_links['tag_prefix'] if compare_links['tag_prefix'] is not None else 'none'}",
        ]
    )

    release_support = plan["release_support"]
    lines.extend(
        [
            "release_support:",
            f"- available_versions: {', '.join(release_support['available_versions']) or 'none'}",
            f"- has_unreleased: {str(release_support['has_unreleased']).lower()}",
            f"- can_release: {str(release_support['can_release']).lower()}",
            f"- can_release_subset: {str(release_support['can_release_subset']).lower()}",
            f"- supports_yank: {str(release_support['supports_yank']).lower()}",
            "groups:",
        ]
    )

    groups = plan["groups"]
    if not groups:
        lines.append("- none")
        return "\n".join(lines)

    for group in groups:
        lines.append(
            f"- {group['category']} {group['domain_key']} ({group['scope_hint']}): "
            f"notability={group['notability']} default_include={str(group['default_include']).lower()} "
            f"{group['reason']}"
        )
        for path in group["paths"]:
            lines.append(f"  - {path}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan Keep a Changelog updates from the current git state.")
    parser.add_argument("--repo", help="Repository root or any path inside the repository.")
    parser.add_argument("--changelog", help="Relative or absolute path to the changelog file.")
    parser.add_argument("--profile", choices=("generic", "lattice"), default="generic")
    parser.add_argument("--strict-quality", action="store_true")
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="Output format.",
    )
    args = parser.parse_args()

    try:
        repo = resolve_repo(args.repo)
        plan = build_plan(
            repo,
            args.changelog,
            profile=args.profile,
            strict_quality=args.strict_quality,
        )
    except PlannerError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(plan, indent=2))
    else:
        print(format_text(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
