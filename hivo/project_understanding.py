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
_SEARCH_INTENT_WORDS = frozenset({
    "add", "adding", "allow", "another", "architecture", "build", "change", "compatibility",
    "compatible", "create", "creating", "current", "duplicate", "existing", "extend", "feature", "key",
    "fix", "implement", "implementation", "instead", "keep", "maintain", "modify", "preserve",
    "owner", "ownership", "preserving", "rather", "refactor", "remove", "replace", "required", "resume", "reuse", "support",
    "task", "update", "use", "using", "with", "while", "than", "second", "not",
    "introduce", "introduced", "currently", "uses", "make", "makes", "easier",
    "understand", "replacing", "does", "do", "another",
})
_SEARCH_ROLE_WORDS = frozenset({
    "assert", "assertion", "spec", "test", "tests",
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
_CLASS_DECLARATION_RE = re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)")
_OBJECT_DECLARATION_RE = re.compile(
    r"\b(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\{"
)
_FUNCTION_DECLARATION_RE = re.compile(
    r"\b(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(|"
    r"\bdef\s+([A-Za-z_$][\w$]*)\s*\(|"
    r"\b(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\([^\n]*\)\s*=>)"
)
_METHOD_DECLARATION_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|static|async|get|set)\s+)*(?:def\s+)?"
    r"([A-Za-z_$][\w$]*)\s*\([^;{}\n]*\)\s*\{"
)
_IMPORT_SYMBOL_RE = re.compile(
    r"(?:import\s+\{([^}]+)\}|(?:const|let|var)\s+\{([^}]+)\}\s*=\s*require\s*\()"
)
_INPUT_SIGNAL_RE = re.compile(
    r"\b(?:input|keyboard|keydown|keyup|arrow|wasd|supportedkeys|ispressed)\b",
    re.IGNORECASE,
)
_STRONG_INPUT_SIGNAL_RE = re.compile(
    r"\b(?:keyboard|keydown|keyup|arrow|wasd|supportedkeys|ispressed)\b",
    re.IGNORECASE,
)
_KEY_STATE_RE = re.compile(
    r"(?:\bthis\s*\.\s*[A-Za-z_$]*keys?\b|\b(?:pressed|held|active)?keys?\s*[:=]|\b(?:pressed|held|active)?keys?\s*\.\s*(?:add|delete|has)\s*\(|"
    r"\b(?:keyboard|key)[-_ ]?(?:state|set|map)\b|\b(?:this\s*\.\s*)?(?:state|store)\s*=)",
    re.IGNORECASE,
)
_PAUSE_STATE_RE = re.compile(
    r"(?:\bthis\s*\.\s*paused\b|\bpaused\s*[:=]|\b(?:pause|paused)[-_ ]?(?:state|flag)\b)",
    re.IGNORECASE,
)
_PAUSE_INTERFACE_RE = re.compile(r"\b(?:togglePause|pause|resume)\s*\(", re.IGNORECASE)
_STRONG_PERSISTENCE_RE = re.compile(
    r"(?:localStorage|sessionStorage|indexedDB|setItem\s*\(|getItem\s*\(|save[A-Za-z_$]*\s*\(|"
    r"load[A-Za-z_$]*\s*\(|persistent\s+(?:store|score|state))",
    re.IGNORECASE,
)
_PERSISTENCE_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9_]*KEY\b")
_TEST_ASSERTION_RE = re.compile(
    r"\b(?:test|it|describe|specify|assert|expect)\s*(?:\(|\.)|\b(?:assert|expect)\b",
    re.IGNORECASE,
)
_CONTROL_FLOW_METHODS = frozenset({"catch", "constructor", "for", "if", "switch", "while"})


def _has_strong_persistence(value):
    return bool(_STRONG_PERSISTENCE_RE.search(str(value or "")) or _PERSISTENCE_KEY_RE.search(str(value or "")))


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


def _search_term_variants(term):
    """Return bounded literal variants for one logical search term."""
    value = str(term or "").strip()
    if not value:
        return []
    variants = [value]
    if "-" in value:
        parts = [part for part in re.split(r"-+", value) if len(part) >= 3]
        if len(parts) > 1:
            variants.append(" ".join(parts))
            variants.extend(parts)
    # A slash-delimited control phrase (for example WASD/arrow) should still
    # expose each useful component without making it a new logical search.
    if "/" in value:
        variants.extend(part for part in re.split(r"/+", value) if len(part) >= 3)
    unique = []
    for variant in variants:
        key = variant.casefold()
        if key and key not in {item.casefold() for item in unique}:
            unique.append(variant)
    return unique[:5]


def _search_term_weight(term):
    value = str(term or "")
    key = value.casefold()
    if key in _SEARCH_INTENT_WORDS:
        return 1
    if key in _SEARCH_ROLE_WORDS:
        return 5
    if "-" in value:
        return 7
    if value.isupper() or "." in value or "_" in value:
        return 7
    return 4


