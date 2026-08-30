"""Bounded project understanding and temporary Task Brain primitives.

Stage 2 is intentionally deterministic-first.  This module may inventory,
search, and read repository files, but it never mutates them and never calls a
model.  The orchestration layer may optionally ask the pinned weak model to
select candidate paths after deterministic search has run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from hivo.requirements import USER_CONFIRMED, USER_STATED, ledger_requirements


NEW_PROJECT = "NEW_PROJECT"
EXISTING_PROJECT = "EXISTING_PROJECT"

REPOSITORY_EMPTY = "REPOSITORY_EMPTY"
REPOSITORY_EVIDENCE_UNAVAILABLE = "REPOSITORY_EVIDENCE_UNAVAILABLE"
REPOSITORY_RECONNAISSANCE_FAILED = "REPOSITORY_RECONNAISSANCE_FAILED"
REPOSITORY_RECONNAISSANCE_COMPLETE = "REPOSITORY_RECONNAISSANCE_COMPLETE"

DIRECT_OBSERVATION = "DIRECT_OBSERVATION"
REPOSITORY_EVIDENCE = "REPOSITORY_EVIDENCE"
PROJECT_BRAIN = "PROJECT_BRAIN"
DERIVED_TASK_ASSUMPTION = "DERIVED_TASK_ASSUMPTION"

MAX_RECON_SEARCHES = 8
MAX_RECON_INVENTORY_FILES = 120
MAX_RECON_FILES = 12
MAX_RECON_SNIPPETS = 24
MAX_RECON_CHARS = 12000
MAX_RECON_MODEL_CALLS = 1
MAX_RECON_FILE_BYTES = 512_000
MAX_RECON_DEPTH = 5

MAX_TASK_BRAIN_CHARS = 10000
MAX_TASK_BRAIN_EVIDENCE = 12
MAX_TASK_BRAIN_TESTS = 8
MAX_TASK_BRAIN_INTERFACES = 8
MAX_TASK_BRAIN_ASSUMPTIONS = 6
MAX_TASK_BRAIN_OPEN_QUESTIONS = 3
MAX_TASK_BRAIN_PROJECT_FACTS = 10
MAX_TASK_BRAIN_PROJECTION_CHARS = 3200

REPOSITORY_EVIDENCE_CATEGORIES = frozenset({
    "CURRENT_OWNER", "CURRENT_INTERFACE", "CURRENT_STATE_OWNER",
    "CURRENT_DEPENDENCY", "CURRENT_TEST", "CURRENT_ENTRYPOINT",
    "CURRENT_CONSTRAINT", "CURRENT_BEHAVIOR", "CURRENT_CONFIG",
    "CURRENT_PERSISTENCE", "CURRENT_FAILURE_EVIDENCE",
})
TASK_BRAIN_PROVENANCE = frozenset({
    USER_STATED, USER_CONFIRMED, PROJECT_BRAIN,
    REPOSITORY_EVIDENCE, DERIVED_TASK_ASSUMPTION,
})

_SOURCE_SUFFIXES = frozenset({
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
    ".java", ".go", ".rs", ".c", ".h", ".cc", ".cpp", ".cs",
    ".rb", ".php", ".swift", ".kt", ".kts", ".scala", ".vue",
    ".svelte", ".html", ".css", ".scss", ".sql", ".sh", ".ps1",
})
_TEXT_SUFFIXES = _SOURCE_SUFFIXES | frozenset({
    ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".md", ".txt",
})
_MANIFEST_NAMES = frozenset({
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg",
    "cargo.toml", "cargo.lock", "go.mod", "go.sum", "pom.xml",
    "build.gradle", "build.gradle.kts", "gemfile", "composer.json",
    "tsconfig.json", "vite.config.js", "vite.config.ts", "pytest.ini",
})
_ENTRY_NAMES = frozenset({
    "index.html", "main.py", "app.py", "server.py", "main.js", "main.ts",
    "main.tsx", "main.jsx", "manage.py", "program.cs",
})
_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", ".idea", ".vscode", "node_modules", "vendor",
    "dist", "build", "coverage", ".coverage", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "__pycache__", ".venv", "venv", "env", ".tox",
    ".agent_runs", ".agent_evidence", ".agent_backups", ".hivo",
})
_IGNORED_FILES = frozenset({
    ".agent_experiment.jsonl", ".agent_memory.json", ".agent_memory.sqlite3",
    ".agent_host_preflight.json",
})
_STOP_WORDS = frozenset({
    "add", "and", "are", "behavior", "build", "change", "code", "create",
    "current", "existing", "feature", "file", "fix", "for", "from", "into",
    "make", "modify", "project", "refactor", "remove", "replace", "repository",
    "should", "task", "that", "the", "this", "update", "user", "with",
})
_MODIFICATION_RE = re.compile(
    r"\b(?:change|fix|update|modify|preserve|refactor|existing|current|replace|"
    r"remove|delete|migrate|legacy|backward compatible|add to)\b", re.IGNORECASE,
)
_GREENFIELD_RE = re.compile(
    r"\b(?:from scratch|greenfield|brand[- ]new project|new project)\b", re.IGNORECASE,
)
_DECLARATION_RE = re.compile(
    r"(?:\bclass\s+([A-Za-z_$][\w$]*)|\bdef\s+([A-Za-z_$][\w$]*)\s*\(|"
    r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(|\binterface\s+([A-Za-z_$][\w$]*)|"
    r"\b(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=)",
)
_STATE_RE = re.compile(
    r"\b(?:state|store|owner|owns|paused|pause|active|enabled|selected|token|session|"
    r"score|theme|auth|callback)\b", re.IGNORECASE,
)
_INTERFACE_RE = re.compile(
    r"\b(?:class|def|function|interface|export|route|endpoint|event|props?|public|api)\b",
    re.IGNORECASE,
)
_TEST_RE = re.compile(r"\b(?:test|tests|spec|assert|expect|describe|it\s*\()", re.IGNORECASE)
_PERSISTENCE_RE = re.compile(
    r"\b(?:persist|storage|database|schema|migration|save|load|localstorage|cookie)\b",
    re.IGNORECASE,
)
_DEPENDENCY_RE = re.compile(r"^\s*(?:from\s+\S+\s+import|import\s+|require\s*\(|use\s+)", re.IGNORECASE)


def _compact(value, limit=320):
    text = " ".join(str(value or "").split())
    limit = max(1, int(limit))
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _json_size(value):
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def _is_test_path(path):
    parts = [part.casefold() for part in Path(path).parts]
    name = Path(path).name.casefold()
    return any(part in {"test", "tests", "spec", "specs"} for part in parts) or bool(
        re.search(r"(?:^test_|_test\.|\.test\.|\.spec\.)", name)
    )


def _file_kind(path):
    value = Path(path)
    name = value.name.casefold()
    if _is_test_path(path):
        return "TEST"
    if name in _MANIFEST_NAMES:
        return "CONFIG"
    if name in _ENTRY_NAMES or value.as_posix().casefold() in {"src/main.tsx", "src/main.jsx"}:
        return "ENTRYPOINT"
    if value.suffix.casefold() in _SOURCE_SUFFIXES:
        return "SOURCE"
    return "TEXT"


def _inventory_fingerprint(files):
    stable = [
        (item.get("path"), int(item.get("size", 0)), int(item.get("mtime_ns", 0)))
        for item in files or []
    ]
    return hashlib.sha256(json.dumps(stable, separators=(",", ":")).encode("utf-8")).hexdigest()


def inventory_repository(workspace, max_files=MAX_RECON_INVENTORY_FILES, max_depth=MAX_RECON_DEPTH):
    """Return a bounded metadata-only inventory; generated/runtime state is ignored."""
    try:
        root = Path(workspace).resolve()
    except (TypeError, OSError, RuntimeError, ValueError) as exc:
        return {
            "status": REPOSITORY_EVIDENCE_UNAVAILABLE, "files": [], "meaningful_files": [],
            "truncated": False, "error": _compact(exc, 300), "fingerprint": None,
        }
    if not root.exists() or not root.is_dir():
        return {
            "status": REPOSITORY_EVIDENCE_UNAVAILABLE, "root": str(root), "files": [],
            "meaningful_files": [], "truncated": False,
            "error": "workspace is not an accessible directory", "fingerprint": None,
        }
    files = []
    total_considered = 0
    truncated = False
    try:
        for current, dirs, names in os.walk(root):
            current_path = Path(current)
            try:
                depth = len(current_path.relative_to(root).parts)
            except ValueError:
                continue
            dirs[:] = [
                name for name in sorted(dirs)
                if name.casefold() not in _SKIP_DIRS and depth < int(max_depth)
            ]
            for name in sorted(names):
                if name.casefold() in _IGNORED_FILES or name.startswith(".agent_"):
                    continue
                path = current_path / name
                try:
                    relative = path.relative_to(root).as_posix()
                    stat = path.stat()
                except OSError:
                    continue
                total_considered += 1
                if len(files) >= max(0, int(max_files)):
                    truncated = True
                    continue
                files.append({
                    "path": relative,
                    "size": int(stat.st_size),
                    "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
                    "suffix": path.suffix.casefold(),
                    "kind": _file_kind(relative),
                })
    except OSError as exc:
        return {
            "status": REPOSITORY_EVIDENCE_UNAVAILABLE, "root": str(root), "files": files,
            "meaningful_files": [], "truncated": truncated, "error": _compact(exc, 300),
            "fingerprint": _inventory_fingerprint(files),
        }
    meaningful = [
        item for item in files
        if item.get("suffix") in _SOURCE_SUFFIXES
        or Path(item.get("path", "")).name.casefold() in _MANIFEST_NAMES
        or item.get("kind") in {"TEST", "ENTRYPOINT"}
    ]
    status = REPOSITORY_EMPTY if not meaningful and not truncated else REPOSITORY_RECONNAISSANCE_COMPLETE
    return {
        "status": status, "root": str(root), "files": files, "meaningful_files": meaningful,
        "files_considered": total_considered, "truncated": truncated,
        "limits": {"max_files": int(max_files), "max_depth": int(max_depth)},
        "fingerprint": _inventory_fingerprint(files),
    }


def _snapshot_has_meaningful_files(snapshot):
    if not isinstance(snapshot, dict):
        return False
    if snapshot.get("meaningful_files"):
        return True
    for item in snapshot.get("files", []) or []:
        path = str(item.get("path", "") if isinstance(item, dict) else item)
        if Path(path).suffix.casefold() in _SOURCE_SUFFIXES or Path(path).name.casefold() in _MANIFEST_NAMES:
            return True
    return False


def classify_project_mode(raw_goal, inventory=None):
    """Classify the task/workspace situation without a model call."""
    inventory = inventory if isinstance(inventory, dict) else {}
    has_project = _snapshot_has_meaningful_files(inventory)
    text = str(raw_goal or "")
    if has_project:
        reason = "meaningful project files are present"
        mode = EXISTING_PROJECT
    elif _GREENFIELD_RE.search(text):
        reason = "the workspace is empty and the request is explicitly greenfield"
        mode = NEW_PROJECT
    elif _MODIFICATION_RE.search(text):
        reason = "the request assumes an existing implementation but no project files were observed"
        mode = EXISTING_PROJECT
    else:
        reason = "no existing implementation was observed"
        mode = NEW_PROJECT
    return {
        "project_mode": mode, "reason": reason,
        "workspace_has_meaningful_files": has_project,
        "inventory_status": inventory.get("status", REPOSITORY_EMPTY),
    }


def repository_search_terms(raw_goal, source_requirements=None, max_searches=MAX_RECON_SEARCHES):
    """Extract exact identifiers first, then a few stable task-domain terms."""
    values = [str(raw_goal or "")]
    for item in source_requirements or []:
        if isinstance(item, dict):
            values.append(str(item.get("text", "")))
        else:
            values.append(str(item))
    text = "\n".join(values)
    candidates = []

    def add(value, priority):
        value = str(value or "").strip("`'\".,:;()[]{}")
        if len(value) < 3 or value.casefold() in _STOP_WORDS:
            return
        key = value.casefold()
        if any(existing[1] == key for existing in candidates):
            return
        candidates.append((priority, key, value))

    for token in re.findall(r"\b[A-Z][A-Za-z0-9_$]{2,}\b|\b[a-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b|\b\w+(?:\.\w+)+\b", text):
        add(token, 0)
    for token in re.findall(r"[A-Za-z0-9_$.-]{3,}", text):
        add(token, 1)
    candidates.sort(key=lambda item: (item[0], len(item[2]), item[1]))
    return [item[2] for item in candidates[:max(0, int(max_searches))]]


def _named_task_symbols(raw_goal):
    symbols = []
    for value in re.findall(
        r"\b[A-Z][A-Za-z0-9_$]{2,}\b|\b[a-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b|\b\w+(?:\.\w+)+\b",
        str(raw_goal or ""),
    ):
        if value.casefold() in _STOP_WORDS or value in symbols:
            continue
        symbols.append(value)
    return symbols[:4]


def _read_searchable_file(path):
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.read(MAX_RECON_FILE_BYTES)


def search_repository(workspace, inventory, terms, max_files=MAX_RECON_FILES):
    """Search bounded inventory contents and return ranked paths without source bodies."""
    root = Path(workspace).resolve()
    terms = list(terms or [])[:MAX_RECON_SEARCHES]
    matches_by_path = {}
    errors = []
    searchable = [
        item for item in inventory.get("files", [])
        if item.get("suffix") in _TEXT_SUFFIXES and int(item.get("size", 0)) <= MAX_RECON_FILE_BYTES
    ]
    for item in searchable:
        relative = item.get("path", "")
        path = root / Path(relative)
        try:
            content = _read_searchable_file(path)
        except OSError as exc:
            errors.append({"path": relative, "error": _compact(exc, 180)})
            continue
        lines = content.splitlines()
        path_lower = relative.casefold()
        for term in terms:
            needle = term.casefold()
            locations = []
            if needle in path_lower:
                locations.append(0)
            for line_number, line in enumerate(lines, 1):
                if needle in line.casefold():
                    locations.append(line_number)
                    if len(locations) >= 6:
                        break
            if locations:
                record = matches_by_path.setdefault(relative, {"path": relative, "terms": [], "lines": []})
                record["terms"].append(term)
                record["lines"].extend(locations)
    ranked = []
    by_path = {item.get("path"): item for item in inventory.get("files", [])}
    for relative, match in matches_by_path.items():
        item = by_path.get(relative, {})
        unique_lines = sorted(set(int(value) for value in match.get("lines", []) if int(value) > 0))
        score = len(set(value.casefold() for value in match.get("terms", []))) * 10
        score += 3 if _is_test_path(relative) else 0
        score += 2 if item.get("kind") == "SOURCE" else 0
        ranked.append({
            "path": relative, "terms": match.get("terms", [])[:MAX_RECON_SEARCHES],
            "lines": unique_lines[:8], "score": score, "kind": item.get("kind", _file_kind(relative)),
        })
    ranked.sort(key=lambda item: (-item["score"], item["path"]))
    operations = [{
        "operation": "SEARCH", "term": term,
        "candidate_count": sum(1 for item in ranked if term in item.get("terms", [])),
    } for term in terms]
    return {
        "candidates": ranked[:max(0, int(max_files))], "operations": operations,
        "searches": len(terms), "files_searched": len(searchable), "errors": errors[:8],
    }


def _nearest_symbol(lines, line_number):
    if not lines:
        return ""
    start = min(max(int(line_number or 1) - 1, 0), len(lines) - 1)
    for index in range(start, max(-1, start - 12), -1):
        match = _DECLARATION_RE.search(lines[index])
        if match:
            return next((value for value in match.groups() if value), "")
    return ""


def _fact(category, path, symbol, terms, support):
    subject = symbol or path
    focus = ", ".join(list(terms or [])[:3]) or "the current task"
    if category == "CURRENT_TEST":
        return f"{path} contains task-relevant test/assertion evidence for {focus}"
    if category == "CURRENT_INTERFACE":
        return f"{subject} is an observed task-relevant interface for {focus}"
    if category == "CURRENT_STATE_OWNER":
        return f"{subject} contains the observed task-relevant state ownership for {focus}"
    if category == "CURRENT_DEPENDENCY":
        return f"{subject} declares a task-relevant dependency for {focus}"
    if category == "CURRENT_PERSISTENCE":
        return f"{subject} contains observed persistence behavior for {focus}"
    if category == "CURRENT_CONFIG":
        return f"{path} is task-relevant current configuration for {focus}"
    if category == "CURRENT_ENTRYPOINT":
        return f"{path} is a task-relevant current entrypoint for {focus}"
    if category == "CURRENT_CONSTRAINT":
        return f"{subject} contains an observed preservation/compatibility constraint for {focus}"
    return f"{subject} contains the observed current owner/behavior for {focus}: {_compact(support, 120)}"


def _evidence_categories(path, support, symbol):
    categories = []
    kind = _file_kind(path)
    if kind == "TEST" or _TEST_RE.search(support):
        categories.append("CURRENT_TEST")
    elif kind == "CONFIG":
        categories.append("CURRENT_CONFIG")
    elif kind == "ENTRYPOINT":
        categories.append("CURRENT_ENTRYPOINT")
    else:
        categories.append("CURRENT_OWNER")
    if symbol or _INTERFACE_RE.search(support):
        categories.append("CURRENT_INTERFACE")
    if _STATE_RE.search(support):
        categories.append("CURRENT_STATE_OWNER")
    if _DEPENDENCY_RE.search(support):
        categories.append("CURRENT_DEPENDENCY")
    if _PERSISTENCE_RE.search(support):
        categories.append("CURRENT_PERSISTENCE")
    if re.search(r"\b(?:preserve|compatib|must not|invariant|legacy)\b", support, re.IGNORECASE):
        categories.append("CURRENT_CONSTRAINT")
    result = []
    for category in categories:
        if category not in result:
            result.append(category)
    return result


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_repository_candidates(workspace, inventory, candidates, max_files=MAX_RECON_FILES,
                                  max_snippets=MAX_RECON_SNIPPETS, max_chars=MAX_RECON_CHARS):
    """Read only ranked candidates and emit compact, source-located facts."""
    root = Path(workspace).resolve()
    inventory_paths = {item.get("path") for item in inventory.get("files", [])}
    selected = []
    for candidate in candidates or []:
        value = candidate if isinstance(candidate, dict) else {"path": candidate}
        relative = str(value.get("path", "")).replace("\\", "/")
        if relative in inventory_paths and relative not in {item.get("path") for item in selected}:
            selected.append({**value, "path": relative})
        if len(selected) >= max(0, int(max_files)):
            break
    evidence = []
    operations = []
    snippets = 0
    chars_used = 0
    errors = []
    seen = set()
    for candidate in selected:
        relative = candidate["path"]
        path = (root / Path(relative)).resolve()
        try:
            path.relative_to(root)
            content = _read_searchable_file(path)
            fingerprint = _file_sha256(path)
        except (OSError, ValueError) as exc:
            errors.append({"path": relative, "error": _compact(exc, 180)})
            continue
        lines = content.splitlines()
        locations = [int(value) for value in candidate.get("lines", []) if int(value) > 0]
        if not locations:
            matched_terms = [str(item) for item in candidate.get("terms", [])]
            locations = [
                number for number, line in enumerate(lines, 1)
                if any(term.casefold() in line.casefold() for term in matched_terms)
            ][:4]
        if not locations and lines:
            locations = [1]
        operations.append({"operation": "READ", "path": relative, "locations": locations[:4]})
        for line_number in locations[:4]:
            if snippets >= max_snippets or chars_used >= max_chars:
                break
            start = max(1, line_number - 1)
            end = min(len(lines), line_number + 1)
            support = "\n".join(lines[start - 1:end])
            remaining = max(0, max_chars - chars_used)
            support = support[:min(420, remaining)]
            if not support.strip():
                continue
            snippets += 1
            chars_used += len(support)
            symbol = _nearest_symbol(lines, line_number)
            terms = candidate.get("terms", [])
            for category in _evidence_categories(relative, support, symbol):
                key = (category, relative, symbol, start, end)
                if key in seen or len(evidence) >= MAX_TASK_BRAIN_EVIDENCE:
                    continue
                seen.add(key)
                evidence.append({
                    "evidence_id": "",
                    "fact": _compact(_fact(category, relative, symbol, terms, support), 360),
                    "category": category,
                    "path": relative,
                    "symbol": symbol or None,
                    "source_kind": _file_kind(relative),
                    "evidence_type": DIRECT_OBSERVATION,
                    "provenance": REPOSITORY_EVIDENCE,
                    "line_start": start,
                    "line_end": end,
                    "file_sha256": fingerprint,
                    "support": _compact(support, 420),
                })
    for index, record in enumerate(evidence, 1):
        record["evidence_id"] = f"REPO-{index:03d}"
    return {
        "evidence": evidence, "operations": operations,
        "files_inspected": len({item.get("path") for item in operations}),
        "snippets": snippets, "chars": chars_used, "errors": errors[:8],
        "truncated": len(selected) >= max_files or snippets >= max_snippets or chars_used >= max_chars,
    }


def validate_repository_evidence(record):
    if not isinstance(record, dict):
        return False
    if not re.fullmatch(r"REPO-\d{3,}", str(record.get("evidence_id", ""))):
        return False
    if record.get("category") not in REPOSITORY_EVIDENCE_CATEGORIES:
        return False
    if record.get("evidence_type") != DIRECT_OBSERVATION or record.get("provenance") != REPOSITORY_EVIDENCE:
        return False
    if not str(record.get("path", "")).strip() or not str(record.get("fact", "")).strip():
        return False
    if not str(record.get("file_sha256", "")).strip() or not str(record.get("support", "")).strip():
        return False
    return int(record.get("line_start", 0) or 0) >= 1 and int(record.get("line_end", 0) or 0) >= int(
        record.get("line_start", 0) or 0
    )


def run_repository_reconnaissance(workspace, raw_goal, source_requirements=None, inventory=None,
                                  scout_selector=None):
    """Run bounded inventory -> search -> optional scout -> read reconnaissance."""
    inventory = inventory if isinstance(inventory, dict) else inventory_repository(workspace)
    operations = [{
        "operation": "INVENTORY", "files_considered": inventory.get("files_considered", 0),
        "truncated": bool(inventory.get("truncated")),
    }]
    if inventory.get("status") == REPOSITORY_EVIDENCE_UNAVAILABLE:
        return {
            "status": REPOSITORY_EVIDENCE_UNAVAILABLE, "inventory": inventory,
            "evidence": [], "operations": operations, "read_only": True,
        }
    if not _snapshot_has_meaningful_files(inventory):
        return {
            "status": REPOSITORY_EMPTY, "inventory": inventory, "evidence": [],
            "operations": operations, "read_only": True,
            "workspace_fingerprint_before": inventory.get("fingerprint"),
            "workspace_fingerprint_after": inventory.get("fingerprint"),
        }
    before = inventory.get("fingerprint")
    try:
        terms = repository_search_terms(raw_goal, source_requirements)
        search = search_repository(workspace, inventory, terms)
        operations.extend(search.get("operations", []))
        candidates = list(search.get("candidates", []))
        if scout_selector is not None and len(candidates) < 2:
            suggested = scout_selector({
                "task": _compact(raw_goal, 1200), "terms": terms,
                "inventory": [
                    {"path": item.get("path"), "kind": item.get("kind"), "size": item.get("size")}
                    for item in inventory.get("meaningful_files", [])[:40]
                ],
                "search_candidates": candidates[:8],
            })
            by_path = {item.get("path"): item for item in candidates}
            for path in suggested or []:
                relative = str(path).replace("\\", "/")
                if relative not in by_path:
                    by_path[relative] = {"path": relative, "terms": [], "lines": [], "score": 0}
            candidates = sorted(by_path.values(), key=lambda item: (-int(item.get("score", 0)), item.get("path", "")))
        if not candidates:
            # A deterministic last resort keeps the run bounded and honest;
            # it is an inspected current file, not a claim about architecture.
            candidates = [
                {"path": item.get("path"), "terms": [], "lines": [], "score": 0}
                for item in inventory.get("meaningful_files", [])[:2]
            ]
        inspected = inspect_repository_candidates(workspace, inventory, candidates)
        operations.extend(inspected.get("operations", []))
        after_inventory = inventory_repository(
            workspace,
            max_files=inventory.get("limits", {}).get("max_files", MAX_RECON_INVENTORY_FILES),
            max_depth=inventory.get("limits", {}).get("max_depth", MAX_RECON_DEPTH),
        )
        after = after_inventory.get("fingerprint")
        evidence = [item for item in inspected.get("evidence", []) if validate_repository_evidence(item)]
        matched_terms = {
            str(term).casefold()
            for candidate in search.get("candidates", [])
            for term in candidate.get("terms", [])
        }
        if not inventory.get("truncated") and not search.get("errors"):
            for symbol in _named_task_symbols(raw_goal):
                if symbol.casefold() in matched_terms or len(evidence) >= MAX_TASK_BRAIN_EVIDENCE:
                    continue
                evidence.append({
                    "evidence_id": "",
                    "fact": (
                        f"The exact task-named symbol {symbol} was not found in the bounded complete "
                        "repository inventory and content search"
                    ),
                    "category": "CURRENT_CONSTRAINT", "path": ".", "symbol": symbol,
                    "source_kind": "INVENTORY", "evidence_type": DIRECT_OBSERVATION,
                    "provenance": REPOSITORY_EVIDENCE, "line_start": 1, "line_end": 1,
                    "file_sha256": inventory.get("fingerprint"),
                    "support": (
                        f"exact search for {symbol}; files searched={search.get('files_searched', 0)}; "
                        "inventory_truncated=false"
                    ),
                })
        for index, record in enumerate(evidence, 1):
            record["evidence_id"] = f"REPO-{index:03d}"
        return {
            "status": REPOSITORY_RECONNAISSANCE_COMPLETE,
            "inventory": inventory, "search_terms": terms, "search": search,
            "evidence": evidence, "operations": operations, "read_only": before == after,
            "workspace_fingerprint_before": before, "workspace_fingerprint_after": after,
            "mutations_detected": [] if before == after else ["workspace metadata changed during reconnaissance"],
            "files_considered": inventory.get("files_considered", len(inventory.get("files", []))),
            "files_inspected": inspected.get("files_inspected", 0),
            "searches": search.get("searches", 0),
            "snippets": inspected.get("snippets", 0),
            "chars": inspected.get("chars", 0),
            "truncated": bool(inventory.get("truncated") or inspected.get("truncated")),
            "errors": (search.get("errors", []) + inspected.get("errors", []))[:8],
        }
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return {
            "status": REPOSITORY_RECONNAISSANCE_FAILED, "inventory": inventory,
            "evidence": [], "operations": operations, "read_only": True,
            "error": _compact(exc, 500), "workspace_fingerprint_before": before,
        }


def bounded_repository_summary(reconnaissance, project_mode=EXISTING_PROJECT, max_chars=4200):
    """Serialize verified current facts for the Specifier without source bodies."""
    reconnaissance = reconnaissance if isinstance(reconnaissance, dict) else {}
    facts = [{
        "evidence_id": item.get("evidence_id"), "category": item.get("category"),
        "fact": _compact(item.get("fact", ""), 260), "path": item.get("path"),
        "symbol": item.get("symbol"), "line_start": item.get("line_start"),
        "line_end": item.get("line_end"), "provenance": REPOSITORY_EVIDENCE,
    } for item in reconnaissance.get("evidence", [])[:MAX_TASK_BRAIN_EVIDENCE]
       if validate_repository_evidence(item)]
    summary = {
        "authority": "CURRENT_OBSERVED_REPOSITORY_STATE",
        "project_mode": project_mode,
        "status": reconnaissance.get("status"),
        "facts": facts,
        "truncated": bool(reconnaissance.get("truncated")),
        "rule": "facts are current observations; proposed architecture must remain DERIVED",
    }
    while _json_size(summary) > max_chars and summary["facts"]:
        summary["facts"].pop()
        summary["truncated"] = True
    return json.dumps(summary, ensure_ascii=False, default=str)


def repository_grounded_questions(raw_goal, source_requirements, evidence):
    """Create only evidence-backed material remove/preserve conflict questions."""
    text = str(raw_goal or "")
    missing_symbols = [
        item for item in evidence or []
        if validate_repository_evidence(item)
        and item.get("category") == "CURRENT_CONSTRAINT"
        and "was not found" in str(item.get("fact", "")).casefold()
        and item.get("symbol")
    ]
    if missing_symbols and _MODIFICATION_RE.search(text):
        item = missing_symbols[0]
        symbol = str(item.get("symbol"))
        requirement_ids = [
            str(requirement.get("requirement_id")) for requirement in source_requirements or []
            if isinstance(requirement, dict)
            and symbol.casefold() in str(requirement.get("text", "")).casefold()
        ]
        if requirement_ids:
            return [{
                "question_id": "REPO-Q-001",
                "question": (
                    f"The inspected project does not contain {symbol}. Should the task adapt the repository's "
                    "current owner while preserving public behavior, or introduce the named interface?"
                ),
                "reason": "A task-named current interface is absent from the verified repository state.",
                "affected_requirement_ids": requirement_ids,
                "repository_evidence_ids": [item.get("evidence_id")],
                "impact_if_unknown": (
                    "The first option preserves current architecture; the second introduces a new public owner."
                ),
                "recommended_option": "Adapt the repository's current owner and preserve public behavior",
                "options": [
                    "Adapt the repository's current owner and preserve public behavior",
                    f"Introduce {symbol} as a new public interface",
                ],
                "allow_other": True, "blocking": True,
                "category": "repository_discrepancy",
                "phase": "REPOSITORY_GROUNDED_CLARIFICATION",
            }]
    destructive = re.search(
        r"\b(?:remove|delete|replace|retire|drop)\s+([\w ._-]{2,60}?)"
        r"(?=\s+(?:while\s+)?preserv(?:e|ing)\b|[.;]|$)",
        text, re.IGNORECASE,
    )
    preserve = re.search(
        r"\b(?:preserv(?:e|ing)|keep|retain|without breaking)\s+([\w ._-]{2,60}?)(?=[.;]|$)",
        text, re.IGNORECASE,
    )
    if not destructive or not preserve:
        return []
    remove_terms = {
        token for token in re.findall(r"[a-z0-9_]{3,}", destructive.group(1).casefold())
        if token not in _STOP_WORDS
    }
    preserve_terms = {
        token for token in re.findall(r"[a-z0-9_]{3,}", preserve.group(1).casefold())
        if token not in _STOP_WORDS
    }
    supporting = []
    for item in evidence or []:
        if not validate_repository_evidence(item):
            continue
        observed = " ".join(str(item.get(key, "")) for key in ("fact", "path", "symbol", "support")).casefold()
        if any(term in observed for term in remove_terms) and any(term in observed for term in preserve_terms):
            supporting.append(item)
    if not supporting:
        return []
    known_ids = []
    for requirement in source_requirements or []:
        if not isinstance(requirement, dict):
            continue
        requirement_text = str(requirement.get("text", "")).casefold()
        if any(term in requirement_text for term in remove_terms | preserve_terms):
            known_ids.append(str(requirement.get("requirement_id")))
    evidence_ids = [item.get("evidence_id") for item in supporting[:4]]
    remove_label = _compact(destructive.group(1), 100)
    preserve_label = _compact(preserve.group(1), 100)
    return [{
        "question_id": "REPO-Q-001",
        "question": (
            f"Repository evidence shows that {remove_label} also participates in {preserve_label}. "
            "Should the shared behavior be extracted before removal, or should the current owner remain?"
        ),
        "reason": "The requested removal and preservation target share an observed current owner.",
        "affected_requirement_ids": known_ids,
        "repository_evidence_ids": evidence_ids,
        "impact_if_unknown": (
            f"Removing the current owner may also remove the requested {preserve_label} behavior."
        ),
        "recommended_option": f"Extract and preserve {preserve_label} before removing {remove_label}",
        "options": [
            f"Extract and preserve {preserve_label} before removing {remove_label}",
            f"Keep the current owner so {preserve_label} remains unchanged",
        ],
        "allow_other": True, "blocking": True, "category": "repository_conflict",
        "phase": "REPOSITORY_GROUNDED_CLARIFICATION",
    }]


def validate_repository_question(question, valid_requirement_ids, valid_evidence_ids):
    if not isinstance(question, dict):
        return False
    requirement_ids = [str(item) for item in question.get("affected_requirement_ids", [])]
    evidence_ids = [str(item) for item in question.get("repository_evidence_ids", [])]
    return bool(
        str(question.get("question", "")).strip()
        and requirement_ids
        and evidence_ids
        and set(requirement_ids).issubset(set(valid_requirement_ids or []))
        and set(evidence_ids).issubset(set(valid_evidence_ids or []))
        and question.get("phase") == "REPOSITORY_GROUNDED_CLARIFICATION"
    )


def _entry(text, provenance, requirement_ids=None, evidence_ids=None, **extra):
    result = {
        "text": _compact(text, 420), "provenance": provenance,
        "requirement_ids": [str(item) for item in (requirement_ids or []) if item][:12],
        "evidence_ids": [str(item) for item in (evidence_ids or []) if item][:8],
    }
    result.update({key: value for key, value in extra.items() if value not in (None, "", [], {})})
    return result


def _flatten_project_facts(project_brain_projection):
    projection = project_brain_projection if isinstance(project_brain_projection, dict) else {}
    core = projection.get("relevant_core") if isinstance(projection.get("relevant_core"), dict) else {}
    facts = []
    for field in (
        "architecture_invariants", "state_ownership", "interface_contracts",
        "project_specific_quality_rules", "interaction_contracts", "major_components",
    ):
        for item in core.get(field, []) or []:
            text = item.get("text") if isinstance(item, dict) else item
            if str(text or "").strip():
                facts.append(_entry(text, PROJECT_BRAIN, project_brain_field=field))
    return facts[:MAX_TASK_BRAIN_PROJECT_FACTS]


def _repo_entry(record):
    return _entry(
        record.get("fact", ""), REPOSITORY_EVIDENCE,
        evidence_ids=[record.get("evidence_id")], path=record.get("path"),
        symbol=record.get("symbol"), category=record.get("category"),
    )


def build_task_brain(task_id, task_goal, project_mode, contract, project_brain_projection=None,
                     repository_evidence=None, open_questions=None):
    """Assemble one temporary bounded Task Brain from already-established facts."""
    contract = contract if isinstance(contract, dict) else {}
    ledger = contract.get("source_requirement_ledger")
    source_records = ledger_requirements(ledger)
    source_ids = [str(item.get("requirement_id")) for item in source_records if item.get("requirement_id")]
    evidence = [
        item for item in (repository_evidence or [])
        if validate_repository_evidence(item)
    ][:MAX_TASK_BRAIN_EVIDENCE]
    by_category = {}
    for item in evidence:
        by_category.setdefault(item.get("category"), []).append(_repo_entry(item))
    confirmed = []
    for item in contract.get("user_confirmed_requirements", []) or []:
        if not isinstance(item, dict):
            continue
        confirmed.append(_entry(
            item.get("answer") or item.get("text", ""), USER_CONFIRMED,
            requirement_ids=item.get("affected_requirement_ids", []),
            evidence_ids=item.get("repository_evidence_ids", []),
            question_id=item.get("question_id"), decision_id=item.get("decision_id"),
        ))
    derived = []
    for item in contract.get("derived_assumptions", []) or []:
        value = item.get("text") or item.get("answer", "") if isinstance(item, dict) else item
        if str(value or "").strip():
            derived.append(_entry(value, DERIVED_TASK_ASSUMPTION))
    project_facts = _flatten_project_facts(project_brain_projection)
    projection = project_brain_projection if isinstance(project_brain_projection, dict) else {}
    core = projection.get("relevant_core") if isinstance(projection.get("relevant_core"), dict) else {}
    product = core.get("product_contract") if isinstance(core.get("product_contract"), dict) else {}
    acceptance = [
        _entry(value, PROJECT_BRAIN)
        for value in (product.get("acceptance_criteria", []) or [])[:8]
        if str(value or "").strip()
    ]
    preservation = list(by_category.get("CURRENT_CONSTRAINT", []))
    for source in source_records:
        if re.search(r"\b(?:preserve|keep|retain|without breaking|compatib)\b", str(source.get("text", "")), re.IGNORECASE):
            preservation.append(_entry(
                source.get("text", ""), USER_STATED,
                requirement_ids=[source.get("requirement_id")],
            ))
    questions = []
    for item in (open_questions or [])[:MAX_TASK_BRAIN_OPEN_QUESTIONS]:
        if not isinstance(item, dict):
            continue
        questions.append(_entry(
            item.get("question", ""), REPOSITORY_EVIDENCE,
            requirement_ids=item.get("affected_requirement_ids", []),
            evidence_ids=item.get("repository_evidence_ids", []),
            question_id=item.get("question_id"), phase=item.get("phase"),
        ))
    evidence_index = [{
        "evidence_id": item.get("evidence_id"), "provenance": REPOSITORY_EVIDENCE,
        "category": item.get("category"), "fact": _compact(item.get("fact", ""), 220),
        "path": item.get("path"), "symbol": item.get("symbol"),
        "line_start": item.get("line_start"), "line_end": item.get("line_end"),
        "file_sha256": item.get("file_sha256"),
    } for item in evidence]
    brain = {
        "version": 1,
        "task_id": _compact(task_id, 100),
        "task_goal": _entry(task_goal, USER_STATED, requirement_ids=source_ids),
        "project_mode": project_mode,
        "source_requirement_ids": source_ids,
        "user_confirmed_decisions": confirmed[:MAX_TASK_BRAIN_ASSUMPTIONS],
        "relevant_project_brain_projection": project_facts,
        "repository_evidence_ids": [item.get("evidence_id") for item in evidence],
        "current_owners": by_category.get("CURRENT_OWNER", [])[:MAX_TASK_BRAIN_INTERFACES],
        "current_interfaces": by_category.get("CURRENT_INTERFACE", [])[:MAX_TASK_BRAIN_INTERFACES],
        "current_state_ownership": by_category.get("CURRENT_STATE_OWNER", [])[:MAX_TASK_BRAIN_INTERFACES],
        "relevant_dependencies": by_category.get("CURRENT_DEPENDENCY", [])[:MAX_TASK_BRAIN_INTERFACES],
        "relevant_tests": by_category.get("CURRENT_TEST", [])[:MAX_TASK_BRAIN_TESTS],
        "preservation_constraints": preservation[:MAX_TASK_BRAIN_INTERFACES],
        "derived_task_assumptions": derived[:MAX_TASK_BRAIN_ASSUMPTIONS],
        "open_questions": questions,
        "acceptance_conditions": acceptance[:8],
        "known_non_goals": [
            _entry(value, PROJECT_BRAIN)
            for value in (core.get("non_goals", []) or [])[:6]
            if str(value or "").strip()
        ],
        "evidence_index": evidence_index,
        "bounds": {
            "max_serialized_chars": MAX_TASK_BRAIN_CHARS,
            "max_evidence": MAX_TASK_BRAIN_EVIDENCE,
            "max_tests": MAX_TASK_BRAIN_TESTS,
            "max_interfaces": MAX_TASK_BRAIN_INTERFACES,
            "max_derived_assumptions": MAX_TASK_BRAIN_ASSUMPTIONS,
            "max_open_questions": MAX_TASK_BRAIN_OPEN_QUESTIONS,
            "truncated": False, "overflow": {},
        },
    }
    original_counts = {
        "repository_evidence": len(repository_evidence or []),
        "user_confirmed_decisions": len(contract.get("user_confirmed_requirements", []) or []),
        "derived_task_assumptions": len(contract.get("derived_assumptions", []) or []),
        "open_questions": len(open_questions or []),
    }
    kept_counts = {
        "repository_evidence": len(evidence),
        "user_confirmed_decisions": len(brain["user_confirmed_decisions"]),
        "derived_task_assumptions": len(brain["derived_task_assumptions"]),
        "open_questions": len(brain["open_questions"]),
    }
    overflow = {
        key: original_counts[key] - kept_counts[key]
        for key in original_counts if original_counts[key] > kept_counts[key]
    }
    if overflow:
        brain["bounds"]["truncated"] = True
        brain["bounds"]["overflow"].update(overflow)
    trim_order = (
        "known_non_goals", "derived_task_assumptions", "relevant_dependencies",
        "preservation_constraints", "relevant_project_brain_projection", "current_interfaces",
        "current_state_ownership", "current_owners", "relevant_tests", "acceptance_conditions",
    )
    trimmed = 0
    while _json_size(brain) > MAX_TASK_BRAIN_CHARS:
        removed = False
        for field in trim_order:
            values = brain.get(field)
            if isinstance(values, list) and len(values) > 1:
                values.pop()
                trimmed += 1
                removed = True
                break
        if not removed:
            break
    if trimmed:
        brain["bounds"]["truncated"] = True
        brain["bounds"]["overflow"]["serialized_size_items"] = trimmed
    return brain


_TASK_BRAIN_ENTRY_FIELDS = (
    "user_confirmed_decisions", "relevant_project_brain_projection", "current_owners",
    "current_interfaces", "current_state_ownership", "relevant_dependencies",
    "relevant_tests", "preservation_constraints", "derived_task_assumptions",
    "open_questions", "acceptance_conditions", "known_non_goals",
)
_FORBIDDEN_TASK_BRAIN_KEYS = frozenset({
    "source_requirement_ledger", "conversation", "conversation_history", "messages",
    "raw_conversation", "transcript", "recon_agent_transcript", "worker_transcript",
    "chain_of_thought", "reasoning", "file_contents", "full_file_contents",
})


def validate_task_brain(task_brain, valid_requirement_ids=None, repository_evidence=None):
    """Return a deterministic validation envelope; invalid brains cannot reach planning."""
    errors = []
    brain = task_brain if isinstance(task_brain, dict) else {}
    valid_requirement_ids = set(str(item) for item in (valid_requirement_ids or []))
    valid_evidence_ids = {
        str(item.get("evidence_id")) for item in (repository_evidence or [])
        if validate_repository_evidence(item)
    }
    if not str(brain.get("task_id", "")).strip():
        errors.append("task_id is required")
    goal = brain.get("task_goal")
    if not isinstance(goal, dict) or not str(goal.get("text", "")).strip() or goal.get("provenance") != USER_STATED:
        errors.append("task_goal must be a USER_STATED entry")
    if brain.get("project_mode") not in {NEW_PROJECT, EXISTING_PROJECT}:
        errors.append("project_mode is invalid")
    source_ids = [str(item) for item in brain.get("source_requirement_ids", [])]
    if valid_requirement_ids and not set(source_ids).issubset(valid_requirement_ids):
        errors.append("Task Brain references an unknown Source Requirement ID")
    evidence_ids = [str(item) for item in brain.get("repository_evidence_ids", [])]
    if not set(evidence_ids).issubset(valid_evidence_ids):
        errors.append("Task Brain references an unknown repository evidence ID")
    for field in _TASK_BRAIN_ENTRY_FIELDS:
        values = brain.get(field)
        if not isinstance(values, list):
            errors.append(f"{field} must be a list")
            continue
        for item in values:
            if not isinstance(item, dict) or item.get("provenance") not in TASK_BRAIN_PROVENANCE:
                errors.append(f"{field} contains invalid provenance")
                break
            if not set(str(value) for value in item.get("evidence_ids", [])).issubset(valid_evidence_ids):
                errors.append(f"{field} references unknown repository evidence")
                break
    if len(brain.get("evidence_index", [])) > MAX_TASK_BRAIN_EVIDENCE:
        errors.append("Task Brain evidence bound exceeded")
    if len(brain.get("relevant_tests", [])) > MAX_TASK_BRAIN_TESTS:
        errors.append("Task Brain test-reference bound exceeded")
    if len(brain.get("current_interfaces", [])) > MAX_TASK_BRAIN_INTERFACES:
        errors.append("Task Brain interface bound exceeded")
    if len(brain.get("derived_task_assumptions", [])) > MAX_TASK_BRAIN_ASSUMPTIONS:
        errors.append("Task Brain assumption bound exceeded")
    if len(brain.get("open_questions", [])) > MAX_TASK_BRAIN_OPEN_QUESTIONS:
        errors.append("Task Brain open-question bound exceeded")
    if _json_size(brain) > MAX_TASK_BRAIN_CHARS:
        errors.append("Task Brain serialized-size bound exceeded")

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).casefold() in _FORBIDDEN_TASK_BRAIN_KEYS:
                    errors.append(f"forbidden Task Brain field: {key}")
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(brain)
    return {"valid": not errors, "errors": errors[:12], "serialized_chars": _json_size(brain)}


def task_brain_projection(task_brain, task=None, max_chars=MAX_TASK_BRAIN_PROJECTION_CHARS):
    """Select one bounded task/node slice; never return the full Task Brain."""
    brain = task_brain if isinstance(task_brain, dict) else {}
    task = task if isinstance(task, dict) else {}
    query = " ".join([
        str(task.get("goal", "")),
        " ".join(str(item) for item in task.get("done_when", []) or []),
        " ".join(str(item) for item in task.get("scope_hint", []) or []),
    ]).casefold()
    terms = {token for token in re.findall(r"[a-z0-9_$.-]{3,}", query) if token not in _STOP_WORDS}

    def relevant(values, limit):
        values = list(values or [])
        if not terms or str(task.get("id", "")) == "ROOT":
            return values[:limit]
        scored = []
        for index, item in enumerate(values):
            encoded = json.dumps(item, ensure_ascii=False, default=str).casefold()
            overlap = sum(1 for term in terms if term in encoded)
            if overlap:
                scored.append((-overlap, index, item))
        scored.sort(key=lambda row: (row[0], row[1]))
        return [row[2] for row in scored[:limit]]

    projection = {
        "task_id": brain.get("task_id"),
        "task_goal": brain.get("task_goal"),
        "project_mode": brain.get("project_mode"),
        "source_requirement_ids": list(brain.get("source_requirement_ids", [])),
        "user_confirmed_decisions": relevant(brain.get("user_confirmed_decisions"), 4),
        "relevant_project_brain_projection": relevant(brain.get("relevant_project_brain_projection"), 5),
        "current_owners": relevant(brain.get("current_owners"), 5),
        "current_interfaces": relevant(brain.get("current_interfaces"), 5),
        "current_state_ownership": relevant(brain.get("current_state_ownership"), 5),
        "relevant_dependencies": relevant(brain.get("relevant_dependencies"), 4),
        "relevant_tests": relevant(brain.get("relevant_tests"), 4),
        "preservation_constraints": relevant(brain.get("preservation_constraints"), 4),
        "derived_task_assumptions": relevant(brain.get("derived_task_assumptions"), 3),
        "acceptance_conditions": relevant(brain.get("acceptance_conditions"), 5),
        "known_non_goals": relevant(brain.get("known_non_goals"), 3),
    }
    trim_order = (
        "known_non_goals", "derived_task_assumptions", "relevant_dependencies",
        "relevant_project_brain_projection", "current_interfaces", "current_state_ownership",
        "current_owners", "relevant_tests", "preservation_constraints", "acceptance_conditions",
        "user_confirmed_decisions",
    )
    while _json_size(projection) > max_chars:
        removed = False
        for field in trim_order:
            values = projection.get(field)
            if isinstance(values, list) and values:
                values.pop()
                removed = True
                break
        if not removed:
            projection["source_requirement_ids"] = projection.get("source_requirement_ids", [])[:16]
            break
    return projection
