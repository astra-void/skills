#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from pathlib import Path

from plan_changelog import (
    ChangelogDocument,
    DATE_RE,
    PlannerError,
    Section,
    STANDARD_CATEGORIES,
    build_plan,
    parse_changelog_document,
    render_changelog_document,
    resolve_repo,
)


def read_payload(payload_arg: str) -> dict[str, object]:
    if payload_arg == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(payload_arg).read_text()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlannerError(f"Invalid payload JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise PlannerError("Payload must be a JSON object.")
    return payload


def normalize_categories(payload: dict[str, object]) -> OrderedDict[str, list[str]]:
    categories = OrderedDict()

    raw_categories = payload.get("categories")
    raw_entries = payload.get("entries")
    if raw_categories is None and raw_entries is None:
        raise PlannerError("Payload must contain either 'categories' or 'entries'.")

    if raw_categories is not None:
        if not isinstance(raw_categories, dict):
            raise PlannerError("'categories' must be a JSON object mapping headings to item lists.")
        source_items = raw_categories.items()
    else:
        if not isinstance(raw_entries, list):
            raise PlannerError("'entries' must be a JSON array.")
        source_items = []
        for entry in raw_entries:
            if not isinstance(entry, dict):
                raise PlannerError("Each entry in 'entries' must be a JSON object.")
            category = entry.get("category")
            items = entry.get("items")
            source_items.append((category, items))

    for category, raw_items in source_items:
        if category not in STANDARD_CATEGORIES:
            raise PlannerError(f"Unsupported changelog category: {category}")
        if not isinstance(raw_items, list):
            raise PlannerError(f"Category '{category}' must map to a list of strings.")

        normalized_items = categories.setdefault(category, [])
        for item in raw_items:
            if not isinstance(item, str):
                raise PlannerError(f"Category '{category}' contains a non-string item.")
            text = item.strip()
            if not text:
                continue
            if text.startswith("- "):
                normalized_items.append(text)
            else:
                normalized_items.append(f"- {text}")

    if not any(categories.values()):
        raise PlannerError("Payload does not contain any changelog items.")

    ordered = OrderedDict()
    for category in STANDARD_CATEGORIES:
        items = categories.get(category)
        if items:
            ordered[category] = items
    return ordered


def default_preamble() -> list[str]:
    return [
        "# Changelog",
        "",
        "All notable changes to this project will be documented in this file.",
        "",
        "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),",
        "and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).",
    ]


def ensure_document(text: str | None) -> ChangelogDocument:
    if text is None:
        return ChangelogDocument(
            preamble_lines=default_preamble(),
            sections=[],
            footer_links=OrderedDict(),
            errors=[],
            warnings=[],
        )
    return parse_changelog_document(text)


def ensure_unreleased_section(document: ChangelogDocument) -> Section:
    section = document.get_section("Unreleased")
    if section is not None:
        return section

    section = Section(
        title="Unreleased",
        date=None,
        yanked=False,
        heading_line="## [Unreleased]",
        body_lines=[],
        modified=True,
    )
    document.sections.insert(0, section)
    return section


def merge_categories(section: Section, additions: OrderedDict[str, list[str]]) -> None:
    for category in STANDARD_CATEGORIES:
        existing = section.categories.get(category)
        incoming = additions.get(category)
        if existing is None and incoming is None:
            continue
        if existing is None:
            section.categories[category] = list(incoming or [])
            continue
        if incoming:
            existing_items = list(existing)
            existing_items.extend(incoming)
            section.categories[category] = existing_items
    section.modified = True


def insert_empty_unreleased(document: ChangelogDocument) -> None:
    new_section = Section(
        title="Unreleased",
        date=None,
        yanked=False,
        heading_line="## [Unreleased]",
        body_lines=[],
        modified=True,
    )
    document.sections.insert(0, new_section)


def update_footer_links(document: ChangelogDocument, compare_links: dict[str, object], version: str) -> list[str]:
    warnings: list[str] = []
    if not compare_links.get("feasible"):
        warnings.append("Skipped compare-link update because the compare strategy is ambiguous.")
        return warnings

    compare_base_url = compare_links.get("compare_base_url")
    tag_prefix = compare_links.get("tag_prefix") or ""
    if not isinstance(compare_base_url, str) or not compare_base_url:
        warnings.append("Skipped compare-link update because the compare base URL is unavailable.")
        return warnings

    version_tag = f"{tag_prefix}{version}"
    previous_releases = [section.title for section in document.sections if section.title not in {"Unreleased", version}]
    previous_version = previous_releases[0] if previous_releases else None

    new_footer = OrderedDict(document.footer_links)
    new_footer["Unreleased"] = f"{compare_base_url}/{version_tag}...HEAD"
    if previous_version:
        previous_tag = f"{tag_prefix}{previous_version}"
        new_footer[version] = f"{compare_base_url}/{previous_tag}...{version_tag}"
    else:
        warnings.append("Skipped release compare link because there is no previous version section to compare against.")

    document.footer_links = new_footer
    return warnings


def write_changelog(
    repo: Path,
    changelog_path: Path,
    mode: str,
    payload: dict[str, object],
) -> tuple[Path, list[str]]:
    plan = build_plan(repo, str(changelog_path))
    if plan["has_partial_staging"]:
        raise PlannerError("Refusing to update changelog with partially staged changes present.")
    if plan["has_merge_conflicts"]:
        raise PlannerError("Refusing to update changelog while merge conflicts are present.")
    if plan["structure"]["errors"]:
        raise PlannerError("Refusing to update changelog with malformed structure:\n- " + "\n- ".join(plan["structure"]["errors"]))

    existing_text = changelog_path.read_text() if changelog_path.exists() else None
    document = ensure_document(existing_text)
    warnings: list[str] = []

    unreleased = ensure_unreleased_section(document)
    additions = normalize_categories(payload)
    merge_categories(unreleased, additions)

    if mode == "release":
        version = payload.get("version")
        date = payload.get("date")
        if not isinstance(version, str) or not version.strip():
            raise PlannerError("Release mode requires a non-empty 'version' in the payload.")
        if not isinstance(date, str) or not DATE_RE.match(date.strip()):
            raise PlannerError("Release mode requires a 'date' in YYYY-MM-DD format.")

        version = version.strip()
        date = date.strip()

        released_section = document.get_section("Unreleased")
        if released_section is None:
            raise PlannerError("Missing Unreleased section after normalization.")

        released_section.title = version
        released_section.date = date
        released_section.yanked = False
        released_section.modified = True
        insert_empty_unreleased(document)
        warnings.extend(update_footer_links(document, plan["compare_links"], version))

    content = render_changelog_document(document)
    changelog_path.parent.mkdir(parents=True, exist_ok=True)
    changelog_path.write_text(content)
    return changelog_path, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply deterministic Keep a Changelog updates.")
    parser.add_argument("--repo", help="Repository root or any path inside the repository.")
    parser.add_argument("--mode", choices=("unreleased", "release"), required=True)
    parser.add_argument("--payload", required=True, help="Path to a JSON payload file or '-' for stdin.")
    parser.add_argument("--changelog", help="Relative or absolute path to the changelog file.")
    args = parser.parse_args()

    try:
        repo = resolve_repo(args.repo)
        changelog_path = Path(args.changelog or "CHANGELOG.md")
        if not changelog_path.is_absolute():
            changelog_path = repo / changelog_path
        payload = read_payload(args.payload)
        updated_path, warnings = write_changelog(repo, changelog_path, args.mode, payload)
    except (PlannerError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(str(updated_path))
    if warnings:
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
