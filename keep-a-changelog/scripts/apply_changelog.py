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
    collect_quality_warnings,
    normalize_bullet_text,
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
        return OrderedDict()

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
            normalized_items.append(text if text.startswith("- ") else f"- {text}")

    ordered = OrderedDict()
    for category in STANDARD_CATEGORIES:
        items = categories.get(category)
        if items:
            ordered[category] = items
    return ordered


def normalize_string_list(value: object, *, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        raise PlannerError(f"'{label}' must be a string or list of strings.")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise PlannerError(f"'{label}' must contain only strings.")
        text = item.strip()
        if text:
            normalized.append(text)
    return normalized


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


def dedupe_list_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        normalized = normalize_bullet_text(item) if item.strip().startswith("-") else " ".join(item.lower().split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(item)
    return deduped


def merge_categories(section: Section, additions: OrderedDict[str, list[str]]) -> None:
    for category in STANDARD_CATEGORIES:
        existing = list(section.categories.get(category, []))
        incoming = additions.get(category, [])
        if not existing and not incoming:
            continue
        section.categories[category] = dedupe_list_preserve_order(existing + list(incoming))
    section.modified = True


def normalize_intro_lines(section: Section) -> None:
    lines = [line.rstrip() for line in section.intro_lines]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    normalized: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line.strip()
        if blank and previous_blank:
            continue
        normalized.append(line)
        previous_blank = blank
    section.intro_lines = normalized


def cleanup_section(section: Section) -> None:
    cleaned = OrderedDict()
    for category in STANDARD_CATEGORIES:
        items = section.categories.get(category, [])
        deduped = dedupe_list_preserve_order([item for item in items if item.strip()])
        if deduped:
            cleaned[category] = deduped
    section.categories = cleaned
    normalize_intro_lines(section)
    section.modified = True


def intro_from_payload(payload: dict[str, object]) -> list[str]:
    summary = normalize_string_list(payload.get("summary"), label="summary")
    migration = normalize_string_list(payload.get("migration_notes"), label="migration_notes")

    lines: list[str] = []
    for index, paragraph in enumerate(summary):
        if index:
            lines.append("")
        lines.append(paragraph)

    if migration:
        if lines:
            lines.append("")
        lines.append("Migration notes:")
        for note in migration:
            lines.append(note if note.startswith("- ") else f"- {note}")

    return lines


def merge_intro_lines(existing: list[str], additions: list[str]) -> list[str]:
    if not additions:
        return list(existing)
    merged = list(existing)
    if merged and merged[-1].strip():
        merged.append("")
    merged.extend(additions)
    return merged


def parse_selection(payload: dict[str, object]) -> tuple[set[str], set[str]]:
    selection = payload.get("selection")
    if selection is None:
        raise PlannerError("release-subset mode requires a 'selection' object.")
    if not isinstance(selection, dict):
        raise PlannerError("'selection' must be a JSON object.")

    categories = set(normalize_string_list(selection.get("categories"), label="selection.categories"))
    invalid = categories - set(STANDARD_CATEGORIES)
    if invalid:
        raise PlannerError(f"Unsupported selection categories: {', '.join(sorted(invalid))}")

    bullets = {normalize_bullet_text(item) for item in normalize_string_list(selection.get("bullets"), label="selection.bullets")}
    if not categories and not bullets:
        raise PlannerError("'selection' must include categories, bullets, or both.")
    return categories, bullets


def extract_subset(unreleased: Section, payload: dict[str, object]) -> OrderedDict[str, list[str]]:
    selected_categories, selected_bullets = parse_selection(payload)
    extracted = OrderedDict()

    for category in STANDARD_CATEGORIES:
        items = list(unreleased.categories.get(category, []))
        if not items:
            continue

        moved: list[str] = []
        kept: list[str] = []
        move_whole_category = category in selected_categories
        for item in items:
            normalized = normalize_bullet_text(item)
            if move_whole_category or normalized in selected_bullets:
                moved.append(item)
            else:
                kept.append(item)

        if moved:
            extracted[category] = moved
        if kept:
            unreleased.categories[category] = kept
        elif category in unreleased.categories:
            del unreleased.categories[category]

    if not extracted:
        raise PlannerError("release-subset selection did not match any bullets in [Unreleased].")

    unreleased.modified = True
    return extracted


def ensure_release_payload(payload: dict[str, object]) -> tuple[str, str]:
    version = payload.get("version")
    date = payload.get("date")
    if not isinstance(version, str) or not version.strip():
        raise PlannerError("This mode requires a non-empty 'version' in the payload.")
    if not isinstance(date, str) or not DATE_RE.match(date.strip()):
        raise PlannerError("This mode requires a 'date' in YYYY-MM-DD format.")
    return version.strip(), date.strip()


def find_version_section(document: ChangelogDocument, version: str) -> Section:
    section = document.get_section(version)
    if section is None or section.title == "Unreleased":
        raise PlannerError(f"Version section [{version}] was not found.")
    return section


def rebuild_footer_links(document: ChangelogDocument, compare_links: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    if not compare_links.get("feasible"):
        warnings.append("Skipped compare-link update because the compare strategy is ambiguous.")
        return warnings

    compare_base_url = compare_links.get("compare_base_url")
    tag_prefix = compare_links.get("tag_prefix") or ""
    if not isinstance(compare_base_url, str) or not compare_base_url:
        warnings.append("Skipped compare-link update because the compare base URL is unavailable.")
        return warnings

    known_labels = {"Unreleased"}
    known_labels.update(section.title for section in document.sections if section.title != "Unreleased")
    preserved = OrderedDict(
        (label, url) for label, url in document.footer_links.items() if label not in known_labels
    )

    releases = [section.title for section in document.sections if section.title != "Unreleased"]
    rebuilt = OrderedDict()
    if releases:
        newest_tag = f"{tag_prefix}{releases[0]}"
        rebuilt["Unreleased"] = f"{compare_base_url}/{newest_tag}...HEAD"

    for index, version in enumerate(releases):
        if index + 1 < len(releases):
            older = releases[index + 1]
            older_tag = f"{tag_prefix}{older}"
            version_tag = f"{tag_prefix}{version}"
            rebuilt[version] = f"{compare_base_url}/{older_tag}...{version_tag}"
            continue

        existing = document.footer_links.get(version)
        if existing:
            rebuilt[version] = existing
        else:
            warnings.append(
                f"Skipped compare link for oldest release [{version}] because there is no previous version section to compare against."
            )

    rebuilt.update(preserved)
    document.footer_links = rebuilt
    return warnings


def validate_quality(document: ChangelogDocument, *, strict_quality: bool) -> list[str]:
    quality_warnings = collect_quality_warnings(document)
    if strict_quality and quality_warnings:
        raise PlannerError("Refusing to update changelog because strict quality checks failed:\n- " + "\n- ".join(quality_warnings))
    return quality_warnings


def write_changelog(
    repo: Path,
    changelog_path: Path,
    mode: str,
    payload: dict[str, object],
    *,
    profile: str,
    strict_quality: bool,
) -> tuple[Path, list[str]]:
    plan = build_plan(repo, str(changelog_path), profile=profile, strict_quality=strict_quality)
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
    if additions:
        merge_categories(unreleased, additions)
        cleanup_section(unreleased)

    if mode == "unreleased":
        unreleased.intro_lines = merge_intro_lines(unreleased.intro_lines, intro_from_payload(payload))
        cleanup_section(unreleased)

    elif mode == "release":
        version, date = ensure_release_payload(payload)
        released_section = document.get_section("Unreleased")
        if released_section is None:
            raise PlannerError("Missing Unreleased section after normalization.")
        released_section.title = version
        released_section.date = date
        released_section.yanked = False
        released_section.intro_lines = merge_intro_lines(released_section.intro_lines, intro_from_payload(payload))
        cleanup_section(released_section)
        released_section.modified = True
        document.sections.insert(
            0,
            Section(
                title="Unreleased",
                date=None,
                yanked=False,
                heading_line="## [Unreleased]",
                body_lines=[],
                modified=True,
            ),
        )

    elif mode == "release-subset":
        version, date = ensure_release_payload(payload)
        released_categories = extract_subset(unreleased, payload)
        cleanup_section(unreleased)
        released_section = Section(
            title=version,
            date=date,
            yanked=False,
            heading_line=f"## [{version}] - {date}",
            body_lines=[],
            intro_lines=intro_from_payload(payload),
            categories=released_categories,
            modified=True,
        )
        cleanup_section(released_section)
        document.sections.insert(1 if document.sections and document.sections[0].title == "Unreleased" else 0, released_section)

    elif mode == "yank":
        target_version = payload.get("target_version")
        if not isinstance(target_version, str) or not target_version.strip():
            raise PlannerError("yank mode requires 'target_version' in the payload.")
        target_section = find_version_section(document, target_version.strip())
        target_section.yanked = True
        target_section.modified = True

    elif mode == "unyank":
        target_version = payload.get("target_version")
        if not isinstance(target_version, str) or not target_version.strip():
            raise PlannerError("unyank mode requires 'target_version' in the payload.")
        target_section = find_version_section(document, target_version.strip())
        target_section.yanked = False
        target_section.modified = True

    else:
        raise PlannerError(f"Unsupported mode: {mode}")

    if mode in {"unreleased", "release", "release-subset", "yank", "unyank"}:
        warnings.extend(rebuild_footer_links(document, plan["compare_links"]))

    quality_warnings = validate_quality(document, strict_quality=strict_quality)
    warnings.extend(quality_warnings)
    content = render_changelog_document(document)
    changelog_path.parent.mkdir(parents=True, exist_ok=True)
    changelog_path.write_text(content)
    return changelog_path, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply deterministic Keep a Changelog updates.")
    parser.add_argument("--repo", help="Repository root or any path inside the repository.")
    parser.add_argument(
        "--mode",
        choices=("unreleased", "release", "release-subset", "yank", "unyank"),
        required=True,
    )
    parser.add_argument("--payload", required=True, help="Path to a JSON payload file or '-' for stdin.")
    parser.add_argument("--changelog", help="Relative or absolute path to the changelog file.")
    parser.add_argument("--profile", choices=("generic", "lattice"), default="generic")
    parser.add_argument("--strict-quality", action="store_true")
    args = parser.parse_args()

    try:
        repo = resolve_repo(args.repo)
        changelog_path = Path(args.changelog or "CHANGELOG.md")
        if not changelog_path.is_absolute():
            changelog_path = repo / changelog_path
        payload = read_payload(args.payload)
        updated_path, warnings = write_changelog(
            repo,
            changelog_path,
            args.mode,
            payload,
            profile=args.profile,
            strict_quality=args.strict_quality,
        )
    except (PlannerError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(str(updated_path))
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
