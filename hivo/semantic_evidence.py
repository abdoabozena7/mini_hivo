"""Bounded semantic evidence completion for targeted Worker requests.

This module sits behind the existing ContextSufficiencyGate provider seam.
It does not create a repository memory or a second orchestration loop.  The
gate still owns the completion budget and mutation authorization; this module
only turns one narrow request into a small, provenance-preserving evidence
bundle.

The resolver uses the existing RepositoryMap when a caller has one.  The
source fallback is intentionally lightweight: it recognizes the Python,
JavaScript, and TypeScript shapes already used by HIVO's repository
inspection surfaces, and falls back to bounded lexical excerpts for the
remaining supported text types.  Structural matches always outrank that
fallback.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable, Mapping


# Canonical names are deliberately separate from the older lower-case gate
# request names.  The gate accepts both forms, while evidence metadata keeps
# the semantic class visible to the controller and Worker.
CONTRACT = "CONTRACT"
CALLER_EXPECTATION = "CALLER_EXPECTATION"
CALLEE_DEPENDENCY = "CALLEE_DEPENDENCY"
TEST_EXPECTATION = "TEST_EXPECTATION"
TYPE_OR_SCHEMA = "TYPE_OR_SCHEMA"
STATE_INVARIANT = "STATE_INVARIANT"
STATE_TRANSITION = "STATE_TRANSITION"
SYMBOL_DEFINITION = "SYMBOL_DEFINITION"
SIBLING_IMPLEMENTATION = "SIBLING_IMPLEMENTATION"
EXPORT_OR_PUBLIC_SURFACE = "EXPORT_OR_PUBLIC_SURFACE"
CONFIGURATION_DEPENDENCY = "CONFIGURATION_DEPENDENCY"

SEMANTIC_REQUEST_KINDS = (
    CONTRACT,
    CALLER_EXPECTATION,
    CALLEE_DEPENDENCY,
    TEST_EXPECTATION,
    TYPE_OR_SCHEMA,
    STATE_INVARIANT,
    STATE_TRANSITION,
    SYMBOL_DEFINITION,
    SIBLING_IMPLEMENTATION,
    EXPORT_OR_PUBLIC_SURFACE,
    CONFIGURATION_DEPENDENCY,
)
RESOLUTION_STATUSES = ("resolved", "partial", "unresolved", "conflicting")

# These bounds are local to one provider request.  The gate's existing
# MAX_CONTEXT_EVIDENCE_ITEMS/MAX_CONTEXT_EVIDENCE_CHARS remain the global
# Worker working-set limits.
MAX_RELATIONSHIP_HOPS = 2
MAX_CANDIDATES_PER_REQUEST = 8
MAX_FILES_SCANNED_PER_REQUEST = 32
MAX_RESOLVED_EVIDENCE_ITEMS = 3
MAX_FACTS_PER_REQUEST = 8
MAX_SOURCE_CHARS = 120_000
MAX_EXCERPT_CHARS = 650
MAX_FACT_CHARS = 300
MAX_CONFLICTS = 4

HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"

_REQUEST_ALIASES = {
    "contract": CONTRACT,
    "authoritative_contract": CONTRACT,
    "interface": CONTRACT,
    "callers": CALLER_EXPECTATION,
    "consumers": CALLER_EXPECTATION,
    "return_expectation": CALLER_EXPECTATION,
    "caller_expectation": CALLER_EXPECTATION,
    "callee_dependency": CALLEE_DEPENDENCY,
    "tests": TEST_EXPECTATION,
    "test_expectation": TEST_EXPECTATION,
    "schema": TYPE_OR_SCHEMA,
    "type_or_schema": TYPE_OR_SCHEMA,
    "invariant": STATE_INVARIANT,
    "state_invariant": STATE_INVARIANT,
    "state_transition": STATE_TRANSITION,
    "definition": SYMBOL_DEFINITION,
    "symbol_definition": SYMBOL_DEFINITION,
    "sibling_implementation": SIBLING_IMPLEMENTATION,
    "export_or_public_surface": EXPORT_OR_PUBLIC_SURFACE,
    "configuration_dependency": CONFIGURATION_DEPENDENCY,
}

_GATE_KIND = {
    CONTRACT: "contract",
    CALLER_EXPECTATION: "callers",
    CALLEE_DEPENDENCY: "callee_dependency",
    TEST_EXPECTATION: "tests",
    TYPE_OR_SCHEMA: "schema",
    STATE_INVARIANT: "invariant",
    STATE_TRANSITION: "state_transition",
    SYMBOL_DEFINITION: "definition",
    SIBLING_IMPLEMENTATION: "sibling_implementation",
    EXPORT_OR_PUBLIC_SURFACE: "export_or_public_surface",
    CONFIGURATION_DEPENDENCY: "configuration_dependency",
}

SUPPORTED_SOURCE_EXTENSIONS = frozenset({
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
    ".html", ".htm", ".css", ".scss", ".json", ".toml", ".yaml", ".yml",
    ".go", ".rs", ".java", ".c", ".cpp", ".h", ".md", ".txt",
})
IGNORED_DIRECTORY_NAMES = frozenset({
    ".git", ".hivo", ".agent_runs", ".agent_evidence", ".agent_backups",
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".venv", "venv", "env", "dist", "build", "coverage",
    ".next", ".cache", "target",
})
_IDENTIFIER = r"[A-Za-z_$][A-Za-z0-9_$]*"
_STOPWORDS = frozenset({
    "a", "an", "and", "all", "another", "api", "behavior", "behaviour",
    "caller", "callers", "callee", "code", "component", "consumers",
    "contract", "definition", "dependency", "expectation", "function",
    "implementation", "interface", "invariant", "module", "object",
    "public", "return", "schema", "source", "state", "target", "test",
    "tests", "the", "transition", "type", "value", "with", "field",
    "result", "response", "request", "expect", "expected", "output",
    "requirement", "configuration", "config", "surface", "export",
    "exports", "sibling", "supporting", "for", "of", "to", "from",
})
_BUILTIN_CALLS = frozenset({
    "if", "for", "while", "return", "assert", "print", "len", "str", "int",
    "dict", "list", "set", "tuple", "super", "range", "isinstance",
    "typeof", "expect", "describe", "it", "test", "require",
})


def _normalise(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")


def canonical_request_kind(value: Any) -> str:
    """Return one of the explicit semantic request classes, or UNKNOWN."""
    normalised = _normalise(value)
    for kind in SEMANTIC_REQUEST_KINDS:
        if normalised == kind.casefold():
            return kind
    return _REQUEST_ALIASES.get(normalised, "UNKNOWN")


def gate_request_kind(value: Any) -> str:
    """Return the compatible lower-case kind used in gate evidence items."""
    kind = canonical_request_kind(value)
    return _GATE_KIND.get(kind, _normalise(value) or "evidence")


def _text(value: Any, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: max(0, limit - 3)] + "..."


def _unique(values: Iterable[Any], limit: int = 16) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _text(value, MAX_FACT_CHARS)
        if not item or item.casefold() in seen:
            continue
        seen.add(item.casefold())
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _is_test_path(path: str) -> bool:
    lowered = str(path).replace("\\", "/").casefold()
    name = Path(path).name.casefold()
    return (
        "/tests/" in f"/{lowered}/"
        or "/__tests__/" in f"/{lowered}/"
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )


def _is_comment(line: str) -> bool:
    stripped = str(line).lstrip()
    return stripped.startswith(("#", "//", "/*", "*", "<!--", "--"))


def _identifier_tokens(target: str) -> list[str]:
    tokens = re.findall(_IDENTIFIER, str(target or ""))
    selected: list[str] = []
    for token in tokens:
        if token.casefold() in _STOPWORDS:
            continue
        if len(token) < 2:
            continue
        if token.casefold() not in {item.casefold() for item in selected}:
            selected.append(token)
    states = [token for token in tokens if token.isupper() and len(token) >= 2]
    return _unique([*states, *selected], limit=12)


def _primary_symbol(target: str, kind: str) -> str:
    tokens = _identifier_tokens(target)
    if kind == STATE_TRANSITION and tokens:
        return tokens[0]
    if not tokens:
        return _text(target, 180)
    # Qualified targets and natural-language request suffixes are common in
    # Worker requests. Prefer the most symbol-like token, then the rightmost
    # identifier, so ``module.refresh_token callers`` resolves to
    # ``refresh_token`` rather than ``module``.
    return next(
        (token for token in reversed(tokens) if "_" in token or "$" in token),
        tokens[-1],
    )


class SemanticEvidenceResolver:
    """Resolve one semantic request into a bounded evidence bundle."""

    def __init__(
        self,
        workspace: str | Path,
        allowed_inspection_paths: Iterable[str | Path] | None = None,
        *,
        repository_map: Any = None,
        max_relationship_hops: int = MAX_RELATIONSHIP_HOPS,
        max_candidates: int = MAX_CANDIDATES_PER_REQUEST,
        max_files_scanned: int = MAX_FILES_SCANNED_PER_REQUEST,
        max_evidence_items: int = MAX_RESOLVED_EVIDENCE_ITEMS,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.repository_map = repository_map
        self.max_relationship_hops = max(0, min(MAX_RELATIONSHIP_HOPS, int(max_relationship_hops)))
        self.max_candidates = max(1, min(MAX_CANDIDATES_PER_REQUEST, int(max_candidates)))
        self.max_files_scanned = max(1, min(MAX_FILES_SCANNED_PER_REQUEST, int(max_files_scanned)))
        self.max_evidence_items = max(1, min(MAX_RESOLVED_EVIDENCE_ITEMS, int(max_evidence_items)))
        if allowed_inspection_paths is None:
            self.allowed_inspection_paths = [self.workspace]
        else:
            self.allowed_inspection_paths = list(allowed_inspection_paths)
        self._texts: dict[str, str] = {}
        self._path_set: set[str] = set()
        self._authority_paths: set[str] = set()
        self._relationship_hops = 0
        self._files = self._enumerate_allowed_files()

    # ---------- bounded source and map access ----------

    def _safe_path(self, raw: str | Path) -> Path | None:
        candidate = (Path(raw) if Path(str(raw)).is_absolute() else self.workspace / str(raw)).resolve()
        try:
            candidate.relative_to(self.workspace)
        except (OSError, ValueError):
            return None
        return candidate

    def _enumerate_allowed_files(self) -> list[str]:
        paths: set[str] = set()
        if not self.workspace.is_dir():
            return []
        for raw in self.allowed_inspection_paths:
            candidate = self._safe_path(raw)
            if candidate is None or not candidate.exists():
                continue
            if candidate.is_file():
                children = [candidate]
            elif candidate.is_dir():
                try:
                    children = [
                        item for item in candidate.rglob("*")
                        if item.is_file()
                        and item.suffix.casefold() in SUPPORTED_SOURCE_EXTENSIONS
                        and not any(part in IGNORED_DIRECTORY_NAMES for part in item.parts)
                    ]
                except OSError:
                    children = []
            else:
                children = []
            for item in children:
                try:
                    resolved = item.resolve()
                    resolved.relative_to(self.workspace)
                    relative = resolved.relative_to(self.workspace).as_posix()
                except (OSError, ValueError):
                    continue
                paths.add(relative)
        return sorted(paths)

    def _read(self, relative: str) -> str:
        if relative in self._texts:
            return self._texts[relative]
        path = self._safe_path(relative)
        if path is None or not path.is_file():
            return ""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:MAX_SOURCE_CHARS]
        except OSError:
            text = ""
        self._texts[relative] = text
        return text

    def _map_value(self, key: str, default: Any = None) -> Any:
        current = self.repository_map
        if current is None:
            return default
        if isinstance(current, Mapping):
            return current.get(key, default)
        return getattr(current, key, default)

    def _map_file(self, relative: str) -> Mapping[str, Any]:
        files = self._map_value("files", {})
        value = files.get(relative, {}) if isinstance(files, Mapping) else {}
        return value if isinstance(value, Mapping) else {}

    def _map_symbols(self, relative: str) -> list[Mapping[str, Any]]:
        symbols = self._map_value("symbols", {})
        rows = []
        if isinstance(symbols, Mapping):
            for row in symbols.values():
                if isinstance(row, Mapping) and str(row.get("path", "")).replace("\\", "/") == relative:
                    rows.append(row)
        return sorted(rows, key=lambda row: (int(row.get("start_line", 0) or 0), str(row.get("symbol_id", ""))))

    def _context_authority(self, context: Mapping[str, Any] | None) -> None:
        for item in (context or {}).get("working_evidence", []) or []:
            if not isinstance(item, Mapping) or not item.get("authoritative"):
                continue
            source = str(item.get("source_identity") or item.get("source") or "")
            path = source.rsplit(":", 1)[0] if ":" in source else source
            if path:
                self._authority_paths.add(path.replace("\\", "/").lstrip("./"))

    def _source_order(self, request_kind: str, target: str = "") -> list[str]:
        """Return a bounded source scan order.

        Path names are only a tie-breaker.  Content is still inspected for
        structural matches so a semantically useful caller in 'session.py'
        beats a filename-only lexical hit in 'refresh_token_notes.py'.
        """
        kind_words = {
            CONTRACT: ("contract", "interface", "api", "type", "schema"),
            TYPE_OR_SCHEMA: ("type", "schema", "model", "interface"),
            TEST_EXPECTATION: ("test", "spec"),
            EXPORT_OR_PUBLIC_SURFACE: ("index", "__init__", "export", "public"),
            CONFIGURATION_DEPENDENCY: ("config", "settings", "env"),
        }.get(request_kind, ())

        def score(path: str) -> tuple[int, int, str]:
            lowered = path.casefold()
            score_value = sum(2 for word in kind_words if word in lowered)
            target_terms = [
                item.casefold() for item in _identifier_tokens(target)
                if len(item) >= 3
            ]
            score_value += sum(4 for item in target_terms if item in lowered)
            if _is_test_path(path) and request_kind == TEST_EXPECTATION:
                score_value += 4
            if path in self._authority_paths:
                score_value += 8
            return (-score_value, len(path), path.casefold())

        return sorted(self._files, key=score)[: self.max_files_scanned]

    def _resolve_relative_import(self, source: str, specifier: str) -> str | None:
        if not str(specifier).startswith("."):
            return None
        base = (self.workspace / source).parent
        candidate = (base / specifier).resolve()
        try:
            candidate.relative_to(self.workspace)
        except ValueError:
            return None
        choices = [candidate]
        if not candidate.suffix:
            choices.extend(candidate.with_suffix(suffix) for suffix in (
                ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
            ))
            choices.extend((candidate / "index").with_suffix(suffix) for suffix in (
                ".js", ".jsx", ".ts", ".tsx", ".py",
            ))
        for choice in choices:
            if choice.is_file():
                try:
                    return choice.relative_to(self.workspace).as_posix()
                except ValueError:
                    return None
        return None

    def _imports_from_text(self, relative: str, text: str) -> list[str]:
        result = []
        mapped_imports = self._map_file(relative).get("imports", [])
        if isinstance(mapped_imports, list):
            result.extend(
                str(item.get("resolved_path"))
                for item in mapped_imports
                if isinstance(item, Mapping)
                and item.get("resolved_path") in self._path_set
            )
        specifiers = re.findall(
            r"""(?m)(?:\b(?:from|import|export)\s+['"]([^'"]+)['"]|"""
            r"""\brequire\s*\(\s*['"]([^'"]+)['"]\s*\))""",
            text,
        )
        for first, second in specifiers:
            resolved = self._resolve_relative_import(relative, first or second)
            if resolved and resolved in self._path_set:
                result.append(resolved)
        return sorted(set(result))

    def _bounded_relationship_paths(self, seeds: Iterable[str]) -> tuple[list[str], int]:
        """Follow local imports only as a bounded provider-side hint."""
        selected = list(dict.fromkeys(path for path in seeds if path in self._path_set))
        frontier = list(selected)
        max_hop = 0
        for hop in range(1, self.max_relationship_hops + 1):
            next_frontier: list[str] = []
            for path in frontier:
                for neighbour in self._imports_from_text(path, self._read(path)):
                    if neighbour not in selected:
                        selected.append(neighbour)
                        next_frontier.append(neighbour)
                        if len(selected) >= self.max_candidates:
                            break
                if len(selected) >= self.max_candidates:
                    break
            if not next_frontier:
                break
            frontier = next_frontier
            max_hop = hop
            if len(selected) >= self.max_candidates:
                break
        return selected[: self.max_candidates], max_hop

    # ---------- candidate construction ----------

    def _line_excerpt(self, lines: list[str], line_number: int) -> str:
        if not lines:
            return ""
        line_number = max(1, min(len(lines), int(line_number or 1)))
        start = max(1, line_number - 2)
        end = min(len(lines), line_number + 2)
        excerpt = "\n".join(f"{index}: {lines[index - 1]}" for index in range(start, end + 1))
        return excerpt[:MAX_EXCERPT_CHARS]

    def _record(
        self,
        *,
        request: Mapping[str, Any],
        request_kind: str,
        path: str,
        line_number: int,
        lines: list[str],
        role: str,
        facts: Iterable[str],
        score: int,
        claim_key: str = "",
        claim_value: str = "",
        relationship: str = "direct_source",
        authoritative: bool | None = None,
        source_kind: str = "source_excerpt",
    ) -> dict[str, Any]:
        identity = f"{path}:{max(1, int(line_number or 1))}"
        fact_values = []
        for fact in facts:
            clean = _text(fact, MAX_FACT_CHARS)
            if clean:
                fact_values.append(f"{clean} (source: {identity})")
        tier = HIGH if score >= 80 else MEDIUM if score >= 40 else LOW
        if path in self._authority_paths:
            score += 20
            tier = HIGH
        item_identity = f"{request_kind}|{identity}|{role}|{claim_key}|{claim_value}"
        evidence_id = "SEMANTIC-" + hashlib.sha256(item_identity.encode("utf-8")).hexdigest()[:16].upper()
        return {
            "evidence_id": evidence_id,
            "kind": _GATE_KIND.get(request_kind, request_kind.casefold()),
            "semantic_request_kind": request_kind,
            "target": _text(request.get("target"), 180),
            "source_identity": identity,
            "symbol": _text(_primary_symbol(str(request.get("target", "")), request_kind), 180),
            "excerpt": self._line_excerpt(lines, line_number),
            "purpose": _text(request.get("why"), 320),
            "provenance": "SEMANTIC_EVIDENCE_RESOLVER",
            "source_kind": source_kind,
            "role": role,
            "authoritative": bool(authoritative if authoritative is not None else tier == HIGH),
            "authority_tier": tier,
            "authority_score": score,
            "relationship": relationship,
            "claim_key": _text(claim_key, 180),
            "claim_value": _text(claim_value, MAX_FACT_CHARS),
            "facts_established": _unique(fact_values, limit=MAX_FACTS_PER_REQUEST),
            "resolution_status": "candidate",
        }

    def _definition_lines(self, path: str, lines: list[str], symbols: list[str]) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        wanted = {item.casefold() for item in symbols}
        for row in self._map_symbols(path):
            name = str(row.get("qualified_name", ""))
            if name.casefold() in wanted:
                matches.append({
                    "line": int(row.get("start_line", 1) or 1),
                    "name": name,
                    "signature": str(row.get("signature", "")),
                    "mapped": True,
                })
        patterns = [
            re.compile(rf"^\s*(?:async\s+)?def\s+({_IDENTIFIER})\s*\("),
            re.compile(rf"^\s*(?:export\s+)?(?:async\s+)?function\s+({_IDENTIFIER})\s*\("),
            re.compile(rf"^\s*(?:export\s+)?(?:const|let|var)\s+({_IDENTIFIER})\s*="),
            re.compile(rf"^\s*(?:export\s+)?(?:class|interface|type)\s+({_IDENTIFIER})\b"),
        ]
        for number, line in enumerate(lines, 1):
            for pattern in patterns:
                match = pattern.search(line)
                if match and match.group(1).casefold() in wanted:
                    matches.append({"line": number, "name": match.group(1), "signature": line, "mapped": False})
                    break
        unique: dict[tuple[str, int], dict[str, Any]] = {}
        for item in matches:
            unique[(str(item["name"]).casefold(), int(item["line"]))] = item
        return sorted(unique.values(), key=lambda item: (int(item["line"]), str(item["name"]).casefold()))

    def _all_definition_lines(self, lines: list[str]) -> list[tuple[int, str]]:
        patterns = [
            re.compile(r"^\s*(?:async\s+)?def\s+(" + _IDENTIFIER + r")\s*\("),
            re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(" + _IDENTIFIER + r")\s*\("),
            re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(" + _IDENTIFIER + r")\s*="),
            re.compile(r"^\s*(?:export\s+)?class\s+(" + _IDENTIFIER + r")\b"),
        ]
        result = []
        for number, line in enumerate(lines, 1):
            for pattern in patterns:
                match = pattern.search(line)
                if match:
                    result.append((number, match.group(1)))
                    break
        return result

    def _return_type_names(self, lines: list[str], symbol: str) -> set[str]:
        names: set[str] = set()
        pattern = re.compile(rf"\b{re.escape(symbol)}\s*\([^)]*\)\s*(?:->|:)\s*([A-Za-z_][A-Za-z0-9_.\[\], |]*)")
        for line in lines:
            match = pattern.search(line)
            if match:
                names.update(re.findall(_IDENTIFIER, match.group(1)))
        return {name for name in names if name.casefold() not in _STOPWORDS}

    def _declared_return_claim(self, line: str) -> str:
        """Extract only a coarse, comparable return-shape claim."""
        text = str(line)
        return_match = re.search(r"->\s*(.+)$", text)
        if return_match is None:
            return_match = re.search(r"\)\s*:\s*(.+)$", text)
        if return_match is None:
            return ""
        lowered = return_match.group(1).casefold()
        if re.search(r"\b(?:none|null|nil|void)\b", lowered):
            return "None/null"
        if re.search(r"\b(?:str|string|number|integer|int|float|boolean|bool)\b", lowered):
            return "scalar/string"
        if re.search(r"[\{\[]|\b(?:dict|mapping|object|record|response|result)\b", lowered):
            return "mapping/object"
        return ""

    def _definition_candidates(
        self,
        request: Mapping[str, Any],
        request_kind: str,
        path: str,
        lines: list[str],
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        exact = self._definition_lines(path, lines, symbols)
        target_symbol = _primary_symbol(str(request.get("target", "")), request_kind)
        all_definitions = self._all_definition_lines(lines)
        for item in exact:
            line_number = int(item["line"])
            line = lines[line_number - 1] if line_number <= len(lines) else str(item.get("signature", ""))
            is_stub = Path(path).suffix.casefold() == ".pyi"
            annotated_signature = bool(re.search(r"\)\s*(?:->|:)\s*[A-Za-z_]", line))
            explicit_contract = bool(re.search(
                r"^\s*(?:export\s+)?(?:interface|protocol|abstract\s+class|type)\b|"
                r"\b(typedDict|dataclass|BaseModel|schema|overload)\b",
                line,
                re.IGNORECASE,
            ))
            if request_kind == CONTRACT:
                if is_stub or explicit_contract or annotated_signature:
                    role, score, fact = "contract_declaration", 104, f"declared contract for {item['name']}"
                else:
                    role, score, fact = "implementation", 58, f"implementation of {item['name']}"
            elif request_kind == TYPE_OR_SCHEMA:
                if re.search(r"\b(interface|type|schema|model|dataclass|typedDict|BaseModel)\b", line, re.IGNORECASE):
                    role, score, fact = "type_schema", 104, f"type or schema declaration for {item['name']}"
                else:
                    continue
            elif request_kind == SYMBOL_DEFINITION:
                role, score, fact = "symbol_definition", 100, f"definition of {item['name']}"
            elif request_kind == SIBLING_IMPLEMENTATION:
                if str(item["name"]).casefold() == target_symbol.casefold():
                    continue
                role, score, fact = "sibling_implementation", 68, f"sibling implementation {item['name']}"
            else:
                continue
            records.append(self._record(
                request=request, request_kind=request_kind, path=path, line_number=line_number,
                lines=lines, role=role, facts=(fact,), score=score,
                relationship="defines_symbol", source_kind="symbol_declaration",
                claim_key=(f"{item['name']}.return_expectation" if request_kind == CONTRACT else ""),
                claim_value=(self._declared_return_claim(line) if request_kind == CONTRACT else ""),
            ))

        if request_kind in {CONTRACT, TYPE_OR_SCHEMA}:
            return records

        if request_kind == SIBLING_IMPLEMENTATION:
            target_lower = target_symbol.casefold()
            for line_number, name in all_definitions:
                name_lower = name.casefold()
                if name_lower == target_lower:
                    continue
                shared = (
                    target_lower.split("_")[0] == name_lower.split("_")[0]
                    or target_lower.endswith(name_lower)
                    or name_lower.endswith(target_lower)
                )
                if shared:
                    records.append(self._record(
                        request=request, request_kind=request_kind, path=path, line_number=line_number,
                        lines=lines, role="sibling_implementation",
                        facts=(f"sibling implementation {name} provides comparable behavior",),
                        score=68, relationship="same_module_sibling", source_kind="symbol_declaration",
                    ))
            return records
        return records

    def _type_and_contract_records(
        self,
        request: Mapping[str, Any],
        request_kind: str,
        path: str,
        lines: list[str],
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        if request_kind not in {CONTRACT, TYPE_OR_SCHEMA}:
            return []
        target = _primary_symbol(str(request.get("target", "")), request_kind)
        return_types = self._return_type_names(lines, target)
        records: list[dict[str, Any]] = []
        for number, line in enumerate(lines, 1):
            if _is_comment(line):
                continue
            nearby = lines[max(0, number - 12):number]
            non_comment_nearby = [item for item in nearby if not _is_comment(item)]
            interface_scope = any(
                re.search(r"\b(?:interface|protocol|abstract\s+class)\b", item, re.IGNORECASE)
                for item in non_comment_nearby
            )
            decorator_scope = any(
                re.search(r"\b(?:dataclass|BaseModel|TypedDict|schema)\b", item, re.IGNORECASE)
                for item in non_comment_nearby[-3:]
            )
            mentions_target = any(
                re.search(rf"(?<![A-Za-z0-9_$]){re.escape(symbol)}(?![A-Za-z0-9_$])", line)
                for symbol in symbols
            )
            mentions_return_type = bool(return_types & set(re.findall(_IDENTIFIER, line)))
            annotated_signature = bool(re.search(r"\)\s*(?:->|:)\s*[A-Za-z_]", line))
            explicit = bool(re.search(
                r"\b(interface|protocol|abstract|typedDict|dataclass|BaseModel|schema|overload|"
                r"type\s+[A-Za-z_]|class\s+[A-Za-z_].*(?:Model|Schema|Response|Result))\b",
                line,
                re.IGNORECASE,
            )) or interface_scope or decorator_scope or annotated_signature
            if not explicit or not (mentions_target or mentions_return_type):
                continue
            declared_claim = self._declared_return_claim(line) if request_kind == CONTRACT else ""
            records.append(self._record(
                request=request, request_kind=request_kind, path=path, line_number=number,
                lines=lines, role="type_schema" if request_kind == TYPE_OR_SCHEMA else "contract_declaration",
                facts=(
                    f"declared type/schema evidence is associated with {target}",
                    f"declared return type {sorted(return_types)[0]}" if return_types else "explicit interface or schema declaration",
                ),
                score=104, relationship="declared_type_or_contract", source_kind="type_or_schema",
                claim_key=(f"{target}.return_expectation" if declared_claim else ""),
                claim_value=declared_claim,
            ))
        return records

    def _call_records(
        self,
        request: Mapping[str, Any],
        request_kind: str,
        path: str,
        lines: list[str],
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        if request_kind not in {CONTRACT, CALLER_EXPECTATION, TEST_EXPECTATION}:
            return []
        target = _primary_symbol(str(request.get("target", "")), request_kind)
        if not target:
            return []
        records: list[dict[str, Any]] = []
        call_pattern = re.compile(rf"(?<![A-Za-z0-9_$]){re.escape(target)}\s*\(")
        for number, line in enumerate(lines, 1):
            if _is_comment(line) or not call_pattern.search(line):
                continue
            if re.search(rf"\b(?:def|function)\s+{re.escape(target)}\b", line):
                continue
            start = max(0, number - 1)
            end = min(len(lines), number + 3)
            window = "\n".join(lines[start:end])
            assertions = bool(re.search(
                r"\b(assert|expect|should|toEqual|toBe|toHaveProperty|assertEqual|assertRaises)\b|"
                r"\bis\s+None\b|\bis\s+not\s+None\b|===?|!==?",
                window,
                re.IGNORECASE,
            ))
            fields = []
            destructure_shape = ""
            destructure_pattern = re.compile(
                r"(?:\b(?:const|let|var)\s+)?(?P<open>[\{\[])\s*"
                r"(?P<body>[^\}\]\n]+?)\s*(?P<close>[\}\]])\s*=\s*"
                + re.escape(target) + r"\s*\("
            )
            destructure = destructure_pattern.search(line)
            if destructure and (
                (destructure.group("open") == "{" and destructure.group("close") == "}")
                or (destructure.group("open") == "[" and destructure.group("close") == "]")
            ):
                destructure_shape = "mapping/object" if destructure.group("open") == "{" else "sequence/array"
                for part in destructure.group("body").split(","):
                    candidate = part.split(":", 1)[0].split("=", 1)[0].strip()
                    match = re.search(r"\b([A-Za-z_$][A-Za-z0-9_$]*)\b", candidate)
                    if match and match.group(1).casefold() not in _STOPWORDS:
                        fields.append(match.group(1))
            for match in re.finditer(r"""(?:\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\]|\.([A-Za-z_][A-Za-z0-9_]*))""", window):
                field = match.group(1) or match.group(2)
                if field and field.casefold() not in _STOPWORDS and field.casefold() != target.casefold():
                    fields.append(field)
            fields = _unique(fields, limit=3)
            expects_none = bool(re.search(r"\b(?:is|toBe)\s+None\b|\btoBeNull\b|\bnull\b", window, re.IGNORECASE))
            expects_string = bool(re.search(r"""['"][^'"]+['"]""", window)) and not fields
            semantic_use = bool(fields or assertions or re.search(
                r"\b(?:except|catch|raise|throw|if\s+not|typeof|isinstance)\b", window, re.IGNORECASE,
            ))
            is_test = _is_test_path(path) or assertions
            if request_kind == TEST_EXPECTATION and not is_test:
                continue
            if fields:
                shape = destructure_shape or "mapping/object"
                fact = (
                    f"caller accesses or destructures {target} result field '{fields[0]}', "
                    f"establishing a {shape}-like return"
                )
                claim = f"{shape} with field {fields[0]}"
            elif expects_none:
                fact = f"caller or test expects {target} to return None/null"
                claim = "None/null"
            elif expects_string:
                fact = f"caller or test expects {target} to return a scalar/string value"
                claim = "scalar/string"
            elif semantic_use:
                fact = f"caller or test asserts a behavior of {target}"
                claim = "behavior assertion"
            else:
                fact = f"call site invokes {target} without a visible result expectation"
                claim = ""

            if request_kind == CALLER_EXPECTATION and not semantic_use:
                score = 64
            elif is_test:
                score = 96
            else:
                score = 92
            records.append(self._record(
                request=request, request_kind=request_kind, path=path, line_number=number,
                lines=lines, role="test_direct" if is_test else "caller_expectation",
                facts=(fact,), score=score,
                claim_key=f"{target}.return_expectation" if claim else "",
                claim_value=claim,
                relationship="direct_call_site",
                source_kind="behavioral_assertion" if assertions else "consumer_call_site",
            ))
        return records

    def _state_records(
        self,
        request: Mapping[str, Any],
        request_kind: str,
        path: str,
        lines: list[str],
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        if request_kind not in {STATE_TRANSITION, STATE_INVARIANT}:
            return []
        states = [item for item in _identifier_tokens(str(request.get("target", ""))) if len(item) >= 2]
        state_pattern = r"(?:" + "|".join(re.escape(item) for item in states) + ")" if states else r"[A-Z][A-Z0-9_]+"
        pairs: list[tuple[int, str, str]] = []
        for number, line in enumerate(lines, 1):
            if _is_comment(line):
                continue
            equality = re.search(rf"\b(?:state|status)\b\s*(?:==|is)\s*({state_pattern})", line)
            assignment = re.search(rf"\b(?:state|status)\b\s*=\s*({state_pattern})", line)
            setter = re.search(
                rf'''\b(?:setState|transition|set_status)\s*\(\s*['"]?({state_pattern})['"]?\s*(?:,|['"]?\s*\)|,\s*['"]?({state_pattern}))''',
                line,
                re.IGNORECASE,
            )
            if equality and assignment:
                pairs.append((number, equality.group(1), assignment.group(1)))
            elif setter:
                values = [item for item in setter.groups() if item]
                if len(values) >= 2:
                    pairs.append((number, values[0], values[1]))
            elif equality:
                # Support the common multiline guard form:
                #   if state == IDLE:
                #       state = RUNNING
                for following_number in range(number + 1, min(len(lines), number + 3) + 1):
                    following = lines[following_number - 1]
                    next_assignment = re.search(
                        rf"\b(?:state|status)\b\s*=\s*({state_pattern})",
                        following,
                    )
                    if next_assignment:
                        pairs.append((number, equality.group(1), next_assignment.group(1)))
                        break
        if request_kind == STATE_INVARIANT:
            records = []
            target = _primary_symbol(str(request.get("target", "")), request_kind)
            guarded_lines: set[int] = set()
            for definition in self._definition_lines(path, lines, [target]):
                start = int(definition["line"])
                guarded_lines.update(range(start, min(len(lines), start + 24) + 1))
            for number, line in enumerate(lines, 1):
                if _is_comment(line):
                    continue
                if not re.search(r"\b(assert|raise|throw|must|invariant|guard|if)\b", line, re.IGNORECASE):
                    continue
                mentions_target = bool(symbols and any(
                    re.search(rf"\b{re.escape(symbol)}\b", line) for symbol in symbols
                ))
                state_signal = bool(re.search(r"\b(?:state|status|phase|lifecycle|transition)\b", line, re.IGNORECASE))
                strong_signal = bool(re.search(r"\b(?:assert|raise|throw|must|invariant|guard|precondition)\b", line, re.IGNORECASE))
                if not mentions_target and not state_signal and not strong_signal:
                    continue
                records.append(self._record(
                    request=request, request_kind=request_kind, path=path, line_number=number,
                    lines=lines, role="state_invariant",
                    facts=(f"guard or assertion establishes an invariant for {target}",),
                    score=94 if re.search(r"\b(assert|raise|throw)\b", line, re.IGNORECASE) else 82,
                    relationship="state_guard", source_kind="guard_or_assertion",
                ))
            return records
        if not pairs:
            return []
        sequence = [pairs[0][1], pairs[0][2]]
        for _number, before, after in pairs[1:]:
            if before == sequence[-1]:
                sequence.append(after)
        target_sequence = [item for item in states if item]
        if target_sequence and not all(item in sequence for item in target_sequence):
            return []
        value = " -> ".join(sequence)
        return [self._record(
            request=request, request_kind=request_kind, path=path,
            line_number=pairs[0][0], lines=lines, role="state_transition",
            facts=(f"state transition {value} is performed by guarded transition logic",),
            score=98, claim_key="state.transition", claim_value=value,
            relationship="before_after_transition", source_kind="state_transition_logic",
        )]

    def _export_records(
        self,
        request: Mapping[str, Any],
        request_kind: str,
        path: str,
        lines: list[str],
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        if request_kind != EXPORT_OR_PUBLIC_SURFACE:
            return []
        records: list[dict[str, Any]] = []
        target = _primary_symbol(str(request.get("target", "")), request_kind)
        map_exports = self._map_file(path).get("exports", [])
        for number, line in enumerate(lines, 1):
            if _is_comment(line):
                continue
            export_match = bool(re.search(
                rf"\b(?:export|exports|module\.exports|__all__)\b.*\b{re.escape(target)}\b|"
                rf"\bfrom\b.*\bimport\b.*\b{re.escape(target)}\b|"
                rf"\bimport\b.*\b{re.escape(target)}\b",
                line,
                re.IGNORECASE,
            ))
            if not export_match and target in {str(item) for item in map_exports}:
                export_match = True
            if not export_match:
                continue
            records.append(self._record(
                request=request, request_kind=request_kind, path=path, line_number=number,
                lines=lines, role="public_export",
                facts=(f"public surface exports or re-exports {target}",),
                score=106, relationship="module_export", source_kind="export_surface",
            ))
        return records

    def _dependency_records(
        self,
        request: Mapping[str, Any],
        request_kind: str,
        path: str,
        lines: list[str],
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        if request_kind not in {CALLEE_DEPENDENCY, CONFIGURATION_DEPENDENCY}:
            return []
        target = _primary_symbol(str(request.get("target", "")), request_kind)
        records: list[dict[str, Any]] = []
        definition = self._definition_lines(path, lines, [target])
        if request_kind == CALLEE_DEPENDENCY:
            if definition:
                start = definition[0]["line"]
                end = min(len(lines), start + 24)
                for number in range(start, end + 1):
                    line = lines[number - 1]
                    if _is_comment(line):
                        continue
                    calls = [
                        name for name in re.findall(r"\b(" + _IDENTIFIER + r")\s*\(", line)
                        if name.casefold() not in _BUILTIN_CALLS and name.casefold() != target.casefold()
                    ]
                    for name in _unique(calls, limit=2):
                        records.append(self._record(
                            request=request, request_kind=request_kind, path=path, line_number=number,
                            lines=lines, role="callee_dependency",
                            facts=(f"{target} calls or depends on {name}",),
                            score=86, relationship="callee_call", source_kind="callee_call_site",
                        ))
            import_count = 0
            for number, line in enumerate(lines, 1):
                if re.search(r"\b(?:from|import|require)\b", line) and definition:
                    records.append(self._record(
                        request=request, request_kind=request_kind, path=path, line_number=number,
                        lines=lines, role="callee_dependency",
                        facts=(f"{target} has a module dependency visible at this source",),
                        score=82, relationship="callee_import", source_kind="import_edge",
                    ))
                    import_count += 1
                    if import_count >= 2:
                        break
        else:
            target_lines: set[int] = set()
            for definition_row in definition:
                start = int(definition_row["line"])
                target_lines.update(range(start, min(len(lines), start + 24) + 1))
            for number, line in enumerate(lines, 1):
                if _is_comment(line):
                    continue
                config_signal = re.search(
                    r"\b(?:os\.environ|process\.env|settings|config|configuration|"
                    r"getenv|dotenv|env\.)\b",
                    line,
                    re.IGNORECASE,
                )
                if config_signal and (target.casefold() in line.casefold() or number in target_lines or not target):
                    records.append(self._record(
                        request=request, request_kind=request_kind, path=path, line_number=number,
                        lines=lines, role="configuration_dependency",
                        facts=(f"{target} reads or depends on configuration at this source",),
                        score=88, relationship="configuration_read", source_kind="configuration_access",
                    ))
        return records

    def _lexical_records(
        self,
        request: Mapping[str, Any],
        request_kind: str,
        path: str,
        lines: list[str],
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        records = []
        for number, line in enumerate(lines, 1):
            if not any(re.search(rf"(?<![A-Za-z0-9_$]){re.escape(symbol)}(?![A-Za-z0-9_$])", line, re.IGNORECASE) for symbol in symbols):
                continue
            records.append(self._record(
                request=request, request_kind=request_kind, path=path, line_number=number,
                lines=lines, role="lexical_mention",
                facts=(), score=12 if _is_comment(line) else 18,
                relationship="textual_match", source_kind="lexical_fallback",
                authoritative=False,
            ))
            if len(records) >= 2:
                break
        return records

    def _collect_records(
        self,
        request: Mapping[str, Any],
        request_kind: str,
        paths: list[str],
    ) -> tuple[list[dict[str, Any]], bool]:
        symbols = _identifier_tokens(str(request.get("target", "")))
        structural: list[dict[str, Any]] = []
        for path in paths:
            text = self._read(path)
            lines = text.splitlines()
            if not lines:
                continue
            structural.extend(self._definition_candidates(request, request_kind, path, lines, symbols))
            structural.extend(self._type_and_contract_records(request, request_kind, path, lines, symbols))
            structural.extend(self._call_records(request, request_kind, path, lines, symbols))
            structural.extend(self._state_records(request, request_kind, path, lines, symbols))
            structural.extend(self._export_records(request, request_kind, path, lines, symbols))
            structural.extend(self._dependency_records(request, request_kind, path, lines, symbols))
        return structural, bool(structural)

    def _candidate_key(self, item: Mapping[str, Any]) -> tuple[str, str, str]:
        return (
            str(item.get("source_identity", "")),
            str(item.get("relationship", "")),
            str(item.get("claim_value", "")),
        )

    def _conflicts(self, records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        claims: dict[str, dict[str, list[Mapping[str, Any]]]] = {}
        for item in records:
            if not item.get("authoritative") or not item.get("claim_key") or not item.get("claim_value"):
                continue
            key = str(item["claim_key"])
            value = str(item["claim_value"]).casefold()
            claims.setdefault(key, {}).setdefault(value, []).append(item)
        result = []
        for key, values in claims.items():
            if len(values) < 2:
                continue
            evidence = [item for rows in values.values() for item in rows]
            result.append({
                "claim_key": key,
                "values": [str(value) for value in sorted(values)],
                "evidence_ids": [str(item.get("evidence_id")) for item in evidence[: self.max_evidence_items]],
            })
        return result[:MAX_CONFLICTS]

    def _select_records(
        self,
        request_kind: str,
        records: list[dict[str, Any]],
        conflicts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ordered = sorted(records, key=lambda item: (
            -int(item.get("authority_score", 0) or 0),
            str(item.get("role", "")),
            str(item.get("source_identity", "")),
        ))
        selected: list[dict[str, Any]] = []
        seen_facts: set[str] = set()
        if conflicts:
            conflict_values = {
                (str(conflict.get("claim_key")), str(value).casefold())
                for conflict in conflicts
                for value in conflict.get("values", [])
            }
            for item in ordered:
                marker = (str(item.get("claim_key")), str(item.get("claim_value", "")).casefold())
                if marker not in conflict_values:
                    continue
                selected.append(item)
                if len(selected) >= self.max_evidence_items:
                    break
            return selected

        for item in ordered:
            facts = item.get("facts_established", []) or []
            fact_key = "|".join(str(fact).split("(source:", 1)[0].strip().casefold() for fact in facts)
            if fact_key and fact_key in seen_facts:
                continue
            if fact_key:
                seen_facts.add(fact_key)
            selected.append(item)
            if request_kind in {CONTRACT, TYPE_OR_SCHEMA, TEST_EXPECTATION, SYMBOL_DEFINITION, EXPORT_OR_PUBLIC_SURFACE}:
                if item.get("authoritative"):
                    break
            elif request_kind == CALLER_EXPECTATION:
                if item.get("claim_value") or len(selected) >= 2:
                    break
            elif request_kind in {STATE_TRANSITION, STATE_INVARIANT}:
                break
            elif len(selected) >= 2:
                break
            if len(selected) >= self.max_evidence_items:
                break
        return selected[: self.max_evidence_items]

    def _status(
        self,
        request_kind: str,
        records: list[dict[str, Any]],
        selected: list[dict[str, Any]],
        conflicts: list[dict[str, Any]],
    ) -> str:
        if conflicts:
            return "conflicting"
        if not selected:
            return "unresolved"
        if any(item.get("role") == "lexical_mention" for item in selected):
            return "unresolved"
        if request_kind == CONTRACT:
            return "resolved" if any(
                item.get("role") in {"contract_declaration", "type_schema", "test_direct", "caller_expectation"}
                and item.get("authoritative")
                for item in selected
            ) else "partial"
        if request_kind == TYPE_OR_SCHEMA:
            return "resolved" if any(item.get("role") == "type_schema" and item.get("authoritative") for item in selected) else "partial"
        if request_kind == TEST_EXPECTATION:
            return "resolved" if any(item.get("role") == "test_direct" and item.get("authoritative") for item in selected) else "partial"
        if request_kind == CALLER_EXPECTATION:
            return "resolved" if any(
                item.get("role") in {"caller_expectation", "test_direct"} and item.get("claim_value")
                for item in selected
            ) else "partial"
        if request_kind == EXPORT_OR_PUBLIC_SURFACE:
            return "resolved" if any(item.get("role") == "public_export" for item in selected) else "partial"
        if request_kind == SYMBOL_DEFINITION:
            return "resolved" if any(item.get("role") == "symbol_definition" for item in selected) else "partial"
        if request_kind == SIBLING_IMPLEMENTATION:
            return "resolved" if any(item.get("role") == "sibling_implementation" for item in selected) else "partial"
        return "resolved" if any(item.get("authoritative") for item in selected) else "partial"

    def resolve(
        self,
        request: Mapping[str, Any] | None,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resolve one validated request without expanding the Worker context."""
        value = request if isinstance(request, Mapping) else {}
        request_kind = canonical_request_kind(value.get("kind"))
        if request_kind == "UNKNOWN":
            return {
                "request_kind": "UNKNOWN",
                "target": _text(value.get("target"), 180),
                "resolution_status": "unresolved",
                "facts_established": [],
                "evidence": [],
                "candidates_considered": 0,
                "candidate_files_considered": 0,
                "relationship_hops": 0,
                "provenance": [],
            }
        self._context_authority(context)
        self._path_set = set(self._files)
        ordered_paths = self._source_order(request_kind, str(value.get("target", "")))
        relationship_paths, relationship_hops = self._bounded_relationship_paths(ordered_paths[: self.max_candidates])
        self._relationship_hops = relationship_hops
        paths = list(dict.fromkeys([*ordered_paths, *relationship_paths]))[: self.max_files_scanned]
        structural, had_structural = self._collect_records(value, request_kind, paths)
        records = structural
        fallback_used = False
        if not records:
            fallback_used = True
            for path in paths:
                lines = self._read(path).splitlines()
                records.extend(self._lexical_records(
                    value, request_kind, path, lines, _identifier_tokens(str(value.get("target", ""))),
                ))
        unique: dict[tuple[str, str, str], dict[str, Any]] = {}
        for item in records:
            unique.setdefault(self._candidate_key(item), item)
        records = list(unique.values())
        records.sort(key=lambda item: (
            -int(item.get("authority_score", 0) or 0),
            str(item.get("source_identity", "")),
        ))
        all_conflicts = self._conflicts(records)
        bounded_records = records[: self.max_candidates]
        # A low-ranked authoritative claim must not disappear merely because
        # several agreeing lexical/structural candidates filled the candidate
        # cap first. Reserve one source for every conflicting claim value.
        for conflict in all_conflicts:
            claim_values = {str(item).casefold() for item in conflict.get("values", [])}
            for claim_value in claim_values:
                match = next(
                    (
                        item for item in records
                        if str(item.get("claim_key")) == str(conflict.get("claim_key"))
                        and str(item.get("claim_value", "")).casefold() == claim_value
                    ),
                    None,
                )
                if match is None or match in bounded_records:
                    continue
                if len(bounded_records) >= self.max_candidates:
                    bounded_records[-1] = match
                else:
                    bounded_records.append(match)
        conflicts = self._conflicts(bounded_records)
        selected = self._select_records(request_kind, bounded_records, conflicts)
        status = self._status(request_kind, bounded_records, selected, conflicts)
        for item in selected:
            item["resolution_status"] = status
        facts = _unique(
            (fact for item in selected for fact in item.get("facts_established", []) or []),
            limit=MAX_FACTS_PER_REQUEST,
        )
        provenance = [
            {
                "evidence_id": item.get("evidence_id"),
                "source_identity": item.get("source_identity"),
                "relationship": item.get("relationship"),
                "authority_tier": item.get("authority_tier"),
            }
            for item in selected
        ]
        highest = max((int(item.get("authority_score", 0) or 0) for item in selected), default=0)
        return {
            "request_kind": request_kind,
            "gate_request_kind": gate_request_kind(request_kind),
            "target": _text(value.get("target"), 180),
            "resolution_status": status,
            "facts_established": facts,
            "evidence": selected,
            "provenance": provenance,
            "conflicts": conflicts,
            "authority": {
                "highest_tier": HIGH if highest >= 80 else MEDIUM if highest >= 40 else LOW if highest else None,
                "highest_score": highest,
            },
            "candidates_considered": min(len(records), self.max_candidates),
            "candidate_files_considered": len(paths),
            "relationship_hops": self._relationship_hops,
            "max_relationship_hops": self.max_relationship_hops,
            "max_candidates": self.max_candidates,
            "max_evidence_items": self.max_evidence_items,
            "structural_search": bool(had_structural),
            "fallback_used": fallback_used,
            "resolver": "SEMANTIC_EVIDENCE_RESOLVER",
        }