def repository_search_terms(raw_goal, source_requirements=None, max_searches=MAX_RECON_SEARCHES):
    """Extract bounded, task-grounded terms with useful hyphen expansion.

    The returned list contains logical search terms.  ``search_repository``
    expands a compound term such as ``pause-state`` into its source-searchable
    variants without consuming another logical search slot.
    """
    values = [str(raw_goal or "")]
    for item in source_requirements or []:
        if isinstance(item, dict):
            values.append(str(item.get("text", "")))
        else:
            values.append(str(item))
    text = "\n".join(values)
    normalized_text = text.casefold()
    candidates = {}
    order = 0
    represented_parts = set()

    def add(value, priority, kind="content"):
        nonlocal order
        value = str(value or "").strip("`'\".,:;()[]{}")
        if len(value) < 3:
            return
        key = value.casefold()
        if key in _STOP_WORDS:
            return
        entry = candidates.get(key)
        if entry is None:
            entry = {
                "value": value, "priority": int(priority), "kind": kind,
                "order": order,
            }
            candidates[key] = entry
            order += 1
        else:
            entry["priority"] = min(entry["priority"], int(priority))
            if kind == "identifier":
                entry["kind"] = kind

    # Exact code-like spellings are the strongest search anchors.  Generic
    # sentence-leading verbs are excluded from this tier so ``Preserve`` and
    # ``Update`` cannot displace domain terms.
    identifier_pattern = (
        r"\b[A-Z][A-Za-z0-9_$]{2,}\b|"
        r"\b[a-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b|"
        r"\b\w+(?:\.\w+)+\b"
    )
    for token in re.findall(identifier_pattern, text):
        if token.casefold() in _SEARCH_INTENT_WORDS or token.casefold() in _STOP_WORDS:
            continue
        # Sentence-leading title case (``Escape``, ``Preserve``) is ordinary
        # prose, not necessarily a repository symbol.  Retain all-uppercase,
        # snake/dotted, or internally-capitalized spellings as code anchors.
        if (
            token[:1].isupper() and not token.isupper()
            and not any(character.isupper() for character in token[1:])
            and "_" not in token and "." not in token
        ):
            continue
        add(token, 0, "identifier")

    # Keep a hyphenated engineering phrase as one logical term, while marking
    # its components as represented.  Search itself expands these components.
    for token in re.findall(r"\b[A-Za-z0-9_$]+(?:-[A-Za-z0-9_$]+)+\b", text):
        parts = [part for part in re.split(r"-+", token) if len(part) >= 3]
        if not parts:
            continue
        # A title-cased prose modifier such as ``Escape-key`` is more useful
        # as its components than as a scarce logical search slot.  Lowercase
        # engineering compounds (``pause-state``/``best-score``) stay intact.
        compound_priority = 3 if (
            parts[0][:1].isupper() and not parts[0].isupper()
            and not any(character.isupper() for character in parts[0][1:])
        ) else 1
        add(token, compound_priority, "compound")
        if compound_priority == 1:
            represented_parts.update(part.casefold() for part in parts)

    for token in re.findall(r"[A-Za-z0-9_$]+", text):
        key = token.casefold()
        if len(token) < 3 or key in _STOP_WORDS or key in represented_parts:
            continue
        if key in _SEARCH_INTENT_WORDS:
            # Imperative verbs and generic constraint words guide extraction,
            # but are poor repository anchors and must not consume the cap.
            continue
        if key in _SEARCH_ROLE_WORDS:
            priority = 2
            kind = "role"
        else:
            priority = 2
            kind = "content"
        add(token, priority, kind)

    def importance(entry):
        key = entry["value"].casefold()
        variants = _search_term_variants(entry["value"])
        frequency = sum(normalized_text.count(variant.casefold()) for variant in variants)
        role_bonus = 4 if key in _SEARCH_ROLE_WORDS else 0
        compound_bonus = 2 if entry["kind"] == "compound" else 0
        identifier_bonus = 2 if entry["kind"] == "identifier" else 0
        return frequency + role_bonus + compound_bonus + identifier_bonus

    ordered = sorted(
        candidates.values(),
        key=lambda entry: (entry["priority"], -importance(entry), entry["order"], entry["value"].casefold()),
    )
    return [entry["value"] for entry in ordered[:max(0, int(max_searches))]]


