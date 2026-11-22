"""Deterministic Assume-Guarantee Interface Certificate & Disjoint Child Ownership.

Grounded in Interface Automata (de Alfaro & Henzinger, ESEC/FSE 2001) and
HarrTest 5.1 Producer -> Consumer contracts, this zero-model module enforces:

1. Disjoint child mutation ownership and acyclic Producer -> Consumer dependency
   ordering across decomposed child tasks (`partition_disjoint_child_ownership`).
2. Static extraction of per-file interface guarantees and assumptions across
   Python, HTML, JavaScript, and CSS (`extract_file_certificate`).
3. Compositional verification of cross-file assumptions against sibling
   guarantees with 1-line ACI repair counterexamples
   (`verify_compositional_certificates`).
4. Bounded, deterministic rendering of verified sibling interface contracts for
   downstream consumer workers (`format_sibling_guarantees_context`).
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import posixpath
import re
from html.parser import HTMLParser
from typing import Any

from hivo.execution_contracts import (
    classify_code_location_reference,
    code_location_references,
)


SCHEMA_VERSION = "ASSUME-GUARANTEE-1"

# Compositional Violation Codes
MISSING_RELATIVE_MODULE = "MISSING_RELATIVE_MODULE"
MISSING_JS_EXPORT = "MISSING_JS_EXPORT"
THREE_CORE_MISIMPORTED_FROM_ADDONS = "THREE_CORE_MISIMPORTED_FROM_ADDONS"
MISSING_IMPORTMAP_SPECIFIER = "MISSING_IMPORTMAP_SPECIFIER"
MISSING_DOM_ID = "MISSING_DOM_ID"
MISSING_PYTHON_SYMBOL = "MISSING_PYTHON_SYMBOL"
MISSING_HTML_SCRIPT = "MISSING_HTML_SCRIPT"
MISSING_HTML_STYLESHEET = "MISSING_HTML_STYLESHEET"

# Known Three.js r160 core exports (never located under three/addons/*)
_THREE_CORE_NOT_ADDONS = frozenset({
    "Scene",
    "PerspectiveCamera",
    "OrthographicCamera",
    "WebGLRenderer",
    "AmbientLight",
    "DirectionalLight",
    "PointLight",
    "HemisphereLight",
    "SpotLight",
    "GridHelper",
    "AxesHelper",
    "BoxGeometry",
    "SphereGeometry",
    "CylinderGeometry",
    "ConeGeometry",
    "TorusGeometry",
    "PlaneGeometry",
    "OctahedronGeometry",
    "IcosahedronGeometry",
    "RingGeometry",
    "BufferGeometry",
    "Float32BufferAttribute",
    "Points",
    "PointsMaterial",
    "Mesh",
    "Group",
    "MeshStandardMaterial",
    "MeshPhongMaterial",
    "MeshBasicMaterial",
    "Color",
    "Vector2",
    "Vector3",
    "Clock",
    "Raycaster",
    "Fog",
    "FogExp2",
})

# Producer -> Consumer Tiers
TIER_FOUNDATION_PRODUCER = 0
TIER_CONSUMER_ENTRYPOINT = 1
TIER_VERIFICATION_SUITE = 2

_PY_CLI_BASENAMES = frozenset({
    "cli.py",
    "main.py",
    "app.py",
    "__main__.py",
    "run.py",
    "server.py",
    "manage.py",
    "wsgi.py",
    "asgi.py",
})

_JS_EXTENSIONS = frozenset({".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"})
_HTML_EXTENSIONS = frozenset({".html", ".htm"})
_CSS_EXTENSIONS = frozenset({".css", ".scss"})
_CONFIG_EXTENSIONS = frozenset({".json", ".toml", ".yaml", ".yml"})
_PY_EXTENSIONS = frozenset({".py", ".pyi"})

_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_UPPER_CONST_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Clause-level intent analysis patterns for ownership partitioning
_PRIMARY_MUTATION_VERB_RE = re.compile(
    r"\b(?:"
    r"implement|create|write|build|add|author|define|develop|construct|"
    r"scaffold|generate|update|edit|modify|refactor|patch|fix|repair|"
    r"populate|produce"
    r")(?:es|s|ed|ing)?\b",
    re.IGNORECASE,
)

_CONSUMER_CONTEXT_RE = re.compile(
    r"\b(?:"
    r"import(?:s|ed|ing)?(?:\s+from)?|"
    r"from|"
    r"us(?:e|es|ed|ing)|"
    r"call(?:s|ed|ing)?|"
    r"invok(?:e|es|ed|ing)|"
    r"referenc(?:e|es|ed|ing)|"
    r"read(?:s|ing)?(?:\s+from)?|"
    r"load(?:s|ed|ing)?(?:\s+from)?|"
    r"consum(?:e|es|ed|ing)|"
    r"depend(?:s|ed|ing)?\s+on|"
    r"against|"
    r"cover(?:s|ed|ing)?|"
    r"test(?:s|ed|ing)?(?:\s+for)?|"
    r"verif(?:y|ies|ied|ying)|"
    r"inspect(?:s|ed|ing)?|"
    r"check(?:s|ed|ing)?|"
    r"query(?:ing)?|"
    r"mount(?:s|ed|ing)?\s+(?:into|in|to)|"
    r"attach(?:es|ed|ing)?\s+to|"
    r"render(?:s|ed|ing)?\s+into|"
    r"link(?:s|ed|ing)?\s+to|"
    r"integrat(?:e|es|ed|ing)\s+with|"
    r"connect(?:s|ed|ing)?\s+to|"
    r"wire(?:s|d|ing)?\s+(?:to|into|with)|"
    r"defin(?:ed|es)\s+in|"
    r"declar(?:ed|es)\s+in|"
    r"provid(?:ed|es)\s+by|"
    r"export(?:ed|s)\s+(?:by|from)|"
    r"exposed\s+by"
    r")\b",
    re.IGNORECASE,
)

_NEGATION_RE = re.compile(
    r"\b(?:do\s+not|don['’]t|must\s+not|never|avoid|without|read[- ]only)\b",
    re.IGNORECASE,
)

_COORDINATION_ONLY_RE = re.compile(
    r"^[\s`'\"(),]*(?:and|or|&|plus|along\s+with|as\s+well\s+as|,)\s*[\s`'\"(]*$",
    re.IGNORECASE,
)

_DESTINATION_IN_RE = re.compile(
    r"[\s`'\"(),]*\b(?:in|into|inside|within|at|under)\s+[\s`'\"(]*$",
    re.IGNORECASE,
)

_SENTENCE_BOUNDARY_RE = re.compile(r"[!?;]|\.(?=\s|$)|\r?\n")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_posix_path(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    cleaned = raw.strip().strip("`'\"")
    cleaned = cleaned.rstrip(".,;:!?)]}")
    cleaned = cleaned.replace("\\", "/")
    if not cleaned or _SCHEME_RE.match(cleaned) or cleaned.startswith("//"):
        return ""
    # Strip URL query/hash fragments for local file references
    cleaned = re.split(r"[?#]", cleaned, maxsplit=1)[0].strip()
    if not cleaned:
        return ""
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if cleaned in {"", "."}:
        return ""
    had_leading_slash = cleaned.startswith("/")
    normed = posixpath.normpath(cleaned)
    if normed in {"", "."}:
        return ""
    if had_leading_slash and not normed.startswith("/"):
        normed = "/" + normed
    return normed


def _is_valid_workspace_code_path(path: str) -> bool:
    if not path:
        return False
    if _SCHEME_RE.match(path) or path.startswith(("/", "../")) or path == "..":
        return False
    if re.match(r"^[A-Za-z]:/", path):
        return False
    if "*" in path or "?" in path:
        return False
    return True


def _path_extension(path: str) -> str:
    base = posixpath.basename(path)
    if "." not in base:
        return ""
    return "." + base.rsplit(".", 1)[-1].casefold()


def _is_test_path(path: str) -> bool:
    norm = path.casefold().lstrip("/")
    parts = [p for p in norm.split("/") if p]
    if any(seg in {"tests", "test", "__tests__"} for seg in parts[:-1]):
        return True
    base = parts[-1] if parts else norm
    if base == "conftest.py":
        return True
    if base.startswith("test_") and (base.endswith(".py") or base.endswith(".js") or base.endswith(".ts")):
        return True
    if re.search(r"(?:_test\.py|\.(?:test|spec)\.(?:js|mjs|cjs|jsx|ts|tsx))$", base):
        return True
    return False


def _is_py_cli_path(path: str) -> bool:
    base = posixpath.basename(path).casefold()
    if base in _PY_CLI_BASENAMES:
        return True
    if base.endswith("_cli.py") or base.startswith("cli_"):
        return True
    return False


def _classify_path_tier(path: str, *, has_external_js: bool) -> int:
    if _is_test_path(path):
        return TIER_VERIFICATION_SUITE
    ext = _path_extension(path)
    if ext in _PY_EXTENSIONS:
        return TIER_CONSUMER_ENTRYPOINT if _is_py_cli_path(path) else TIER_FOUNDATION_PRODUCER
    if ext in _CSS_EXTENSIONS or ext in _CONFIG_EXTENSIONS:
        return TIER_FOUNDATION_PRODUCER
    if ext in _HTML_EXTENSIONS:
        return TIER_FOUNDATION_PRODUCER if has_external_js else TIER_CONSUMER_ENTRYPOINT
    if ext in _JS_EXTENSIONS:
        return TIER_CONSUMER_ENTRYPOINT
    return TIER_FOUNDATION_PRODUCER


def _path_ecosystem(path: str) -> str:
    ext = _path_extension(path)
    if ext in _PY_EXTENSIONS:
        return "python"
    if ext in _HTML_EXTENSIONS or ext in _JS_EXTENSIONS or ext in _CSS_EXTENSIONS:
        return "web"
    return "other"


def _resolve_against_declared(path: str, declared_list: list[str]) -> str:
    if not declared_list:
        return path
    exact_map = {d.casefold(): d for d in declared_list}
    if path.casefold() in exact_map:
        return exact_map[path.casefold()]
    if "/" not in path:
        matches = [d for d in declared_list if posixpath.basename(d).casefold() == path.casefold()]
        if len(matches) == 1:
            return matches[0]
    return path


def _extract_paths_from_value(
    value: Any,
    contract: dict[str, Any] | None,
    declared_list: list[str],
) -> list[str]:
    found: list[str] = []
    if value is None:
        return found
    items = [value] if isinstance(value, str) else list(value) if isinstance(value, (list, tuple, set)) else [str(value)]
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        # Direct token check first (e.g. scope_hint=["metrics.py", "cli.py"])
        direct_ref = classify_code_location_reference(text, contract)
        if direct_ref and direct_ref.get("classification") == "CODE_PATH":
            norm = _normalize_posix_path(direct_ref["path"])
            if _is_valid_workspace_code_path(norm):
                resolved = _resolve_against_declared(norm, declared_list)
                if resolved not in found:
                    found.append(resolved)
                continue
        for ref in code_location_references(text, contract, include_action=True):
            if ref.get("classification") != "CODE_PATH":
                continue
            raw_tok = str(ref.get("text") or "")
            if _SCHEME_RE.match(raw_tok) or "://" in raw_tok:
                continue
            norm = _normalize_posix_path(ref.get("path"))
            if not _is_valid_workspace_code_path(norm):
                continue
            resolved = _resolve_against_declared(norm, declared_list)
            if resolved not in found:
                found.append(resolved)
    return found


# Intent score constants
_INTENT_CONSUMER = 1
_INTENT_SHARED_SCOPE = 2
_INTENT_NARROW_GOAL_OR_SCOPE = 3
_INTENT_PRIMARY_MUTATION = 4


def _analyze_goal_path_intents(
    goal: str,
    contract: dict[str, Any] | None,
    declared_list: list[str],
) -> tuple[list[str], dict[str, int]]:
    """Extract paths mentioned in `goal` and score each path's mutation vs consumer intent."""
    source = str(goal or "")
    if not source.strip():
        return [], {}

    raw_refs = code_location_references(source, contract, include_action=True)
    # Locate non-overlapping character spans for CODE_PATH mentions in goal
    occurrences: list[tuple[int, int, str]] = []
    cursor = 0
    for ref in raw_refs:
        if ref.get("classification") not in {"CODE_PATH", "TEST_PATH"}:
            continue
        raw_tok = str(ref.get("raw") or ref.get("text") or ref.get("path") or "")
        if not raw_tok or _SCHEME_RE.match(raw_tok) or "://" in raw_tok:
            continue
        norm = _normalize_posix_path(ref.get("path"))
        if not _is_valid_workspace_code_path(norm):
            continue
        resolved = _resolve_against_declared(norm, declared_list)
        pos = source.find(raw_tok, cursor)
        if pos < 0:
            pos = source.find(raw_tok)
        if pos >= 0:
            end = pos + len(raw_tok)
            cursor = end
            occurrences.append((pos, end, resolved))

    ordered_paths: list[str] = []
    intents: dict[str, int] = {}
    prev_end = 0
    prev_intent: int | None = None

    for idx, (start, end, path) in enumerate(occurrences):
        if path not in ordered_paths:
            ordered_paths.append(path)

        # Clause slice leading up to this path
        sent_bounds = list(_SENTENCE_BOUNDARY_RE.finditer(source[:start]))
        clause_start = sent_bounds[-1].end() if sent_bounds else 0
        local_Start = max(clause_start, prev_end if idx > 0 and prev_end >= clause_start else clause_start)
        between_prev = source[prev_end:start] if idx > 0 and prev_end >= clause_start else ""
        clause_prefix = source[clause_start:start]
        immediate_prefix = source[local_Start:start]

        intent: int
        if _NEGATION_RE.search(immediate_prefix) or (idx == 0 and _NEGATION_RE.search(clause_prefix)):
            intent = _INTENT_CONSUMER
        elif idx > 0 and prev_intent is not None and between_prev and _COORDINATION_ONLY_RE.match(between_prev):
            intent = prev_intent
        elif _CONSUMER_CONTEXT_RE.search(immediate_prefix) and not (
            _is_test_path(path) and _DESTINATION_IN_RE.search(immediate_prefix)
        ):
            # Watch out for "Write unit tests for metrics.py in test_metrics.py":
            # for `test_metrics.py`, `immediate_prefix` is ` in ` (not consumer),
            # whereas for `metrics.py`, `clause_prefix` has `tests for` (consumer!).
            intent = _INTENT_CONSUMER
        elif idx == 0 and _CONSUMER_CONTEXT_RE.search(clause_prefix) and not (
            _is_test_path(path) and _DESTINATION_IN_RE.search(clause_prefix)
        ):
            # E.g. "Write unit tests for metrics.py in test_metrics.py":
            # On `metrics.py` (idx == 0, non-test path), `tests for` is consumer!
            # Wait: what about "Write unit tests in test_metrics.py"? `path` IS a test path and has `in`!
            if _PRIMARY_MUTATION_VERB_RE.search(clause_prefix):
                # Check which appears closer to `path`: primary mutation verb or consumer marker
                mut_matches = list(_PRIMARY_MUTATION_VERB_RE.finditer(clause_prefix))
                cons_matches = list(_CONSUMER_CONTEXT_RE.finditer(clause_prefix))
                last_mut = mut_matches[-1].end() if mut_matches else -1
                last_cons = cons_matches[-1].start() if cons_matches else -1
                if last_cons > last_mut and not (_is_test_path(path) and _DESTINATION_IN_RE.search(clause_prefix)):
                    intent = _INTENT_CONSUMER
                else:
                    intent = _INTENT_PRIMARY_MUTATION
            else:
                intent = _INTENT_CONSUMER
        elif _PRIMARY_MUTATION_VERB_RE.search(immediate_prefix):
            intent = _INTENT_PRIMARY_MUTATION
        elif _DESTINATION_IN_RE.search(immediate_prefix) and _PRIMARY_MUTATION_VERB_RE.search(clause_prefix):
            # E.g. "Write tests for metrics.py in test_metrics.py" -> `in test_metrics.py`
            intent = _INTENT_PRIMARY_MUTATION
        elif _PRIMARY_MUTATION_VERB_RE.search(clause_prefix):
            intent = _INTENT_PRIMARY_MUTATION
        else:
            # Check trailing passive or colon definition, e.g. "metrics.py: implement ..."
            trailing = source[end:min(len(source), end + 80)]
            if re.match(r"^[\s`'\":,-]+", trailing) and _PRIMARY_MUTATION_VERB_RE.search(trailing):
                intent = _INTENT_PRIMARY_MUTATION
            else:
                intent = _INTENT_NARROW_GOAL_OR_SCOPE

        prev_end = end
        prev_intent = intent
        intents[path] = max(intents.get(path, 0), intent)

    return ordered_paths, intents


