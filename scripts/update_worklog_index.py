"""Deterministic worklog index generator and validator for docs/worklogs/.

Scans ``docs/worklogs/<person>/<YYYY-MM-DD_slug>/REPORT.md`` files, validates
required core metadata and hygiene rules, and regenerates ``docs/worklogs/INDEX.md``
sorted newest-first so 10 contributors working on parallel branches avoid manual
merge conflicts.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys

VALID_TYPES = frozenset({"analysis", "test", "change", "experiment"})
VALID_STATUSES = frozenset({"verified", "completed-analysis", "partial", "blocked", "in-progress"})
FOLDER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_[a-z0-9][a-z0-9._-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
META_LINE_RE = re.compile(r"^\s*-\s*\*\*([^*:]+):\*\*\s*(.*?)\s*$")
LINK_RE = re.compile(r"\]\(([^)#]+)\)")
BAD_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/Users/|C:/Users)")
BAD_SECRET_RE = re.compile(r"\b(?:gsk_[A-Za-z0-9]+|nvapi-[A-Za-z0-9]+|AIza[A-Za-z0-9_-]+|sk-[A-Za-z0-9]{10,})\b")
FORBIDDEN_SUFFIXES = frozenset({".sqlite", ".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".db"})
RESOLVED_PROPOSAL_PREFIXES = ("[applied", "[rejected", "[deferred")


def is_pending_proposal(value: str) -> bool:
    cleaned = value.strip().strip("`").strip().lower()
    if cleaned in {"", "none", "—", "-"}:
        return False
    return not cleaned.startswith(RESOLVED_PROPOSAL_PREFIXES)


@dataclass(frozen=True)
class WorklogEntry:
    contributor: str
    folder: str
    date: str
    author: str
    work_type: str
    subsystem: str
    status: str
    title: str
    tldr: str
    builds_on: str
    next_issue: str
    rule_proposal: str
    report_rel: str
    has_protocol: bool
    has_results: bool
    has_provenance: bool
    has_patches: bool


def _clean_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().strip("`")).replace("|", "\\|")


def _extract_section(lines: list[str], heading: str) -> list[str]:
    target = f"## {heading}".lower()
    collecting = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if collecting:
                break
            if stripped.lower() == target:
                collecting = True
                continue
        elif collecting:
            out.append(line)
    return out


def _parse_metadata(lines: list[str]) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in _extract_section(lines, "Metadata"):
        match = META_LINE_RE.match(line)
        if match:
            key = match.group(1).strip().lower()
            val = match.group(2).strip()
            meta[key] = val
    return meta


def _parse_tldr(lines: list[str]) -> str:
    body = [ln.strip() for ln in _extract_section(lines, "TL;DR") if ln.strip() and not ln.strip().startswith("<!--")]
    if not body:
        return ""
    joined = " ".join(body)
    first_sentence = re.split(r"(?<=[.!?])\s+", joined, maxsplit=1)[0]
    if len(first_sentence) > 140:
        return first_sentence[:137].rstrip() + "..."
    return first_sentence


def _parse_title(lines: list[str], fallback: str) -> str:
    for line in lines:
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return fallback


def scan_worklogs(worklogs_root: Path) -> tuple[list[str], list[WorklogEntry], list[str]]:
    """Return ``(contributors, entries_newest_first, validation_errors)``."""
    contributors: list[str] = []
    entries: list[WorklogEntry] = []
    errors: list[str] = []

    if not worklogs_root.is_dir():
        return contributors, entries, [f"Worklogs directory not found: {worklogs_root}"]

    for person_dir in sorted(p for p in worklogs_root.iterdir() if p.is_dir()):
        contributor = person_dir.name
        if contributor != contributor.lower() or not re.match(r"^[a-z0-9][a-z0-9_-]*$", contributor):
            errors.append(f"Contributor folder must be lowercase POSIX: {contributor}")
        contributors.append(contributor)

        for dossier_dir in sorted(d for d in person_dir.iterdir() if d.is_dir()):
            folder = dossier_dir.name
            rel_folder = f"{contributor}/{folder}"
            if not FOLDER_RE.match(folder):
                errors.append(
                    f"{rel_folder}: folder name must match YYYY-MM-DD_<lowercase-slug>"
                )

            # Hygiene check for forbidden files inside dossier.
            for item in dossier_dir.rglob("*"):
                if not item.is_file():
                    continue
                if item.name == ".env" or item.name.startswith(".env."):
                    errors.append(f"{rel_folder}/{item.name}: forbidden secret file inside worklogs")
                if item.suffix.lower() in FORBIDDEN_SUFFIXES:
                    errors.append(f"{rel_folder}/{item.name}: forbidden database file inside worklogs")

            report_path = dossier_dir / "REPORT.md"
            if not report_path.is_file():
                errors.append(f"{rel_folder}: missing required REPORT.md")
                continue

            raw_text = report_path.read_text(encoding="utf-8", errors="replace")
            lines = raw_text.splitlines()
            meta = _parse_metadata(lines)
            tldr = _parse_tldr(lines)
            title = _parse_title(lines, folder)

            date_val = meta.get("date", "").strip("`")
            author_val = meta.get("author", "").strip("`")
            type_val = meta.get("type", "").strip("`").lower()
            subsystem_val = meta.get("subsystem", "").strip("`")
            status_val = meta.get("status", "").strip("`").lower()
            builds_on = meta.get("builds on", "").strip()
            next_issue = meta.get("next / open issue", "").strip()
            rule_proposal = meta.get("rule proposal", "").strip()

            if not DATE_RE.match(date_val):
                errors.append(f"{rel_folder}/REPORT.md: missing or invalid Date (YYYY-MM-DD): {date_val!r}")
            elif FOLDER_RE.match(folder) and not folder.startswith(date_val + "_"):
                errors.append(f"{rel_folder}/REPORT.md: Date {date_val!r} does not match folder prefix {folder!r}")
            if not author_val or author_val.startswith("<"):
                errors.append(f"{rel_folder}/REPORT.md: missing Author metadata")
            if type_val not in VALID_TYPES:
                errors.append(
                    f"{rel_folder}/REPORT.md: invalid Type {type_val!r} (expected one of {sorted(VALID_TYPES)})"
                )
            if not subsystem_val or subsystem_val.startswith("<"):
                errors.append(f"{rel_folder}/REPORT.md: missing Subsystem metadata")
            if status_val not in VALID_STATUSES:
                errors.append(
                    f"{rel_folder}/REPORT.md: invalid Status {status_val!r} (expected one of {sorted(VALID_STATUSES)})"
                )
            if not tldr or tldr.startswith("<"):
                errors.append(f"{rel_folder}/REPORT.md: missing TL;DR section")

            # Validate relative links and privacy hygiene inside markdown/json files.
            for text_file in dossier_dir.rglob("*"):
                if not text_file.is_file() or text_file.suffix.lower() not in {".md", ".json"}:
                    continue
                content = text_file.read_text(encoding="utf-8", errors="replace")
                if BAD_PATH_RE.search(content):
                    errors.append(f"{rel_folder}/{text_file.name}: contains host-private absolute path")
                if BAD_SECRET_RE.search(content):
                    errors.append(f"{rel_folder}/{text_file.name}: matches real vendor API-key prefix")
                if text_file.suffix.lower() == ".md":
                    for link in LINK_RE.findall(content):
                        if link.startswith(("http://", "https://", "mailto:", "<")):
                            continue
                        if not (text_file.parent / link).resolve().exists():
                            errors.append(f"{rel_folder}/{text_file.name}: broken relative link {link!r}")

            has_protocol = (dossier_dir / "PROTOCOL.md").is_file()
            has_results = (dossier_dir / "results.json").is_file()
            has_provenance = (dossier_dir / "provenance.json").is_file()
            has_patches = (dossier_dir / "patches").is_dir() and any((dossier_dir / "patches").iterdir())

            if type_val == "experiment" and not has_protocol:
                errors.append(f"{rel_folder}: Type 'experiment' requires sibling PROTOCOL.md")

            entries.append(
                WorklogEntry(
                    contributor=contributor,
                    folder=folder,
                    date=date_val or folder[:10],
                    author=author_val or contributor,
                    work_type=type_val or "unknown",
                    subsystem=subsystem_val or "—",
                    status=status_val or "unknown",
                    title=title,
                    tldr=tldr,
                    builds_on="" if builds_on.lower() in {"", "none", "—", "-"} else builds_on,
                    next_issue="" if next_issue.lower() in {"", "none", "—", "-"} else next_issue,
                    rule_proposal="" if rule_proposal.lower() in {"", "none", "—", "-"} else rule_proposal,
                    report_rel=f"{contributor}/{folder}/REPORT.md",
                    has_protocol=has_protocol,
                    has_results=has_results,
                    has_provenance=has_provenance,
                    has_patches=has_patches,
                )
            )

    entries.sort(key=lambda e: (e.date, e.folder, e.contributor), reverse=True)
    return contributors, entries, errors


def render_index(contributors: list[str], entries: list[WorklogEntry]) -> str:
    by_person: dict[str, list[WorklogEntry]] = {c: [] for c in contributors}
    for entry in entries:
        by_person.setdefault(entry.contributor, []).append(entry)

    lines: list[str] = [
        "# Team Worklogs & Evidence Locker (`docs/worklogs/INDEX.md`)",
        "",
        "This is the team's chronological evidence locker for detailed, small-scoped engineering and research work dossiers.",
        "**Row 1 of the Latest Activity table below is always the most recent worklog across all contributors** — use it to see what was solved last and which open issue to pick up next.",
        "",
        "- **Policy:** Read [`../../dev_rules/documentation_rules.md`](../../dev_rules/documentation_rules.md) before creating or updating a dossier.",
        "- **Templates:** Copy [`REPORT_TEMPLATE.md`](REPORT_TEMPLATE.md) (every dossier), [`PROTOCOL_TEMPLATE.md`](PROTOCOL_TEMPLATE.md) (`Type: experiment`), and [`PROVENANCE_TEMPLATE.json`](PROVENANCE_TEMPLATE.json) (`test`/`change`/`experiment`).",
        "- **Auto-regenerate & validate (prevents merge conflicts):** Run `python scripts/update_worklog_index.py` (or `--check` in CI/review) after adding a dossier.",
        "- **Folder hygiene:** Keep `.gitkeep` inside each contributor folder so empty directories remain tracked across branches.",
        "- **Frozen legacy archives:** Historical pre-worklog records stay untouched in [`../../reports/INDEX.md`](../../reports/INDEX.md) and `updates/`.",
        "",
        "---",
        "",
        "## Latest Activity (Newest First)",
        "",
        "| Date | Author | Type | Subsystem | Status | Headline & Open Next Issue | Report | Data / Chain |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    if not entries:
        lines.append(
            "| *(no dossiers yet)* | — | `analysis` / `test` / `change` / `experiment` | — | — | Run `python scripts/update_worklog_index.py` after adding your first dossier | — | — |"
        )
    else:
        for e in entries:
            headline = _clean_cell(e.tldr or e.title)
            if e.next_issue:
                headline = f"{headline} **Next:** {_clean_cell(e.next_issue)}"
            tags: list[str] = []
            if e.has_protocol:
                tags.append(f"[protocol]({e.contributor}/{e.folder}/PROTOCOL.md)")
            if e.has_results:
                tags.append(f"[results]({e.contributor}/{e.folder}/results.json)")
            if e.has_provenance:
                tags.append(f"[prov]({e.contributor}/{e.folder}/provenance.json)")
            if e.has_patches:
                tags.append(f"[patches]({e.contributor}/{e.folder}/patches/)")
            if e.builds_on:
                tags.append(f"from {_clean_cell(e.builds_on)}")
            data_col = ", ".join(tags) if tags else "—"
            lines.append(
                f"| `{_clean_cell(e.date)}` | {_clean_cell(e.author)} | `{_clean_cell(e.work_type)}` "
                f"| `{_clean_cell(e.subsystem)}` | `{_clean_cell(e.status)}` | {headline} "
                f"| [{_clean_cell(e.title)}]({e.report_rel}) | {data_col} |"
            )

    proposals = [e for e in entries if is_pending_proposal(e.rule_proposal)]
    lines.extend([
        "",
        "---",
        "",
        "## Pending Rule Proposals (Maintainer Review Queue)",
        "",
        "Coding agents and feature PRs must **never** auto-edit `dev_rules/*.md`, `AGENTS.md`, or `CLAUDE.md`. Any worklog carrying an unresolved `Rule Proposal:` metadata entry appears below for explicit maintainer review (prefix `[APPLIED]`, `[REJECTED]`, or `[DEFERRED]` once resolved to clear this queue while preserving history):",
        "",
        "| Date | Author | Subsystem | Proposed Rule Update (NOT APPLIED) | Evidence Dossier |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ])
    if not proposals:
        lines.append("| *(no pending rule proposals)* | — | — | — | — |")
    else:
        for e in proposals:
            lines.append(
                f"| `{_clean_cell(e.date)}` | {_clean_cell(e.author)} | `{_clean_cell(e.subsystem)}` "
                f"| {_clean_cell(e.rule_proposal)} | [{_clean_cell(e.title)}]({e.report_rel}) |"
            )

    lines.extend([
        "",
        "---",
        "",
        "## Contributor Folders",
        "",
        "| Contributor | Folder | Dossiers | Latest Entry |",
        "| :--- | :--- | :---: | :--- |",
    ])
    for contributor in sorted(contributors):
        person_entries = by_person.get(contributor, [])
        display = contributor.capitalize()
        if person_entries:
            latest = person_entries[0]
            latest_cell = f"`{latest.date}` — [{_clean_cell(latest.title)}]({latest.report_rel})"
        else:
            latest_cell = "—"
        lines.append(f"| {display} | [`{contributor}/`]({contributor}/) | `{len(person_entries)}` | {latest_cell} |")

    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate or validate docs/worklogs/INDEX.md.")
    parser.add_argument(
        "--worklogs-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "docs" / "worklogs",
        help="Path to the docs/worklogs directory.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate dossiers and verify INDEX.md is up to date without writing.",
    )
    args = parser.parse_args(argv)

    worklogs_root: Path = args.worklogs_dir.resolve()
    contributors, entries, errors = scan_worklogs(worklogs_root)
    rendered = render_index(contributors, entries)
    index_path = worklogs_root / "INDEX.md"

    if errors:
        for err in errors:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    if args.check:
        existing = index_path.read_text(encoding="utf-8").replace("\r\n", "\n") if index_path.is_file() else ""
        if existing != rendered:
            print(
                f"[STALE] {index_path} is out of date. Run: python scripts/update_worklog_index.py",
                file=sys.stderr,
            )
            return 1
        print(f"[OK] Validated {len(entries)} worklog dossier(s) across {len(contributors)} contributor folders; INDEX.md is current.")
        return 0

    with index_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(rendered)
    print(f"[UPDATED] Wrote {index_path} ({len(entries)} dossier(s) across {len(contributors)} contributor folders).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