def _named_task_symbols(raw_goal):
    symbols = []
    for value in re.findall(
        r"\b[A-Z][A-Za-z0-9_$]{2,}\b|\b[a-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b|\b\w+(?:\.\w+)+\b",
        str(raw_goal or ""),
    ):
        key = value.casefold()
        if key in _STOP_WORDS or key in _SEARCH_INTENT_WORDS or value in symbols:
            continue
        if (
            value[:1].isupper() and not value.isupper()
            and not any(character.isupper() for character in value[1:])
            and "_" not in value and "." not in value
        ):
            continue
        if value.isupper() and "_" not in value and "." not in value:
            # Domain acronyms such as WASD/API/SSO are search vocabulary, not
            # exact named interfaces whose absence should trigger a question.
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
            locations = []
            for variant in _search_term_variants(term):
                needle = variant.casefold()
                if needle in path_lower:
                    locations.append(0)
                for line_number, line in enumerate(lines, 1):
                    if needle in line.casefold():
                        locations.append(line_number)
                        if len(locations) >= 6:
                            break
                if len(locations) >= 6:
                    break
            if locations:
                record = matches_by_path.setdefault(relative, {"path": relative, "terms": [], "lines": []})
                record["terms"].append(term)
                record["lines"].extend(locations)
                if "declaration_names" not in record:
                    record["declaration_names"] = []
                    for declaration_line in lines:
                        declaration_match = re.search(
                            r"\bclass\s+([A-Za-z_$][\w$]*)|\b(?:function|def|interface)\s+([A-Za-z_$][\w$]*)|"
                            r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=",
                            declaration_line,
                        )
                        if declaration_match:
                            record["declaration_names"].extend(
                                value for value in declaration_match.groups() if value
                            )
                    record["strong_persistence"] = _has_strong_persistence(content)
                variants = _search_term_variants(term)
                match_strength = 0
                for variant_index, variant in enumerate(variants):
                    if variant.casefold() not in path_lower and not any(
                        variant.casefold() in line.casefold() for line in lines
                    ):
                        continue
                    base = _search_term_weight(term)
                    if variant_index == 0:
                        strength = base * 2
                    elif " " in variant:
                        strength = base
                    else:
                        # A component match (``score`` inside ``best-score``)
                        # is useful but weaker than the complete task phrase.
                        strength = max(1, base // 2)
                    if variant.casefold() in path_lower:
                        strength += base
                    match_strength = max(match_strength, strength)
                record.setdefault("term_strength", {})[term] = match_strength
    ranked = []
    by_path = {item.get("path"): item for item in inventory.get("files", [])}
    for relative, match in matches_by_path.items():
        item = by_path.get(relative, {})
        unique_lines = sorted(set(int(value) for value in match.get("lines", []) if int(value) > 0))
        unique_terms = list(dict.fromkeys(str(value) for value in match.get("terms", [])))
        term_strength = match.get("term_strength", {}) if isinstance(match, dict) else {}
        score = sum(int(term_strength.get(value, _search_term_weight(value))) for value in unique_terms)
        score += 5 if _is_test_path(relative) else 0
        score += 7 if item.get("kind") == "SOURCE" else 0
        score += 1 if item.get("kind") == "ENTRYPOINT" else 0
        declaration_names = list(match.get("declaration_names", []))
        declaration_overlap = sum(
            1 for term in unique_terms
            if any(
                any(variant.casefold() in name.casefold() for variant in _search_term_variants(term))
                for name in declaration_names
            )
        )
        # A task term in a declaration/name is stronger than the same term in
        # an incidental comment or repeated fixture text.
        score += declaration_overlap * 12
        score += 10 if match.get("strong_persistence") else 0
        ranked.append({
            "path": relative, "terms": unique_terms[:MAX_RECON_SEARCHES],
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


def _line_window(lines, start, end=None, radius=1, max_lines=8):
    """Return a bounded inclusive line window around one or more anchors."""
    if not lines:
        return 1, 1, ""
    anchors = [int(value) for value in ([start] if end is None else [start, end]) if int(value or 0) > 0]
    if not anchors:
        anchors = [1]
    first = min(anchors)
    last = max(anchors)
    if end is None:
        first = max(1, first - int(radius))
        last = min(len(lines), last + int(radius))
    max_lines = max(1, int(max_lines))
    if last - first + 1 > max_lines:
        last = min(len(lines), first + max_lines - 1)
    return first, last, "\n".join(lines[first - 1:last])


def _declaration_records(lines):
    """Yield source declarations with their line numbers and enclosing class."""
    current_class = ""
    for number, line in enumerate(lines, 1):
        class_match = _CLASS_DECLARATION_RE.search(line)
        if class_match:
            current_class = class_match.group(1)
            yield {
                "kind": "class", "name": current_class, "qualified": current_class,
                "line": number, "class": current_class,
            }
            continue
        object_match = _OBJECT_DECLARATION_RE.search(line)
        if object_match:
            name = object_match.group(1)
            current_class = name
            yield {
                "kind": "object", "name": name, "qualified": name,
                "line": number, "class": name,
            }
            continue
        function_match = _FUNCTION_DECLARATION_RE.search(line)
        if function_match:
            name = next((value for value in function_match.groups() if value), "")
            if name:
                yield {
                    "kind": "function", "name": name,
                    "qualified": f"{current_class}.{name}" if current_class else name,
                    "line": number, "class": current_class,
                }
        method_match = _METHOD_DECLARATION_RE.match(line)
        if method_match:
            name = method_match.group(1)
            if name.casefold() not in _CONTROL_FLOW_METHODS:
                yield {
                    "kind": "method", "name": name,
                    "qualified": f"{current_class}.{name}" if current_class else name,
                    "line": number, "class": current_class,
                }


def _source_term_match(content, terms):
    normalized = str(content or "").casefold()
    for term in terms or []:
        if any(variant.casefold() in normalized for variant in _search_term_variants(term)):
            return True
    return False


def _source_support(lines, anchors, max_lines=8):
    anchors = [int(value) for value in anchors or [] if int(value or 0) > 0]
    if not anchors:
        anchors = [1]
    first = min(anchors)
    last = max(anchors)
    if last - first + 1 > int(max_lines):
        # Keep the later state/API anchor in the compact range.  The symbol and
        # full-file hash still bind the fact to the declaration, while the
        # support window contains the behavior-bearing line that validates it.
        first = max(1, last - int(max_lines) + 1)
    return _line_window(lines, first, last, max_lines=max_lines)


def _evidence_candidate(category, fact, path, symbol, source_kind, line_start, line_end,
                        file_sha256, support, quality=0, semantic_key=None):
    return {
        "evidence_id": "", "fact": _compact(fact, 360), "category": category,
        "path": path, "symbol": symbol or None, "source_kind": source_kind,
        "evidence_type": DIRECT_OBSERVATION, "provenance": REPOSITORY_EVIDENCE,
        "line_start": int(line_start), "line_end": int(line_end),
        "file_sha256": file_sha256, "support": _compact(support, 420),
        "_quality": int(quality), "_semantic_key": semantic_key or "",
    }


def _test_imported_symbol(lines):
    for line in lines:
        match = _IMPORT_SYMBOL_RE.search(line)
        if not match:
            continue
        values = match.group(1) or match.group(2) or ""
        for value in values.split(","):
            symbol = value.strip().split(" as ")[-1].strip()
            if re.fullmatch(r"[A-Z][A-Za-z0-9_$]*", symbol):
                return symbol
    return ""


def _test_referenced_symbol(content):
    """Find a likely application symbol in a test without treating test APIs as owners."""
    ignored = {
        "assert", "expect", "describe", "it", "test", "specify", "input", "escape",
        "true", "false", "null", "undefined", "promise", "string", "number",
    }
    for value in re.findall(r"\b[A-Z][A-Za-z0-9_$]{2,}\b", content):
        if value.casefold() not in ignored:
            return value
    return ""


def _semantic_evidence_candidates(relative, lines, fingerprint, candidate_terms, task_terms):
    """Extract compact source-backed facts from one already selected file."""
    kind = _file_kind(relative)
    content = "\n".join(lines)
    normalized = content.casefold()
    candidates = []

    if kind == "TEST":
        if _TEST_ASSERTION_RE.search(content):
            test_lines = [
                number for number, line in enumerate(lines, 1)
                if _TEST_ASSERTION_RE.search(line)
            ]
            imported = _test_imported_symbol(lines) or _test_referenced_symbol(content)
            import_lines = [
                number for number, line in enumerate(lines, 1)
                if _IMPORT_SYMBOL_RE.search(line)
            ]
            anchors = (import_lines[:1] + test_lines[:2]) or [1]
            start, end, support = _source_support(lines, anchors, max_lines=8)
            focus = "keyboard/input behavior" if _INPUT_SIGNAL_RE.search(content) else "task behavior"
            if imported:
                focus = f"{imported} {focus}"
            candidates.append(_evidence_candidate(
                "CURRENT_TEST", f"{relative} protects {focus}", relative, imported,
                kind, start, end, fingerprint, support, quality=70,
                semantic_key=f"CURRENT_TEST|{relative}|{imported or focus}",
            ))
        return candidates

    if kind == "ENTRYPOINT":
        anchor = next((number for number, line in enumerate(lines, 1) if line.strip()), 1)
        start, end, support = _line_window(lines, anchor, radius=1, max_lines=4)
        candidates.append(_evidence_candidate(
            "CURRENT_ENTRYPOINT", f"{relative} is a task-relevant current entrypoint", relative, "",
            kind, start, end, fingerprint, support, quality=12,
            semantic_key=f"CURRENT_ENTRYPOINT|{relative}",
        ))
        # An entrypoint is persistence evidence only when the entrypoint itself
        # executes a persistence API; a script tag merely loading storage.js
        # is not enough.
        if _has_strong_persistence(content):
            persistence_line = next(
                (number for number, line in enumerate(lines, 1) if _has_strong_persistence(line)),
                anchor,
            )
            start, end, support = _line_window(lines, persistence_line, radius=1, max_lines=4)
            candidates.append(_evidence_candidate(
                "CURRENT_PERSISTENCE", f"{relative} contains direct persistence behavior", relative, "",
                kind, start, end, fingerprint, support, quality=58,
                semantic_key=f"CURRENT_PERSISTENCE|{relative}",
            ))
        return candidates

    declarations = list(_declaration_records(lines))
    class_records = [item for item in declarations if item["kind"] in {"class", "object"}]
    methods = [item for item in declarations if item["kind"] == "method"]
    source_focus = _source_term_match(content, task_terms or candidate_terms)

    for class_record in class_records:
        name = class_record["name"]
        class_line = class_record["line"]
        input_signal = (
            bool(_STRONG_INPUT_SIGNAL_RE.search(content))
            or any(token in name.casefold() for token in ("input", "keyboard"))
            or bool(_KEY_STATE_RE.search(content) and re.search(r"(?:event\s*\.\s*key|key(?:down|up))", content, re.IGNORECASE))
        ) and (
            source_focus or _INPUT_SIGNAL_RE.search(" ".join(str(term) for term in task_terms or []))
        )
        pause_signal = bool(_PAUSE_STATE_RE.search(content) or _PAUSE_INTERFACE_RE.search(content)) and (
            source_focus or _PAUSE_STATE_RE.search(" ".join(str(term) for term in task_terms or []))
        )
        if input_signal:
            state_lines = [number for number, line in enumerate(lines, 1) if _KEY_STATE_RE.search(line)]
            anchors = [class_line] + state_lines[:1]
            start, end, support = _source_support(lines, anchors, max_lines=8)
            candidates.append(_evidence_candidate(
                "CURRENT_OWNER", f"{name} owns keyboard/input behavior", relative, name,
                kind, start, end, fingerprint, support, quality=95,
                semantic_key=f"CURRENT_OWNER|{relative}|{name}|keyboard",
            ))
            if state_lines:
                start, end, support = _source_support(lines, [state_lines[0]], max_lines=5)
                candidates.append(_evidence_candidate(
                    "CURRENT_STATE_OWNER", f"{name} owns keyboard key state", relative, name,
                    kind, start, end, fingerprint, support, quality=96,
                    semantic_key=f"CURRENT_STATE_OWNER|{relative}|{name}|keyboard",
                ))
        if pause_signal:
            state_lines = [number for number, line in enumerate(lines, 1) if _PAUSE_STATE_RE.search(line)]
            anchors = [class_line] + state_lines[:1]
            start, end, support = _source_support(lines, anchors, max_lines=8)
            candidates.append(_evidence_candidate(
                "CURRENT_OWNER", f"{name} owns pause/game-state behavior", relative, name,
                kind, start, end, fingerprint, support, quality=82,
                semantic_key=f"CURRENT_OWNER|{relative}|{name}|pause",
            ))
            if state_lines:
                start, end, support = _source_support(lines, [state_lines[0]], max_lines=5)
                candidates.append(_evidence_candidate(
                    "CURRENT_STATE_OWNER", f"{name} owns paused state", relative, name,
                    kind, start, end, fingerprint, support, quality=98,
                    semantic_key=f"CURRENT_STATE_OWNER|{relative}|{name}|paused",
                ))

    # Public class methods are interfaces; skip constructors and private
    # implementation helpers.  Keep only methods with a task/domain signal.
    for method in methods:
        name = method["name"]
        if name.casefold() in _CONTROL_FLOW_METHODS or name.startswith("_"):
            continue
        line = lines[method["line"] - 1]
        method_signal = (
            bool(_INPUT_SIGNAL_RE.search(line) or _PAUSE_INTERFACE_RE.search(line))
            or name.casefold() in {"ispressed", "togglepause", "loadbestscore", "savebestscore"}
            or bool(re.search(r"\b(?:authenticate|authorize|route|navigate|cache|get|set)\w*\s*\(", line, re.IGNORECASE))
        )
        if not method_signal:
            continue
        qualified = method["qualified"]
        start, end, support = _line_window(lines, method["line"], radius=1, max_lines=4)
        candidates.append(_evidence_candidate(
            "CURRENT_INTERFACE", f"{qualified}() is a current task-relevant interface", relative, qualified,
            kind, start, end, fingerprint, support, quality=88,
            semantic_key=f"CURRENT_INTERFACE|{relative}|{qualified}",
        ))

    strong_persistence_lines = [
        number for number, line in enumerate(lines, 1) if _has_strong_persistence(line)
    ]
    if strong_persistence_lines:
        key_match = next(
            (re.search(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", line)
             for line in lines if re.search(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", line)
             and re.search(r"key|score|persist", line, re.IGNORECASE)),
            None,
        )
        persistence_symbol = key_match.group(1) if key_match else ""
        first_api = strong_persistence_lines[0]
        key_line = next(
            (number for number, line in enumerate(lines, 1)
             if re.search(r"\b(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=", line)
             and re.search(r"key|score|persist", line, re.IGNORECASE)),
            first_api,
        )
        api_lines = [
            number for number, line in enumerate(lines, 1)
            if re.search(r"localStorage|sessionStorage|indexedDB|getItem\s*\(|setItem\s*\(|save[A-Za-z_$]*\s*\(|load[A-Za-z_$]*\s*\(", line, re.IGNORECASE)
        ]
        first_api = api_lines[0] if api_lines else first_api
        start, end, support = _source_support(lines, [key_line, first_api], max_lines=8)
        label = "best-score persistence" if re.search(r"best[-_ ]?score|BEST_SCORE", normalized) else "persistence"
        candidates.append(_evidence_candidate(
            "CURRENT_PERSISTENCE", f"{relative} owns {label}", relative, persistence_symbol,
            kind, start, end, fingerprint, support, quality=92,
            semantic_key=f"CURRENT_PERSISTENCE|{relative}|{persistence_symbol or label}",
        ))

    # Keep one compact declaration fact for other task-relevant source files,
    # including a legacy auth function used by the existing clarification tests.
    if not candidates and declarations and source_focus:
        declaration = declarations[0]
        start, end, support = _line_window(lines, declaration["line"], radius=1, max_lines=4)
        candidates.append(_evidence_candidate(
            "CURRENT_OWNER", f"{declaration['qualified']} is an observed current implementation owner",
            relative, declaration["qualified"], kind, start, end, fingerprint, support, quality=10,
            semantic_key=f"CURRENT_OWNER|{relative}|{declaration['qualified']}",
        ))

    # A source declaration can provide a dependency fact, but only when an
    # actual import/require line is present; this is intentionally compact.
    dependency_line = next((number for number, line in enumerate(lines, 1) if _DEPENDENCY_RE.search(line)), None)
    if dependency_line is not None and source_focus:
        start, end, support = _line_window(lines, dependency_line, radius=0, max_lines=2)
        candidates.append(_evidence_candidate(
            "CURRENT_DEPENDENCY", f"{relative} declares a task-relevant dependency", relative, "",
            kind, start, end, fingerprint, support, quality=24,
            semantic_key=f"CURRENT_DEPENDENCY|{relative}|{start}",
        ))
    return candidates


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


def _record_window_supports_source(lines, record):
    """Check that compact support overlaps the claimed source line range."""
    try:
        start = int(record.get("line_start", 0) or 0)
        end = int(record.get("line_end", 0) or 0)
    except (TypeError, ValueError):
        return False
    if start < 1 or end < start or end > max(1, len(lines)):
        return False
    support = " ".join(str(record.get("support", "")).split()).casefold()
    if not support:
        return False
    window = " ".join(" ".join(lines[start - 1:end]).split()).casefold()
    if not window:
        return False
    if support in window or window in support:
        return True
    # Evidence support is deliberately compacted.  Requiring one meaningful
    # fragment from the claimed range keeps it independently revalidatable
    # without requiring the full source window to fit in the record.
    for line in lines[start - 1:end]:
        fragment = " ".join(str(line).split()).casefold()
        if len(fragment) >= 10 and fragment[: min(48, len(fragment))] in support:
            return True
    return any(token in support for token in re.findall(r"[a-z_$][\w$.-]{3,}", window)[:4])


def _declaration_matches(content, symbol):
    name = str(symbol or "").split(".")[-1]
    if not name or not re.fullmatch(r"[A-Za-z_$][\w$]*", name):
        return False
    return bool(re.search(
        rf"\b(?:class|function|def|interface)\s+{re.escape(name)}\b|"
        rf"\b(?:const|let|var)\s+{re.escape(name)}\s*=|"
        rf"\b{re.escape(name)}\s*\([^;{{}}\n]*\)\s*\{{",
        content,
    ))


def _category_source_valid(record, content, lines):
    """Validate semantic meaning after structural/path/hash checks."""
    category = record.get("category")
    path = str(record.get("path", ""))
    symbol = str(record.get("symbol") or "")
    support = str(record.get("support", ""))
    kind = _file_kind(path)
    normalized = content.casefold()
    support_normalized = support.casefold()
    if category == "CURRENT_ENTRYPOINT":
        return kind == "ENTRYPOINT"
    if category == "CURRENT_TEST":
        if kind != "TEST" or not _TEST_ASSERTION_RE.search(content):
            return False
        if symbol and not re.search(rf"\b{re.escape(symbol.split('.')[-1])}\b", content):
            return False
        return _TEST_ASSERTION_RE.search(support) is not None or bool(
            re.search(r"\b(?:test|assert|expect|describe|it)\b", support, re.IGNORECASE)
        )
    if category == "CURRENT_PERSISTENCE":
        # ``<script src=storage.js>`` is a dependency/entrypoint fact, not
        # direct persistence behavior.  Require an API/key signal in support.
        return _has_strong_persistence(content) and _has_strong_persistence(support)
    if category == "CURRENT_OWNER":
        symbol_hint = symbol.casefold()
        semantic_hint = bool(re.search(
            r"\b(?:owns?|owner|current|behavior|input|state|auth|game|pause|router|cache)\b",
            support, re.IGNORECASE,
        ))
        if not semantic_hint:
            semantic_hint = any(
                token in symbol_hint
                for token in ("input", "keyboard", "game", "state", "auth", "router", "cache", "api", "service", "storage", "token")
            )
        return (
            kind in {"SOURCE", "TEXT"} and not _is_test_path(path)
            and bool(symbol) and _declaration_matches(content, symbol)
            and semantic_hint
        )
    if category == "CURRENT_STATE_OWNER":
        return (
            kind in {"SOURCE", "TEXT"} and not _is_test_path(path)
            and bool(symbol) and _declaration_matches(content, symbol)
            and bool(_KEY_STATE_RE.search(content) or _PAUSE_STATE_RE.search(content))
            and bool(_KEY_STATE_RE.search(support) or _PAUSE_STATE_RE.search(support))
        )
    if category == "CURRENT_INTERFACE":
        if kind in {"TEST", "ENTRYPOINT", "CONFIG"} or not symbol:
            return False
        if symbol.casefold().split(".")[-1] in {"assert", "expect", "input", "test", "it", "describe"}:
            return False
        return _declaration_matches(content, symbol) and bool(
            re.search(rf"\b{re.escape(symbol.split('.')[-1])}\b", support)
            or re.search(r"\b(?:class|function|def|export|route|endpoint|api|public)\b", support, re.IGNORECASE)
        )
    if category == "CURRENT_DEPENDENCY":
        return bool(_DEPENDENCY_RE.search(content)) and bool(_DEPENDENCY_RE.search(support))
    if category == "CURRENT_CONSTRAINT":
        return bool(re.search(r"\b(?:preserve|compatib|must\s+not|invariant|legacy|was\s+not\s+found)\b", support, re.IGNORECASE))
    # Remaining categories retain the prior shape semantics but still need
    # actual content overlap and a non-empty source range.
    return bool(content and support and (support_normalized in normalized or normalized in support_normalized))


def _category_shape_valid_without_workspace(record):
    """Apply category semantics even when only a serialized record is available."""
    category = record.get("category")
    path = str(record.get("path", ""))
    symbol = str(record.get("symbol") or "")
    support = str(record.get("support", ""))
    kind = _file_kind(path)
    if category == "CURRENT_ENTRYPOINT":
        return kind == "ENTRYPOINT"
    if category == "CURRENT_TEST":
        return kind == "TEST" and bool(_TEST_ASSERTION_RE.search(support))
    if category == "CURRENT_PERSISTENCE":
        return _has_strong_persistence(support)
    if category == "CURRENT_INTERFACE":
        return (
            kind not in {"TEST", "ENTRYPOINT", "CONFIG"} and bool(symbol)
            and symbol.casefold().split(".")[-1] not in {"assert", "expect", "input", "test", "it", "describe"}
            and bool(re.search(rf"\b{re.escape(symbol.split('.')[-1])}\b", support))
        )
    if category == "CURRENT_OWNER":
        semantic_hint = bool(re.search(
            r"\b(?:owns?|owner|behavior|input|state|auth|game|pause|paused|router|cache)\b",
            support, re.IGNORECASE,
        ))
        if not semantic_hint:
            semantic_hint = any(token in symbol.casefold() for token in ("input", "keyboard", "game", "state", "auth", "router", "cache", "api", "service", "storage", "token"))
        declaration_hint = bool(re.search(r"\b(?:class|function|def|interface|export)\b|\([^)]*\)\s*\{", support, re.IGNORECASE))
        return (
            kind not in {"TEST", "ENTRYPOINT", "CONFIG"} and bool(symbol)
            and semantic_hint and declaration_hint
        )
    if category == "CURRENT_STATE_OWNER":
        return (
            kind not in {"TEST", "ENTRYPOINT", "CONFIG"} and bool(symbol)
            and bool(_KEY_STATE_RE.search(support) or _PAUSE_STATE_RE.search(support))
        )
    if category == "CURRENT_DEPENDENCY":
        return bool(_DEPENDENCY_RE.search(support))
    if category == "CURRENT_CONSTRAINT":
        return bool(re.search(r"\b(?:preserve|compatib|must\s+not|invariant|legacy|was\s+not\s+found)\b", support, re.IGNORECASE))
    return bool(support)


def validate_repository_evidence(record, workspace=None):
    """Validate repository evidence shape, source location, hash, and category semantics."""
    if not isinstance(record, dict):
        return False
    if not re.fullmatch(r"REPO-\d{3,}", str(record.get("evidence_id", ""))):
        return False
    if record.get("category") not in REPOSITORY_EVIDENCE_CATEGORIES:
        return False
    if record.get("evidence_type") != DIRECT_OBSERVATION or record.get("provenance") != REPOSITORY_EVIDENCE:
        return False
    path = str(record.get("path", "")).strip().replace("\\", "/")
    fact = str(record.get("fact", "")).strip()
    support = str(record.get("support", "")).strip()
    digest = str(record.get("file_sha256", "")).strip().casefold()
    if not path or not fact or not support or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return False
    try:
        start = int(record.get("line_start", 0) or 0)
        end = int(record.get("line_end", 0) or 0)
    except (TypeError, ValueError):
        return False
    if start < 1 or end < start:
        return False
    # Inventory-level absence facts intentionally use ``.`` and the inventory
    # fingerprint rather than a source file hash.
    if path == ".":
        return (
            record.get("source_kind") == "INVENTORY"
            and record.get("category") == "CURRENT_CONSTRAINT"
            and "was not found" in fact.casefold()
            and "exact search" in support.casefold()
        )
    if workspace is None:
        # The caller may be validating a serialized record after the workspace
        # has gone away; structural/category checks remain deterministic.
        if record.get("source_kind") and record.get("source_kind") != _file_kind(path):
            return False
        return _category_shape_valid_without_workspace(record)
    root = Path(workspace).resolve()
    candidate_path = (root / Path(path)).resolve()
    try:
        candidate_path.relative_to(root)
    except ValueError:
        return False
    if not candidate_path.is_file():
        return False
    try:
        content = _read_searchable_file(candidate_path)
        actual_hash = _file_sha256(candidate_path)
    except OSError:
        return False
    lines = content.splitlines()
    if digest != actual_hash.casefold() or end > max(1, len(lines)):
        return False
    if record.get("source_kind") and record.get("source_kind") != _file_kind(path):
        return False
    if not _record_window_supports_source(lines, record):
        return False
    return _category_source_valid(record, content, lines)


def _evidence_semantic_key(record):
    explicit = str(record.get("_semantic_key", "") or "").strip()
    if explicit:
        return explicit
    category = str(record.get("category", ""))
    path = str(record.get("path", ""))
    symbol = str(record.get("symbol") or "")
    if category in {"CURRENT_ENTRYPOINT", "CURRENT_TEST"}:
        return f"{category}|{path}|{symbol}"
    return f"{category}|{path}|{symbol or str(record.get('fact', '')).casefold()}"


def _evidence_quality(record, task_terms=None):
    category_weight = {
        "CURRENT_STATE_OWNER": 110, "CURRENT_OWNER": 105,
        "CURRENT_INTERFACE": 96, "CURRENT_PERSISTENCE": 94,
        "CURRENT_TEST": 90, "CURRENT_DEPENDENCY": 48,
        "CURRENT_CONSTRAINT": 42, "CURRENT_ENTRYPOINT": 18,
        "CURRENT_CONFIG": 16, "CURRENT_BEHAVIOR": 32,
        "CURRENT_FAILURE_EVIDENCE": 26,
    }
    text = " ".join(str(record.get(field, "")) for field in ("fact", "symbol", "support")).casefold()
    overlap = 0
    for term in task_terms or []:
        if any(variant.casefold() in text for variant in _search_term_variants(term)):
            overlap += 1
    return int(record.get("_quality", 0) or 0) + category_weight.get(record.get("category"), 20) + overlap * 3


def _deduplicate_evidence(candidates, task_terms=None):
    """Collapse semantically identical facts before the unchanged 12-record cap."""
    best = {}
    duplicates = 0
    for index, candidate in enumerate(candidates or []):
        key = _evidence_semantic_key(candidate)
        candidate = dict(candidate)
        candidate["_quality_score"] = _evidence_quality(candidate, task_terms)
        candidate["_candidate_order"] = index
        previous = best.get(key)
        if previous is None:
            best[key] = candidate
            continue
        duplicates += 1
        previous_key = (
            int(previous.get("_quality_score", 0)),
            -int(previous.get("line_start", 0) or 0),
            -len(str(previous.get("support", ""))),
            str(previous.get("path", "")),
        )
        current_key = (
            int(candidate.get("_quality_score", 0)),
            -int(candidate.get("line_start", 0) or 0),
            -len(str(candidate.get("support", ""))),
            str(candidate.get("path", "")),
        )
        if current_key > previous_key:
            best[key] = candidate
    return list(best.values()), duplicates


def _select_evidence(candidates, task_terms=None, max_evidence=MAX_TASK_BRAIN_EVIDENCE):
    """Select strongest valid facts while preserving category/path diversity."""
    deduplicated, duplicate_count = _deduplicate_evidence(candidates, task_terms)
    ordered = sorted(
        deduplicated,
        key=lambda item: (
            -int(item.get("_quality_score", 0)),
            str(item.get("category", "")), str(item.get("path", "")),
            int(item.get("line_start", 0) or 0), str(item.get("fact", "")),
        ),
    )
    selected = []
    selected_keys = set()
    category_order = (
        "CURRENT_OWNER", "CURRENT_STATE_OWNER", "CURRENT_INTERFACE",
        "CURRENT_PERSISTENCE", "CURRENT_TEST", "CURRENT_DEPENDENCY",
        "CURRENT_CONSTRAINT", "CURRENT_BEHAVIOR", "CURRENT_ENTRYPOINT",
        "CURRENT_CONFIG", "CURRENT_FAILURE_EVIDENCE",
    )
    # First ensure that every available semantic category has a representative;
    # the global pass below then restores all distinct owners/interfaces.
    for category in category_order:
        category_candidates = [item for item in ordered if item.get("category") == category]
        if category_candidates:
            item = category_candidates[0]
            key = _evidence_semantic_key(item)
            if key not in selected_keys and len(selected) < max(0, int(max_evidence)):
                selected.append(item)
                selected_keys.add(key)
    for item in ordered:
        if len(selected) >= max(0, int(max_evidence)):
            break
        key = _evidence_semantic_key(item)
        if key in selected_keys:
            continue
        selected.append(item)
        selected_keys.add(key)
    selected.sort(key=lambda item: (str(item.get("path", "")), int(item.get("line_start", 0) or 0), str(item.get("category", ""))))
    return selected, duplicate_count, max(0, len(deduplicated) - len(selected))


def _strip_evidence_internals(records):
    result = []
    for record in records or []:
        clean = {key: value for key, value in record.items() if not str(key).startswith("_")}
        result.append(clean)
    return result


def inspect_repository_candidates(workspace, inventory, candidates, max_files=MAX_RECON_FILES,
                                  max_snippets=MAX_RECON_SNIPPETS, max_chars=MAX_RECON_CHARS,
                                  task_terms=None):
    """Read ranked candidates and extract compact, validated semantic facts."""
    root = Path(workspace).resolve()
    inventory_paths = {item.get("path") for item in inventory.get("files", [])}
    selected = []
    selected_paths = set()
    for candidate in candidates or []:
        value = candidate if isinstance(candidate, dict) else {"path": candidate}
        relative = str(value.get("path", "")).replace("\\", "/")
        if relative in inventory_paths and relative not in selected_paths:
            selected.append({**value, "path": relative})
            selected_paths.add(relative)
        if len(selected) >= max(0, int(max_files)):
            break
    raw_candidates = []
    operations = []
    snippets = 0
    chars_used = 0
    errors = []
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
                if any(
                    any(variant.casefold() in line.casefold() for variant in _search_term_variants(term))
                    for term in matched_terms
                )
            ][:4]
        if not locations and lines:
            locations = [1]
        operations.append({"operation": "READ", "path": relative, "locations": locations[:4]})
        file_had_snippet = False
        for line_number in locations[:4]:
            if snippets >= max(0, int(max_snippets)) or chars_used >= max(0, int(max_chars)):
                break
            start = max(1, line_number - 1)
            end = min(len(lines), line_number + 1)
            support = "\n".join(lines[start - 1:end])
            remaining = max(0, int(max_chars) - chars_used)
            support = support[:min(420, remaining)]
            if not support.strip():
                continue
            snippets += 1
            chars_used += len(support)
            file_had_snippet = True
        # Semantic extraction runs only over files that contributed a bounded
        # snippet.  It never expands the read budget or source payload.
        if file_had_snippet:
            raw_candidates.extend(_semantic_evidence_candidates(
                relative, lines, fingerprint, candidate.get("terms", []), task_terms or [],
            ))
    provisional = []
    rejected = 0
    for index, candidate in enumerate(raw_candidates, 1):
        candidate = dict(candidate)
        candidate["evidence_id"] = f"REPO-{index:03d}"
        if validate_repository_evidence(candidate, root):
            provisional.append(candidate)
        else:
            rejected += 1
    selected_evidence, duplicate_count, truncated_valid = _select_evidence(
        provisional, task_terms or [], MAX_TASK_BRAIN_EVIDENCE,
    )
    evidence = _strip_evidence_internals(selected_evidence)
    for index, record in enumerate(evidence, 1):
        record["evidence_id"] = f"REPO-{index:03d}"
    return {
        "evidence": evidence, "operations": operations,
        "files_inspected": len({item.get("path") for item in operations}),
        "snippets": snippets, "chars": chars_used, "errors": errors[:8],
        "candidate_count": len(raw_candidates), "validated_count": len(provisional),
        "deduplicated_count": max(0, len(provisional) - duplicate_count),
        "selected_count": len(evidence), "rejected_semantic_invalid_count": rejected,
        "rejected_duplicate_count": duplicate_count,
        "truncated_valid_count": truncated_valid,
        "truncated": len(selected) >= max_files or snippets >= max_snippets or chars_used >= max_chars,
    }


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
        inspected = inspect_repository_candidates(
            workspace, inventory, candidates, task_terms=terms,
        )
        operations.extend(inspected.get("operations", []))
        after_inventory = inventory_repository(
            workspace,
            max_files=inventory.get("limits", {}).get("max_files", MAX_RECON_INVENTORY_FILES),
            max_depth=inventory.get("limits", {}).get("max_depth", MAX_RECON_DEPTH),
        )
        after = after_inventory.get("fingerprint")
        evidence = [
            item for item in inspected.get("evidence", [])
            if validate_repository_evidence(item, workspace)
        ]
        evidence_candidate_count = int(inspected.get("candidate_count", 0) or 0)
        evidence_validated_count = int(inspected.get("validated_count", 0) or 0)
        evidence_deduplicated_count = int(inspected.get("deduplicated_count", 0) or 0)
        evidence_rejected_count = int(inspected.get("rejected_semantic_invalid_count", 0) or 0)
        evidence_duplicate_count = int(inspected.get("rejected_duplicate_count", 0) or 0)
        evidence_truncated_count = int(inspected.get("truncated_valid_count", 0) or 0)
        matched_terms = {
            str(term).casefold()
            for candidate in search.get("candidates", [])
            for term in candidate.get("terms", [])
        }
        missing_candidates = []
        if not inventory.get("truncated") and not search.get("errors"):
            for symbol in _named_task_symbols(raw_goal):
                if symbol.casefold() in matched_terms:
                    continue
                missing_candidates.append({
                    "evidence_id": "REPO-CANDIDATE",
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
        if missing_candidates:
            for index, record in enumerate(missing_candidates, len(evidence) + 1):
                record["evidence_id"] = f"REPO-{index:03d}"
            valid_missing = [
                item for item in missing_candidates
                if validate_repository_evidence(item, workspace)
            ]
            evidence_candidate_count += len(missing_candidates)
            evidence_validated_count += len(valid_missing)
            evidence_rejected_count += len(missing_candidates) - len(valid_missing)
            # Missing-symbol discrepancies are low-quality inventory facts;
            # include them only after semantic source facts have been selected.
            combined = [dict(item) for item in evidence] + valid_missing
            combined, duplicate_count, truncated_valid = _select_evidence(
                combined, terms, MAX_TASK_BRAIN_EVIDENCE,
            )
            evidence = _strip_evidence_internals(combined)
            evidence_duplicate_count += duplicate_count
            evidence_truncated_count = max(evidence_truncated_count, truncated_valid)
            evidence_deduplicated_count = len(evidence) + truncated_valid
        for index, record in enumerate(evidence, 1):
            record["evidence_id"] = f"REPO-{index:03d}"
        evidence = [
            item for item in evidence
            if validate_repository_evidence(item, workspace)
        ]
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
            "evidence_candidates": evidence_candidate_count,
            "evidence_validated": evidence_validated_count,
            "evidence_deduplicated": evidence_deduplicated_count,
            "evidence_selected": len(evidence),
            "evidence_rejected": evidence_rejected_count,
            "evidence_rejected_duplicates": evidence_duplicate_count,
            "evidence_truncated_valid": evidence_truncated_count,
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