def _would_create_cycle(adj: dict[str, set[str]], src: str, dst: str) -> bool:
    """Return True if adding directed edge `src -> dst` (dst depends on src) creates a cycle."""
    if src == dst:
        return True
    # Cycle exists iff `src` is already reachable from `dst`
    stack = [dst]
    visited: set[str] = set()
    while stack:
        curr = stack.pop()
        if curr == src:
            return True
        if curr in visited:
            continue
        visited.add(curr)
        stack.extend(adj.get(curr, ()))
    return False


def partition_disjoint_child_ownership(
    children: list[dict],
    declared_paths: list[str] | None = None,
) -> dict:
    """Partition file mutation ownership disjointly and infer acyclic dependencies.

    Returns a dictionary containing:
    - ``children``: deep-copied list of child dicts enriched with
      ``owned_mutation_paths``, ``read_only_sibling_paths``, ``depends_on``,
      and narrowed ``scope_hint``.
    - ``ownership_map``: ``dict[path, owner_child_id]``.
    - ``dependency_edges``: ``list[tuple[producer_child_id, consumer_child_id]]``.
    - ``conflicts``: ``list[dict]`` recording adjudicated ownership overlaps or
      broken dependency cycles.
    """
    copied_children: list[dict[str, Any]] = [
        copy.deepcopy(child) for child in (children or []) if isinstance(child, dict)
    ]
    clean_declared: list[str] = []
    for item in declared_paths or []:
        norm = _normalize_posix_path(item)
        if _is_valid_workspace_code_path(norm) and norm not in clean_declared:
            clean_declared.append(norm)

    contract_ctx = {"allowed_mutation_paths": clean_declared} if clean_declared else None

    child_ids: list[str] = []
    goal_paths_by_idx: list[list[str]] = []
    goal_intents_by_idx: list[dict[str, int]] = []
    scope_paths_by_idx: list[list[str]] = []
    done_paths_by_idx: list[list[str]] = []
    all_candidate_paths: list[str] = []

    for idx, child in enumerate(copied_children):
        raw_id = child.get("id") or child.get("task_id") or child.get("child_id")
        cid = str(raw_id).strip() if raw_id is not None and str(raw_id).strip() else f"child_{idx + 1}"
        child["id"] = cid
        child_ids.append(cid)

        g_paths, g_intents = _analyze_goal_path_intents(
            str(child.get("goal") or ""),
            contract_ctx,
            clean_declared,
        )
        s_paths = _extract_paths_from_value(child.get("scope_hint"), contract_ctx, clean_declared)
        d_paths = _extract_paths_from_value(child.get("done_when"), contract_ctx, clean_declared)

        # Fallback: only consult done_when for ownership if goal and scope_hint yielded nothing
        if not g_paths and not s_paths and d_paths:
            s_paths = list(d_paths)

        goal_paths_by_idx.append(g_paths)
        goal_intents_by_idx.append(g_intents)
        scope_paths_by_idx.append(s_paths)
        done_paths_by_idx.append(d_paths)

        for p in [*g_paths, *s_paths]:
            if p not in all_candidate_paths:
                all_candidate_paths.append(p)

    for decl in clean_declared:
        if decl not in all_candidate_paths:
            all_candidate_paths.append(decl)

    has_external_js = any(
        _path_extension(p) in _JS_EXTENSIONS and not _is_test_path(p)
        for p in all_candidate_paths
    )
    path_tiers: dict[str, int] = {
        p: _classify_path_tier(p, has_external_js=has_external_js)
        for p in all_candidate_paths
    }

    # Refine intents: if a child has a Tier 2 test target in its goal/narrow scope,
    # non-test paths mentioned in its goal (e.g. "Test metrics.py in test_metrics.py")
    # are subjects under test (consumer references), not primary mutation targets.
    child_primary_tiers: list[int] = []
    effective_intents: list[dict[str, int]] = []

    for idx in range(len(copied_children)):
        g_paths = goal_paths_by_idx[idx]
        g_intents = dict(goal_intents_by_idx[idx])
        s_paths = scope_paths_by_idx[idx]
        mentioned = list(dict.fromkeys([*g_paths, *s_paths]))

        has_test_primary = any(
            _is_test_path(p)
            and (
                g_intents.get(p, 0) >= _INTENT_NARROW_GOAL_OR_SCOPE
                or (len(s_paths) == 1 and s_paths[0] == p)
            )
            for p in mentioned
        )

        child_map: dict[str, int] = {}
        for p in mentioned:
            if p in g_intents:
                score = g_intents[p]
                if has_test_primary and not _is_test_path(p):
                    score = _INTENT_CONSUMER
            elif len(s_paths) == 1 and s_paths[0] == p:
                score = _INTENT_NARROW_GOAL_OR_SCOPE
            else:
                score = _INTENT_SHARED_SCOPE
            child_map[p] = score

        effective_intents.append(child_map)
        primary_candidates = [
            path_tiers[p]
            for p, sc in child_map.items()
            if sc >= _INTENT_NARROW_GOAL_OR_SCOPE
        ]
        if primary_candidates:
            child_primary_tiers.append(min(primary_candidates))
        elif mentioned:
            child_primary_tiers.append(min(path_tiers[p] for p in mentioned))
        else:
            goal_lower = str(copied_children[idx].get("goal") or "").casefold()
            if re.search(r"\b(?:unit\s+tests?|test\s+suite|pytest|unittest)\b", goal_lower):
                child_primary_tiers.append(TIER_VERIFICATION_SUITE)
            else:
                child_primary_tiers.append(TIER_FOUNDATION_PRODUCER)

    # Detect blanket inherited scope_hint shared verbatim across multiple children
    scope_sets = [frozenset(s) for s in scope_paths_by_idx]
    blanket_scope_paths: set[str] = set()
    if len(copied_children) >= 2:
        for idx_a in range(len(copied_children)):
            if len(scope_sets[idx_a]) >= 2 and sum(1 for s in scope_sets if s == scope_sets[idx_a]) >= 2:
                blanket_scope_paths.update(scope_sets[idx_a])

    ownership_map: dict[str, str] = {}
    owner_idx_by_path: dict[str, int] = {}
    conflicts: list[dict[str, Any]] = []

    for path in all_candidate_paths:
        contenders = [
            idx for idx in range(len(copied_children))
            if path in effective_intents[idx]
        ]
        if not contenders and copied_children:
            # Unclaimed declared_path: match by stem mention or tier alignment
            stem = posixpath.splitext(posixpath.basename(path))[0].casefold()
            p_tier = path_tiers[path]
            best_idx = max(
                range(len(copied_children)),
                key=lambda i: (
                    1 if stem and re.search(rf"\b{re.escape(stem)}\b", str(copied_children[i].get("goal") or "").casefold()) else 0,
                    1 if child_primary_tiers[i] == p_tier else 0,
                    -len([p for p, o in owner_idx_by_path.items() if o == i]),
                    -i,
                ),
            )
            owner_idx_by_path[path] = best_idx
            ownership_map[path] = child_ids[best_idx]
            continue

        if not contenders:
            continue

        p_tier = path_tiers[path]

        def _rank_child(i: int) -> tuple[int, int, int, int]:
            intent_sc = effective_intents[i][path]
            tier_align = 1 if child_primary_tiers[i] == p_tier else 0
            return (intent_sc, tier_align, -child_primary_tiers[i], -i)

        winner_idx = max(contenders, key=_rank_child)
        owner_idx_by_path[path] = winner_idx
        ownership_map[path] = child_ids[winner_idx]

        # Record conflict if >=2 children made mutation/scope_hint claims on `path`
        mutation_claimants = [
            i for i in contenders
            if effective_intents[i][path] >= _INTENT_SHARED_SCOPE or path in scope_paths_by_idx[i]
        ]
        if len(mutation_claimants) >= 2:
            winner_intent = effective_intents[winner_idx][path]
            loser_max = max(effective_intents[i][path] for i in mutation_claimants if i != winner_idx)
            if winner_intent > loser_max:
                resolution = "primary_intent"
            elif any(child_primary_tiers[winner_idx] < child_primary_tiers[i] for i in mutation_claimants if i != winner_idx):
                resolution = "producer_tier"
            else:
                resolution = "child_order"
            conflicts.append({
                "kind": "overlapping_mutation_claim",
                "path": path,
                "owner_child_id": child_ids[winner_idx],
                "contender_child_ids": [child_ids[i] for i in mutation_claimants],
                "resolution": resolution,
            })

    owned_by_idx: list[list[str]] = [[] for _ in copied_children]
    for path, w_idx in owner_idx_by_path.items():
        owned_by_idx[w_idx].append(path)

    # Recompute each child's effective tier from its actual owned paths when non-empty
    actual_child_tiers: list[int] = []
    for idx in range(len(copied_children)):
        if owned_by_idx[idx]:
            actual_child_tiers.append(min(path_tiers[p] for p in owned_by_idx[idx]))
        else:
            actual_child_tiers.append(child_primary_tiers[idx])

    # Build candidate read_only_sibling_paths and dependency candidates
    # Directed graph `adj[producer_id]` = set of `consumer_id`s
    adj: dict[str, set[str]] = {cid: set() for cid in child_ids}
    read_only_by_idx: list[list[str]] = [[] for _ in copied_children]

    def _add_read_only(c_idx: int, sibling_path: str) -> None:
        if sibling_path not in owned_by_idx[c_idx] and sibling_path not in read_only_by_idx[c_idx]:
            read_only_by_idx[c_idx].append(sibling_path)

    # Collect candidate dependency edges with priority so higher-confidence / tier-aligned
    # Producer -> Consumer edges win if two siblings mutually mention each other.
    # Tuple: (priority, producer_idx, consumer_idx, reason_path_or_tag)
    candidate_edges: list[tuple[int, int, int, str]] = []

    # 1. Preserve any pre-existing explicit `depends_on` on input children
    id_to_idx = {cid: idx for idx, cid in enumerate(child_ids)}
    for c_idx, child in enumerate(copied_children):
        raw_deps = child.get("depends_on") or []
        if isinstance(raw_deps, str):
            raw_deps = [raw_deps]
        for dep in raw_deps:
            dep_id = str(dep).strip()
            if dep_id in id_to_idx and id_to_idx[dep_id] != c_idx:
                p_idx = id_to_idx[dep_id]
                candidate_edges.append((100, p_idx, c_idx, "explicit_depends_on"))

    # 2. Sibling path mentions in goal / done_when / non-blanket scope_hint
    for c_idx in range(len(copied_children)):
        c_tier = actual_child_tiers[c_idx]
        explicit_mentions = list(dict.fromkeys([
            *goal_paths_by_idx[c_idx],
            *done_paths_by_idx[c_idx],
        ]))
        for path in explicit_mentions:
            p_idx = owner_idx_by_path.get(path)
            if p_idx is None or p_idx == c_idx:
                continue
            p_tier = path_tiers[path]
            if p_tier < c_tier:
                # Strictly upstream producer tier -> highest priority
                candidate_edges.append((90, p_idx, c_idx, path))
            elif p_tier == c_tier:
                candidate_edges.append((70, p_idx, c_idx, path))
            else:
                # Higher tier mentioned by lower tier (e.g. index.html mentioning game.js):
                # lowest priority so Tier 0 -> Tier 1 wins instead!
                candidate_edges.append((20, p_idx, c_idx, path))

        for path in scope_paths_by_idx[c_idx]:
            if path in explicit_mentions:
                continue
            p_idx = owner_idx_by_path.get(path)
            if p_idx is None or p_idx == c_idx:
                continue
            p_tier = path_tiers[path]
            if path in blanket_scope_paths:
                if p_tier < c_tier:
                    candidate_edges.append((60, p_idx, c_idx, path))
            else:
                if p_tier <= c_tier:
                    candidate_edges.append((65, p_idx, c_idx, path))

    # 3. Structural Producer -> Consumer tier dependencies:
    #    - Tier 2 verification suites depend on Tier 0/1 implementation siblings.
    #    - Tier 1 JS browser modules depend on Tier 0 HTML/CSS shells.
    #    - Tier 1 Python CLI entrypoints depend on Tier 0 Python core modules.
    for c_idx in range(len(copied_children)):
        c_owned = owned_by_idx[c_idx]
        c_tier = actual_child_tiers[c_idx]

        if c_tier == TIER_VERIFICATION_SUITE:
            for p_idx in range(len(copied_children)):
                if p_idx == c_idx or not owned_by_idx[p_idx]:
                    continue
                if actual_child_tiers[p_idx] in {TIER_FOUNDATION_PRODUCER, TIER_CONSUMER_ENTRYPOINT}:
                    for p_path in owned_by_idx[p_idx]:
                        if not _is_test_path(p_path):
                            candidate_edges.append((85, p_idx, c_idx, p_path))

        if any(_path_extension(p) in _JS_EXTENSIONS and not _is_test_path(p) for p in c_owned):
            for p_idx in range(len(copied_children)):
                if p_idx == c_idx:
                    continue
                for p_path in owned_by_idx[p_idx]:
                    if _path_extension(p_path) in _HTML_EXTENSIONS or _path_extension(p_path) in _CSS_EXTENSIONS:
                        candidate_edges.append((88, p_idx, c_idx, p_path))

        if any(_is_py_cli_path(p) for p in c_owned):
            for p_idx in range(len(copied_children)):
                if p_idx == c_idx:
                    continue
                for p_path in owned_by_idx[p_idx]:
                    if (
                        _path_extension(p_path) in _PY_EXTENSIONS
                        and not _is_py_cli_path(p_path)
                        and not _is_test_path(p_path)
                    ):
                        candidate_edges.append((85, p_idx, c_idx, p_path))

    # Sort candidate edges deterministically: highest priority first, then lower producer tier,
    # then earlier producer index, then earlier consumer index.
    candidate_edges.sort(
        key=lambda item: (
            -item[0],
            actual_child_tiers[item[1]],
            -actual_child_tiers[item[2]],
            item[1],
            item[2],
        )
    )

    recorded_cycle_pairs: set[tuple[str, str]] = set()
    for priority, p_idx, c_idx, reason in candidate_edges:
        p_id = child_ids[p_idx]
        c_id = child_ids[c_idx]
        # Never let a low-priority reverse mention invert a strict Producer -> Consumer tier boundary
        if priority < 50 and actual_child_tiers[p_idx] > actual_child_tiers[c_idx]:
            continue
        if _would_create_cycle(adj, p_id, c_id):
            pair_key = (p_id, c_id)
            if pair_key not in recorded_cycle_pairs:
                recorded_cycle_pairs.add(pair_key)
                conflicts.append({
                    "kind": "cycle_prevented",
                    "dropped_dependency": p_id,
                    "child_id": c_id,
                    "reason": reason,
                })
            continue
        adj[p_id].add(c_id)
        if reason != "explicit_depends_on" and reason in ownership_map:
            _add_read_only(c_idx, reason)
        elif reason == "explicit_depends_on":
            for p_path in owned_by_idx[p_idx]:
                _add_read_only(c_idx, p_path)

    dependency_edges: list[tuple[str, str]] = []
    for c_idx, child in enumerate(copied_children):
        c_id = child_ids[c_idx]
        deps = [
            child_ids[p_idx]
            for p_idx in range(len(copied_children))
            if c_id in adj.get(child_ids[p_idx], ())
        ]
        owned = list(owned_by_idx[c_idx])
        read_only = list(read_only_by_idx[c_idx])

        child["owned_mutation_paths"] = owned
        child["read_only_sibling_paths"] = read_only
        child["depends_on"] = deps
        if owned:
            child["scope_hint"] = list(owned)
        elif isinstance(child.get("scope_hint"), list):
            child["scope_hint"] = [
                item for item in child["scope_hint"]
                if _normalize_posix_path(str(item)) not in ownership_map
            ]
        elif isinstance(child.get("scope_hint"), str) and child["scope_hint"].strip():
            extracted_sh = _extract_paths_from_value(child["scope_hint"], contract_ctx, clean_declared)
            if extracted_sh and all(p in ownership_map for p in extracted_sh):
                child["scope_hint"] = []

        for dep_id in deps:
            edge = (dep_id, c_id)
            if edge not in dependency_edges:
                dependency_edges.append(edge)

    return {
        "children": copied_children,
        "ownership_map": ownership_map,
        "dependency_edges": dependency_edges,
        "conflicts": conflicts,
    }


