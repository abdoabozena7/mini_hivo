"""Deterministic, metadata-only repository navigation for CORE-1.

The map is intentionally a compact index.  It stores paths, hashes, symbol
locations/signatures, and structural edges; it never stores source bodies.
The parser is deliberately modest and currently gives JavaScript first-class
support because that is the project's active fixture language.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .project_brain_refs import CORE1_METRIC_KEYS, canonical_hash, canonical_json, normalize_relative_path


SUPPORTED_SUFFIXES = frozenset({
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".py", ".json", ".md",
    ".css", ".html", ".htm", ".yaml", ".yml", ".toml",
})
IGNORED_DIRECTORY_NAMES = frozenset({
    ".git", ".hivo", ".agent_runs", ".agent_evidence", ".agent_backups",
    "output", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".venv", "venv", "env", "dist", "build", "coverage",
    ".next", ".cache", "target",
})
MAX_INDEX_FILE_BYTES = 2_000_000
MAP_SCHEMA_VERSION = "CORE-1-REPOSITORY-MAP-V1"
EDGE_KINDS = ("defines", "imports", "exports", "depends_on", "tested_by", "contains")


def _metric(metrics: dict[str, int] | None, key: str, value: int = 1) -> None:
    if metrics is not None:
        metrics[key] = metrics.get(key, 0) + int(value)


def _safe_root(root: str | Path) -> Path:
    candidate = Path(root).expanduser().resolve()
    if not candidate.is_dir():
        raise ValueError(f"repository root is not a directory: {root}")
    return candidate


def _safe_relative(root: Path, path: str | Path) -> str:
    raw = Path(str(path))
    candidate = (raw if raw.is_absolute() else root / raw).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("repository path escapes the canonical root") from exc
    return normalize_relative_path(relative.as_posix())


def _safe_existing_file(root: Path, relative: str) -> Path | None:
    try:
        target = (root / normalize_relative_path(relative)).resolve()
        target.relative_to(root)
    except (OSError, ValueError):
        return None
    return target if target.is_file() else None


def _language_for(path: str) -> str:
    suffix = Path(path).suffix.casefold()
    return {
        ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
        ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescript",
        ".py": "python", ".json": "json", ".md": "markdown", ".css": "css",
        ".html": "html", ".htm": "html", ".yaml": "yaml", ".yml": "yaml",
        ".toml": "toml",
    }.get(suffix, "text")


def _is_test_path(path: str) -> bool:
    lowered = path.casefold()
    name = Path(path).name.casefold()
    return (
        "/tests/" in f"/{lowered}/"
        or "/__tests__/" in f"/{lowered}/"
        or name.endswith((".test.js", ".test.jsx", ".test.ts", ".test.tsx", ".spec.js", ".spec.ts"))
        or name.startswith("test_")
    )


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _content_hash(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def _package_identity(root: Path, relative: str) -> str:
    parts = Path(relative).parts
    if len(parts) > 1:
        return parts[0]
    # The repository root is intentionally not part of the logical map
    # identity: identical content in two temporary roots must hash alike.
    return "root"


def _line_number(text: str, position: int) -> int:
    return text.count("\n", 0, max(0, position)) + 1


def _balanced_end(text: str, start: int) -> int:
    opening = text.find("{", start)
    if opening < 0:
        return _line_number(text, text.find("\n", start) if "\n" in text[start:] else len(text))
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "'\"`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return _line_number(text, index)
    return _line_number(text, len(text))


def _anchor_hash(signature: str) -> str:
    normalized = " ".join(str(signature).split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _resolve_module(root: Path, source_path: str, specifier: str) -> str | None:
    if not str(specifier).startswith("."):
        return None
    base = (root / source_path).parent
    candidate = (base / specifier).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    choices = [candidate]
    if not candidate.suffix:
        choices.extend(candidate.with_suffix(suffix) for suffix in (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"))
        choices.extend((candidate / "index").with_suffix(suffix) for suffix in (".js", ".jsx", ".ts", ".tsx"))
    for choice in choices:
        if choice.is_file():
            try:
                return choice.relative_to(root).as_posix()
            except ValueError:
                return None
    return None


def _parse_javascript(root: Path, relative: str, text: str) -> tuple[list[dict], list[dict], list[str]]:
    symbols: dict[tuple[str, str], dict] = {}
    exports: set[str] = set()

    def add_symbol(kind: str, name: str, start: int, signature: str, end_line: int | None = None) -> None:
        clean_name = str(name).strip()
        if not clean_name:
            return
        key = (kind, clean_name)
        start_line = _line_number(text, start)
        row = {
            "symbol_id": f"{relative}::{kind}::{clean_name}",
            "path": relative,
            "kind": kind,
            "qualified_name": clean_name,
            "start_line": start_line,
            "end_line": int(end_line or _balanced_end(text, start)),
            "signature": " ".join(signature.strip().split())[:500],
            "anchor_hash": _anchor_hash(signature),
        }
        symbols.setdefault(key, row)

    function_pattern = re.compile(
        r"(?m)^\s*(?:export\s+default\s+|export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\([^\n)]*\)[^\n{]*\{?"
    )
    for match in function_pattern.finditer(text):
        add_symbol("function", match.group(1), match.start(), match.group(0))
        if text[match.start():match.end()].lstrip().startswith("export"):
            exports.add(match.group(1))

    class_pattern = re.compile(
        r"(?m)^\s*(?:export\s+default\s+|export\s+)?class\s+([A-Za-z_$][\w$]*)[^\n{]*\{?"
    )
    for match in class_pattern.finditer(text):
        add_symbol("class", match.group(1), match.start(), match.group(0))
        if text[match.start():match.end()].lstrip().startswith("export"):
            exports.add(match.group(1))

    const_pattern = re.compile(
        r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([^;\n]+)"
    )
    for match in const_pattern.finditer(text):
        signature = match.group(0)
        add_symbol("constant", match.group(1), match.start(), signature, _line_number(text, match.end()))
        if signature.lstrip().startswith("export"):
            exports.add(match.group(1))

    for match in re.finditer(r"(?m)^\s*export\s*\{([^}]+)\}", text):
        for item in match.group(1).split(","):
            name = item.strip().split(" as ")[-1].strip()
            if name:
                exports.add(name)

    for match in re.finditer(r"(?m)\bexports\.([A-Za-z_$][\w$]*)\s*=", text):
        exports.add(match.group(1))
    for match in re.finditer(r"(?m)\bmodule\.exports\s*=\s*\{([^}]*)\}", text):
        for item in match.group(1).split(","):
            name = item.strip().split(":", 1)[0].strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*", name):
                exports.add(name)
    if re.search(r"(?m)\bmodule\.exports\s*=\s*(?!\{)([A-Za-z_$][\w$]*)", text):
        exports.add("default")
    for name in sorted(exports):
        if not any(row["qualified_name"] == name for row in symbols.values()):
            export_match = re.search(rf"(?m)^.*\b{re.escape(name)}\b.*$", text)
            if export_match:
                add_symbol("export", name, export_match.start(), export_match.group(0), _line_number(text, export_match.end()))

    imports: list[dict] = []
    patterns = [
        re.compile(r"(?m)\b(?:import|export)\s+(?:[^;\n]*?\s+from\s+)?['\"]([^'\"]+)['\"]"),
        re.compile(r"\brequire\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"),
    ]
    seen_imports: set[tuple[str, str | None]] = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            specifier = match.group(1)
            resolved = _resolve_module(root, relative, specifier)
            key = (specifier, resolved)
            if key in seen_imports:
                continue
            seen_imports.add(key)
            imports.append({
                "specifier": specifier,
                "resolved_path": resolved,
                "unresolved": resolved is None,
            })
    return (
        sorted(symbols.values(), key=lambda row: row["symbol_id"]),
        sorted(imports, key=lambda row: (row["specifier"], str(row["resolved_path"]))),
        sorted(exports),
    )


def _parse_file(root: Path, relative: str) -> dict:
    path = _safe_existing_file(root, relative)
    if path is None:
        raise FileNotFoundError(relative)
    digest, size = _content_hash(path)
    text = _read_text(path)
    language = _language_for(relative)
    symbols: list[dict] = []
    imports: list[dict] = []
    exports: list[str] = []
    if language == "javascript":
        symbols, imports, exports = _parse_javascript(root, relative, text)
    return {
        "path": relative,
        "language": language,
        "content_hash": digest,
        "size": size,
        "module_identity": _package_identity(root, relative),
        "top_level_symbols": [row["symbol_id"] for row in symbols],
        "imports": imports,
        "exports": exports,
        "known_tests": [],
        "index_revision": digest,
        "is_test": _is_test_path(relative),
        "_symbols": symbols,
    }


def _iter_candidate_paths(root: Path) -> list[str]:
    paths: list[str] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name for name in directories
            if name not in IGNORED_DIRECTORY_NAMES and not name.startswith(".")
        )
        for filename in sorted(filenames):
            path = Path(current) / filename
            if path.suffix.casefold() not in SUPPORTED_SUFFIXES:
                continue
            try:
                if path.is_symlink() and not path.resolve().is_relative_to(root):
                    continue
                if path.stat().st_size > MAX_INDEX_FILE_BYTES:
                    continue
                paths.append(path.resolve().relative_to(root).as_posix())
            except (OSError, ValueError):
                continue
    return sorted(set(paths))


def _directory_index(files: Mapping[str, dict]) -> dict[str, dict]:
    directories: dict[str, dict] = {}
    for path, entry in files.items():
        parts = Path(path).parts[:-1]
        for index in range(1, len(parts) + 1):
            directory = "/".join(parts[:index])
            directories.setdefault(directory, {
                "path": directory,
                "module_identity": directory.split("/", 1)[0],
                "file_count": 0,
            })
            directories[directory]["file_count"] += 1
    return {key: directories[key] for key in sorted(directories)}


def _build_edges(files: Mapping[str, dict], symbols: Mapping[str, dict]) -> list[dict]:
    edges: set[tuple[str, str, str]] = set()
    for path, entry in files.items():
        for symbol_id in entry.get("top_level_symbols", []):
            edges.add(("contains", path, symbol_id))
            edges.add(("defines", path, symbol_id))
        for name in entry.get("exports", []):
            symbol_id = next((sid for sid, row in symbols.items() if row.get("path") == path and row.get("qualified_name") == name), None)
            edges.add(("exports", path, symbol_id or f"{path}::export::{name}"))
        for imported in entry.get("imports", []):
            resolved = imported.get("resolved_path")
            target = str(resolved) if resolved else f"unresolved://{imported.get('specifier', '')}"
            edges.add(("imports", path, target))
            if resolved:
                edges.add(("depends_on", path, str(resolved)))
        for test in entry.get("known_tests", []):
            edges.add(("tested_by", path, str(test)))
    return [
        {"kind": kind, "source": source, "target": target}
        for kind, source, target in sorted(edges)
    ]


def _recompute_tests(files: dict[str, dict]) -> None:
    for entry in files.values():
        entry["known_tests"] = []
    test_paths = [path for path, entry in files.items() if entry.get("is_test")]
    for test_path in test_paths:
        test_entry = files[test_path]
        imported_sources = {
            str(imported.get("resolved_path"))
            for imported in test_entry.get("imports", [])
            if imported.get("resolved_path")
        }
        stem = Path(test_path).name.casefold()
        stem = re.sub(r"\.(test|spec)\.[^.]+$", "", stem)
        stem = re.sub(r"^test_", "", stem)
        for source_path, source_entry in files.items():
            if source_entry.get("is_test"):
                continue
            source_stem = Path(source_path).stem.casefold()
            if source_path in imported_sources or source_stem == stem or source_stem in stem:
                source_entry.setdefault("known_tests", []).append(test_path)
    for entry in files.values():
        entry["known_tests"] = sorted(set(entry.get("known_tests", [])))


def _canonical_map_payload(repository_map: "RepositoryMap") -> dict[str, Any]:
    return {
        "schema_version": repository_map.schema_version,
        "index_revision": repository_map.index_revision,
        "directories": repository_map.directories,
        "files": repository_map.files,
        "symbols": repository_map.symbols,
        "edges": repository_map.edges,
        "invalidated_references": repository_map.invalidated_references,
    }


@dataclass
class RepositoryMap:
    """Metadata-only repository index with a stable logical identity."""

    project_root: str = field(repr=False, default="")
    files: dict[str, dict] = field(default_factory=dict)
    directories: dict[str, dict] = field(default_factory=dict)
    symbols: dict[str, dict] = field(default_factory=dict)
    edges: list[dict] = field(default_factory=list)
    index_revision: str = ""
    invalidated_references: list[str] = field(default_factory=list)
    schema_version: str = MAP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.project_root:
            self.project_root = str(Path(self.project_root).expanduser().resolve())
        self.files = {str(key).replace("\\", "/"): dict(value) for key, value in self.files.items()}
        self.directories = {str(key): dict(value) for key, value in self.directories.items()}
        self.symbols = {str(key): dict(value) for key, value in self.symbols.items()}
        self.edges = [dict(edge) for edge in self.edges]
        self.invalidated_references = sorted(set(str(item) for item in self.invalidated_references))

    @property
    def logical_hash(self) -> str:
        return canonical_hash(_canonical_map_payload(self))

    @property
    def map_hash(self) -> str:
        return self.logical_hash

    @property
    def file_index(self) -> dict[str, dict]:
        return self.files

    @property
    def symbol_index(self) -> dict[str, dict]:
        return self.symbols

    @property
    def dependency_graph(self) -> list[dict]:
        return self.edges

    @property
    def logical_map_hash(self) -> str:
        return self.logical_hash

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def to_dict(self) -> dict[str, Any]:
        """Serialize only canonical metadata; absolute root is intentionally omitted."""
        payload = _canonical_map_payload(self)
        return {
            "schema_version": payload["schema_version"],
            "index_revision": payload["index_revision"],
            "directories": {key: payload["directories"][key] for key in sorted(payload["directories"])},
            "files": {key: payload["files"][key] for key in sorted(payload["files"])},
            "symbols": {key: payload["symbols"][key] for key in sorted(payload["symbols"])},
            "edges": sorted(payload["edges"], key=lambda edge: (edge.get("kind", ""), edge.get("source", ""), edge.get("target", ""))),
            "invalidated_references": payload["invalidated_references"],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], project_root: str | Path = "") -> "RepositoryMap":
        data = dict(value)
        return cls(
            project_root=str(project_root),
            files=dict(data.get("files", {}) or {}),
            directories=dict(data.get("directories", {}) or {}),
            symbols=dict(data.get("symbols", {}) or {}),
            edges=list(data.get("edges", []) or []),
            index_revision=str(data.get("index_revision", "")),
            invalidated_references=list(data.get("invalidated_references", []) or []),
            schema_version=str(data.get("schema_version", MAP_SCHEMA_VERSION)),
        )


def _finalize_map(
    root: Path,
    files: dict[str, dict],
    *,
    invalidated: Iterable[str] = (),
    prior_revision: str = "",
    existing_symbols: Mapping[str, dict] | None = None,
) -> RepositoryMap:
    symbols: dict[str, dict] = {
        str(key): dict(value) for key, value in (existing_symbols or {}).items()
    }
    for path in sorted(files):
        entry = files[path]
        entry.pop("_symbols", None)
        for symbol in entry.pop("_symbols_pending", []) if isinstance(entry.get("_symbols_pending"), list) else []:
            symbols[str(symbol["symbol_id"])] = dict(symbol)
    # If a caller supplied already-finalized entries, recover unchanged symbol
    # rows from the previous map and use a small stable fallback only when an
    # older serialized map omitted symbol metadata.
    for entry in files.values():
        for symbol_id in entry.get("top_level_symbols", []):
            symbols.setdefault(str(symbol_id), {
                "symbol_id": str(symbol_id), "path": entry["path"],
                "kind": str(symbol_id).split("::")[-2] if "::" in str(symbol_id) else "unknown",
                "qualified_name": str(symbol_id).rsplit("::", 1)[-1],
            })
    _recompute_tests(files)
    edges = _build_edges(files, symbols)
    revision_payload = [(path, files[path].get("content_hash", "")) for path in sorted(files)]
    revision = canonical_hash({"files": revision_payload})
    if prior_revision and not revision:
        revision = prior_revision
    return RepositoryMap(
        project_root=str(root), files={key: files[key] for key in sorted(files)},
        directories=_directory_index(files), symbols={key: symbols[key] for key in sorted(symbols)},
        edges=edges, index_revision=revision,
        invalidated_references=sorted(set(str(item) for item in invalidated)),
    )


def build_repository_map(
    project_root: str | Path,
    *,
    metrics: dict[str, int] | None = None,
) -> RepositoryMap:
    """Build a deterministic cold index without provider or Worker calls."""
    root = _safe_root(project_root)
    files: dict[str, dict] = {}
    for relative in _iter_candidate_paths(root):
        try:
            entry = _parse_file(root, relative)
        except (OSError, UnicodeError, ValueError):
            continue
        symbols = entry.pop("_symbols", [])
        entry["_symbols_pending"] = symbols
        files[relative] = entry
        _metric(metrics, "cold_index_files_scanned")
    return _finalize_map(root, files)


def _remove_file(repository_map: RepositoryMap, relative: str, invalidated: set[str]) -> None:
    old = repository_map.files.pop(relative, None)
    if not old:
        return
    invalidated.add(relative)
    invalidated.update(str(item) for item in old.get("top_level_symbols", []))
    for symbol_id in list(repository_map.symbols):
        row = repository_map.symbols.get(symbol_id, {})
        if row.get("path") == relative or symbol_id.startswith(relative + "::"):
            repository_map.symbols.pop(symbol_id, None)


def _replace_path_in_metadata(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return new if value == old else value
    if isinstance(value, list):
        return [_replace_path_in_metadata(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: _replace_path_in_metadata(item, old, new) for key, item in value.items()}
    return value


def incremental_reindex(
    repository_map: RepositoryMap | Mapping[str, Any],
    project_root: str | Path | None = None,
    *,
    changed_paths: Iterable[str | Path] | None = None,
    deleted_paths: Iterable[str | Path] | None = None,
    moved_paths: Iterable[tuple[str | Path, str | Path] | Mapping[str, str]] | None = None,
    metrics: dict[str, int] | None = None,
) -> RepositoryMap:
    """Reparse only changed files and rebuild direct structural metadata."""
    if isinstance(repository_map, RepositoryMap):
        current = RepositoryMap.from_dict(repository_map.to_dict(), repository_map.project_root)
    else:
        current = RepositoryMap.from_dict(repository_map, project_root or "")
    root = _safe_root(project_root or current.project_root)
    invalidated = set(current.invalidated_references)
    changes = {_safe_relative(root, path) for path in (changed_paths or [])}
    deletions = {_safe_relative(root, path) for path in (deleted_paths or [])}

    for move in moved_paths or []:
        if isinstance(move, Mapping):
            old_raw = move.get("old", move.get("old_path", ""))
            new_raw = move.get("new", move.get("new_path", ""))
        else:
            old_raw, new_raw = move
        old = _safe_relative(root, old_raw)
        new = _safe_relative(root, new_raw)
        old_entry = current.files.get(old)
        new_path = _safe_existing_file(root, new)
        if old_entry and new_path and not current.files.get(new):
            new_hash, _ = _content_hash(new_path)
            if new_hash == old_entry.get("content_hash"):
                renamed = dict(old_entry)
                renamed["path"] = new
                renamed["top_level_symbols"] = [str(item).replace(f"{old}::", f"{new}::", 1) for item in old_entry.get("top_level_symbols", [])]
                renamed["known_tests"] = [new if item == old else item for item in old_entry.get("known_tests", [])]
                renamed["imports"] = [_replace_path_in_metadata(item, old, new) for item in old_entry.get("imports", [])]
                current.files.pop(old, None)
                current.files[new] = renamed
                for entry in current.files.values():
                    entry["imports"] = [
                        _replace_path_in_metadata(item, old, new)
                        for item in entry.get("imports", [])
                    ]
                    entry["known_tests"] = [new if item == old else item for item in entry.get("known_tests", [])]
                for symbol_id in list(current.symbols):
                    if symbol_id.startswith(old + "::"):
                        row = current.symbols.pop(symbol_id)
                        replacement = symbol_id.replace(f"{old}::", f"{new}::", 1)
                        row["symbol_id"] = replacement
                        row["path"] = new
                        current.symbols[replacement] = row
                changes.discard(new)
                invalidated.add(old)
                invalidated.update(str(item) for item in old_entry.get("top_level_symbols", []))
                continue
        deletions.add(old)
        changes.add(new)

    for relative in sorted(deletions):
        _remove_file(current, relative, invalidated)

    reparsed = 0
    for relative in sorted(changes):
        path = _safe_existing_file(root, relative)
        if path is None:
            _remove_file(current, relative, invalidated)
            continue
        new_hash, _ = _content_hash(path)
        if current.files.get(relative, {}).get("content_hash") == new_hash:
            continue
        old_entry = current.files.get(relative)
        if old_entry:
            invalidated.add(relative)
            invalidated.update(str(item) for item in old_entry.get("top_level_symbols", []))
            for symbol_id in list(current.symbols):
                row = current.symbols.get(symbol_id, {})
                if row.get("path") == relative or symbol_id.startswith(relative + "::"):
                    current.symbols.pop(symbol_id, None)
        try:
            entry = _parse_file(root, relative)
        except (OSError, UnicodeError, ValueError):
            _remove_file(current, relative, invalidated)
            continue
        entry["_symbols_pending"] = entry.pop("_symbols", [])
        current.files[relative] = entry
        reparsed += 1
    _metric(metrics, "incremental_files_reparsed", reparsed)

    old_edges = current.edges
    result = _finalize_map(
        root, current.files, invalidated=invalidated, prior_revision=current.index_revision,
        existing_symbols=current.symbols,
    )
    affected = set(changes) | set(deletions)
    affected.update(
        edge.get("source") for edge in old_edges
        if edge.get("source") in affected or edge.get("target") in affected
    )
    recomputed = sum(
        1 for edge in result.edges
        if edge.get("source") in affected or edge.get("target") in affected
    )
    _metric(metrics, "incremental_edges_recomputed", recomputed)
    return result


def query_repository_map(
    repository_map: RepositoryMap | Mapping[str, Any],
    query: str = "",
    *,
    max_items: int = 24,
) -> list[dict[str, Any]]:
    """Return bounded metadata projections without loading source bodies."""
    current = repository_map if isinstance(repository_map, RepositoryMap) else RepositoryMap.from_dict(repository_map)
    tokens = set(re.findall(r"[\w.-]{2,}", str(query).casefold()))
    rows: list[dict[str, Any]] = []
    for path, entry in current.files.items():
        searchable = " ".join((path, entry.get("module_identity", ""), *entry.get("exports", []), *entry.get("top_level_symbols", []))).casefold()
        overlap = sum(1 for token in tokens if token in searchable)
        rows.append({
            "kind": "file", "path": path, "language": entry.get("language"),
            "content_hash": entry.get("content_hash"), "size": entry.get("size"),
            "module_identity": entry.get("module_identity"),
            "top_level_symbols": list(entry.get("top_level_symbols", [])),
            "imports": list(entry.get("imports", [])), "exports": list(entry.get("exports", [])),
            "known_tests": list(entry.get("known_tests", [])), "relevance": overlap,
        })
    for symbol_id, symbol in current.symbols.items():
        searchable = " ".join((symbol_id, symbol.get("qualified_name", ""))).casefold()
        overlap = sum(1 for token in tokens if token in searchable)
        symbol_row = dict(symbol)
        symbol_row.pop("kind", None)
        rows.append({"kind": "symbol", **symbol_row, "relevance": overlap})
    rows.sort(key=lambda row: (int(row.get("relevance", 0)), row.get("kind", ""), row.get("path", row.get("symbol_id", ""))), reverse=True)
    for row in rows:
        row.pop("relevance", None)
    return rows[: max(0, int(max_items))]


def map_hash(repository_map: RepositoryMap | Mapping[str, Any]) -> str:
    current = repository_map if isinstance(repository_map, RepositoryMap) else RepositoryMap.from_dict(repository_map)
    return current.logical_hash


RepositoryMapSnapshot = RepositoryMap
incremental_update = incremental_reindex
index_repository = build_repository_map
reindex_repository = incremental_reindex


__all__ = [
    "SUPPORTED_SUFFIXES", "IGNORED_DIRECTORY_NAMES", "MAP_SCHEMA_VERSION",
    "EDGE_KINDS", "RepositoryMap", "RepositoryMapSnapshot", "build_repository_map",
    "incremental_reindex", "incremental_update", "index_repository", "reindex_repository",
    "query_repository_map", "map_hash",
]