def resolve_targeted_evidence(
    request: Mapping[str, Any] | None,
    *,
    workspace: str | Path,
    allowed_inspection_paths: Iterable[str | Path] | None = None,
    repository_map: Any = None,
    context: Mapping[str, Any] | None = None,
    max_relationship_hops: int = MAX_RELATIONSHIP_HOPS,
    max_candidates: int = MAX_CANDIDATES_PER_REQUEST,
    max_files_scanned: int = MAX_FILES_SCANNED_PER_REQUEST,
    max_evidence_items: int = MAX_RESOLVED_EVIDENCE_ITEMS,
) -> dict[str, Any]:
    resolver = SemanticEvidenceResolver(
        workspace,
        allowed_inspection_paths,
        repository_map=repository_map,
        max_relationship_hops=max_relationship_hops,
        max_candidates=max_candidates,
        max_files_scanned=max_files_scanned,
        max_evidence_items=max_evidence_items,
    )
    return resolver.resolve(request, context)


__all__ = [
    "CONTRACT", "CALLER_EXPECTATION", "CALLEE_DEPENDENCY", "TEST_EXPECTATION",
    "TYPE_OR_SCHEMA", "STATE_INVARIANT", "STATE_TRANSITION", "SYMBOL_DEFINITION",
    "SIBLING_IMPLEMENTATION", "EXPORT_OR_PUBLIC_SURFACE", "CONFIGURATION_DEPENDENCY",
    "SEMANTIC_REQUEST_KINDS", "RESOLUTION_STATUSES", "MAX_RELATIONSHIP_HOPS",
    "MAX_CANDIDATES_PER_REQUEST", "MAX_FILES_SCANNED_PER_REQUEST",
    "MAX_RESOLVED_EVIDENCE_ITEMS", "canonical_request_kind", "gate_request_kind",
    "SemanticEvidenceResolver", "resolve_targeted_evidence",
]