# ---------------------------------------------------------------------------
# 2. Static Zero-Model File Interface Certificate Extraction
# ---------------------------------------------------------------------------


def _extract_python_certificate(content: str) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    functions: list[dict[str, Any]] = []
    classes: list[dict[str, Any]] = []
    constants: list[str] = []
    cli_flags: list[str] = []
    imports_by_module: dict[str, list[str]] = {}
    module_order: list[str] = []

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return (
            False,
            {"functions": [], "classes": [], "constants": [], "cli_flags": []},
            {"python_imports": []},
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            arg_names: list[str] = [a.arg for a in getattr(node.args, "posonlyargs", [])]
            arg_names.extend(a.arg for a in node.args.args)
            if node.args.vararg is not None:
                arg_names.append(f"*{node.args.vararg.arg}")
            arg_names.extend(a.arg for a in node.args.kwonlyargs)
            if node.args.kwarg is not None:
                arg_names.append(f"**{node.args.kwarg.arg}")
            defaults_count = len(node.args.defaults) + sum(
                1 for d in node.args.kw_defaults if d is not None
            )
            functions.append({
                "name": node.name,
                "args": arg_names,
                "defaults_count": defaults_count,
            })
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            methods: list[str] = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("_"):
                    if item.name not in methods:
                        methods.append(item.name)
            classes.append({"name": node.name, "methods": methods})
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id == "__all__" and isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str) and elt.value:
                                if elt.value not in constants:
                                    constants.append(elt.value)
                    elif _UPPER_CONST_RE.match(target.id) and target.id not in constants:
                        constants.append(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            t_name = node.target.id
            if _UPPER_CONST_RE.match(t_name) and t_name not in constants:
                constants.append(t_name)

    def _record_import(mod_name: str, imported_names: list[str]) -> None:
        if not mod_name:
            return
        if mod_name not in imports_by_module:
            imports_by_module[mod_name] = []
            module_order.append(mod_name)
        bucket = imports_by_module[mod_name]
        for sym in imported_names:
            if sym and sym not in bucket:
                bucket.append(sym)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _record_import(alias.name, [])
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * (node.level or 0)
            mod_name = f"{prefix}{node.module or ''}"
            if mod_name:
                _record_import(mod_name, [alias.name for alias in node.names])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "add_argument":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        flag = arg.value.strip()
                        if flag.startswith("-") and flag not in cli_flags:
                            cli_flags.append(flag)

    python_imports = [
        {"module": mod, "names": imports_by_module[mod]}
        for mod in module_order
    ]
    return (
        True,
        {
            "functions": functions,
            "classes": classes,
            "constants": constants,
            "cli_flags": cli_flags,
        },
        {"python_imports": python_imports},
    )


def _is_local_relative_asset(ref: str) -> bool:
    val = str(ref or "").strip()
    if not val:
        return False
    lower = val.casefold()
    if lower.startswith(("http://", "https://", "//", "data:", "blob:", "javascript:", "mailto:", "#")):
        return False
    return True


class _HTMLCertificateParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.dom_ids: set[str] = set()
        self.canvas_ids: set[str] = set()
        self.button_ids: set[str] = set()
        self.data_attributes: set[str] = set()
        self.importmap_keys: set[str] = set()
        self.module_scripts: list[str] = []
        self.stylesheets: list[str] = []
        self.saw_open_body: bool = False
        self._active_script_kind: str | None = None
        self._script_chunks: list[str] = []

    def _note_tag_attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.casefold()
        attr_map: dict[str, str] = {}
        for k, v in attrs:
            if not k:
                continue
            k_lower = k.casefold()
            val = "" if v is None else v.strip()
            attr_map[k_lower] = val
            if k_lower.startswith("data-") and len(k_lower) > 5:
                self.data_attributes.add(k_lower)

        elem_id = attr_map.get("id", "").strip()
        if elem_id:
            self.dom_ids.add(elem_id)
            if tag_lower == "canvas":
                self.canvas_ids.add(elem_id)
            elif tag_lower == "button" or (
                tag_lower == "input"
                and attr_map.get("type", "").casefold() in {"button", "submit", "reset"}
            ):
                self.button_ids.add(elem_id)

        if tag_lower == "body":
            self.saw_open_body = True
        elif tag_lower == "link":
            rel_tokens = set(attr_map.get("rel", "").casefold().split())
            href = attr_map.get("href", "").strip()
            if "stylesheet" in rel_tokens and _is_local_relative_asset(href):
                clean_href = re.split(r"[?#]", href, maxsplit=1)[0].strip()
                if clean_href and clean_href not in self.stylesheets:
                    self.stylesheets.append(clean_href)
        elif tag_lower == "script":
            src = attr_map.get("src", "").strip()
            script_type = attr_map.get("type", "").strip().casefold()
            if src and _is_local_relative_asset(src):
                clean_src = re.split(r"[?#]", src, maxsplit=1)[0].strip()
                if clean_src and clean_src not in self.module_scripts:
                    self.module_scripts.append(clean_src)
            if script_type == "importmap":
                self._active_script_kind = "importmap"
                self._script_chunks = []
            elif script_type == "module" and not src:
                self._active_script_kind = "inline_module"
                self._script_chunks = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._note_tag_attrs(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._note_tag_attrs(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self._active_script_kind is not None:
            self._script_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._active_script_kind is not None:
            raw_script = "".join(self._script_chunks).strip()
            kind = self._active_script_kind
            self._active_script_kind = None
            self._script_chunks = []
            if kind == "importmap" and raw_script:
                try:
                    parsed = json.loads(raw_script)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict) and isinstance(parsed.get("imports"), dict):
                    for key in parsed["imports"]:
                        if isinstance(key, str) and key.strip():
                            self.importmap_keys.add(key.strip())
            elif kind == "inline_module" and raw_script:
                _, _, js_assumes = _extract_js_certificate(raw_script)
                for rel_imp in js_assumes.get("relative_imports", []):
                    src = rel_imp.get("source", "")
                    if src and src not in self.module_scripts:
                        self.module_scripts.append(src)


def _extract_html_certificate(content: str) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    parser = _HTMLCertificateParser()
    try:
        parser.feed(content)
        parser.close()
        parse_valid = True
    except Exception:
        parse_valid = False

    has_closing_body = bool(re.search(r"</body\s*>", content, re.IGNORECASE))
    has_closing_html = bool(re.search(r"</html\s*>", content, re.IGNORECASE))
    has_malformed_close = bool(re.search(r"</(?:html|body)\\[^>]*>", content, re.IGNORECASE))
    has_body_tag = bool(
        parser.saw_open_body
        and has_closing_body
        and has_closing_html
        and not has_malformed_close
    )

    guarantees = {
        "dom_ids": sorted(parser.dom_ids),
        "canvas_ids": sorted(parser.canvas_ids),
        "button_ids": sorted(parser.button_ids),
        "data_attributes": sorted(parser.data_attributes),
        "importmap_keys": sorted(parser.importmap_keys),
        "has_body_tag": has_body_tag,
    }
    assumes = {
        "module_scripts": parser.module_scripts,
        "stylesheets": parser.stylesheets,
    }
    return parse_valid, guarantees, assumes


def _strip_js_comments_preserving_strings(source: str) -> str:
    """Replace `//...` and `/*...*/` comments with spaces while keeping string/template literals intact."""
    out: list[str] = []
    n = len(source)
    i = 0
    in_template = False
    template_brace_stack: list[int] = []

    while i < n:
        if in_template:
            c = source[i]
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(source[i + 1])
                i += 2
                continue
            if c == "`":
                in_template = False
                i += 1
                continue
            if c == "$" and i + 1 < n and source[i + 1] == "{":
                out.append("{")
                template_brace_stack.append(0)
                in_template = False
                i += 2
                continue
            i += 1
            continue

        ch = source[i]
        if ch in {"'", '"'}:
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                c = source[i]
                out.append(c)
                if c == "\\" and i + 1 < n:
                    out.append(source[i + 1])
                    i += 2
                    continue
                i += 1
                if c == quote or c in "\r\n":
                    break
            continue
        if ch == "`":
            out.append(ch)
            in_template = True
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            nxt = source[i + 1]
            if nxt == "/":
                out.append("  ")
                i += 2
                while i < n and source[i] not in "\r\n":
                    out.append(" ")
                    i += 1
                continue
            if nxt == "*":
                out.append("  ")
                i += 2
                while i < n:
                    if source[i] == "*" and i + 1 < n and source[i + 1] == "/":
                        out.append("  ")
                        i += 2
                        break
                    out.append("\n" if source[i] == "\n" else " ")
                    i += 1
                continue
        if template_brace_stack:
            if ch == "{":
                template_brace_stack[-1] += 1
            elif ch == "}":
                if template_brace_stack[-1] == 0:
                    template_brace_stack.pop()
                    out.append(ch)
                    in_template = True
                    i += 1
                    continue
                template_brace_stack[-1] -= 1
        out.append(ch)
        i += 1
    return "".join(out)


_JS_STATIC_IMPORT_RE = re.compile(
    r"\bimport\s*(?P<spec>[A-Za-z0-9_$*,\s{}]+?)\s*\bfrom\s*(?P<q>['\"])(?P<src>[^'\"\r\n]+)(?P=q)"
)
_JS_SIDE_EFFECT_IMPORT_RE = re.compile(
    r"\bimport\s*(?P<q>['\"])(?P<src>[^'\"\r\n]+)(?P=q)"
)
_JS_DYNAMIC_IMPORT_RE = re.compile(
    r"\bimport\s*\(\s*(?P<q>['\"])(?P<src>[^'\"\r\n]+)(?P=q)\s*\)"
)
_JS_REEXPORT_FROM_RE = re.compile(
    r"\bexport\s*(?P<spec>\*(?:\s+as\s+[A-Za-z_$][A-Za-z0-9_$]*)?|\{[A-Za-z0-9_$*,\s]*\})\s*\bfrom\s*(?P<q>['\"])(?P<src>[^'\"\r\n]+)(?P=q)"
)
_JS_CJS_DESTRUCTURED_REQUIRE_RE = re.compile(
    r"\b(?:const|let|var)\s*\{(?P<names>[A-Za-z0-9_$:,\s]+)\}\s*=\s*require\s*\(\s*(?P<q>['\"])(?P<src>[^'\"\r\n]+)(?P=q)\s*\)"
)
_JS_CJS_REQUIRE_RE = re.compile(
    r"\brequire\s*\(\s*(?P<q>['\"])(?P<src>[^'\"\r\n]+)(?P=q)\s*\)"
)


def _parse_js_import_specifiers(spec_text: str) -> list[str]:
    names: list[str] = []
    spec = spec_text.strip()
    if not spec:
        return names

    # Extract named `{ ... }` block if present
    brace_match = re.search(r"\{([^}]*)\}", spec)
    outside = spec
    if brace_match:
        outside = (spec[:brace_match.start()] + " " + spec[brace_match.end():]).strip()

    # Check default and namespace imports in `outside`
    for part in [p.strip() for p in outside.split(",") if p.strip()]:
        if part.startswith("*"):
            if "*" not in names:
                names.append("*")
        elif re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", part):
            if "default" not in names:
                names.append("default")

    if brace_match:
        inner = brace_match.group(1)
        for token in inner.split(","):
            tok = token.strip()
            if not tok:
                continue
            # `Foo as LocalFoo` -> imported producer symbol is `Foo`
            parts = re.split(r"\s+as\s+", tok)
            imported_name = parts[0].strip()
            if imported_name and imported_name not in names:
                names.append(imported_name)

    return names


def _extract_balanced_brace_body(text: str, open_brace_idx: int) -> str:
    if open_brace_idx < 0 or open_brace_idx >= len(text) or text[open_brace_idx] != "{":
        return ""
    depth = 0
    i = open_brace_idx
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in {"'", '"', "`"}:
            q = ch
            i += 1
            while i < n:
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if text[i] == q:
                    i += 1
                    break
                i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_idx + 1:i]
        i += 1
    return text[open_brace_idx + 1:]


def _extract_top_level_object_keys(brace_body: str) -> list[str]:
    """Extract property/method names at brace/paren/bracket depth 0 inside an object literal."""
    keys: list[str] = []
    # Blank nested `{...}`, `(...)`, `[...]` and string literals to inspect top-level entries cleanly
    chars: list[str] = []
    depth_brace = 0
    depth_paren = 0
    depth_bracket = 0
    i = 0
    n = len(brace_body)
    while i < n:
        ch = brace_body[i]
        if ch in {"'", '"', "`"}:
            q = ch
            if depth_brace == 0 and depth_paren == 0 and depth_bracket == 0:
                chars.append(" ")
            i += 1
            while i < n:
                if brace_body[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if brace_body[i] == q:
                    i += 1
                    break
                i += 1
            continue
        if ch == "{":
            if depth_brace == 0 and depth_paren == 0 and depth_bracket == 0:
                chars.append("{}")
            depth_brace += 1
        elif ch == "}":
            depth_brace = max(0, depth_brace - 1)
        elif ch == "(":
            if depth_brace == 0 and depth_paren == 0 and depth_bracket == 0:
                chars.append("()")
            depth_paren += 1
        elif ch == ")":
            depth_paren = max(0, depth_paren - 1)
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]":
            depth_bracket = max(0, depth_bracket - 1)
        elif depth_brace == 0 and depth_paren == 0 and depth_bracket == 0:
            chars.append(ch)
        i += 1

    top_text = "".join(chars)
    for entry in top_text.split(","):
        seg = entry.strip()
        if not seg or seg.startswith("..."):
            continue
        # Matches `getState() {}`, `async step() {}`, `move: () =>`, or shorthand `forceWin`
        m = re.match(r"^(?:async\s+)?(?:\*\s*)?([A-Za-z_$][A-Za-z0-9_$]*)\s*(?::|\(\)|$)", seg)
        if m:
            name = m.group(1)
            if name not in {"get", "set", "async"} and name not in keys:
                keys.append(name)
    return keys


def _extract_js_certificate(content: str) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    code = _strip_js_comments_preserving_strings(content)

    exports: list[str] = []

    def _add_export(name: str) -> None:
        if name and name not in exports:
            exports.append(name)

    # `export default ...`
    if re.search(r"\bexport\s+default\b", code):
        _add_export("default")

    # `export [async] function[*] Name` / `export class Name`
    for m in re.finditer(
        r"\bexport\s+(?!default\b)(?:async\s+)?(?:function(?:\s*\*)?|class)\s+([A-Za-z_$][A-Za-z0-9_$]*)",
        code,
    ):
        _add_export(m.group(1))

    # `export const/let/var ...`
    for m in re.finditer(r"\bexport\s+(?:const|let|var)\s+([^;\r\n]+)", code):
        decl = m.group(1).strip()
        destruct = re.match(r"^\{([^}]+)\}", decl)
        if destruct:
            for item in destruct.group(1).split(","):
                tok = item.strip().split("=", 1)[0].strip()
                if not tok:
                    continue
                parts = [p.strip() for p in tok.split(":")]
                exported = parts[-1]
                if re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", exported):
                    _add_export(exported)
        else:
            # Split top-level declarators (`export const A = 1, B = 2`)
            depth = 0
            chunk: list[str] = []
            declarators: list[str] = []
            for ch in decl:
                if ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    depth = max(0, depth - 1)
                if ch == "," and depth == 0:
                    declarators.append("".join(chunk))
                    chunk = []
                else:
                    chunk.append(ch)
            if chunk:
                declarators.append("".join(chunk))
            for d_item in declarators:
                ident_match = re.match(r"^\s*([A-Za-z_$][A-Za-z0-9_$]*)\b", d_item)
                if ident_match:
                    _add_export(ident_match.group(1))

    # `export { a, b as c }` (with or without `from '...'`)
    for m in re.finditer(r"\bexport\s*\{([^}]*)\}", code):
        for item in m.group(1).split(","):
            tok = item.strip()
            if not tok:
                continue
            parts = re.split(r"\s+as\s+", tok)
            public_name = parts[-1].strip()
            if public_name:
                _add_export(public_name)

    # `export * as ns from '...'`
    for m in re.finditer(r"\bexport\s*\*\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)\s+from\b", code):
        _add_export(m.group(1))

    # CommonJS `module.exports = { ... }` / `exports.foo = ...`
    for m in re.finditer(r"\b(?:module\.)?exports\.([A-Za-z_$][A-Za-z0-9_$]*)\s*=", code):
        _add_export(m.group(1))
    for m in re.finditer(r"\bmodule\.exports\s*=\s*\{", code):
        body = _extract_balanced_brace_body(code, m.end() - 1)
        for key in _extract_top_level_object_keys(body):
            _add_export(key)

    # Globals: `window.AGENT_GAME` / `globalThis.AGENT_GAME` methods
    globals_list: list[str] = []

    def _add_global(name: str) -> None:
        if name and name not in globals_list:
            globals_list.append(name)

    for m in re.finditer(r"\b(?:window|globalThis)\.AGENT_GAME\s*=\s*\{", code):
        body = _extract_balanced_brace_body(code, m.end() - 1)
        for key in _extract_top_level_object_keys(body):
            _add_global(key)

    for m in re.finditer(r"\bObject\.assign\s*\(\s*(?:window|globalThis)\.AGENT_GAME\s*,\s*\{", code):
        body = _extract_balanced_brace_body(code, m.end() - 1)
        for key in _extract_top_level_object_keys(body):
            _add_global(key)

    for m in re.finditer(
        r"\b(?:window|globalThis)\.AGENT_GAME\s*=\s*([A-Za-z_$][A-Za-z0-9_$]*)\b",
        code,
    ):
        ident = m.group(1)
        if ident not in {"window", "globalThis", "undefined", "null"}:
            obj_match = re.search(
                rf"\b(?:const|let|var)\s+{re.escape(ident)}\s*=\s*\{{",
                code,
            )
            if obj_match:
                body = _extract_balanced_brace_body(code, obj_match.end() - 1)
                for key in _extract_top_level_object_keys(body):
                    _add_global(key)

    for m in re.finditer(r"\b(?:window|globalThis)\.AGENT_GAME\.([A-Za-z_$][A-Za-z0-9_$]*)\s*=", code):
        _add_global(m.group(1))

    for m in re.finditer(
        r"\b(?:window|globalThis)\.AGENT_GAME\[\s*(['\"])([A-Za-z_$][A-Za-z0-9_$]*)\1\s*\]\s*=",
        code,
    ):
        _add_global(m.group(2))

    # Dynamic created DOM IDs: `.id = 'foo'`, `.setAttribute('id', 'foo')`, or `id="foo"` in strings/templates
    created_dom_ids: set[str] = set()
    for m in re.finditer(r"\.\s*id\s*=\s*(['\"`])([^'\"`${}\s]+)\1", code):
        created_dom_ids.add(m.group(2))
    for m in re.finditer(
        r"\.\s*setAttribute\s*\(\s*(['\"])id\1\s*,\s*(['\"`])([^'\"`${}\s]+)\2\s*\)",
        code,
    ):
        created_dom_ids.add(m.group(3))
    for str_match in re.finditer(r"(['\"`])((?:\\.|(?!\1)[\s\S])*)\1", code):
        literal_body = str_match.group(2)
        if "<" in literal_body and "id=" in literal_body:
            for id_m in re.finditer(r"""\bid\s*=\s*(?:\\?['"])([A-Za-z_][A-Za-z0-9_:-]*|[A-Za-z0-9_-]+)""", literal_body):
                val = id_m.group(1).strip()
                if val and "${" not in val:
                    created_dom_ids.add(val)

    # Imports: `relative_imports` and `package_imports`
    rel_map: dict[str, list[str]] = {}
    rel_order: list[str] = []
    pkg_map: dict[str, list[str]] = {}
    pkg_order: list[str] = []

    def _record_js_import(raw_source: str, imported_names: list[str]) -> None:
        src = raw_source.strip()
        if not src:
            return
        lower = src.casefold()
        if lower.startswith(("http://", "https://", "//", "data:", "blob:")):
            return
        if src.startswith(("./", "../", "/")):
            if src not in rel_map:
                rel_map[src] = []
                rel_order.append(src)
            bucket = rel_map[src]
        else:
            if src not in pkg_map:
                pkg_map[src] = []
                pkg_order.append(src)
            bucket = pkg_map[src]
        for sym in imported_names:
            if sym and sym not in bucket:
                bucket.append(sym)

    matched_spans: list[tuple[int, int]] = []
    for m in _JS_STATIC_IMPORT_RE.finditer(code):
        matched_spans.append((m.start(), m.end()))
        _record_js_import(m.group("src"), _parse_js_import_specifiers(m.group("spec")))

    for m in _JS_REEXPORT_FROM_RE.finditer(code):
        matched_spans.append((m.start(), m.end()))
        spec_txt = m.group("spec").strip()
        if spec_txt.startswith("*"):
            _record_js_import(m.group("src"), ["*"])
        else:
            _record_js_import(m.group("src"), _parse_js_import_specifiers(spec_txt))

    for m in _JS_SIDE_EFFECT_IMPORT_RE.finditer(code):
        if any(s <= m.start() and m.end() <= e for s, e in matched_spans):
            continue
        _record_js_import(m.group("src"), [])

    for m in _JS_DYNAMIC_IMPORT_RE.finditer(code):
        _record_js_import(m.group("src"), [])

    cjs_spans: list[tuple[int, int]] = []
    for m in _JS_CJS_DESTRUCTURED_REQUIRE_RE.finditer(code):
        cjs_spans.append((m.start(), m.end()))
        req_names: list[str] = []
        for item in m.group("names").split(","):
            tok = item.strip().split("=", 1)[0].strip()
            if not tok:
                continue
            orig = tok.split(":", 1)[0].strip()
            if re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", orig) and orig not in req_names:
                req_names.append(orig)
        _record_js_import(m.group("src"), req_names)

    for m in _JS_CJS_REQUIRE_RE.finditer(code):
        if any(s <= m.start() and m.end() <= e for s, e in cjs_spans):
            continue
        _record_js_import(m.group("src"), [])

    # Queried DOM IDs: `document.getElementById('foo')` and `document.querySelector('#foo')`
    queried_dom_ids: set[str] = set()
    for m in re.finditer(
        r"\bdocument\s*\.\s*getElementById\s*\(\s*(['\"`])([^'\"`${}\r\n]+)\1\s*\)",
        code,
    ):
        dom_id = m.group(2).strip()
        if dom_id:
            queried_dom_ids.add(dom_id)

    for m in re.finditer(
        r"\b(?:document|[A-Za-z_$][A-Za-z0-9_$]*)\s*\.\s*querySelector(?:All)?\s*\(\s*(['\"`])([^'\"`${}\r\n]+)\1\s*\)",
        code,
    ):
        selector = re.sub(r"\[[^\]]*\]", " ", m.group(2))
        for sel_id in re.finditer(r"#([A-Za-z_][A-Za-z0-9_-]*|-[A-Za-z_][A-Za-z0-9_-]*)", selector):
            queried_dom_ids.add(sel_id.group(1))

    guarantees = {
        "exports": exports,
        "globals": globals_list,
        "created_dom_ids": sorted(created_dom_ids),
    }
    assumes = {
        "relative_imports": [{"source": s, "names": rel_map[s]} for s in rel_order],
        "package_imports": [{"source": s, "names": pkg_map[s]} for s in pkg_order],
        "queried_dom_ids": sorted(queried_dom_ids),
    }
    return True, guarantees, assumes


def _extract_css_certificate(content: str) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    # Strip block comments `/* ... */`
    stripped = re.sub(r"/\*[\s\S]*?\*/", " ", content)
    css_ids: set[str] = set()
    css_classes: set[str] = set()

    # Walk rule headers (text segments preceding `{`), skipping `@keyframes` / `@font-face`
    n = len(stripped)
    i = 0
    segment_start = 0
    in_keyframes_depth: int | None = None
    depth = 0

    while i < n:
        ch = stripped[i]
        if ch in {"'", '"'}:
            q = ch
            i += 1
            while i < n:
                if stripped[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if stripped[i] == q:
                    i += 1
                    break
                i += 1
            continue
        if ch == "{":
            prelude = stripped[segment_start:i].strip()
            prelude_lower = prelude.casefold()
            if in_keyframes_depth is None:
                if prelude_lower.startswith(("@keyframes", "@-webkit-keyframes", "@-moz-keyframes")):
                    in_keyframes_depth = depth + 1
                elif not prelude_lower.startswith("@"):
                    clean_sel = re.sub(r"(['\"])(?:\\.|(?!\1).)*\1", " ", prelude)
                    clean_sel = re.sub(r"\[[^\]]*\]", " ", clean_sel)
                    for m_id in re.finditer(
                        r"#([A-Za-z_][A-Za-z0-9_-]*|-[A-Za-z_][A-Za-z0-9_-]*)",
                        clean_sel,
                    ):
                        css_ids.add(m_id.group(1))
                    for m_cls in re.finditer(
                        r"\.([A-Za-z_][A-Za-z0-9_-]*|-[A-Za-z_][A-Za-z0-9_-]*)",
                        clean_sel,
                    ):
                        css_classes.add(m_cls.group(1))
            depth += 1
            segment_start = i + 1
        elif ch == "}":
            if in_keyframes_depth is not None and depth == in_keyframes_depth:
                in_keyframes_depth = None
            depth = max(0, depth - 1)
            segment_start = i + 1
        elif ch == ";":
            segment_start = i + 1
        i += 1

    return (
        True,
        {
            "css_ids": sorted(css_ids),
            "css_classes": sorted(css_classes),
        },
        {},
    )


def extract_file_certificate(path: str, content: str) -> dict:
    """Extract a deterministic interface certificate (`guarantees` + `assumes`) for one file."""
    norm_path = _normalize_posix_path(path) or str(path or "").strip().replace("\\", "/")
    text = content if isinstance(content, str) else str(content or "")
    ext = _path_extension(norm_path)

    if ext in _PY_EXTENSIONS:
        language = "python"
        parse_valid, guarantees, assumes = _extract_python_certificate(text)
    elif ext in _HTML_EXTENSIONS:
        language = "html"
        parse_valid, guarantees, assumes = _extract_html_certificate(text)
    elif ext in _JS_EXTENSIONS:
        language = "javascript"
        parse_valid, guarantees, assumes = _extract_js_certificate(text)
    elif ext in _CSS_EXTENSIONS:
        language = "css"
        parse_valid, guarantees, assumes = _extract_css_certificate(text)
    else:
        language = "unknown"
        parse_valid = True
        guarantees = {}
        assumes = {}

    content_sha256 = _sha256_text(text)
    cert_payload = {
        "path": norm_path,
        "language": language,
        "parse_valid": parse_valid,
        "guarantees": guarantees,
        "assumes": assumes,
    }
    certificate_sha256 = _sha256_text(_canonical_json(cert_payload))
    return {
        "path": norm_path,
        "language": language,
        "parse_valid": parse_valid,
        "guarantees": guarantees,
        "assumes": assumes,
        "content_sha256": content_sha256,
        "certificate_sha256": certificate_sha256,
    }


# ---------------------------------------------------------------------------
# 3. Compositional Assume-Guarantee Verification
# ---------------------------------------------------------------------------


def _resolve_relative_path(importer_path: str, target_ref: str) -> str:
    clean_ref = re.split(r"[?#]", str(target_ref or "").strip(), maxsplit=1)[0].strip()
    if not clean_ref:
        return ""
    if clean_ref.startswith("/"):
        return _normalize_posix_path(clean_ref.lstrip("/"))
    base_dir = posixpath.dirname(importer_path)
    joined = posixpath.join(base_dir, clean_ref) if base_dir else clean_ref
    return _normalize_posix_path(joined)


def _importmap_matches_specifier(specifier: str, importmap_keys: set[str]) -> bool:
    if specifier in importmap_keys:
        return True
    return any(key.endswith("/") and specifier.startswith(key) for key in importmap_keys)


def _reachable_js_modules_from_html(
    html_path: str,
    html_cert: dict[str, Any],
    norm_certs: dict[str, dict[str, Any]],
) -> set[str]:
    visited: set[str] = set()
    queue: list[str] = []
    for script_src in html_cert.get("assumes", {}).get("module_scripts", []):
        resolved = _resolve_relative_path(html_path, script_src)
        if resolved:
            queue.append(resolved)

    while queue:
        curr = queue.pop(0)
        if curr in visited:
            continue
        visited.add(curr)
        js_cert = norm_certs.get(curr)
        if not isinstance(js_cert, dict):
            continue
        for rel_imp in js_cert.get("assumes", {}).get("relative_imports", []):
            nxt = _resolve_relative_path(curr, rel_imp.get("source", ""))
            if nxt and nxt not in visited:
                queue.append(nxt)
    return visited


def _resolve_python_sibling_cert(
    importer_path: str,
    module_spec: str,
    norm_certs: dict[str, dict[str, Any]],
) -> tuple[str | None, dict[str, Any] | None, bool]:
    """Resolve `module_spec` to a sibling Python certificate if present.

    Returns ``(sibling_path, sibling_cert, is_dot_only_package_import)``.
    """
    if not module_spec:
        return None, None, False

    leading_dots = len(module_spec) - len(module_spec.lstrip("."))
    remainder = module_spec[leading_dots:]
    imp_dir = posixpath.dirname(importer_path)

    if leading_dots > 0:
        base_dir = imp_dir
        for _ in range(leading_dots - 1):
            base_dir = posixpath.dirname(base_dir)
        if not remainder:
            # `from . import metrics` -> module itself is package dir (`__init__.py` if present)
            init_cand = _normalize_posix_path(posixpath.join(base_dir, "__init__.py"))
            return (init_cand, norm_certs.get(init_cand), True)
        rel_mod = remainder.replace(".", "/")
        candidates = [
            _normalize_posix_path(posixpath.join(base_dir, f"{rel_mod}.py")),
            _normalize_posix_path(posixpath.join(base_dir, rel_mod, "__init__.py")),
        ]
    else:
        rel_mod = remainder.replace(".", "/")
        candidates = []
        if imp_dir:
            candidates.append(_normalize_posix_path(posixpath.join(imp_dir, f"{rel_mod}.py")))
            candidates.append(_normalize_posix_path(posixpath.join(imp_dir, rel_mod, "__init__.py")))
        candidates.append(_normalize_posix_path(f"{rel_mod}.py"))
        candidates.append(_normalize_posix_path(posixpath.join(rel_mod, "__init__.py")))

    for cand in candidates:
        if cand and cand in norm_certs and cand != importer_path:
            return cand, norm_certs[cand], False
    return None, None, False


def verify_compositional_certificates(
    certificates: dict[str, dict],
    workspace_files: set[str] | None = None,
    *,
    check_html_assets: bool = True,
) -> dict:
    """Verify cross-file interface assumptions against sibling guarantees."""
    norm_certs: dict[str, dict[str, Any]] = {}
    for raw_key, cert in (certificates or {}).items():
        if not isinstance(cert, dict):
            continue
        norm_key = _normalize_posix_path(str(raw_key)) or _normalize_posix_path(str(cert.get("path") or ""))
        if norm_key:
            norm_certs[norm_key] = cert

    known_files: set[str] = set(norm_certs.keys())
    for wf in workspace_files or set():
        norm_wf = _normalize_posix_path(str(wf))
        if norm_wf:
            known_files.add(norm_wf)

    html_certs: dict[str, dict[str, Any]] = {
        p: c for p, c in norm_certs.items()
        if c.get("language") == "html" or _path_extension(p) in _HTML_EXTENSIONS
    }
    html_loaded_js: dict[str, set[str]] = {
        h_path: _reachable_js_modules_from_html(h_path, h_cert, norm_certs)
        for h_path, h_cert in html_certs.items()
    }

    violations: list[dict[str, Any]] = []
    seen_violation_keys: set[tuple[str, str, str | None, str]] = set()
    repair_counterexamples: list[str] = []

    def _emit(
        code: str,
        consumer_path: str,
        producer_path: str | None,
        symbol: str,
        message: str,
    ) -> None:
        v_key = (code, consumer_path, producer_path, symbol)
        if v_key in seen_violation_keys:
            return
        seen_violation_keys.add(v_key)
        one_line = " ".join(message.splitlines()).strip()
        violations.append({
            "code": code,
            "consumer_path": consumer_path,
            "producer_path": producer_path,
            "symbol": symbol,
            "message": one_line,
        })
        if one_line not in repair_counterexamples:
            repair_counterexamples.append(one_line)

    for path in sorted(norm_certs.keys()):
        cert = norm_certs[path]
        lang = cert.get("language") or ""
        ext = _path_extension(path)
        assumes = cert.get("assumes") if isinstance(cert.get("assumes"), dict) else {}
        guarantees = cert.get("guarantees") if isinstance(cert.get("guarantees"), dict) else {}

        # 1, 2, 3: JavaScript cross-file checks
        if lang == "javascript" or ext in _JS_EXTENSIONS:
            # 1. JS relative_imports
            for rel_imp in assumes.get("relative_imports", []) or []:
                raw_src = str(rel_imp.get("source") or "")
                target_path = _resolve_relative_path(path, raw_src)
                if not target_path or target_path not in known_files:
                    _emit(
                        MISSING_RELATIVE_MODULE,
                        path,
                        target_path or raw_src,
                        raw_src,
                        f"{path} imports '{raw_src}' (resolved to '{target_path or raw_src}'), "
                        f"but no such module exists in workspace files: {sorted(known_files)}",
                    )
                    continue

                target_cert = norm_certs.get(target_path)
                if isinstance(target_cert, dict):
                    target_exports = set(
                        (target_cert.get("guarantees") or {}).get("exports", []) or []
                    )
                    for name in rel_imp.get("names", []) or []:
                        if name == "*":
                            continue
                        if name not in target_exports:
                            _emit(
                                MISSING_JS_EXPORT,
                                path,
                                target_path,
                                name,
                                f"{path} imports '{name}' from '{target_path}', "
                                f"but {target_path} only exports: {sorted(target_exports)}",
                            )

            # Determine HTML certificates loading this JS module
            loading_htmls = [
                h_path for h_path in sorted(html_certs.keys())
                if path in html_loaded_js.get(h_path, set())
            ]

            # 2. JS package_imports
            for pkg_imp in assumes.get("package_imports", []) or []:
                src = str(pkg_imp.get("source") or "")
                names = list(pkg_imp.get("names", []) or [])
                flagged_core_addon = False

                if src.startswith(("three/addons/", "three/examples/jsm/")):
                    misimported = [n for n in names if n in _THREE_CORE_NOT_ADDONS]
                    if not misimported:
                        stem = posixpath.splitext(posixpath.basename(src))[0]
                        if stem in _THREE_CORE_NOT_ADDONS and ("default" in names or not names):
                            misimported = [stem]
                    for core_sym in misimported:
                        flagged_core_addon = True
                        _emit(
                            THREE_CORE_MISIMPORTED_FROM_ADDONS,
                            path,
                            "three",
                            core_sym,
                            f"{path} imports Three.js core symbol '{core_sym}' from '{src}', "
                            f"but '{core_sym}' is in core 'three' (use: import {{ {core_sym} }} from 'three')",
                        )

                for h_path in loading_htmls:
                    h_cert = html_certs[h_path]
                    imap_keys = set(
                        (h_cert.get("guarantees") or {}).get("importmap_keys", []) or []
                    )
                    effective_spec = "three" if flagged_core_addon else src
                    if not _importmap_matches_specifier(effective_spec, imap_keys):
                        _emit(
                            MISSING_IMPORTMAP_SPECIFIER,
                            path,
                            h_path,
                            effective_spec,
                            f"{path} imports bare specifier '{effective_spec}', but {h_path} "
                            f"<script type=\"importmap\"> only maps: {sorted(imap_keys)}",
                        )

            # 3. JS queried_dom_ids against unique HTML entrypoint
            entry_html_path: str | None = None
            if len(loading_htmls) == 1:
                entry_html_path = loading_htmls[0]
            elif len(html_certs) == 1:
                only_html = next(iter(html_certs.keys()))
                if path in html_loaded_js.get(only_html, set()) or posixpath.basename(only_html).casefold() == "index.html":
                    entry_html_path = only_html

            if entry_html_path is not None:
                entry_html_cert = html_certs[entry_html_path]
                html_dom_ids = set(
                    (entry_html_cert.get("guarantees") or {}).get("dom_ids", []) or []
                )
                dynamic_dom_ids = set(guarantees.get("created_dom_ids", []) or [])
                # Also include dynamic IDs created by relative helper modules in the same graph
                for sibling_js in html_loaded_js.get(entry_html_path, set()):
                    sib_cert = norm_certs.get(sibling_js)
                    if isinstance(sib_cert, dict):
                        dynamic_dom_ids.update(
                            (sib_cert.get("guarantees") or {}).get("created_dom_ids", []) or []
                        )

                for dom_id in assumes.get("queried_dom_ids", []) or []:
                    if dom_id in dynamic_dom_ids:
                        continue
                    if dom_id not in html_dom_ids:
                        _emit(
                            MISSING_DOM_ID,
                            path,
                            entry_html_path,
                            dom_id,
                            f"{path} assumes DOM '#{dom_id}', but {entry_html_path} "
                            f"only defines IDs: {sorted(html_dom_ids)}",
                        )

        # 4. Python cross-file imports
        elif lang == "python" or ext in _PY_EXTENSIONS:
            for py_imp in assumes.get("python_imports", []) or []:
                mod_spec = str(py_imp.get("module") or "")
                names = list(py_imp.get("names", []) or [])
                if not names:
                    continue
                sib_path, sib_cert, is_dot_only = _resolve_python_sibling_cert(
                    path,
                    mod_spec,
                    norm_certs,
                )
                if is_dot_only:
                    # `from . import submodule` -> check if submodule file exists in norm_certs/known_files
                    imp_dir = posixpath.dirname(path)
                    if sib_cert is not None:
                        sib_guar = sib_cert.get("guarantees") or {}
                        sib_syms = (
                            {f["name"] for f in sib_guar.get("functions", []) if isinstance(f, dict) and "name" in f}
                            | {c["name"] for c in sib_guar.get("classes", []) if isinstance(c, dict) and "name" in c}
                            | set(sib_guar.get("constants", []) or [])
                        )
                    else:
                        sib_syms = set()
                    for name in names:
                        if name == "*":
                            continue
                        submod_py = _normalize_posix_path(posixpath.join(imp_dir, f"{name}.py"))
                        submod_init = _normalize_posix_path(posixpath.join(imp_dir, name, "__init__.py"))
                        if submod_py in known_files or submod_init in known_files or name in sib_syms:
                            continue
                        if sib_cert is not None and sib_path is not None:
                            _emit(
                                MISSING_PYTHON_SYMBOL,
                                path,
                                sib_path,
                                name,
                                f"{path} imports '{name}' from '{sib_path}', "
                                f"but {sib_path} only defines: {sorted(sib_syms)}",
                            )
                    continue

                if sib_cert is None or sib_path is None:
                    continue

                sib_guar = sib_cert.get("guarantees") or {}
                sibling_symbols: set[str] = set()
                for fn in sib_guar.get("functions", []) or []:
                    if isinstance(fn, dict) and fn.get("name"):
                        sibling_symbols.add(str(fn["name"]))
                for cls in sib_guar.get("classes", []) or []:
                    if isinstance(cls, dict) and cls.get("name"):
                        sibling_symbols.add(str(cls["name"]))
                for const in sib_guar.get("constants", []) or []:
                    if isinstance(const, str) and const:
                        sibling_symbols.add(const)
                if posixpath.basename(sib_path) == "__init__.py":
                    for re_imp in (sib_cert.get("assumes") or {}).get("python_imports", []) or []:
                        for re_name in re_imp.get("names", []) or []:
                            if re_name and re_name != "*":
                                sibling_symbols.add(re_name)

                for name in names:
                    if name == "*":
                        continue
                    if name not in sibling_symbols:
                        _emit(
                            MISSING_PYTHON_SYMBOL,
                            path,
                            sib_path,
                            name,
                            f"{path} imports '{name}' from '{sib_path}', "
                            f"but {sib_path} only defines: {sorted(sibling_symbols)}",
                        )

        # 5. HTML local relative module_scripts / stylesheets
        elif (lang == "html" or ext in _HTML_EXTENSIONS) and check_html_assets:
            for script_src in assumes.get("module_scripts", []) or []:
                resolved_js = _resolve_relative_path(path, script_src)
                if not resolved_js or resolved_js not in known_files:
                    _emit(
                        MISSING_HTML_SCRIPT,
                        path,
                        resolved_js or script_src,
                        script_src,
                        f"{path} loads script '{script_src}' (resolved to '{resolved_js or script_src}'), "
                        f"which is missing from workspace files: {sorted(known_files)}",
                    )
            for href in assumes.get("stylesheets", []) or []:
                resolved_css = _resolve_relative_path(path, href)
                if not resolved_css or resolved_css not in known_files:
                    _emit(
                        MISSING_HTML_STYLESHEET,
                        path,
                        resolved_css or href,
                        href,
                        f"{path} links stylesheet '{href}' (resolved to '{resolved_css or href}'), "
                        f"which is missing from workspace files: {sorted(known_files)}",
                    )

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "interface_hallucination_count": len(violations),
        "repair_counterexamples": repair_counterexamples,
    }


# ---------------------------------------------------------------------------
# 4. Bounded Sibling Interface Guarantees Context Formatter
# ---------------------------------------------------------------------------


def _format_python_fn_sig(fn: dict[str, Any]) -> str:
    name = str(fn.get("name") or "")
    args = [str(a) for a in (fn.get("args") or [])]
    defaults_count = int(fn.get("defaults_count") or 0)
    plain_indices = [i for i, a in enumerate(args) if not a.startswith("*")]
    default_idx_set = set(plain_indices[-defaults_count:]) if defaults_count > 0 else set()
    rendered_args = [
        f"{a}=..." if idx in default_idx_set else a
        for idx, a in enumerate(args)
    ]
    return f"{name}({', '.join(rendered_args)})"


def _compact_items(items: list[str], max_items: int = 8) -> str:
    if len(items) <= max_items:
        return ", ".join(items)
    shown = ", ".join(items[:max_items])
    return f"{shown}, ...+{len(items) - max_items}"


def _format_single_certificate_line(cert: dict[str, Any]) -> str:
    path = str(cert.get("path") or "unknown")
    lang = str(cert.get("language") or "")
    ext = _path_extension(path)
    guar = cert.get("guarantees") if isinstance(cert.get("guarantees"), dict) else {}
    parts: list[str] = []

    if lang == "python" or ext in _PY_EXTENSIONS:
        fns = [_format_python_fn_sig(f) for f in (guar.get("functions") or []) if isinstance(f, dict)]
        classes = [
            f"{c.get('name')}[{', '.join(c.get('methods') or [])}]"
            if c.get("methods")
            else str(c.get("name"))
            for c in (guar.get("classes") or [])
            if isinstance(c, dict) and c.get("name")
        ]
        consts = [str(x) for x in (guar.get("constants") or [])]
        flags = [str(x) for x in (guar.get("cli_flags") or [])]
        if fns:
            parts.append(f"functions=[{_compact_items(fns, 6)}]")
        if classes:
            parts.append(f"classes=[{_compact_items(classes, 5)}]")
        if consts:
            parts.append(f"constants=[{_compact_items(consts, 6)}]")
        if flags:
            parts.append(f"cli_flags=[{_compact_items(flags, 6)}]")
    elif lang == "html" or ext in _HTML_EXTENSIONS:
        dom_ids = [f"#{x}" for x in (guar.get("dom_ids") or [])]
        canvas_ids = [f"#{x}" for x in (guar.get("canvas_ids") or [])]
        button_ids = [f"#{x}" for x in (guar.get("button_ids") or [])]
        imap = [repr(str(x)) for x in (guar.get("importmap_keys") or [])]
        data_attrs = [str(x) for x in (guar.get("data_attributes") or [])]
        parts.append(f"dom_ids=[{_compact_items(dom_ids, 10)}]")
        if canvas_ids:
            parts.append(f"canvas_ids=[{_compact_items(canvas_ids, 4)}]")
        if button_ids:
            parts.append(f"button_ids=[{_compact_items(button_ids, 6)}]")
        if imap:
            parts.append(f"importmap=[{_compact_items(imap, 6)}]")
        if data_attrs:
            parts.append(f"data_attrs=[{_compact_items(data_attrs, 5)}]")
    elif lang == "javascript" or ext in _JS_EXTENSIONS:
        exps = [str(x) for x in (guar.get("exports") or [])]
        globs = [f"AGENT_GAME.{x}" for x in (guar.get("globals") or [])]
        dyn_ids = [f"#{x}" for x in (guar.get("created_dom_ids") or [])]
        parts.append(f"exports=[{_compact_items(exps, 8)}]")
        if globs:
            parts.append(f"globals=[{_compact_items(globs, 6)}]")
        if dyn_ids:
            parts.append(f"created_dom_ids=[{_compact_items(dyn_ids, 6)}]")
    elif lang == "css" or ext in _CSS_EXTENSIONS:
        c_ids = [f"#{x}" for x in (guar.get("css_ids") or [])]
        c_cls = [f".{x}" for x in (guar.get("css_classes") or [])]
        if c_ids:
            parts.append(f"css_ids=[{_compact_items(c_ids, 8)}]")
        if c_cls:
            parts.append(f"css_classes=[{_compact_items(c_cls, 8)}]")

    detail = "; ".join(parts) if parts else "(no public symbols)"
    return f"- {path}: {detail}"


def format_sibling_guarantees_context(
    certificates: list[dict],
    *,
    owned_paths: list[str] | None = None,
    read_only_paths: list[str] | None = None,
    max_chars: int = 1200,
) -> str:
    """Render a deterministic, bounded (`<= max_chars`) sibling interface contract block."""
    if max_chars <= 0:
        return ""

    norm_owned = [
        p for p in (_normalize_posix_path(x) for x in (owned_paths or []))
        if p
    ]
    valid_certs = [c for c in (certificates or []) if isinstance(c, dict)]
    valid_certs_sorted = sorted(valid_certs, key=lambda c: str(c.get("path") or ""))

    if read_only_paths is not None:
        norm_ro = [
            p for p in (_normalize_posix_path(x) for x in read_only_paths)
            if p and p not in norm_owned
        ]
    else:
        norm_ro = [
            str(c.get("path"))
            for c in valid_certs_sorted
            if c.get("path") and str(c.get("path")) not in norm_owned
        ]

    owned_str = _compact_items(norm_owned, 8) if norm_owned else "(none)"
    ro_str = _compact_items(norm_ro, 8) if norm_ro else "(none)"

    header_lines = [
        f"OWNED WRITABLE FILES (edit/create ONLY these): {owned_str}",
        "READ-ONLY VERIFIED SIBLING FILES (DO NOT write_file/edit_file these; "
        f"import/reference their exact interfaces below): {ro_str}",
    ]

    base_text = "\n".join(header_lines)
    if len(base_text) >= max_chars:
        if max_chars <= 3:
            return base_text[:max_chars]
        return base_text[: max_chars - 3].rstrip() + "..."

    lines = list(header_lines)
    current_len = len(base_text)

    ro_filter = set(norm_ro) if read_only_paths is not None and norm_ro else None
    display_certs = [
        c for c in valid_certs_sorted
        if str(c.get("path") or "") not in norm_owned
        and (ro_filter is None or str(c.get("path") or "") in ro_filter or not any(str(x.get("path") or "") in ro_filter for x in valid_certs_sorted))
    ]

    for idx, cert in enumerate(display_certs):
        cert_line = _format_single_certificate_line(cert)
        remaining_certs = len(display_certs) - idx - 1
        reserve = 24 if remaining_certs > 0 else 0
        available = max_chars - current_len - 1 - reserve

        if available < 16:
            omitted = len(display_certs) - idx
            suffix = f"... (+{omitted} more)"
            if current_len + 1 + len(suffix) <= max_chars:
                lines.append(suffix)
            break

        if len(cert_line) > available:
            cert_line = cert_line[: available - 3].rstrip() + "..."
        lines.append(cert_line)
        current_len += 1 + len(cert_line)

    rendered = "\n".join(lines)
    if len(rendered) > max_chars:
        rendered = rendered[: max_chars - 3].rstrip() + "..." if max_chars > 3 else rendered[:max_chars]
    return rendered
