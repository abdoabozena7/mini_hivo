import argparse
import base64
import copy
import hashlib
import importlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

from hivo.browser_checks import run_profile_interactions
from hivo.context import compact_messages
from hivo.evidence import evidence_for_review
from hivo.evidence import MUTATION_TOOLS
from hivo.evidence import mutation_failure_record
from hivo.evidence import result_failed as evidence_result_failed
from hivo.evidence import result_not_applicable
from hivo.evidence import result_is_tool_rejection
from hivo.evidence import unresolved_tool_failures
from hivo.host_preflight import failed_host_preflight_result, format_host_preflight_report, run_host_preflight
from hivo.http_client import HttpTransportError, get_json as http_get_json, post_json as http_post_json
from hivo.memory import MemoryStore
from hivo.model_policy import GEMMA_MODEL, SingleModelPolicy
from hivo.playbooks import classify_project, playbook_context
from hivo.projects import ProjectStore
from hivo import project_understanding as stage2
from hivo import impact_planning as stage3
from hivo.requirements import DERIVED
from hivo.requirements import USER_CONFIRMED
from hivo.requirements import USER_STATED
from hivo.requirements import VERIFIED
from hivo.requirements import MAX_CLARIFICATION_OPTIONS as REQUIREMENT_MAX_CLARIFICATION_OPTIONS
from hivo.requirements import MAX_CLARIFICATION_QUESTIONS as REQUIREMENT_MAX_CLARIFICATION_QUESTIONS
from hivo.requirements import MAX_SOURCE_REQUIREMENT_CHARS
from hivo.requirements import MAX_SOURCE_REQUIREMENTS
from hivo.requirements import MAX_SOURCE_EXPLICIT_ITEMS
from hivo.requirements import MAX_SOURCE_SEGMENTS
from hivo.requirements import MAX_SOURCE_SEGMENT_CHARS
from hivo.requirements import append_confirmed_requirement
from hivo.requirements import bounded_source_segments
from hivo.requirements import build_source_requirement_ledger
from hivo.requirements import classify_interaction_style
from hivo.requirements import conflict_questions
from hivo.requirements import detect_explicit_conflicts
from hivo.requirements import deterministic_requirement_candidates
from hivo.requirements import freeze
from hivo.requirements import has_explicit_requirement_signal
from hivo.requirements import ledger_requirements
from hivo.requirements import normalize_question
from hivo.requirements import question_is_eligible
from hivo.requirements import question_priority
from hivo.requirements import retention_summary
from hivo.requirements import source_contract_from_ledger
from hivo.requirements import specification_coverage
from hivo.requirements import thaw
from hivo.verification import GAME_BRIDGE_EXPRESSION, GAME_BRIDGE_NAME
from hivo.verification import evaluate_web_snapshot, infer_web_profile

# ---------------------------------------------------------------------------
# RESEARCH CONFIGURATION
# ---------------------------------------------------------------------------

MODEL_POLICY = SingleModelPolicy()
MODEL = GEMMA_MODEL
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_URL = OLLAMA_BASE_URL + "/api/chat"

WORKSPACE = None
DEFAULT_PROJECTS_ROOT = Path(__file__).resolve().parent / "list"
MEMORY_FILE = ".agent_memory.json"  # legacy compatibility only; SQLite is authoritative
EXPERIMENT_FILE = ".agent_experiment.jsonl"
EVIDENCE_DIR = ".agent_evidence"
RUNS_DIR = ".agent_runs"

# One focused Builder execution is the leaf budget. solve_task() is the only
# adaptive granularity controller in recursive mode.
MAX_TOOL_STEPS = 28
MAX_DEPTH = 6
MAX_CHILDREN = 4
MAX_TOTAL_TASKS = 64
MAX_DECOMPOSITION_ALTERNATIVES = 2
# v5 strategy search is deliberately bounded to two sequential alternatives.
MAX_STRATEGY_ALTERNATIVES = 2
STRATEGY_SEARCH_UNAVAILABLE = "STRATEGY_SEARCH_UNAVAILABLE"
# Reaching the focused execution budget is an observation, not a diagnosis.
# The failure router must inspect the resulting evidence before choosing a
# decomposition, strategy, dependency, verifier, or capability path.
EXECUTION_BUDGET_EXHAUSTED = "EXECUTION_BUDGET_EXHAUSTED"
VERIFICATION_TARGET_UNRESOLVED = "VERIFICATION_TARGET_UNRESOLVED"
# Keep the old name as a read-only compatibility alias for callers that
# inspected the v3 prototype; all new routing uses the v5 name above.
MAX_ALTERNATE_STRATEGIES = MAX_STRATEGY_ALTERNATIVES
MAX_CLARIFICATION_QUESTIONS = REQUIREMENT_MAX_CLARIFICATION_QUESTIONS
MAX_REPAIRS_PER_LEAF = 2
MAX_STRUCTURED_RETRIES = 5
MAX_PROVIDER_RETRIES = 2
MAX_RECON_FILES = 120
MAX_RECON_DEPTH = 3
MAX_RECON_CHARS = 6000
# Stage 2 targeted reconnaissance has separate read/model bounds.  The legacy
# shallow snapshot above remains a metadata inventory for older callers.
MAX_RECON_SEARCHES = stage2.MAX_RECON_SEARCHES
MAX_TARGETED_RECON_FILES = stage2.MAX_RECON_FILES
MAX_RECON_SNIPPETS = stage2.MAX_RECON_SNIPPETS
MAX_TARGETED_RECON_CHARS = stage2.MAX_RECON_CHARS
MAX_RECON_MODEL_CALLS = stage2.MAX_RECON_MODEL_CALLS
MAX_TASK_BRAIN_CHARS = stage2.MAX_TASK_BRAIN_CHARS
MAX_TASK_BRAIN_EVIDENCE = stage2.MAX_TASK_BRAIN_EVIDENCE
MAX_TASK_BRAIN_TESTS = stage2.MAX_TASK_BRAIN_TESTS
MAX_TASK_BRAIN_INTERFACES = stage2.MAX_TASK_BRAIN_INTERFACES
MAX_TASK_BRAIN_ASSUMPTIONS = stage2.MAX_TASK_BRAIN_ASSUMPTIONS
MAX_TASK_BRAIN_OPEN_QUESTIONS = stage2.MAX_TASK_BRAIN_OPEN_QUESTIONS
MAX_TASK_BRAIN_PROJECTION_CHARS = stage2.MAX_TASK_BRAIN_PROJECTION_CHARS
MAX_IMPACT_ENTRIES = stage3.MAX_IMPACT_ENTRIES
MAX_PLAN_NODES = stage3.MAX_PLAN_NODES
MAX_IMPACT_CHALLENGES = stage3.MAX_CHALLENGES
MAX_IMPACT_PLAN_CHARS = stage3.MAX_PLAN_CHARS
MAX_IMPACT_CHALLENGE_ROUNDS = stage3.MAX_CHALLENGE_ROUNDS
MAX_IMPACT_PLAN_REVISION_ROUNDS = stage3.MAX_REVISION_ROUNDS
NEW_PROJECT = stage2.NEW_PROJECT
EXISTING_PROJECT = stage2.EXISTING_PROJECT
REPOSITORY_EMPTY = stage2.REPOSITORY_EMPTY
REPOSITORY_EVIDENCE_UNAVAILABLE = stage2.REPOSITORY_EVIDENCE_UNAVAILABLE
REPOSITORY_RECONNAISSANCE_FAILED = stage2.REPOSITORY_RECONNAISSANCE_FAILED
REPOSITORY_RECONNAISSANCE_COMPLETE = stage2.REPOSITORY_RECONNAISSANCE_COMPLETE
PROJECT_BRAIN = stage2.PROJECT_BRAIN
REPOSITORY_EVIDENCE = stage2.REPOSITORY_EVIDENCE
DERIVED_TASK_ASSUMPTION = stage2.DERIVED_TASK_ASSUMPTION
DERIVED_PLAN_DECISION = stage3.DERIVED_PLAN_DECISION
PLAN_APPROVAL_REQUIRED = "PLAN_APPROVAL_REQUIRED"
PLAN_REJECTED = "PLAN_REJECTED"
PLAN_INCOMPLETE = "PLAN_INCOMPLETE"
UNAPPROVED_SCOPE_EXPANSION = "UNAPPROVED_SCOPE_EXPANSION"
MAX_NODE_SUMMARY_CHARS = 700
MAX_NODE_PACKET_CHARS = 12000
MAX_ROOT_PACKET_CHARS = 2400
MAX_MEMORY_CONTEXT_CHARS = 1800
MAX_FALSIFIER_STEPS = 8
MAX_MUTATION_FAILURE_RECORDS = 6
MAX_MUTATION_RECOVERY_CONTEXT_LINES = 12
MAX_MUTATION_RECOVERY_CONTEXT_CHARS = 1400
MAX_INTEGRATION_MANIFEST_ITEMS = 8
MAX_INTEGRATION_FACT_CHARS = 280
MAX_INTEGRATION_CONFLICTS = 24
# Recursive prompt compilation has its own small context caps.  These are
# prompt-size limits only; they do not change any execution, repair, depth, or
# strategy budget.
MAX_PROJECT_SPECIFICATION_CHARS = 5200
MAX_PROJECT_BRAIN_CHARS = 7600
MAX_BRAIN_PROJECTION_CHARS = 3600
MAX_WORKER_MISSION_CHARS = 4200
MAX_MISSION_COMPILER_CONTEXT_CHARS = 5200
MAX_BRAIN_ITEMS = 8
MAX_SOURCE_LEDGER_CHARS = 26000
MAX_SOURCE_EXTRACTION_MODEL_CALLS = 8
MAX_CLARIFIER_INPUT_CHARS = 9000
OLLAMA_TIMEOUT_SECONDS = 120
CONTEXT_LIMIT_TOKENS = MODEL_POLICY.context_window("builder")
MODEL_TASK_CAPACITY = 2  # heuristic prior only: parameter size is not a measured capability score
ENABLE_VISION = True
MODEL_CAPABILITIES = set()
VISION_MODEL = ""
VISION_ERROR = None
FORCE_CPU_FOR_RUN = False
# Compatibility labels retained for callers that inspected the old single-model
# configuration. They are never used to route to another model.
ROUTER_MODEL = MODEL
FALLBACK_MODEL = ""

DANGEROUS = ["rm -rf", "sudo", "mkfs", "shutdown", "reboot", "format ", "del /f", ":(){"]
KNOWN_DEPENDENCIES = {
    "rich": "rich>=13.7,<15",
    "prompt_toolkit": "prompt_toolkit>=3.0.43,<4",
    "playwright": "playwright>=1.45,<2",
}

RICH_AVAILABLE = False
PROMPT_TOOLKIT_AVAILABLE = False
PLAYWRIGHT_AVAILABLE = False
Console = Live = Panel = Table = Tree = Group = Text = None
prompt = KeyBindings = PathCompleter = None
sync_playwright = None

RUN = {}
TASKS = {}
ROLE_STATUS = {}
DASHBOARD = {
    "mode": "baseline", "context": 0, "active_role": "-", "active_task": "-",
    "action": "-", "tool": "-", "event": "-",
}
LIVE_VIEW = None
RUN_STARTED = 0.0
RUN_ID = ""
ACTIVE_TRANSACTION = None
LAST_COMMITTED_TRANSACTION = None
ACTIVE_CONTRACT = None
ACTIVE_TOOL_CONTRACT = None
MEMORY_STORE = None
VISION_ENABLED_FOR_RUN = False
PREFLIGHT_CONFLICT_STATE = {"registry": {}, "active": set(), "sequence": 0}
HOST_PREFLIGHT_RESULT = None


class ProviderError(RuntimeError):
    """The local model provider could not complete a request."""


class StructuredOutputError(RuntimeError):
    """The provider replied, but a tiny structured orchestration contract was invalid."""


class MissionCompilationError(RuntimeError):
    """A bounded worker mission could not be compiled from verified context."""


class TaskBrainValidationError(RuntimeError):
    """The temporary task context failed its deterministic Stage 2 gate."""


class ImpactPlanningError(RuntimeError):
    """The bounded Stage 3 evidence/coverage gate rejected a plan."""


class PlanApprovalRequiredError(RuntimeError):
    """An existing-project Worker was reached without a current approval."""


# ---------------------------------------------------------------------------
# OPTIONAL DEPENDENCIES / LOCAL MODEL
# ---------------------------------------------------------------------------

def configure_console_streams(streams=None):
    for stream in streams or (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="backslashreplace")
            except (OSError, ValueError):
                pass


def _load_optional_imports():
    global RICH_AVAILABLE, PROMPT_TOOLKIT_AVAILABLE, PLAYWRIGHT_AVAILABLE
    global Console, Live, Panel, Table, Tree, Group, Text, prompt, KeyBindings, PathCompleter, sync_playwright
    try:
        rich_console = importlib.import_module("rich.console")
        rich_live = importlib.import_module("rich.live")
        rich_panel = importlib.import_module("rich.panel")
        rich_table = importlib.import_module("rich.table")
        rich_tree = importlib.import_module("rich.tree")
        rich_text = importlib.import_module("rich.text")
        Console, Group = rich_console.Console, rich_console.Group
        Live, Panel, Table, Tree, Text = (
            rich_live.Live, rich_panel.Panel, rich_table.Table, rich_tree.Tree, rich_text.Text,
        )
        RICH_AVAILABLE = True
    except ImportError:
        RICH_AVAILABLE = False

    try:
        pt = importlib.import_module("prompt_toolkit")
        kb = importlib.import_module("prompt_toolkit.key_binding")
        completion = importlib.import_module("prompt_toolkit.completion")
        prompt, KeyBindings, PathCompleter = pt.prompt, kb.KeyBindings, completion.PathCompleter
        PROMPT_TOOLKIT_AVAILABLE = True
    except ImportError:
        PROMPT_TOOLKIT_AVAILABLE = False

    try:
        pw = importlib.import_module("playwright.sync_api")
        sync_playwright = pw.sync_playwright
        PLAYWRIGHT_AVAILABLE = True
    except ImportError:
        PLAYWRIGHT_AVAILABLE = False


def ensure_dependencies(auto_install=True):
    _load_optional_imports()
    missing = [name for name in KNOWN_DEPENDENCIES if importlib.util.find_spec(name) is None]
    if missing and auto_install:
        for name in missing:
            spec = KNOWN_DEPENDENCIES[name]
            print(f"[SETUP] installing missing dependency: {name}")
            result = subprocess.run([sys.executable, "-m", "pip", "install", spec], text=True)
            if result.returncode != 0:
                print(f"[SETUP_ERROR] failed to install {name}")
                return False
        _load_optional_imports()
    return not [name for name in KNOWN_DEPENDENCIES if importlib.util.find_spec(name) is None]


def is_local_ollama_url(url):
    try:
        from urllib.parse import urlparse
        return urlparse(url).hostname in {"127.0.0.1", "localhost", "::1"}
    except Exception:
        return False


def is_cloud_model_name(name):
    lower = str(name).lower()
    return lower.endswith("-cloud") or ":cloud" in lower or "-cloud:" in lower


def fetch_local_ollama_models():
    if not is_local_ollama_url(OLLAMA_BASE_URL):
        raise RuntimeError(f"OLLAMA_BASE_URL must point to local Ollama only; got: {OLLAMA_BASE_URL}")
    try:
        response = http_get_json(OLLAMA_BASE_URL + "/api/tags", timeout=5)
    except HttpTransportError as exc:
        raise RuntimeError(
            f"could not reach local Ollama at {OLLAMA_BASE_URL}. Start Ollama first. Details: {exc}"
        ) from exc
    if response.status_code != 200:
        raise RuntimeError(f"local Ollama /api/tags returned status {response.status_code}: {response.text[:300]}")
    try:
        models = response.json().get("models", [])
    except ValueError as exc:
        raise RuntimeError(f"invalid response from local Ollama: {exc}") from exc
    result = []
    for item in models:
        name = item.get("name") or item.get("model")
        if name and not is_cloud_model_name(name):
            result.append(item)
    return result


def _parameter_billions(model_info):
    text = str((model_info.get("details") or {}).get("parameter_size", "")).strip().upper()
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([BM])", text)
    if match:
        value = float(match.group(1))
        return value if match.group(2) == "B" else value / 1000.0
    name = str(model_info.get("name") or model_info.get("model") or "").upper()
    matches = re.findall(r"([0-9]+(?:\.[0-9]+)?)B", name)
    return float(matches[-1]) if matches else None


def infer_model_capacity(model_info):
    """Rough size-derived prior only; observed execution failure is stronger evidence."""
    billions = _parameter_billions(model_info)
    if billions is None:
        return 2
    if billions <= 8:
        return 1
    if billions <= 16:
        return 2
    if billions <= 34:
        return 3
    return 4


def fetch_model_capabilities(model_name):
    try:
        response = http_post_json(
            OLLAMA_BASE_URL + "/api/show", timeout=10, payload={"model": model_name}
        )
        if response.status_code == 200:
            return {str(item).lower() for item in response.json().get("capabilities", [])}
    except Exception:
        pass
    return set()


def configure_role_models(models, primary_name):
    """Validate the one-model experiment without creating a routing layer.

    The old harness exposed this function while it still had router/fallback
    roles.  Keeping the validation entry point makes the single-model policy
    explicit for integrations and tests; every role still resolves to the same
    pinned model and fallback remains disabled.
    """
    global MODEL, MODEL_TASK_CAPACITY, MODEL_CAPABILITIES, VISION_MODEL
    global ROUTER_MODEL, FALLBACK_MODEL
    required = MODEL_POLICY.validate(primary_name)
    by_name = {(item.get("name") or item.get("model")): item for item in models or []}
    if required not in by_name:
        raise RuntimeError(f"required local model '{required}' was not found")
    MODEL = required
    MODEL_TASK_CAPACITY = infer_model_capacity(by_name[required])
    MODEL_CAPABILITIES = fetch_model_capabilities(required)
    VISION_MODEL = required if "vision" in MODEL_CAPABILITIES else ""
    ROUTER_MODEL = required
    FALLBACK_MODEL = ""
    return by_name[required]


def select_local_ollama_model(explicit=None):
    global MODEL, MODEL_TASK_CAPACITY, MODEL_CAPABILITIES, VISION_MODEL
    global ROUTER_MODEL, FALLBACK_MODEL
    required = MODEL_POLICY.validate(explicit)
    models = fetch_local_ollama_models()
    by_name = {(item.get("name") or item.get("model")): item for item in models}
    if required not in by_name:
        raise RuntimeError(f"required local model '{required}' was not found. Run `ollama pull {required}`.")
    MODEL = required
    MODEL_TASK_CAPACITY = infer_model_capacity(by_name[required])
    MODEL_CAPABILITIES = fetch_model_capabilities(required)
    VISION_MODEL = required if "vision" in MODEL_CAPABILITIES else ""
    ROUTER_MODEL = required
    FALLBACK_MODEL = ""
    print(f"[MODEL] {MODEL}")
    print("[PROVIDER] local Ollama only")
    print(f"[CAPACITY] {MODEL_TASK_CAPACITY}/4 (PARAMETER-SIZE HEURISTIC; NOT A BENCHMARK)")
    return by_name[required]


# ---------------------------------------------------------------------------
# WORKSPACE TOOLS AND SAFETY
# ---------------------------------------------------------------------------

TOOLS = [
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create a new file. Existing user/verified files are protected; use focused edits.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Replace one small exact text fragment in an existing file after reading it.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"},
            "expected_replacements": {"type": "integer", "minimum": 1, "maximum": 20}},
            "required": ["path", "old", "new"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "read_file_range",
        "description": "Read a bounded 1-based line range with line numbers.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1}},
            "required": ["path"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "edit_file_range",
        "description": "Replace a bounded 1-based line range after reading it.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1}, "new": {"type": "string"}},
            "required": ["path", "start_line", "end_line", "new"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a file's content.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                       "required": ["path"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "backup_file", "description": "Make a timestamped backup copy without changing the file.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                       "required": ["path"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "list_files", "description": "List top-level workspace files.",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "run_file", "description": "Run a .py, .js, .cpp/.cc file or inspect an HTML entry in Chromium.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                       "required": ["path"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "run_command", "description": "Run an allowlisted verification command inside the workspace.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}},
                       "required": ["command"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "verify_web_app", "description": "Serve local HTML and run deterministic Chromium checks.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                       "required": ["path"], "additionalProperties": False},
    }},
]
TOOL_DEFINITIONS = {item["function"]["name"]: item["function"] for item in TOOLS}


def safe_path(path_str):
    try:
        candidate = Path(path_str)
        if not candidate.is_absolute():
            candidate = WORKSPACE / candidate
        resolved = candidate.resolve()
        return resolved if resolved.is_relative_to(WORKSPACE) else None
    except Exception:
        return None


def tool_argument_error(name, args):
    definition = TOOL_DEFINITIONS.get(name)
    if definition is None:
        return None
    if not isinstance(args, dict):
        if name in MUTATION_TOOLS:
            return (
                f"error: malformed {name} tool arguments; expected one JSON object with "
                f"{_mutation_contract_text(definition)}. No file was changed."
            )
        return f"error: {name} arguments must be one JSON object"
    required = definition.get("parameters", {}).get("required", [])
    missing = [key for key in required if key not in args or args.get(key) is None]
    if missing:
        contract = (
            f" Expected contract: {_mutation_contract_text(definition)}."
            if name in MUTATION_TOOLS else ""
        )
        return (
            f"error: incomplete or truncated {name} tool call; missing: {', '.join(missing)}. "
            f"Retry with every required field and smaller content/edit fragments.{contract} No file was changed."
        )
    if name not in MUTATION_TOOLS:
        return None

    properties = definition.get("parameters", {}).get("properties", {})
    unexpected = sorted(str(key) for key in args if key not in properties)
    invalid = []
    for key, value in args.items():
        spec = properties.get(key)
        if spec is None:
            continue
        expected_type = spec.get("type")
        valid_type = (
            expected_type == "string" and isinstance(value, str)
        ) or (
            expected_type == "integer" and isinstance(value, int) and not isinstance(value, bool)
        )
        if not valid_type:
            invalid.append(f"{key} must be {expected_type}")
            continue
        if expected_type == "integer":
            minimum = spec.get("minimum")
            maximum = spec.get("maximum")
            if minimum is not None and value < minimum:
                invalid.append(f"{key} must be >= {minimum}")
            if maximum is not None and value > maximum:
                invalid.append(f"{key} must be <= {maximum}")
    if not unexpected and not invalid:
        return None
    details = []
    if unexpected:
        details.append(f"unexpected field(s): {', '.join(unexpected)}")
    if invalid:
        details.append("; ".join(invalid))
    return (
        f"error: invalid {name} tool arguments; {'; '.join(details)}. "
        f"Expected contract: {_mutation_contract_text(definition)}. No file was changed."
    )


def _mutation_contract_text(definition):
    parameters = definition.get("parameters", {}) if isinstance(definition, dict) else {}
    required = set(parameters.get("required", []))
    fields = []
    for key, spec in (parameters.get("properties", {}) or {}).items():
        field = f"{key}:{spec.get('type', 'value')}"
        if key not in required:
            field += " (optional)"
        if spec.get("minimum") is not None or spec.get("maximum") is not None:
            field += f" [{spec.get('minimum', '')}..{spec.get('maximum', '')}]"
        fields.append(field)
    return ", ".join(fields) or "no fields"


def begin_transaction(task_id):
    global ACTIVE_TRANSACTION, LAST_COMMITTED_TRANSACTION
    if ACTIVE_TRANSACTION is not None:
        raise RuntimeError(f"transaction already active for {ACTIVE_TRANSACTION['task_id']}")
    LAST_COMMITTED_TRANSACTION = None
    ACTIVE_TRANSACTION = {"task_id": task_id, "files": {}}


def _transaction_capture(target):
    if ACTIVE_TRANSACTION is None:
        return
    key = str(target)
    if key in ACTIVE_TRANSACTION["files"]:
        return
    ACTIVE_TRANSACTION["files"][key] = {
        "existed": target.exists(),
        "content": target.read_bytes() if target.exists() and target.is_file() else None,
    }


def commit_transaction():
    global ACTIVE_TRANSACTION, LAST_COMMITTED_TRANSACTION
    transaction = ACTIVE_TRANSACTION or {"task_id": None, "files": {}}
    ACTIVE_TRANSACTION = None
    LAST_COMMITTED_TRANSACTION = transaction
    changed = sorted(transaction["files"])
    record_run_event("transaction_commit", task_id=transaction.get("task_id"), changed=changed)
    return changed


def rollback_transaction():
    global ACTIVE_TRANSACTION
    transaction = ACTIVE_TRANSACTION
    ACTIVE_TRANSACTION = None
    if not transaction:
        return []
    restored = []
    for raw_path, snapshot in transaction["files"].items():
        target = Path(raw_path)
        try:
            if snapshot["existed"]:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(snapshot["content"])
            elif target.exists() and target.is_file():
                target.unlink()
            restored.append(raw_path)
            store = get_memory_store()
            if store:
                store.reconcile_rolled_back_artifact(raw_path, existed=bool(snapshot["existed"]))
        except OSError as exc:
            print(f"[ROLLBACK_ERROR] {target}: {exc}")
    record_run_event("transaction_rollback", task_id=transaction.get("task_id"), restored=restored)
    return restored


def backup(target):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    relative = target.relative_to(WORKSPACE)
    path = WORKSPACE / ".agent_backups" / (RUN_ID or stamp) / relative
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path = path.with_name(path.name + f".{stamp}")
        shutil.copy2(target, path)
        return f" (managed backup: {path.relative_to(WORKSPACE)})"
    except OSError as exc:
        return f"error: backup failed, file NOT changed: {exc}"


def source_validation_error(target, content):
    suffix = target.suffix.casefold()
    text = str(content)
    if suffix == ".py":
        try:
            compile(text, str(target), "exec")
        except SyntaxError as exc:
            return f"Python syntax validation failed at line {exc.lineno}: {exc.msg}"
        return None
    if suffix == ".json":
        try:
            json.loads(text)
        except (ValueError, TypeError) as exc:
            return f"JSON syntax validation failed: {exc}"
        return None
    javascript = text if suffix in {".js", ".mjs", ".cjs"} else ""
    if suffix in {".html", ".htm"}:
        javascript = "\n;\n".join(re.findall(
            r"<script(?![^>]*\bsrc=)(?![^>]*type=[\"'](?:application|application/ld)\/json[\"'])[^>]*>([\s\S]*?)</script>",
            text, flags=re.IGNORECASE,
        ))
    if not javascript.strip():
        return None
    try:
        checked = subprocess.run(
            ["node", "--check", "-"], input=javascript, text=True,
            encoding="utf-8", errors="replace", capture_output=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if checked.returncode != 0:
        return f"JavaScript syntax validation failed: {compact_text(checked.stderr or checked.stdout, 500)}"
    return None


def _mutation_recovery_target(raw_path):
    """Return a safe target and workspace-relative identity for recovery feedback."""
    if WORKSPACE is None:
        return None, None
    target = safe_path(raw_path)
    if target is None:
        return None, None
    try:
        relative = target.relative_to(Path(WORKSPACE).resolve()).as_posix()
    except (ValueError, OSError):
        return None, None
    return target, relative


def _mutation_recovery_file_state(target):
    """Read only the current file bytes needed for a bounded deterministic packet."""
    try:
        if not target.exists() or not target.is_file():
            return False, None, None, None
        raw = target.read_bytes()
        return True, f"sha256:{hashlib.sha256(raw).hexdigest()}", raw.decode("utf-8", "replace"), None
    except OSError as exc:
        return True, None, None, f"current file could not be read: {exc}"


def _recovery_context_window(lines, focus_start=None, focus_end=None):
    """Choose a small numbered source window without fuzzy-editing the file."""
    line_count = len(lines)
    if not line_count:
        return [], 0, 0, False
    max_lines = MAX_MUTATION_RECOVERY_CONTEXT_LINES
    if focus_start is not None:
        raw_start = int(focus_start)
        if focus_end is None:
            start = max(1, min(line_count, raw_start))
            start = max(1, start - max_lines // 2)
            end = min(line_count, start + max_lines - 1)
            start = max(1, end - max_lines + 1)
            return list(range(start, end + 1)), start, end, False
        raw_end = int(focus_end)
        if raw_end < raw_start or raw_start < 1 or raw_end > line_count:
            focus = max(1, min(line_count, raw_start))
            start = max(1, focus - max_lines // 2)
            end = min(line_count, start + max_lines - 1)
            start = max(1, end - max_lines + 1)
            return list(range(start, end + 1)), start, end, True
        start = raw_start
        end = raw_end
        if end < start:
            end = start
        span = end - start + 1
        if span <= max_lines:
            numbers = list(range(start, end + 1))
            return numbers, start, end, False
        head_count = max_lines // 2
        tail_count = max_lines - head_count
        numbers = list(range(start, start + head_count)) + list(range(end - tail_count + 1, end + 1))
        return numbers, start, end, True
    if line_count <= max_lines:
        return list(range(1, line_count + 1)), 1, line_count, False
    head_count = max_lines // 2
    tail_count = max_lines - head_count
    return list(range(1, head_count)) + list(range(line_count - tail_count + 1, line_count + 1)), 1, line_count, True


def _mutation_recovery_context(text, old=None, focus_start=None, focus_end=None):
    """Produce bounded current source context and its deterministic selection reason."""
    if text is None:
        return "No current source context is available; perform a normal bounded read before retrying.", "normal_read_required", None
    lines = text.splitlines()
    line_count = len(lines)
    if focus_start is not None:
        context_source = "requested_range"
        focus = focus_start
    else:
        focus = None
        context_source = "bounded_file_state"
        if isinstance(old, str) and old:
            exact_matches = text.count(old)
            if exact_matches == 1:
                anchor_offset = text.find(old)
                focus = text.count("\n", 0, anchor_offset) + 1
                context_source = "exact_text_anchor"
            elif exact_matches == 0:
                anchor = next((line.strip() for line in old.splitlines() if line.strip()), "")
                if anchor:
                    matching_lines = [index for index, line in enumerate(lines, start=1) if anchor in line]
                    if len(matching_lines) == 1:
                        focus = matching_lines[0]
                        context_source = "text_anchor"
        if focus is None and line_count:
            context_source = "bounded_file_state"

    numbers, first, last, omitted = _recovery_context_window(lines, focus, focus_end)
    if not numbers:
        return "[current file is empty; 0 lines]", context_source, line_count
    rendered = []
    for number in numbers:
        line = lines[number - 1]
        if len(line) > 240:
            line = line[:237] + "..."
        rendered.append(f"{number}: {line}")
    if omitted:
        if focus_start is not None:
            header = f"[current bounded lines around requested range; file has {line_count} lines]"
        else:
            header = f"[current file beginning/end; file has {line_count} lines]"
    else:
        header = f"[current lines {first}-{last} of {line_count}]"
    context = header + "\n" + "\n".join(rendered)
    if context_source == "bounded_file_state" and focus_start is None:
        context += "\nNo unique deterministic anchor was found; perform a normal bounded read before retrying."
    if len(context) > MAX_MUTATION_RECOVERY_CONTEXT_CHARS:
        suffix = "\n...[bounded recovery context truncated]"
        context = context[:MAX_MUTATION_RECOVERY_CONTEXT_CHARS - len(suffix)] + suffix
    return context, context_source, line_count


def _mutation_recovery_syntax_state(target, exists, text):
    if not exists:
        return "ABSENT", None
    if text is None:
        return "UNKNOWN", "current source could not be read"
    if target.suffix.casefold() not in {".py", ".json", ".js", ".mjs", ".cjs", ".html", ".htm"}:
        return "NOT_APPLICABLE", None
    validation = source_validation_error(target, text)
    return ("FAIL", validation) if validation else ("PASS", None)


def _mutation_recovery_packet(name, args, mutation_record, result):
    """Build feedback for recoverable mutation failures; never apply a retry."""
    category = str((mutation_record or {}).get("category", ""))
    if category not in {"STALE_TARGET", "MISSING_TARGET", "SYNTAX_INVALID_MUTATION"}:
        return None
    target, relative = _mutation_recovery_target((args or {}).get("path"))
    if target is None or relative is None:
        return None
    exists, file_hash, text, read_error = _mutation_recovery_file_state(target)
    if category == "MISSING_TARGET":
        context = (
            "No current regular file exists at this workspace path; perform a normal bounded read or list operation "
            "before choosing the next mutation."
        )
        context_source = "file_absent"
        line_count = None
    elif name == "edit_file_range":
        start_line = (args or {}).get("start_line")
        end_line = (args or {}).get("end_line")
        context, context_source, line_count = _mutation_recovery_context(
            text, focus_start=start_line, focus_end=end_line,
        )
    else:
        context, context_source, line_count = _mutation_recovery_context(
            text, old=(args or {}).get("old"),
        )
    if read_error:
        context = f"{context}\n{read_error}; perform a normal bounded read before retrying."
        context = context[:MAX_MUTATION_RECOVERY_CONTEXT_CHARS]

    packet = {
        "category": category,
        "target": relative,
        "mutation_applied": False,
        "candidate_applied": False,
        "filesystem_changed": False,
        "current_file_exists": bool(exists),
        "current_file_hash": file_hash,
        "current_file_line_count": line_count,
        "fresh_context": context,
        "context_source": context_source,
        "retry_allowed": True,
    }
    if category == "SYNTAX_INVALID_MUTATION":
        syntax_state, syntax_error = _mutation_recovery_syntax_state(target, exists, text)
        packet["syntax_error"] = compact_text(result, 700)
        packet["current_workspace_syntax_state"] = syntax_state
        if syntax_error:
            packet["current_workspace_syntax_error"] = compact_text(syntax_error, 500)
    if name == "edit_file" and isinstance(text, str) and isinstance((args or {}).get("old"), str):
        packet["current_matching_replacements"] = text.count((args or {}).get("old"))
        expected = (args or {}).get("expected_replacements", 1)
        if isinstance(expected, int) and not isinstance(expected, bool):
            packet["requested_expected_replacements"] = expected
    if name == "edit_file_range":
        packet["requested_range"] = {
            "start_line": (args or {}).get("start_line"),
            "end_line": (args or {}).get("end_line"),
        }
    return packet


def _enrich_mutation_result(name, args, mutation_record, result):
    packet = _mutation_recovery_packet(name, args, mutation_record, result)
    if packet is None:
        return result, None
    encoded = json.dumps({"mutation_recovery": packet}, ensure_ascii=False, separators=(",", ":"))
    return f"{result}\nMUTATION_RECOVERY: {encoded}", packet


def write_file(path, content, role="System"):
    target = safe_path(path)
    if target is None:
        return f"error: '{path}' is outside the workspace."
    if role == "Repairer":
        return "error: Repairer cannot replace files with write_file; use focused edits"
    transaction_snapshot = (ACTIVE_TRANSACTION or {}).get("files", {}).get(str(target))
    created_here = bool(transaction_snapshot and not transaction_snapshot.get("existed"))
    resumable = False
    if target.exists() and role == "Builder" and not created_here:
        store = get_memory_store()
        resumable = bool(ACTIVE_TRANSACTION is not None and store and store.is_unverified_model_artifact(target))
        if not resumable:
            return "error: write_file cannot replace an existing user-owned or verified file; use focused edit_file"
    note = backup(target) if target.exists() and not created_here else ""
    if note.startswith("error"):
        return note
    validation = source_validation_error(target, content)
    if validation:
        return f"error: {validation}; file was not changed"
    try:
        _transaction_capture(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if target.exists() and created_here:
            return f"wrote file: {target}{note}"
        if resumable:
            return f"wrote file: {target} (resumed unverified model artifact){note}"
        return f"wrote file: {target}{note}"
    except OSError as exc:
        return f"error writing file: {exc}"


def edit_file(path, old, new, expected_replacements=1):
    target = safe_path(path)
    if target is None:
        return f"error: '{path}' is outside the workspace."
    if not target.exists() or not target.is_file():
        return f"error: file does not exist: {target}"
    try:
        original = target.read_text(encoding="utf-8")
    except OSError as exc:
        return f"error reading file: {exc}"
    expected = expected_replacements or 1
    actual = original.count(old)
    if actual != expected:
        return f"error: expected {expected} exact replacement(s), found {actual}; file was not changed"
    candidate = original.replace(old, new, expected)
    validation = source_validation_error(target, candidate)
    if validation:
        return f"error: {validation}; edit rejected and file was not changed"
    snapshot = (ACTIVE_TRANSACTION or {}).get("files", {}).get(str(target))
    transaction_owned = bool(snapshot and not snapshot.get("existed"))
    note = "" if transaction_owned else backup(target)
    if note.startswith("error"):
        return note
    try:
        _transaction_capture(target)
        target.write_text(candidate, encoding="utf-8")
        return f"edited file: {target} ({expected} replacement(s)){note}"
    except OSError as exc:
        return f"error writing file: {exc}"


def read_file_range(path, start_line=1, end_line=None):
    target = safe_path(path)
    if target is None:
        return f"error: '{path}' is outside the workspace."
    if not target.exists() or not target.is_file():
        return f"error: file does not exist: {target}"
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return f"error reading file: {exc}"
    start = max(1, int(start_line or 1))
    end = min(len(lines), int(end_line or min(len(lines), start + 199)))
    if start > len(lines) or end < start:
        return f"error: invalid line range {start}-{end}; file has {len(lines)} lines"
    return f"[lines {start}-{end} of {len(lines)}]\n" + "\n".join(
        f"{number}: {line}" for number, line in enumerate(lines[start - 1:end], start=start)
    )


def edit_file_range(path, start_line, end_line, new, role="System"):
    target = safe_path(path)
    if target is None:
        return f"error: '{path}' is outside the workspace."
    if not target.exists() or not target.is_file():
        return f"error: file does not exist: {target}"
    try:
        original = target.read_text(encoding="utf-8")
    except OSError as exc:
        return f"error reading file: {exc}"
    lines = original.splitlines(keepends=True)
    start, end = int(start_line), int(end_line)
    if start < 1 or end < start or end > len(lines):
        return f"error: invalid line range {start}-{end}; file has {len(lines)} lines"
    snapshot = (ACTIVE_TRANSACTION or {}).get("files", {}).get(str(target))
    transaction_owned = bool(snapshot and not snapshot.get("existed"))
    span = end - start + 1
    if not transaction_owned and role in {"Builder", "Repairer"} and span > max(120, int(len(lines) * 0.6)):
        return "error: requested range is too broad for a pre-existing file; use smaller verified edits"
    replacement = str(new)
    if end < len(lines) and replacement and not replacement.endswith(("\n", "\r")):
        replacement += "\n"
    candidate = "".join(lines[:start - 1]) + replacement + "".join(lines[end:])
    validation = source_validation_error(target, candidate)
    if validation:
        return f"error: {validation}; edit rejected and file was not changed"
    note = "" if transaction_owned else backup(target)
    if note.startswith("error"):
        return note
    try:
        _transaction_capture(target)
        target.write_text(candidate, encoding="utf-8")
        return f"edited lines {start}-{end} in file: {target}{note}"
    except OSError as exc:
        return f"error writing file: {exc}"


def read_file(path):
    target = safe_path(path)
    if target is None:
        return f"error: '{path}' is outside the workspace."
    if not target.exists():
        return f"error: file does not exist: {target}"
    try:
        return target.read_text(encoding="utf-8")
    except OSError as exc:
        return f"error reading file: {exc}"


def backup_file(path):
    target = safe_path(path)
    if target is None or not target.exists():
        return "error: file does not exist or escapes workspace"
    return f"backup created for {target}{backup(target)}"


def coherent_rewrite_preflight(args):
    """Reject an obvious fragment before an optional full-draft rewrite.

    The adaptive path does not use a separate rewrite scheduler, but keeping
    this narrow guard protects callers that explicitly request a whole-draft
    recovery from accidentally replacing a large artifact with one function.
    """
    if not isinstance(args, dict):
        return "error: rewrite arguments must be an object; No file was changed"
    target = safe_path(args.get("path", ""))
    content = args.get("content")
    if target is None or content is None:
        return "error: rewrite path and content are required; No file was changed"
    if target.exists() and target.is_file():
        try:
            existing_lines = target.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return f"error: could not inspect rewrite target: {exc}; No file was changed"
        new_lines = str(content).splitlines()
        if len(existing_lines) >= 20 and len(new_lines) < max(3, int(len(existing_lines) * 0.4)):
            return "error: proposed rewrite appears to be a fragment of the existing artifact; No file was changed"
    return None


def list_files():
    try:
        hidden = {
            MEMORY_FILE, EXPERIMENT_FILE, EVIDENCE_DIR, RUNS_DIR, ".hivo", ".agent_backups",
            ".git", ".venv", "__pycache__", "node_modules",
        }
        names = [p.name for p in sorted(WORKSPACE.iterdir()) if p.name not in hidden and ".backup_" not in p.name]
        return "\n".join(names) if names else "(workspace is empty)"
    except OSError as exc:
        return f"error listing files: {exc}"


def run_file(path):
    target = safe_path(path)
    if target is None:
        return f"error: '{path}' is outside the workspace."
    if not target.exists():
        return f"error: file does not exist: {target}"
    ext = target.suffix.lower()
    try:
        if ext == ".py":
            cmd = [sys.executable, str(target)]
        elif ext == ".js":
            source = target.read_text(encoding="utf-8", errors="replace")
            if re.search(r"\b(?:document|localStorage|sessionStorage|navigator|requestAnimationFrame)\b|\bwindow\s*[.[]", source):
                return "[not_applicable] browser-target JavaScript must be verified in a browser with verify_web_app"
            cmd = ["node", str(target)]
        elif ext in (".cpp", ".cc"):
            exe = target.with_suffix(".out")
            build = subprocess.run(["g++", str(target), "-o", str(exe)], cwd=WORKSPACE,
                                   capture_output=True, text=True, timeout=30)
            if build.returncode != 0:
                return f"compile error:\n{build.stderr}"
            cmd = [str(exe)]
        elif ext in (".html", ".htm"):
            return json.dumps(
                verify_browser_application(
                    path, "run_file", evidence={"requested_from_node": path},
                ),
                ensure_ascii=False,
            )
        else:
            return f"error: unsupported file type for running: {ext}"
        result = subprocess.run(cmd, cwd=WORKSPACE, capture_output=True, text=True, timeout=30)
        output = (result.stdout + result.stderr).strip()
        return f"[exit_code={result.returncode}]\n{output or '(no output)'}"
    except subprocess.TimeoutExpired:
        return "error: execution timed out (30s limit)"
    except FileNotFoundError as exc:
        return f"error: required interpreter/compiler not found: {exc}"
    except Exception as exc:
        return f"error running file: {exc}"


def _validated_command_parts(command):
    lower = command.lower()
    if any(bad in lower for bad in DANGEROUS) or any(token in command for token in ("\n", "\r", "&&", "||", ";", "|", ">", "<")):
        return None, "dangerous commands and shell composition are not allowed"
    try:
        parts = shlex.split(command, posix=(os.name != "nt"))
        parts = [part.strip('"') for part in parts]
    except ValueError as exc:
        return None, f"could not parse command: {exc}"
    if not parts:
        return None, "empty command"
    executable = Path(parts[0]).stem.lower()
    allowed = {"python", "python3", "py", "node", "npm", "npx", "pytest", "git", "g++", "clang++", "tsc"}
    if executable not in allowed:
        return None, f"executable '{executable}' is not in the verification allowlist"
    if executable in {"python", "python3", "py"} and "-c" in parts:
        return None, "inline Python is not allowed"
    if executable == "node" and any(flag in parts for flag in ("-e", "--eval")):
        return None, "inline Node.js is not allowed"
    if executable == "git":
        subcommand = next((part for part in parts[1:] if not part.startswith("-")), "")
        if subcommand not in {"status", "diff", "log", "show", "ls-files", "rev-parse"}:
            return None, f"git subcommand '{subcommand}' is not read-only"
    if executable == "npm" and any(word in parts[1:] for word in ("install", "uninstall", "publish", "link")):
        return None, "package mutation is not allowed from run_command"
    if executable == "npx":
        requested = next((Path(part).stem.lower() for part in parts[1:] if not part.startswith("-")), "")
        if requested not in {"eslint", "tsc", "vitest", "jest", "playwright", "vite"}:
            return None, f"npx tool '{requested}' is not in the verification allowlist"
    for part in parts[1:]:
        if part.startswith("-") or "://" in part:
            continue
        candidate = Path(part)
        looks_like_path = candidate.is_absolute() or ".." in candidate.parts or "/" in part or "\\" in part
        if looks_like_path:
            resolved = candidate.resolve() if candidate.is_absolute() else (WORKSPACE / candidate).resolve()
            if not resolved.is_relative_to(WORKSPACE):
                return None, f"path argument escapes the workspace: {part}"
    return parts, None


def run_command(command):
    parts, error = _validated_command_parts(command)
    if error:
        return f"error: command refused: {error}"
    try:
        result = subprocess.run(parts, shell=False, cwd=WORKSPACE, capture_output=True, text=True, timeout=60)
        output = (result.stdout + result.stderr).strip()
        return f"[exit_code={result.returncode}]\n{output or '(no output)'}"
    except subprocess.TimeoutExpired:
        return "error: command timed out (60s limit)"
    except Exception as exc:
        return f"tool error: {exc}"


def tools_for_role(role, tool_policy=None):
    if role == "Falsifier":
        allowed = {"read_file", "read_file_range", "list_files", "run_file", "run_command", "verify_web_app"}
        return [tool for tool in TOOLS if tool["function"]["name"] in allowed]
    if role == "Repairer":
        allowed = {"edit_file", "edit_file_range", "read_file", "read_file_range", "list_files", "run_file", "run_command", "verify_web_app"}
        return [tool for tool in TOOLS if tool["function"]["name"] in allowed]
    if tool_policy == "coherent_rewrite":
        allowed = {"write_file", "read_file", "read_file_range", "list_files", "run_file", "run_command", "verify_web_app"}
        return [tool for tool in TOOLS if tool["function"]["name"] in allowed]
    return TOOLS


def _normalized_workspace_relative_path(raw_path):
    target = safe_path(raw_path)
    if target is None or WORKSPACE is None:
        return None
    try:
        return target.relative_to(Path(WORKSPACE).resolve()).as_posix().casefold()
    except (OSError, RuntimeError, ValueError):
        return None


def _stage3_mutation_guard(name, args):
    if name not in {"write_file", "edit_file", "edit_file_range"}:
        return None
    if not RUN.get("impact_planning_required") or RUN.get("project_mode") != EXISTING_PROJECT:
        return None
    plan = RUN.get("approved_change_plan")
    approval = RUN.get("plan_approval")
    if not stage3.approval_is_current(plan, approval):
        return (
            f"error: {PLAN_APPROVAL_REQUIRED}; existing-project mutation is read-only "
            "until the current plan hash is approved"
        )
    active = ACTIVE_TOOL_CONTRACT if isinstance(ACTIVE_TOOL_CONTRACT, dict) else {}
    if active.get("approved_plan_hash") != plan.get("plan_hash"):
        return f"error: {PLAN_APPROVAL_REQUIRED}; active Worker plan hash is stale"
    target = _normalized_workspace_relative_path((args or {}).get("path"))
    approved = {
        str(item).replace("\\", "/").casefold()
        for item in active.get("approved_targets", []) or []
    }
    inspect_only = {
        str(item).replace("\\", "/").casefold()
        for item in active.get("inspect_only_targets", []) or []
    }
    do_not_touch = {
        str(item).replace("\\", "/").casefold()
        for item in active.get("do_not_touch", []) or []
    }
    if (
        target is None or active.get("verification_only")
        or target in do_not_touch or target in inspect_only or target not in approved
    ):
        RUN["unapproved_scope_expansions"] = RUN.get("unapproved_scope_expansions", 0) + 1
        record_run_event(
            "unapproved_scope_expansion", target=target,
            approved_targets=sorted(approved), inspect_only_targets=sorted(inspect_only),
            do_not_touch=sorted(do_not_touch), plan_id=plan.get("plan_id"),
        )
        return (
            f"error: {UNAPPROVED_SCOPE_EXPANSION}; '{(args or {}).get('path')}' "
            "is not an approved mutation target for this plan node"
        )
    return None


def run_tool(name, args, role="System"):
    if role == "Falsifier" and name in {"write_file", "edit_file", "edit_file_range", "backup_file"}:
        return "error: Falsifier is read-only and may not modify files"
    if role == "Repairer" and name in {"write_file", "backup_file"}:
        return "error: Repairer may only make focused edits"
    issue = tool_argument_error(name, args)
    if issue:
        return issue
    stage3_issue = _stage3_mutation_guard(name, args)
    if stage3_issue:
        return stage3_issue
    if name == "write_file":
        return write_file(args["path"], args["content"], role=role)
    if name == "edit_file":
        return edit_file(args["path"], args["old"], args["new"], args.get("expected_replacements", 1))
    if name == "read_file_range":
        return read_file_range(args["path"], args.get("start_line", 1), args.get("end_line"))
    if name == "edit_file_range":
        return edit_file_range(args["path"], args["start_line"], args["end_line"], args["new"], role=role)
    if name == "read_file":
        return read_file(args["path"])
    if name == "backup_file":
        return backup_file(args["path"])
    if name == "list_files":
        return list_files()
    if name == "run_file":
        return run_file(args["path"])
    if name == "run_command":
        return run_command(args["command"])
    if name == "verify_web_app":
        active = ACTIVE_TOOL_CONTRACT or ACTIVE_CONTRACT or {}
        profile = infer_web_profile(str(active.get("goal") or "web"), active)
        target_evidence = {
            "requested_from_node": args["path"],
            "project_invariants": active.get("project_invariants", RUN.get("project_invariants", [])),
        }
        return json.dumps(
            verify_browser_application(
                args["path"], str(active.get("task_id") or "tool"),
                profile=profile, evidence=target_evidence,
            ),
            ensure_ascii=False,
        )
    return f"unknown tool: {name}"


# ---------------------------------------------------------------------------
# MEMORY / METRICS / EVENTS
# ---------------------------------------------------------------------------

def get_memory_store():
    global MEMORY_STORE
    if WORKSPACE is None:
        return None
    expected = (WORKSPACE / ".hivo" / "memory.sqlite3").resolve()
    if MEMORY_STORE is None or MEMORY_STORE.db_path.resolve() != expected:
        MEMORY_STORE = MemoryStore(WORKSPACE)
    return MEMORY_STORE


def load_memory():
    store = get_memory_store()
    return {
        "workspace": str(WORKSPACE),
        "memory_db": str(store.db_path) if store else "",
        "recent_files": store.recent_files() if store else [],
        "operations": [],
        "last_error": None,
        "resume_snapshot": store.latest_resumable_run(exclude_run_id=RUN_ID or None) if store else None,
    }


def relevant_memory_context(query, role="Builder", memory=None, max_chars=MAX_MEMORY_CONTEXT_CHARS):
    store = get_memory_store()
    if not store or max_chars <= 0:
        return ""
    try:
        verified = store.context_for(query, max_items=5, max_chars=max_chars)
        return verified[:max_chars]
    except Exception as exc:
        print(f"[WARN] could not retrieve durable memory: {exc}")
        return ""


def tool_result_failed(result):
    return evidence_result_failed(result)


def update_memory(memory, tool_name, tool_args, result, role=None, task_id=None):
    path_arg = tool_args.get("path") if isinstance(tool_args, dict) else None
    if path_arg:
        memory["recent_files"] = [path_arg] + [x for x in memory.get("recent_files", []) if x != path_arg][:9]
    if tool_name in {"run_file", "run_command", "verify_web_app"}:
        memory["last_error"] = str(result)[:1200] if tool_result_failed(result) else None
    store = get_memory_store()
    if store:
        try:
            store.record_event(
                run_id=RUN_ID or None, task_id=task_id, role=role, tool=tool_name,
                target=str(path_arg or tool_args.get("command") or ""),
                status="failed" if tool_result_failed(result) else "succeeded",
                content=str(result), details={"model": MODEL},
            )
            if role == "Builder" and path_arg and not tool_result_failed(result):
                if tool_name == "write_file":
                    store.mark_model_artifact(path_arg, RUN_ID or None)
                elif tool_name in {"edit_file", "edit_file_range"}:
                    store.refresh_unverified_model_artifact(path_arg, RUN_ID or None)
            memory["recent_files"] = store.recent_files()
        except Exception as exc:
            print(f"[WARN] memory event failed: {exc}")
    return memory


def _source_hash():
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return "unavailable"


def compact_text(text, limit=120):
    one = " ".join(str(text).split())
    return one if len(one) <= limit else one[:max(0, limit - 3)] + "..."


def bounded_list(values, max_items=8, item_chars=500):
    return [compact_text(value, item_chars) for value in list(values or [])[:max_items]]


def estimate_context_tokens(messages):
    chars = 0
    for message in messages:
        chars += len(str(message.get("role", ""))) + len(str(message.get("content", "")))
        chars += len(json.dumps(message.get("tool_calls", []), ensure_ascii=False))
    return max(1, int(chars / 4))


def record_run_event(kind, **payload):
    """Persist orchestration facts only. Never persist model chain-of-thought."""
    if WORKSPACE is None or not RUN_ID:
        return
    try:
        run_dir = WORKSPACE / RUNS_DIR
        run_dir.mkdir(parents=True, exist_ok=True)
        safe = {
            "time": datetime.now().isoformat(timespec="milliseconds"), "run_id": RUN_ID, "kind": kind,
        }
        for key, value in payload.items():
            if key in {"messages", "thinking", "chain_of_thought", "reasoning"}:
                continue
            if key == "raw_content":
                safe[key] = compact_text(value, 500)
            else:
                safe[key] = value
        with (run_dir / f"{RUN_ID}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def new_metrics(mode):
    host_preflight = HOST_PREFLIGHT_RESULT if isinstance(HOST_PREFLIGHT_RESULT, dict) else {}
    host_preflight_report = host_preflight.get("report") if isinstance(host_preflight.get("report"), dict) else {}
    return {
        "run_id": RUN_ID, "source_sha256": _source_hash(), "mode": mode, "model": MODEL,
        "model_capabilities": sorted(MODEL_CAPABILITIES),
        "role_models": {role: MODEL for role in MODEL_POLICY.role_models()},
        "host_preflight_status": host_preflight.get("status"),
        "host_preflight_id": host_preflight.get("preflight_id"),
        "host_preflight_duration_seconds": host_preflight_report.get("duration_seconds"),
        "host_preflight_report_path": host_preflight.get("marker_path"),
        # v16 requirement/clarification accounting is kept separate from
        # Builder, Repairer, and Falsifier work.  ``clarification_questions``
        # remains as a compatibility alias for older run consumers.
        "clarification_questions": 0,
        "source_requirements_extracted": 0,
        "source_requirements_retained": 0,
        "source_requirements_mapped": 0,
        "source_requirements_unmapped": 0,
        "source_requirement_retention_numerator": 0,
        "source_requirement_retention_denominator": 0,
        "source_requirement_retention_rate_numerator": 0,
        "source_requirement_retention_rate_denominator": 0,
        "source_requirement_retention_rate": 1.0,
        "source_requirement_items_truncated": 0,
        "user_clarification_rounds": 0,
        "user_clarification_questions": 0,
        "user_clarification_answers": 0,
        "user_confirmed_requirements": 0,
        "optional_clarifications_skipped": 0,
        "blocking_clarifications_required": 0,
        "requirement_extractor_calls": 0,
        "clarifier_calls": 0,
        "clarification_terminal_state": None,
        # v17 project-understanding and temporary Task Brain accounting.
        "project_mode_new": 0,
        "project_mode_existing": 0,
        "repository_reconnaissance_runs": 0,
        "repository_reconnaissance_skipped": 0,
        "repository_searches": 0,
        "repository_files_considered": 0,
        "repository_files_inspected": 0,
        "repository_evidence_records": 0,
        "repository_evidence_candidates": 0,
        "repository_evidence_validated": 0,
        "repository_evidence_deduplicated": 0,
        "repository_evidence_selected": 0,
        "repository_evidence_rejected": 0,
        "repository_evidence_rejected_duplicates": 0,
        "repository_evidence_truncated_valid": 0,
        "repo_grounded_clarification_questions": 0,
        "task_brains_created": 0,
        "task_brain_creation_failures": 0,
        "recon_agent_calls": 0,
        "task_brain_compiler_calls": 0,
        # v18 evidence-grounded impact planning and approval accounting.
        "impact_maps_created": 0,
        "impact_map_failures": 0,
        "impact_candidates": 0,
        "impact_supported": 0,
        "impact_preservation_only": 0,
        "impact_unknown_surface_references": 0,
        "impact_unknown_impact_seed_references": 0,
        "impact_surface_evidence_mismatches": 0,
        "impact_invented_existing_paths_rejected": 0,
        "impact_invented_interfaces_rejected": 0,
        "impact_invalid_optional_fields_rejected": 0,
        "impact_invalid_requirement_references_rejected": 0,
        "impact_seed_surface_binding_conflicts": 0,
        "impact_planning_surfaces_selected": 0,
        "impact_planning_surfaces_serialized": 0,
        "impact_planning_surfaces_dropped": 0,
        "impact_seed_decisions_received": 0,
        "impact_seed_decisions_validated": 0,
        "impact_seed_decisions_rejected": 0,
        "impact_planning_context_incomplete": 0,
        "impact_challenger_context_incomplete": 0,
        "impact_challenges": 0,
        "impact_challenges_validated": 0,
        "impact_challenges_rejected": 0,
        "change_plans_created": 0,
        "change_plan_gate_failures": 0,
        "plan_nodes": 0,
        "plan_requirements_covered": 0,
        "plan_requirements_unassigned": 0,
        "plan_approval_required": 0,
        "plan_approval_granted": 0,
        "plan_approval_rejected": 0,
        "unapproved_scope_expansions": 0,
        "impact_planner_calls": 0,
        "impact_challenger_calls": 0,
        "impact_plan_revision_calls": 0,
        "plan_approval_requests": 0,
        "control_flow": [],
        "specification_expansions": 0,
        "specification_expansion_failures": 0,
        "brain_projections_created": 0,
        "mission_compilations": 0,
        "mission_compilation_failures": 0,
        "worker_missions_executed": 0,
        "tasks_created": 0, "leaf_tasks": 0, "splits": 0, "re_splits": 0, "max_depth": 0,
        # ``re_splits`` is the number of controller events.  These fields are
        # outcome metrics over distinct failed nodes, so a partial child
        # rescue is visible even when parent integration still fails.
        "failed_nodes_resplit": 0,
        "resplit_nodes_with_any_verified_child": 0,
        "resplit_nodes_fully_recovered": 0,
        "granularity_rescue_rate": 0.0,
        "terminal_too_broad_nodes": 0,
        "decomposition_backtracks": 0,
        "alternative_decompositions": 0,
        "alternative_decomposition_rescues": 0,
        "decomposition_backtrack_rescue_rate": None,
        "strategy_searches": 0,
        "strategy_generation_failures": 0,
        "alternate_strategies_attempted": 0,
        "strategy_rescues": 0,
        "strategy_search_failures": 0,
        "strategy_rescue_rate": None,
        "capability_floor_nodes": 0,
        "capability_floor_guard_blocks": 0,
        "capability_floor_routed_to_strategy": 0,
        "execution_budget_exhaustions": 0,
        "budget_exhaustion_routed_to_scope": 0,
        "budget_exhaustion_routed_to_strategy": 0,
        "budget_exhaustion_routed_to_dependency": 0,
        "budget_exhaustion_routed_to_other": 0,
        "root_verified": False,
        "verified_nodes": 0, "failed_nodes": 0, "integration_failures": 0,
        "max_depth_failures": 0,
        "failure_diagnosis_counts": {},
        "project_invariants": [],
        "integration_preflight_checks": 0,
        "integration_preflight_failures": 0,
        "integration_conflicts_detected": 0,
        "integration_conflicts_resolved": 0,
        "parent_integrations_attempted": 0,
        "parent_integrations_passed": 0,
        "parent_integrations_failed": 0,
        "parent_integrations_recovered": 0,
        "integration_preflight_conflicts": 0,
        "invariant_violations_detected": 0,
        "integration_success_rate": 0.0,
        "integration_milestone_runs": 0,
        "integration_milestone_steps": 0,
        "integration_tasks_created": 0,
        "integration_splits": 0,
        "integration_resplits": 0,
        "integration_verified_nodes": 0,
        "integration_too_broad_nodes": 0,
        "integration_granularity_rescues": 0,
        "preflight_blocking_conflicts_detected": 0,
        "preflight_blocking_conflicts_resolved": 0,
        "integration_conflict_resolution": None,
        "repairer_calls": 0, "falsifier_calls": 0, "falsifier_detected_failures": 0,
        "planner_structured_retries": 0, "model_calls": 0, "tool_calls": 0,
        "builder_calls": 0, "predictor_calls": 0, "challenger_calls": 0,
        "quality_reviews": 0, "invalid_tool_calls": 0,
        # Retained as zero-valued historical fields; the experimental path no
        # longer hides work inside stage continuation/rewrite schedulers.
        "stage_continuations": 0, "coherent_rewrite_recoveries": 0,
        "browser_checks": 0,
        "browser_entrypoint_resolutions": 0,
        "browser_entrypoint_resolution_failures": 0,
        "browser_checks_skipped_for_syntax_failure": 0,
        "verification_failures": 0, "task_too_broad_count": 0,
        "mutation_failures_recorded": 0, "mutation_recovery_packets_emitted": 0,
        "provider_cpu_fallbacks": 0, "provider_execution": "gpu_or_auto",
        "ollama_http_200": 0, "ollama_tool_call_responses": 0,
        "ollama_thinking_responses": 0, "ollama_terminal_empty_responses": 0,
        "ollama_incomplete_responses": 0, "ollama_retry_count": 0,
        "ollama_transport_failures": 0, "ollama_worker_failures": 0,
        "ollama_timeout_failures": 0, "ollama_malformed_responses": 0,
        "peak_estimated_context_tokens": 0, "peak_leaf_context_tokens": 0,
        "average_leaf_context_tokens": 0.0, "_leaf_context_samples": [],
        "elapsed_seconds": 0.0, "status": "unknown",
    }


def reset_run(mode):
    global RUN, TASKS, ROLE_STATUS, DASHBOARD, RUN_STARTED, RUN_ID
    global ACTIVE_TRANSACTION, LAST_COMMITTED_TRANSACTION, ACTIVE_CONTRACT, ACTIVE_TOOL_CONTRACT, FORCE_CPU_FOR_RUN
    global VISION_ENABLED_FOR_RUN, VISION_ERROR, PREFLIGHT_CONFLICT_STATE
    RUN_ID = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    ACTIVE_TRANSACTION = None
    LAST_COMMITTED_TRANSACTION = None
    ACTIVE_CONTRACT = None
    ACTIVE_TOOL_CONTRACT = None
    FORCE_CPU_FOR_RUN = False
    RUN = new_metrics(mode)
    TASKS = {}
    PREFLIGHT_CONFLICT_STATE = {"registry": {}, "active": set(), "sequence": 0}
    ROLE_STATUS = {"Coordinator": "active", "Builder": "waiting", "Falsifier": "waiting",
                   "Repairer": "unused", "Browser": "waiting", "Quality Review": "waiting"}
    DASHBOARD = {"mode": mode, "context": 0, "active_role": "Coordinator", "active_task": "ROOT",
                 "action": "starting", "tool": "-", "event": f"[MODE] {mode}"}
    RUN_STARTED = time.time()
    VISION_ENABLED_FOR_RUN = ENABLE_VISION and bool(VISION_MODEL)
    VISION_ERROR = None
    record_run_event(
        "run_started", mode=mode, model=MODEL, source_sha256=RUN["source_sha256"],
        host_preflight_status=RUN.get("host_preflight_status"),
        host_preflight_id=RUN.get("host_preflight_id"),
    )


def compact_task_tree():
    result = []
    for task_id, task in TASKS.items():
        entry = {
            "task_id": task_id, "parent_id": task.get("parent"), "depth": task.get("depth", 0),
            "kind": task.get("kind", "implementation"),
            "goal": compact_text(task.get("goal", ""), 500), "status": task.get("status", "unknown"),
            "summary": compact_text(task.get("summary", ""), MAX_NODE_SUMMARY_CHARS),
            "verification_status": task.get("verification_status", "unknown"),
            "children": list(task.get("children", [])),
            "changed_files": bounded_list(task.get("changed_files", []), 12, 140),
        }
        # Keep the failed attempt and its evidence beside the final status.
        # This is what makes a recovered node auditable instead of making the
        # original failure disappear when the parent eventually passes.
        if task.get("initial_result") is not None:
            entry["initial_result"] = task.get("initial_result")
            entry["initial_status"] = task.get("initial_status")
            entry["initial_failure_type"] = task.get("initial_failure_type")
            entry["initial_failure_evidence"] = task.get("initial_failure_evidence", [])
            entry["initial_failure_diagnosis"] = task.get("initial_failure_diagnosis")
        if task.get("fit_before_execution") is not None:
            entry["fit_before_execution"] = task.get("fit_before_execution")
        if task.get("execution_outcome") is not None:
            entry["execution_outcome"] = task.get("execution_outcome")
        if task.get("execution_budget_exhausted"):
            entry["execution_budget_exhausted"] = True
        if task.get("repair_history"):
            entry["repair_history"] = task.get("repair_history", [])[-MAX_REPAIRS_PER_LEAF:]
        if task.get("budget_exhaustion_routing"):
            entry["budget_exhaustion_routing"] = task.get("budget_exhaustion_routing")
        if task.get("attempts"):
            entry["attempts"] = task.get("attempts", [])
        if task.get("failure_diagnosis") is not None:
            entry["failure_diagnosis"] = task.get("failure_diagnosis")
        if task.get("resplit") is not None:
            entry["resplit"] = task.get("resplit")
        if task.get("decomposition_history"):
            entry["decomposition_history"] = task.get("decomposition_history", [])[-3:]
        if task.get("failed_decompositions"):
            entry["failed_decompositions"] = task.get("failed_decompositions", [])[-3:]
        if task.get("decomposition_alternatives"):
            entry["decomposition_alternatives"] = task.get("decomposition_alternatives", [])[-3:]
        if task.get("terminal_too_broad") is not None:
            entry["terminal_too_broad"] = task.get("terminal_too_broad")
        if task.get("decomposition_search_exhausted"):
            entry["decomposition_search_exhausted"] = True
        if task.get("strategy_search") is not None:
            entry["strategy_search"] = task.get("strategy_search")
        if task.get("strategy_attempts"):
            entry["strategy_attempts"] = task.get("strategy_attempts", [])[-MAX_STRATEGY_ALTERNATIVES:]
        if task.get("capability_floor_blocked_by"):
            entry["capability_floor_blocked_by"] = task.get("capability_floor_blocked_by")
            entry["capability_floor_guard_evidence"] = task.get("capability_floor_guard_evidence", {})
        if isinstance(task.get("failure_diagnosis"), dict) and task["failure_diagnosis"].get(
            "capability_floor_evidence"
        ):
            entry["capability_floor_evidence"] = task["failure_diagnosis"].get(
                "capability_floor_evidence"
            )
        if task.get("integration_manifest") is not None:
            entry["integration_manifest"] = task.get("integration_manifest")
        if task.get("integration_preflight") is not None:
            entry["integration_preflight"] = task.get("integration_preflight")
        if task.get("integration_outcome") is not None:
            entry["integration_outcome"] = task.get("integration_outcome")
        if task.get("kind") == "integration":
            entry["integration_conflicts"] = [
                _normalize_integration_conflict(item)
                for item in task.get("integration_conflicts", [])[:MAX_INTEGRATION_MANIFEST_ITEMS]
            ]
            entry["integration_resplit_attempts"] = int(task.get("integration_resplit_attempts", 0) or 0)
            entry["integration_too_broad"] = bool(task.get("integration_too_broad"))
        result.append(entry)
    return sorted(result, key=lambda item: (item["depth"], item["task_id"]))


def print_task_tree():
    """Render the compact ledger as a readable research trace."""
    if not TASKS:
        return

    try:
        "├── ".encode(getattr(sys.stdout, "encoding", None) or "utf-8")
        middle_branch, last_branch, vertical = "├── ", "└── ", "│   "
    except (LookupError, UnicodeEncodeError):
        middle_branch, last_branch, vertical = "|-- ", "`-- ", "|   "

    def status_label(task):
        status = str(task.get("status", "pending")).casefold()
        return {"done": "PASS", "failed": "FAIL", "too_broad": "TOO_BROAD",
                "budget_exhausted": EXECUTION_BUDGET_EXHAUSTED,
                "running": "RUN", "pending": "PENDING"}.get(status, status.upper())

    lines = ["\n[TASK TREE]"]

    def visit(task_id, prefix="", branch="", is_last=False, root=False):
        task = TASKS.get(task_id)
        if not task:
            return
        goal = compact_text(task.get("goal", ""), 92)
        label = f"{task_id} {goal} {status_label(task)}"
        lines.append(label if root else prefix + branch + label)
        children = list(task.get("children", []))
        for index, child_id in enumerate(children):
            last = index == len(children) - 1
            child_prefix = prefix if root else prefix + ("    " if is_last else vertical)
            visit(child_id, child_prefix, last_branch if last else middle_branch, last)

    visit("ROOT", root=True)
    print("\n".join(lines))


def finish_metrics(status):
    samples = RUN.pop("_leaf_context_samples", [])
    RUN["average_leaf_context_tokens"] = round(sum(samples) / len(samples), 2) if samples else 0.0
    RUN["elapsed_seconds"] = round(time.time() - RUN_STARTED, 2)
    RUN["status"] = status
    recompute_resplit_metrics()
    recompute_search_metrics()
    recompute_integration_metrics()
    RUN["task_tree"] = compact_task_tree()
    RUN["node_diagnosis"] = build_node_diagnosis()
    if WORKSPACE is not None:
        try:
            with (WORKSPACE / EXPERIMENT_FILE).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(RUN, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass
    store = get_memory_store()
    if store and RUN_ID:
        try:
            store.finish_run(RUN_ID, status)
        except Exception:
            pass
    print_task_tree()
    print_resplit_metrics()
    print_search_metrics()
    print_integration_metrics()
    print_node_diagnosis()
    print("\n[RUN METRICS]")
    for key, value in RUN.items():
        if key != "task_tree":
            print(f"{key}: {value}")


def event(text, role=None, task=None, action=None, tool=None):
    if role:
        DASHBOARD["active_role"] = role
    if task:
        DASHBOARD["active_task"] = task
    if action:
        DASHBOARD["action"] = action
    if tool:
        DASHBOARD["tool"] = tool
    DASHBOARD["event"] = text
    print(text)
    record_run_event("status", text=text, role=role, task=task, action=action, tool=tool)


def update_task_ledger(task):
    store = get_memory_store()
    if not store or not RUN_ID:
        return
    try:
        store.upsert_task(
            RUN_ID, str(task["id"]), str(task.get("goal", "")), str(task.get("status", "pending")),
            summary=compact_text(task.get("summary", ""), MAX_NODE_SUMMARY_CHARS),
            parent_id=task.get("parent"), stage_index=None,
        )
    except Exception:
        pass


def remember_verified_outcome(task, contract, summary, changed_files):
    store = get_memory_store()
    if not store:
        return
    try:
        store.add_note(
            f"Verified task completed. Goal: {compact_text(task.get('goal',''), 500)}. "
            f"Result: {compact_text(summary, 500)}. Changed files: {', '.join(changed_files[:20]) or '(none)'}",
            kind="verified_outcome", scope=classify_project(contract), verified=True, importance=0.8,
            run_id=RUN_ID or None, task_id=task.get("id"),
        )
        store.mark_artifacts_verified(changed_files, RUN_ID or None)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# BOUNDED REPOSITORY RECONNAISSANCE
# ---------------------------------------------------------------------------

_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".hivo",
              ".agent_backups", EVIDENCE_DIR, RUNS_DIR}
_LANGUAGE_BY_SUFFIX = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript", ".html": "html",
    ".css": "css", ".json": "json", ".toml": "toml", ".yaml": "yaml", ".yml": "yaml",
    ".cpp": "cpp", ".cc": "cpp", ".c": "c", ".java": "java", ".go": "go", ".rs": "rust",
}
_CONFIG_NAMES = {"pyproject.toml", "requirements.txt", "package.json", "package-lock.json", "vite.config.js",
                 "vite.config.ts", "tsconfig.json", "pytest.ini", "setup.cfg", "setup.py", "Cargo.toml", "go.mod"}
_ENTRY_NAMES = {"index.html", "main.py", "app.py", "server.py", "main.js", "main.ts", "src/main.tsx", "src/main.jsx"}


def inspect_repository(workspace=None, max_files=MAX_RECON_FILES, max_depth=MAX_RECON_DEPTH, max_chars=MAX_RECON_CHARS):
    """Return a deterministic, deliberately shallow repository snapshot.

    This is reconnaissance, not indexing.  It records names, sizes, obvious
    entrypoints, configs, tests, and suffix-derived languages; it never reads
    source contents and never follows the ignored/generated directories.
    """
    root = Path(workspace or WORKSPACE).resolve()
    max_files = max(0, int(max_files))
    max_depth = max(0, int(max_depth))
    max_chars = max(256, int(max_chars))
    files = []
    languages = set()
    configs, tests, entrypoints = [], [], []
    truncated = False
    for current, dirs, names in os.walk(root):
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(root).parts)
        except ValueError:
            continue
        dirs[:] = [name for name in sorted(dirs) if name not in _SKIP_DIRS and depth < max_depth]
        for name in sorted(names):
            path = current_path / name
            try:
                relative = path.relative_to(root).as_posix()
                size = path.stat().st_size
            except OSError:
                continue
            if relative.startswith((".agent_", ".hivo/")):
                continue
            suffix = path.suffix.lower()
            if suffix in _LANGUAGE_BY_SUFFIX:
                languages.add(_LANGUAGE_BY_SUFFIX[suffix])
            if name in _CONFIG_NAMES:
                configs.append(relative)
            if "test" in name.lower() or any(part.lower() in {"test", "tests"} for part in path.parts):
                tests.append(relative)
            if name in _ENTRY_NAMES or relative in _ENTRY_NAMES:
                entrypoints.append(relative)
            if len(files) < max_files:
                files.append({"path": relative, "size": size})
            else:
                truncated = True
                dirs[:] = []
                break
        if len(files) >= max_files or truncated:
            if len(files) >= max_files:
                truncated = True
            break

    snapshot = {
        "files": files, "languages": sorted(languages), "configs": configs[:20], "tests": tests[:30],
        "entrypoints": entrypoints[:20], "truncated": truncated, "limits": {
            "max_files": max_files, "max_depth": max_depth, "max_chars": max_chars,
        },
    }

    # Apply the serialized cap to every field, not just the file list.  This
    # keeps a test/config-heavy repository from overflowing the planner prompt.
    def serialized_size():
        return len(json.dumps(snapshot, ensure_ascii=False))

    fields = ("files", "tests", "configs", "entrypoints", "languages")
    while serialized_size() > max_chars:
        removed = False
        for field in fields:
            values = snapshot.get(field) or []
            if values:
                values.pop()
                snapshot["truncated"] = True
                removed = True
                break
        if not removed:
            break
    return snapshot


def repository_hints(snapshot, scope_hint=None, max_chars=2500):
    snapshot = snapshot or {}
    scope_words = {word.casefold() for value in (scope_hint or []) for word in re.findall(r"[\w.-]{3,}", str(value))}
    selected = []
    for item in snapshot.get("files", []):
        path = item["path"]
        if not scope_words or any(word in path.casefold() for word in scope_words):
            selected.append(item)
    if scope_words and not selected:
        selected = snapshot.get("files", [])[:25]
    projection = {
        "languages": snapshot.get("languages", []), "configs": snapshot.get("configs", []),
        "tests": snapshot.get("tests", [])[:15], "entrypoints": snapshot.get("entrypoints", []),
        "files": selected[:35], "truncated": snapshot.get("truncated", False),
    }
    return json.dumps(projection, ensure_ascii=False)[:max_chars]


# ---------------------------------------------------------------------------
# MODEL CALLS / STRUCTURED RETRIES
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a terminal coding agent working ONLY inside one selected workspace. Never access paths outside it. "
    "Inspect current files before editing. Use write_file only for new files or explicitly permitted unverified "
    "model-owned drafts; use focused edit_file/edit_file_range for existing files. Keep changes scoped to CURRENT NODE. "
    "Before stopping, run at least one relevant executable verification covering the current node; a file-write-only "
    "result is incomplete. Use tests, commands, or browser checks before claiming completion. For browser games expose "
    f"{GAME_BRIDGE_EXPRESSION} with getState(), start(), restart(), move(direction), plus forceCollision/forceCollect/forceWin "
    "when those mechanics are requested. If tools or environment fail, report truthfully. Do not reveal hidden reasoning."
)
ROLE_SYSTEM_PROMPTS = {
    "Builder": SYSTEM_PROMPT,
    "Repairer": SYSTEM_PROMPT + " You are Repairer: fix only defects demonstrated by current deterministic failure evidence.",
    "Falsifier": (
        "You are a read-only adversarial verifier inside one workspace. Actively try to produce executable evidence that "
        "the claimed solution is wrong. You may read files and run tests/commands/browser checks, but never modify files. "
        "Use at most two cheap edge-case probes when useful. Prefer the exposed Python/test/browser verification tools; "
        "do not use echo, shell composition, or commands that are unavailable on the host. Narrative suspicion alone is "
        "advisory. Do not reveal hidden reasoning."
    ),
}


def normalize_ollama_tool_calls(raw_calls):
    """Normalize Ollama/OpenAI-compatible tool-call envelopes for the loop."""
    if isinstance(raw_calls, dict):
        raw_calls = [raw_calls]
    if not isinstance(raw_calls, list):
        return []
    normalized = []
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            continue
        function = raw_call.get("function")
        if not isinstance(function, dict):
            function = {}
        name = function.get("name") or raw_call.get("name")
        arguments = function.get("arguments") if "arguments" in function else raw_call.get("arguments", {})
        if name:
            normalized.append({"function": {"name": str(name), "arguments": arguments}})
    return normalized


def normalize_ollama_response(body, status_code=200, raw_text=""):
    """Return an actionable assistant message plus non-secret envelope diagnostics.

    Gemma commonly returns ``message.content == ""`` with a populated
    ``message.tool_calls``.  Thinking is measured but never copied into the
    returned conversation or persisted run records.
    """
    body = body if isinstance(body, dict) else {}
    source = body.get("message")
    if not isinstance(source, dict):
        source = {}
        for key in ("role", "content", "thinking", "reasoning", "tool_calls"):
            if key in body:
                source[key] = body[key]
        if "response" in body and "content" not in source:
            source["content"] = body.get("response")
    content = source.get("content", "")
    if content is None:
        content = ""
    elif not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, default=str)
    tool_calls = normalize_ollama_tool_calls(source.get("tool_calls", body.get("tool_calls")))
    thinking = source.get("thinking", body.get("thinking", ""))
    reasoning = source.get("reasoning", body.get("reasoning", ""))
    diagnostics = {
        "http_status": int(status_code),
        "body_chars": len(str(raw_text or "")),
        "top_keys": sorted(str(key) for key in body),
        "message_keys": sorted(str(key) for key in source),
        "content_chars": len(content),
        "thinking_chars": len(str(thinking or "")),
        "reasoning_chars": len(str(reasoning or "")),
        "tool_calls_count": len(tool_calls),
        "done": body.get("done"),
        "done_reason": body.get("done_reason"),
        "has_error": bool(body.get("error")),
    }
    message = {"role": str(source.get("role") or "assistant"), "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message, diagnostics


def ollama_response_summary(diagnostics):
    """Compact safe diagnostics; never include content or hidden reasoning."""
    fields = {
        key: diagnostics.get(key)
        for key in ("http_status", "top_keys", "message_keys", "content_chars", "thinking_chars",
                    "reasoning_chars", "tool_calls_count", "done", "done_reason", "has_error", "body_chars")
        if key in diagnostics
    }
    return compact_text(json.dumps(fields, ensure_ascii=False), 1200)


def ollama_failure_signals(text):
    """Classify transport/runner failures without conflating them with empty replies."""
    lower = str(text or "").casefold()
    worker = any(marker in lower for marker in (
        "cuda error", "cuda out of memory", "out of memory", "failed to allocate",
        "llama-server process has terminated", "llama runner process has terminated",
        "runner process has terminated", "gpu error", "gpu out of memory",
    ))
    timeout = any(marker in lower for marker in (
        "timed out", "timeout", "deadline exceeded", "context deadline",
    ))
    transient = worker or timeout or any(marker in lower for marker in (
        "connection reset", "broken pipe", "eof", "temporarily unavailable",
    ))
    return {"worker": worker, "timeout": timeout, "transient": transient}


def record_ollama_failure(text):
    signals = ollama_failure_signals(text)
    if signals["worker"]:
        RUN["ollama_worker_failures"] = RUN.get("ollama_worker_failures", 0) + 1
    if signals["timeout"]:
        RUN["ollama_timeout_failures"] = RUN.get("ollama_timeout_failures", 0) + 1
    return signals


def ask_ollama(messages, tools=TOOLS, response_format=None, temperature=None, think=False,
               provider_retries=None, model_override=None, role="Builder"):
    global FORCE_CPU_FOR_RUN
    requested_model = model_override or MODEL
    try:
        MODEL_POLICY.validate(requested_model)
    except ValueError as exc:
        raise ProviderError(str(exc)) from exc
    context_window = MODEL_POLICY.context_window(role)
    if FORCE_CPU_FOR_RUN:
        context_window = min(context_window, 8192)
    provider_messages = compact_messages(
        messages, max_chars=int(context_window * (1.25 if FORCE_CPU_FOR_RUN else 1.5)), keep_recent=4
    )
    estimate = estimate_context_tokens(provider_messages)
    RUN["peak_estimated_context_tokens"] = max(RUN.get("peak_estimated_context_tokens", 0), estimate)
    DASHBOARD["context"] = estimate
    payload = {
        "model": requested_model, "messages": provider_messages, "stream": False, "keep_alive": "10m",
        "options": {
            "num_ctx": context_window,
            "num_predict": {"Builder": 4096, "Repairer": 3072, "Falsifier": 1536,
                            "Coordinator": 1536, "Quality": 1536, "Specifier": 1536,
                            "MissionCompiler": 1536, "Clarifier": 1536,
                            "RequirementExtractor": 1536, "ReconAgent": 1024,
                            "TaskBrainCompiler": 1024, "ImpactPlanner": 1536,
                            "ImpactChallenger": 1280, "ImpactPlanReviser": 1536}.get(role, 2048),
            "temperature": MODEL_POLICY.temperature(role) if temperature is None else temperature,
            "seed": 0,
        },
        "think": bool(think),
    }
    if tools is not None:
        payload["tools"] = tools
    if response_format is not None:
        payload["format"] = response_format
    if FORCE_CPU_FOR_RUN:
        payload["options"]["num_gpu"] = 0
        payload["options"]["num_predict"] = min(payload["options"]["num_predict"], 3072)
    retry_limit = MAX_PROVIDER_RETRIES if provider_retries is None else max(0, int(provider_retries))
    last_error = "unknown provider error"
    for attempt in range(retry_limit + 1):
        RUN["model_calls"] += 1
        record_run_event("model_request", role=role, attempt=attempt + 1,
                         structured=bool(response_format), context_tokens=estimate,
                         num_ctx=context_window, stream=False, think=bool(think))
        try:
            response = http_post_json(OLLAMA_URL, timeout=OLLAMA_TIMEOUT_SECONDS, payload=payload)
        except HttpTransportError as exc:
            response = None
            last_error = f"could not reach Ollama at {OLLAMA_URL}: {exc}"
            RUN["ollama_transport_failures"] = RUN.get("ollama_transport_failures", 0) + 1
            signals = record_ollama_failure(last_error)
        if response is not None and response.status_code == 200:
            try:
                body = response.json()
            except (ValueError, TypeError) as exc:
                RUN["ollama_malformed_responses"] = RUN.get("ollama_malformed_responses", 0) + 1
                last_error = f"invalid response from model: {exc}"
            else:
                RUN["ollama_http_200"] = RUN.get("ollama_http_200", 0) + 1
                clean, diagnostics = normalize_ollama_response(body, response.status_code, response.text)
                record_run_event("model_response_shape", role=role, attempt=attempt + 1,
                                 **diagnostics)
                if diagnostics["tool_calls_count"] or not diagnostics["content_chars"] or diagnostics["thinking_chars"]:
                    print(f"[OLLAMA SHAPE] {role} {ollama_response_summary(diagnostics)}")
                if isinstance(body, dict) and body.get("error"):
                    error_text = compact_text(body.get("error"), 500)
                    last_error = f"Ollama returned HTTP 200 with an error field: {error_text}"
                    signals = record_ollama_failure(last_error)
                elif diagnostics["tool_calls_count"]:
                    RUN["ollama_tool_call_responses"] = RUN.get("ollama_tool_call_responses", 0) + 1
                    if diagnostics["thinking_chars"]:
                        RUN["ollama_thinking_responses"] = RUN.get("ollama_thinking_responses", 0) + 1
                    record_run_event("model_response", role=role, tool_names=[
                        c.get("function", {}).get("name") for c in clean.get("tool_calls", [])
                    ], response_shape=ollama_response_summary(diagnostics))
                    return clean
                elif diagnostics["content_chars"]:
                    if diagnostics["thinking_chars"]:
                        RUN["ollama_thinking_responses"] = RUN.get("ollama_thinking_responses", 0) + 1
                    record_run_event("model_response", role=role, tool_names=[],
                                     response_shape=ollama_response_summary(diagnostics))
                    return clean
                else:
                    if diagnostics["thinking_chars"]:
                        RUN["ollama_thinking_responses"] = RUN.get("ollama_thinking_responses", 0) + 1
                    done_reason = str(diagnostics.get("done_reason") or "").casefold()
                    terminal_after_tool = (
                        diagnostics.get("done") is True
                        and done_reason in {"stop", "tool_calls"}
                        and bool(messages)
                        and isinstance(messages[-1], dict)
                        and messages[-1].get("role") == "tool"
                    )
                    if terminal_after_tool:
                        RUN["ollama_terminal_empty_responses"] = RUN.get("ollama_terminal_empty_responses", 0) + 1
                        record_run_event("model_response", role=role, tool_names=[],
                                         terminal_empty_after_tool=True,
                                         response_shape=ollama_response_summary(diagnostics))
                        return clean
                    RUN["ollama_incomplete_responses"] = RUN.get("ollama_incomplete_responses", 0) + 1
                    last_error = "Ollama returned no actionable content or tool_calls: " + ollama_response_summary(diagnostics)
                    record_run_event("model_response_incomplete", role=role,
                                     response_shape=ollama_response_summary(diagnostics), retrying=attempt < retry_limit)
        elif response is not None:
            last_error = f"Ollama error {response.status_code}: {response.text[:1200]}"
            signals = record_ollama_failure(last_error)
        if attempt < retry_limit:
            signals = ollama_failure_signals(last_error)
            if signals["worker"] and not FORCE_CPU_FOR_RUN:
                FORCE_CPU_FOR_RUN = True
                RUN["provider_cpu_fallbacks"] += 1
                RUN["provider_execution"] = "cpu_only_after_cuda_crash"
                payload["options"]["num_gpu"] = 0
                payload["options"]["num_ctx"] = min(context_window, 8192)
            RUN["ollama_retry_count"] = RUN.get("ollama_retry_count", 0) + 1
            time.sleep(0.2 * (attempt + 1))
    raise ProviderError(last_error)


def _parse_json_content(content):
    text = str(content).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        left, right = text.find("{"), text.rfind("}")
        if left >= 0 and right > left:
            return json.loads(text[left:right + 1])
        raise


def structured_model_call(prompt_text, validator, label, schema, retries=MAX_STRUCTURED_RETRIES,
                         role="Coordinator"):
    schema_text = json.dumps(schema, ensure_ascii=False)
    messages = [
        {"role": "system", "content": "Return ONLY one JSON object matching the supplied schema. No markdown."},
        {"role": "user", "content": f"{prompt_text}\n\nJSON SCHEMA:\n{schema_text}"},
    ]
    last_error = "invalid structured response"
    last_content = ""
    for attempt in range(max(1, int(retries))):
        try:
            message = ask_ollama(messages, tools=None, response_format=schema, temperature=0,
                                 think=False, provider_retries=0,
                                 role=("Quality" if label == "quality-review" else role))
            last_content = message.get("content", "")
            data = _parse_json_content(last_content)
            if validator(data):
                return data
            last_error = f"semantic validation failed: {compact_text(data, 700)}"
        except ProviderError:
            raise
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        RUN["planner_structured_retries"] += 1
        print(f"[STRUCTURED RETRY] {label} {attempt + 1}/{retries} | {last_error}")
        record_run_event("structured_invalid", label=label, attempt=attempt + 1, error=last_error,
                         raw_content=last_content)
        messages = [
            {"role": "system", "content": "STRICT JSON REPAIR. Return only valid JSON matching the schema."},
            {"role": "user", "content": f"{prompt_text}\nPrevious output invalid: {compact_text(last_content, 800)}\nSchema: {schema_text}"},
        ]
    raise StructuredOutputError(f"invalid {label} after {retries} attempts: {last_error}")


# ---------------------------------------------------------------------------
# GOAL CONTRACT
# ---------------------------------------------------------------------------

def extract_explicit_requirements(raw_goal):
    """Legacy bullet extractor retained for v3-v15 callers and tests."""
    requirements = []
    for raw_line in str(raw_goal).splitlines():
        line = raw_line.strip()
        match = re.match(r"^(?:[-*•]|\d+[.)])\s+(.+)$", line)
        if match and len(match.group(1).strip()) >= 3:
            requirements.append(match.group(1).strip())
    return requirements


def source_requirement_ledger_schema():
    """Describe the compact source record for deterministic/model tests."""
    return {
        "type": "object", "properties": {
            "requirements": {
                "type": "array", "maxItems": MAX_SOURCE_REQUIREMENTS,
                "items": {"type": "object", "properties": {
                    "text": {"type": "string"}, "category": {"type": "string"},
                    "source_segment": {"type": ["integer", "null"]},
                }, "required": ["text"], "additionalProperties": False},
            },
        }, "required": ["requirements"], "additionalProperties": False,
    }


def _source_requirement_extraction_validator(data):
    if not isinstance(data, dict):
        return False
    values = data.get("requirements")
    return isinstance(values, list) and len(values) <= MAX_SOURCE_REQUIREMENTS and all(
        (isinstance(item, str) and item.strip())
        or (isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip())
        for item in values
    )


def _source_requirement_prompt(segment):
    return f"""You are the REQUIREMENT EXTRACTOR in a weak-model coding orchestrator.
Extract only facts or requirements explicitly stated by the user in this segment.
Do not infer architecture, implementation details, defaults, or hidden intent.
Return a small JSON list. Preserve the user's wording compactly and use an empty list when this segment has no
explicit requirement. This is source bookkeeping, not planning and not code generation.

SOURCE SEGMENT {segment.get('segment')}:
{compact_text(segment.get('text', ''), MAX_SOURCE_SEGMENT_CHARS)}"""


def _record_source_ledger_metrics(ledger):
    records = ledger_requirements(ledger)
    overflow = ledger.get("overflow", {}) if isinstance(ledger, dict) else {}
    RUN["source_requirement_ledger"] = ledger
    RUN["source_requirements_extracted"] = len(records)
    RUN["source_requirements_retained"] = len(records)
    RUN["source_requirement_retention_numerator"] = len(records)
    RUN["source_requirement_retention_denominator"] = len(records)
    RUN["source_requirement_retention_rate_numerator"] = len(records)
    RUN["source_requirement_retention_rate_denominator"] = len(records)
    RUN["source_requirement_retention_rate"] = 1.0
    RUN["source_requirement_items_truncated"] = int(overflow.get("explicit_items_truncated", 0) or 0)
    record_run_event(
        "source_requirement_ledger_created",
        requirement_ids=[item.get("requirement_id") for item in records],
        requirement_count=len(records),
        segment_count=len({segment for item in records for segment in item.get("source_segments", [])}),
        source_requirement_items_truncated=RUN["source_requirement_items_truncated"],
    )
    return ledger


def extract_source_requirement_ledger(raw_goal, structured_call=None, max_segments=MAX_SOURCE_SEGMENTS,
                                      use_model=None, existing_ledger=None):
    """Extract a stable, bounded source ledger before any spec expansion."""
    raw_text = str(raw_goal or "").strip()
    segments = bounded_source_segments(raw_text, max_segments=max_segments)
    candidates = []
    extraction_failures = []
    for segment in segments:
        candidates.extend(deterministic_requirement_candidates(segment["text"], segment["segment"]))

    # The deterministic path protects explicit bullets.  Long prose is sent
    # in bounded segments to the same weak model only when useful; tests may
    # inject a structured callable without contacting Ollama.
    if use_model is None:
        use_model = bool(structured_call is not None or len(raw_text) > MAX_SOURCE_SEGMENT_CHARS * 2)
    if use_model:
        schema = source_requirement_ledger_schema()
        for segment in segments[:MAX_SOURCE_EXTRACTION_MODEL_CALLS]:
            try:
                RUN["requirement_extractor_calls"] = RUN.get("requirement_extractor_calls", 0) + 1
                if structured_call is None:
                    data = structured_model_call(
                        _source_requirement_prompt(segment),
                        _source_requirement_extraction_validator,
                        "source-requirement-extraction", schema,
                        role="RequirementExtractor",
                    )
                else:
                    data = structured_call(
                        _source_requirement_prompt(segment),
                        _source_requirement_extraction_validator,
                        "source-requirement-extraction", schema,
                    )
                if not _source_requirement_extraction_validator(data):
                    raise StructuredOutputError("source requirement extraction failed semantic validation")
                for item in data.get("requirements", []):
                    candidate = {"text": item} if isinstance(item, str) else dict(item)
                    candidate["source_segment"] = segment["segment"]
                    candidate["provenance"] = USER_STATED
                    candidates.append(candidate)
            except StructuredOutputError as exc:
                extraction_failures.append({"segment": segment["segment"], "kind": "structured", "error": compact_text(exc, 260)})
                record_run_event(
                    "source_requirement_extraction_fallback",
                    segment=segment["segment"], error=str(exc),
                )
            except ProviderError:
                # Do not lose deterministic source candidates because a local
                # model is temporarily unavailable.
                extraction_failures.append({"segment": segment["segment"], "kind": "provider"})
                record_run_event(
                    "source_requirement_extraction_provider_unavailable",
                    segment=segment["segment"],
                )
                break
    ledger = build_source_requirement_ledger(candidates, existing_ledger=existing_ledger)
    if not ledger_requirements(ledger) and raw_text and has_explicit_requirement_signal(raw_text):
        ledger = build_source_requirement_ledger([{
            "text": raw_text, "category": "functional", "source_segment": 1,
            "provenance": USER_STATED,
        }])
    ledger_data = thaw(ledger)
    ledger_data["extraction"] = {
        "mode": "model_plus_deterministic" if use_model else "deterministic",
        "status": "complete" if not extraction_failures else "partial_fallback",
        "segments": len(segments), "failures": extraction_failures[:MAX_CLARIFICATION_QUESTIONS],
        "failure_count": len(extraction_failures),
    }
    ledger = freeze(ledger_data)
    return _record_source_ledger_metrics(ledger)


def source_requirement_ledger(raw_goal, structured_call=None, **kwargs):
    """Public spelling used by callers that treat the ledger as a boundary."""
    return extract_source_requirement_ledger(raw_goal, structured_call=structured_call, **kwargs)


# Clear aliases keep the v16 boundary discoverable to deterministic callers
# without introducing another memory or orchestration framework.
extract_source_requirements = extract_source_requirement_ledger
build_source_ledger = extract_source_requirement_ledger


def _deterministic_contract_from_ledger(raw_goal, ledger, derived=None):
    records = ledger_requirements(ledger)
    requirements = [item.get("text", "") for item in records if item.get("text")]
    first_line = next((line.strip() for line in str(raw_goal or "").splitlines() if line.strip()), "coding task")
    return {
        "status": "ready", "question": "", "goal": compact_text(first_line, 1200),
        "requirements": requirements or [compact_text(raw_goal, MAX_SOURCE_REQUIREMENT_CHARS)],
        "constraints": [item["text"] for item in records if item.get("category") == "constraint"][:12],
        "success_criteria": ["every explicit requirement is implemented and verified"],
        "original_goal": str(raw_goal), "derived_assumptions": list(derived or []),
    }


def normalize_goal_contract(raw_goal, contract, source_ledger=None, confirmed=None, derived=None,
                            clarification_questions=None, clarification_answers=None,
                            interaction_style=None):
    """Preserve explicit user bullets when a weak model summarizes lossy."""
    normalized = dict(contract or {})
    if source_ledger is not None:
        records = ledger_requirements(source_ledger)
        if records:
            normalized["requirements"] = [item.get("text", "") for item in records if item.get("text")]
            source_constraints = [
                item.get("text", "") for item in records if item.get("category") == "constraint"
            ]
            if source_constraints:
                normalized["constraints"] = list(dict.fromkeys(
                    source_constraints + list(normalized.get("constraints", []))
                ))[:MAX_SOURCE_REQUIREMENTS]
    else:
        explicit = extract_explicit_requirements(raw_goal)
        if len(explicit) >= 2:
            normalized["requirements"] = explicit
    normalized.setdefault("status", "ready")
    normalized.setdefault("constraints", [])
    normalized.setdefault("success_criteria", ["every explicit requirement is implemented and verified"])
    normalized["original_goal"] = str(raw_goal)
    if source_ledger is not None:
        normalized["source_requirement_ledger"] = source_ledger
        normalized["source_requirements"] = ledger_requirements(source_ledger)
        normalized["user_stated_requirements"] = ledger_requirements(source_ledger)
    normalized["user_confirmed_requirements"] = list(
        confirmed if confirmed is not None else normalized.get("user_confirmed_requirements", [])
    )
    normalized["derived_assumptions"] = list(
        derived if derived is not None else normalized.get("derived_assumptions", [])
    )
    normalized["clarification_questions"] = list(
        clarification_questions if clarification_questions is not None
        else normalized.get("clarification_questions", [])
    )
    normalized["clarification_answers"] = list(
        clarification_answers if clarification_answers is not None
        else normalized.get("clarification_answers", [])
    )
    if interaction_style:
        normalized["interaction_style"] = interaction_style
    return normalized


def _goal_validator(data):
    if not isinstance(data, dict) or str(data.get("status", "")).lower() not in {"question", "ready"}:
        return False
    if str(data.get("status")).lower() == "question":
        return bool(str(data.get("question", "")).strip())
    return all(isinstance(data.get(key), expected) for key, expected in (
        ("goal", str), ("requirements", list), ("constraints", list), ("success_criteria", list),
    ))


def understand_goal(raw_goal, prior_answers=""):
    schema = {
        "type": "object", "properties": {
            "status": {"type": "string", "enum": ["question", "ready"]}, "question": {"type": "string"},
            "goal": {"type": "string"}, "requirements": {"type": "array", "items": {"type": "string"}},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "success_criteria": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["status", "question", "goal", "requirements", "constraints", "success_criteria"],
        "additionalProperties": False,
    }
    prompt_text = f"""Understand this coding request before execution. Ask one clarification only if a missing fact truly blocks correct execution.
If ready, create a compact authoritative Goal Contract preserving all requirements and constraints. Do not implement.
RAW REQUEST:\n{raw_goal}\nPRIOR CLARIFICATIONS:\n{prior_answers or '(none)'}"""
    try:
        data = structured_model_call(prompt_text, _goal_validator, "goal-understanding", schema)
        data["status"] = str(data["status"]).lower()
        return data
    except StructuredOutputError as exc:
        fallback = {
            "status": "ready", "question": "", "goal": compact_text(raw_goal, 1600),
            "requirements": [raw_goal], "constraints": [prior_answers] if prior_answers else [],
            "success_criteria": ["The requested outcome is implemented and verified with executable evidence"],
        }
        record_run_event("structured_fallback", label="goal-understanding", error=str(exc))
        return fallback


def clarification_schema():
    option_schema = {
        "type": "array", "items": {"type": "string"},
        "maxItems": REQUIREMENT_MAX_CLARIFICATION_OPTIONS,
    }
    question_schema = {
        "type": "object", "properties": {
            "question_id": {"type": "string"}, "question": {"type": "string"},
            "reason": {"type": "string"},
            "affected_requirement_ids": {"type": "array", "items": {"type": "string"}},
            "impact_if_unknown": {"type": "string"}, "recommended_option": {"type": "string"},
            "options": option_schema, "allow_other": {"type": "boolean"},
            "blocking": {"type": "boolean"}, "category": {"type": "string"},
        },
        "required": ["question", "reason", "affected_requirement_ids", "impact_if_unknown",
                     "recommended_option", "options", "allow_other", "blocking"],
        "additionalProperties": False,
    }
    return {
        "type": "object", "properties": {
            "questions": {
                "type": "array", "items": question_schema,
                "maxItems": MAX_CLARIFICATION_QUESTIONS,
            },
        }, "required": ["questions"], "additionalProperties": False,
    }


def _clarification_validator(data):
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        return False
    return len(data["questions"]) <= MAX_CLARIFICATION_QUESTIONS and all(
        isinstance(item, dict) and isinstance(item.get("question"), str)
        and isinstance(item.get("options"), list) for item in data["questions"]
    )


def _compact_source_contract_for_clarifier(ledger, max_chars=MAX_CLARIFIER_INPUT_CHARS):
    records = []
    for item in ledger_requirements(ledger):
        records.append({
            "requirement_id": item.get("requirement_id"),
            "text": compact_text(item.get("text", ""), 420),
            "category": item.get("category"), "source_segment": item.get("source_segment"),
        })
    encoded = json.dumps(records, ensure_ascii=False)
    return encoded if len(encoded) <= max_chars else encoded[:max_chars - 3] + "..."


def _clarifier_prompt(raw_goal, ledger, conflicts, interaction_style):
    return f"""You are the REQUIREMENT CLARIFIER in a weak-model coding orchestrator.
You do not write code, inspect a repository, decompose tasks, choose file layouts, or solve architecture.
Decide whether the user must answer anything before planning. Ask only questions where a wrong assumption would
materially change visible behavior or architecture, resolve an explicit conflict, affect compatibility or destructive
behavior, or make acceptance impossible to judge. Do not ask implementation trivia.
Low-friction requests should usually return zero questions. Return at most {MAX_CLARIFICATION_QUESTIONS} concise questions.
For each question, options are user-facing choices; put a defensible recommendation first and leave the recommendation
empty when there is no defensible preference. Set blocking true only when planning must stop without the answer.
Do not include chain-of-thought.

INTERACTION STYLE (request only, never a person): {interaction_style}
RAW USER REQUEST:
{compact_text(raw_goal, 3600)}
SOURCE REQUIREMENT LEDGER:
{_compact_source_contract_for_clarifier(ledger)}
VISIBLE SOURCE CONFLICTS:
{json.dumps(conflicts, ensure_ascii=False)[:2200] if conflicts else '(none)'}"""


def clarify_request(raw_goal, ledger, structured_call=None):
    """Run one bounded Clarifier pass and return only eligible questions."""
    conflicts = detect_explicit_conflicts(ledger)
    interaction_style = classify_interaction_style(raw_goal, ledger)
    questions = conflict_questions(ledger, conflicts)
    # Explicit conflicts already have a deterministic source-linked question.
    # Precision-sensitive prose receives one weak-model pass for other
    # material choices. Tests may inject a call to exercise the full schema.
    # A visible conflict already has a deterministic question. Avoid spending
    # an extra provider call merely to rediscover it; precision-sensitive
    # non-conflict prose is the bounded Clarifier use case.
    needs_model = bool(structured_call is not None or (not conflicts and interaction_style == "PRECISION_SENSITIVE"))
    if needs_model:
        schema = clarification_schema()
        try:
            RUN["clarifier_calls"] = RUN.get("clarifier_calls", 0) + 1
            if structured_call is None:
                data = structured_model_call(
                    _clarifier_prompt(raw_goal, ledger, conflicts, interaction_style),
                    _clarification_validator, "clarification-gate", schema,
                    role="Clarifier",
                )
            else:
                data = structured_call(
                    _clarifier_prompt(raw_goal, ledger, conflicts, interaction_style),
                    _clarification_validator, "clarification-gate", schema,
                )
            if not _clarification_validator(data):
                raise StructuredOutputError("clarifier returned an invalid question envelope")
            for item in data.get("questions", []):
                normalized = normalize_question(
                    item, len(questions) + 1, ledger, interaction_style, conflicts,
                )
                if not normalized:
                    continue
                same_affected = set(normalized.get("affected_requirement_ids", []))
                duplicate = any(
                    same_affected and same_affected == set(existing.get("affected_requirement_ids", []))
                    for existing in questions
                )
                if not duplicate and len(questions) < MAX_CLARIFICATION_QUESTIONS:
                    questions.append(normalized)
        except StructuredOutputError as exc:
            record_run_event("clarifier_fallback", error=str(exc))
        except ProviderError:
            # Deterministic conflict questions remain actionable when the weak
            # provider is unavailable. Other questions are not invented.
            record_run_event("clarifier_provider_unavailable")
    normalized_questions = []
    ordered_questions = sorted(
        questions, key=lambda item: question_priority(item) if isinstance(item, dict) else 4,
    )
    for index, question in enumerate(ordered_questions[:MAX_CLARIFICATION_QUESTIONS], 1):
        item = normalize_question(question, index, ledger, interaction_style, conflicts)
        if item:
            normalized_questions.append(item)
    RUN["pending_clarification_questions"] = normalized_questions
    if normalized_questions:
        RUN["user_clarification_rounds"] = RUN.get("user_clarification_rounds", 0) + 1
        RUN["user_clarification_questions"] = RUN.get("user_clarification_questions", 0) + len(normalized_questions)
        RUN["clarification_questions"] = RUN.get("clarification_questions", 0) + len(normalized_questions)
    record_run_event(
        "clarification_gate_evaluated",
        interaction_style=interaction_style,
        question_ids=[item.get("question_id") for item in normalized_questions],
        conflict_count=len(conflicts),
    )
    return {
        "questions": normalized_questions, "conflicts": conflicts,
        "interaction_style": interaction_style,
    }


clarification_gate = clarify_request


def clarification_option_labels(question):
    """Return display labels with no numeric option IDs."""
    question = question if isinstance(question, dict) else {}
    options = list(question.get("options", []) or [])[:REQUIREMENT_MAX_CLARIFICATION_OPTIONS]
    recommended = str(question.get("recommended_option", "") or "")
    labels = []
    for option in options:
        label = str(option)
        if recommended and label.casefold() == recommended.casefold() and not labels:
            label += "     Recommended"
        labels.append(label)
    if question.get("allow_other", True):
        labels.append("Other...")
    return labels


def navigate_clarification_options(options, key_sequence, initial_index=0):
    """Deterministically map arrow keys and Enter to an option index."""
    options = list(options or [])
    if not options:
        return None
    index = min(max(int(initial_index), 0), len(options) - 1)
    for key in list(key_sequence or []):
        value = str(key).casefold()
        if value in {"up", "arrowup", "k", "\x1b[a"}:
            index = max(0, index - 1)
        elif value in {"down", "arrowdown", "j", "\x1b[b"}:
            index = min(len(options) - 1, index + 1)
        elif value in {"escape", "esc", "cancel"}:
            return None
        elif value in {"enter", "return", "\r", "\n"}:
            return index
    return index


def select_clarification_option(question, key_sequence=None, output_fn=print, terminal_available=None):
    """Show one compact arrow-key question and return the selected index."""
    question = question if isinstance(question, dict) else {}
    labels = clarification_option_labels(question)
    if key_sequence is not None:
        return navigate_clarification_options(labels, key_sequence)
    if terminal_available is None:
        terminal_available = bool(sys.stdin.isatty() and sys.stdout.isatty())
    if not terminal_available:
        return None
    output_fn("\nHIVO needs one decision before planning.\n")
    output_fn(compact_text(question.get("question", "Choose an option."), 420))
    output_fn(f"Reason: {compact_text(question.get('reason', ''), 260)}")
    if PROMPT_TOOLKIT_AVAILABLE:
        try:
            from prompt_toolkit.shortcuts import radiolist_dialog
            values = [(index, label) for index, label in enumerate(labels)]
            selected = radiolist_dialog(
                title="HIVO clarification", text="Use Up/Down and Enter to select.",
                values=values, ok_text="Select", cancel_text="Skip / use default",
            ).run()
            return int(selected) if selected is not None else None
        except (ImportError, EOFError, KeyboardInterrupt, TypeError, ValueError):
            return None
    # Dependency-free Windows fallback for a real terminal. POSIX users get a
    # concise instruction instead of a numeric option interface.
    if os.name == "nt":
        try:
            import msvcrt
            index = 0
            while True:
                key = msvcrt.getwch()
                if key in {"\r", "\n"}:
                    return index
                if key == "\x1b":
                    return None
                if key in {"\x00", "\xe0"}:
                    arrow = msvcrt.getwch()
                    if arrow == "H":
                        index = max(0, index - 1)
                    elif arrow == "P":
                        index = min(len(labels) - 1, index + 1)
        except (ImportError, EOFError, KeyboardInterrupt):
            return None
    output_fn("Use arrow keys and Enter; Esc skips optional clarification.")
    return None


def _clarification_answer_record(question, answer, selected_option):
    existing = RUN.get("clarification_answers", [])
    numbers = []
    for item in existing:
        if not isinstance(item, dict):
            continue
        match = re.match(r"^DEC-(\d+)$", str(item.get("decision_id", "")))
        if match:
            numbers.append(int(match.group(1)))
    return {
        "decision_id": f"DEC-{max(numbers, default=0) + 1:03d}",
        "question_id": question.get("question_id"),
        "answer": compact_text(answer, 700),
        "selected_option": compact_text(selected_option, 300),
        "affected_requirement_ids": list(question.get("affected_requirement_ids", [])),
        "repository_evidence_ids": list(question.get("repository_evidence_ids", []))[:8],
        "phase": compact_text(question.get("phase") or "REQUEST_CLARIFICATION", 80),
        "provenance": USER_CONFIRMED,
    }


def resolve_clarification_questions(clarification, interactive=True, terminal_available=None,
                                    selector=None, answer_reader=None):
    """Resolve one bounded round or return a clean CLARIFICATION_REQUIRED state."""
    clarification = clarification if isinstance(clarification, dict) else {}
    questions = list(clarification.get("questions", []) or [])[:MAX_CLARIFICATION_QUESTIONS]
    if not questions:
        return {"status": "ready", "answers": [], "derived": [], "unanswered": []}
    if terminal_available is None:
        terminal_available = bool(sys.stdin.isatty() and sys.stdout.isatty())
    can_interact = bool(interactive and terminal_available)
    answers, derived, unanswered = [], [], []
    for question in questions:
        blocking = bool(question.get("blocking"))
        selected = None
        if can_interact:
            choose = selector or select_clarification_option
            try:
                selected = choose(question, terminal_available=terminal_available)
            except TypeError:
                selected = choose(question)
        if selected is None:
            if blocking:
                unanswered.append(question)
                continue
            option = question.get("recommended_option") or (question.get("options") or ["use the default behavior"])[0]
            derived.append({
                "question_id": question.get("question_id"), "text": compact_text(option, 700),
                "answer": compact_text(option, 700), "provenance": DERIVED,
                "source": "recommended/default used without interactive confirmation",
            })
            RUN["optional_clarifications_skipped"] = RUN.get("optional_clarifications_skipped", 0) + 1
            continue
        labels = clarification_option_labels(question)
        selected = min(max(int(selected), 0), len(labels) - 1)
        raw_options = [
            str(item) for item in list(question.get("options", []) or [])[:REQUIREMENT_MAX_CLARIFICATION_OPTIONS]
        ]
        if selected < len(raw_options):
            # The visible label may include the UI-only "Recommended" marker;
            # persist the actual choice, not presentation text.
            selected_option = raw_options[selected]
        else:
            selected_option = "Other..."
        answer = selected_option
        if selected_option == "Other...":
            reader = answer_reader or read_user_prompt
            try:
                answer = reader("Other> ")
            except TypeError:
                answer = reader()
            if not str(answer or "").strip():
                if blocking:
                    unanswered.append(question)
                    continue
                answer = question.get("recommended_option") or (question.get("options") or ["use the default behavior"])[0]
        record = _clarification_answer_record(question, answer, selected_option)
        answers.append(record)
        RUN["user_clarification_answers"] = RUN.get("user_clarification_answers", 0) + 1
        RUN["user_confirmed_requirements"] = RUN.get("user_confirmed_requirements", 0) + 1
    if unanswered:
        RUN["blocking_clarifications_required"] = RUN.get("blocking_clarifications_required", 0) + len(unanswered)
        RUN["clarification_terminal_state"] = "CLARIFICATION_REQUIRED"
        RUN["unanswered_clarification_questions"] = unanswered
        RUN["clarification_answers"] = answers
        RUN["clarification_derived_assumptions"] = derived
        record_run_event(
            "clarification_required",
            question_ids=[item.get("question_id") for item in unanswered], blocking=True,
            phases=[item.get("phase", "REQUEST_CLARIFICATION") for item in unanswered],
            repository_evidence_ids=[
                evidence_id for item in unanswered
                for evidence_id in item.get("repository_evidence_ids", [])
            ],
        )
        return {"status": "clarification_required", "answers": answers, "derived": derived,
                "unanswered": unanswered}
    RUN["clarification_answers"] = answers
    RUN["clarification_derived_assumptions"] = derived
    return {"status": "ready", "answers": answers, "derived": derived, "unanswered": []}


def _contract_needs_clarification(contract):
    return str((contract or {}).get("status", "")).casefold() in {
        "question", "clarification_required", "needs_clarification",
    }


def _clarification_required_contract(raw_goal, ledger, clarification, resolution):
    questions = list(clarification.get("questions", []) or [])
    source_contract = source_contract_from_ledger(
        raw_goal, ledger, questions=questions, answers=resolution.get("answers", []),
        interaction_style=clarification.get("interaction_style"),
    )
    return {
        "status": "clarification_required", "terminal_state": "CLARIFICATION_REQUIRED",
        "question": questions[0].get("question", "clarification required") if questions else "clarification required",
        "questions": questions, "unanswered_questions": resolution.get("unanswered", []),
        "original_goal": str(raw_goal), "source_requirement_ledger": ledger,
        "source_requirements": ledger_requirements(ledger),
        "user_stated_requirements": ledger_requirements(ledger),
        "user_confirmed_requirements": resolution.get("answers", []),
        "derived_assumptions": resolution.get("derived", []),
        "clarification_answers": resolution.get("answers", []),
        "source_contract": source_contract,
        "interaction_style": clarification.get("interaction_style", "LOW_FRICTION"),
    }


def _ledger_with_confirmed_answers(ledger, answers):
    """Append confirmed decisions as new records without changing stated REQs."""
    result = ledger
    for answer in answers or []:
        if not isinstance(answer, dict) or not str(answer.get("answer", "")).strip():
            continue
        result = append_confirmed_requirement(
            result, answer.get("answer"), question_id=answer.get("question_id"),
            affected_requirement_ids=answer.get("affected_requirement_ids", []),
            repository_evidence_ids=answer.get("repository_evidence_ids", []),
            phase=answer.get("phase"),
        )
    return result


def get_goal_contract(raw_goal, interactive=True, structured_call=None, clarifier_call=None,
                      terminal_available=None, selector=None, answer_reader=None):
    """Build the source contract, run one critical round, then return ready."""
    RUN.setdefault("control_flow", []).append("SOURCE_REQUIREMENT_INGESTION")
    ledger = extract_source_requirement_ledger(raw_goal, structured_call=structured_call)
    RUN.setdefault("control_flow", []).append("REQUEST_CLARIFICATION")
    clarification = clarify_request(raw_goal, ledger, structured_call=clarifier_call)
    resolution = resolve_clarification_questions(
        clarification, interactive=interactive, terminal_available=terminal_available,
        selector=selector, answer_reader=answer_reader,
    )
    ledger = _ledger_with_confirmed_answers(ledger, resolution.get("answers", []))
    RUN["source_requirement_ledger"] = ledger
    if resolution["status"] == "clarification_required":
        return _clarification_required_contract(raw_goal, ledger, clarification, resolution)

    contract = _deterministic_contract_from_ledger(
        raw_goal, ledger, derived=resolution.get("derived", []),
    )
    records = ledger_requirements(ledger)
    # Keep the established Goal Contract model useful for short prose, but do
    # not allow its old question path to create a second clarification loop.
    if len(records) < 2 and not extract_explicit_requirements(raw_goal):
        prior_answers = "\n".join(
            f"Q: {item.get('question_id')}\nA: {item.get('answer')}"
            for item in resolution.get("answers", [])
        )
        try:
            model_contract = understand_goal(raw_goal, prior_answers)
            if model_contract.get("status") == "ready":
                contract = normalize_goal_contract(raw_goal, model_contract)
        except ProviderError:
            # Source extraction remains the authoritative fallback for a
            # temporary weak-provider failure.
            pass
    contract = normalize_goal_contract(
        raw_goal, contract, source_ledger=ledger,
        confirmed=resolution.get("answers", []), derived=resolution.get("derived", []),
        clarification_questions=clarification.get("questions", []),
        clarification_answers=resolution.get("answers", []),
        interaction_style=clarification.get("interaction_style"),
    )
    contract["clarifications"] = [
        f"Q: {item.get('question_id')}\nA: {item.get('answer')}"
        for item in resolution.get("answers", [])
    ]
    contract["source_contract"] = source_contract_from_ledger(
        raw_goal, ledger, confirmed=resolution.get("answers", []),
        derived=resolution.get("derived", []),
        questions=clarification.get("questions", []), answers=resolution.get("answers", []),
        interaction_style=clarification.get("interaction_style"),
    )
    RUN["source_contract"] = contract["source_contract"]
    RUN["clarification_answers"] = resolution.get("answers", [])
    RUN["clarification_derived_assumptions"] = resolution.get("derived", [])
    record_run_event(
        "source_contract_ready",
        requirement_count=len(records), confirmed_count=len(resolution.get("answers", [])),
        derived_count=len(resolution.get("derived", [])),
    )
    return contract


_PROJECT_SPECIFICATION_FIELDS = (
    "user_visible_behavior", "major_functional_areas", "major_system_components",
    "state_ownership", "interaction_model", "ui_ux_expectations",
    "persistence_requirements", "important_edge_cases", "architecture_invariants",
    "interface_contracts", "quality_constraints", "project_specific_coding_constraints", "acceptance_criteria",
    "explicit_assumptions", "unresolved_critical_ambiguities", "non_goals",
)


def _bounded_brain_strings(values, max_items=MAX_BRAIN_ITEMS, item_chars=360):
    """Normalize a small list of model/project facts without preserving prose."""
    if values is None:
        values = []
    elif isinstance(values, (str, bytes)):
        values = [values]
    elif not isinstance(values, (list, tuple, set)):
        values = [values]
    result = []
    for value in values:
        if isinstance(value, (dict, list, tuple)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        value = compact_text(value, item_chars)
        if value and value not in result:
            result.append(value)
        if len(result) >= max_items:
            break
    return result


def _compact_brain_record(value, max_chars=MAX_INTEGRATION_FACT_CHARS):
    """Keep deterministic verified records structured and bounded."""
    if not isinstance(value, dict):
        return compact_text(value, max_chars)
    preferred = (
        "kind", "owner", "symbol", "selector", "fact", "source", "rule", "file", "path",
        "evidence_id", "category", "evidence_type", "source_kind", "line_start", "line_end",
        "file_sha256", "support",
        "requirement_id", "decision_id", "text", "category", "provenance", "source_segment",
        "source_segments", "source_variants", "question_id", "answer", "selected_option",
        "affected_requirement_ids",
        "task_id", "goal", "summary", "evidence", "status", "changed_files",
        "introduced_symbols", "modified_symbols", "interfaces", "invariants", "verification",
    )
    keys = [key for key in preferred if key in value]
    record = {}
    for key in keys[:12]:
        item = value.get(key)
        if isinstance(item, (list, tuple, set)):
            record[str(key)] = _bounded_brain_strings(item, 8, 220)
        elif isinstance(item, dict):
            record[str(key)] = compact_text(json.dumps(item, ensure_ascii=False, default=str), 260)
        else:
            record[str(key)] = compact_text(item, 260)
    encoded = json.dumps(record, ensure_ascii=False, default=str)
    if len(encoded) <= max_chars:
        return record
    # Drop less important trailing fields before falling back to a compact
    # string.  The state remains evidence-shaped rather than becoming an
    # unbounded record.
    while len(encoded) > max_chars and len(record) > 1:
        record.pop(next(reversed(record)))
        encoded = json.dumps(record, ensure_ascii=False, default=str)
    return record if len(encoded) <= max_chars else compact_text(encoded, max_chars)


def _bounded_brain_records(values, max_items=MAX_BRAIN_ITEMS, item_chars=MAX_INTEGRATION_FACT_CHARS):
    if values is None:
        return []
    if isinstance(values, (str, bytes, dict)):
        values = [values]
    result = []
    seen = set()
    for value in values:
        compacted = _compact_brain_record(value, item_chars)
        key = json.dumps(compacted, ensure_ascii=False, sort_keys=True, default=str)
        if key not in seen:
            result.append(compacted)
            seen.add(key)
        if len(result) >= max_items:
            break
    return result


def _project_specification_schema():
    array_schema = {"type": "array", "items": {"type": "string"}, "maxItems": MAX_BRAIN_ITEMS}
    properties = {"root_goal": {"type": "string"}}
    properties.update({field: array_schema for field in _PROJECT_SPECIFICATION_FIELDS})
    return {
        "type": "object", "properties": properties,
        "required": ["root_goal", *_PROJECT_SPECIFICATION_FIELDS],
        "additionalProperties": False,
    }


def _project_specification_validator(data):
    if not isinstance(data, dict) or not str(data.get("root_goal", "")).strip():
        return False
    return all(
        isinstance(data.get(field), list)
        and all(isinstance(item, str) and item.strip() for item in data.get(field, []))
        for field in _PROJECT_SPECIFICATION_FIELDS
    )


def _compact_source_ledger_for_prompt(ledger, max_chars=MAX_SOURCE_LEDGER_CHARS):
    """Serialize source requirements for Specifier/Clarifier prompts only."""
    records = []
    for item in ledger_requirements(ledger):
        records.append({
            "requirement_id": item.get("requirement_id"),
            "text": item.get("text", ""),
            "category": item.get("category"),
            "provenance": item.get("provenance", USER_STATED),
            "source_segments": item.get("source_segments", [item.get("source_segment")]),
            "status": item.get("status", "active"),
        })
    encoded = json.dumps(records, ensure_ascii=False, default=str)
    if len(encoded) <= max_chars:
        return encoded or "(none)"
    # Preserve every record boundary and ID while progressively shortening
    # only the prompt copy. The full immutable ledger remains lossless in the
    # contract/Brain object.
    for text_limit in (420, 300, 220, 160, 120, 80):
        compacted = [{
            "requirement_id": item.get("requirement_id"),
            "text": compact_text(item.get("text", ""), text_limit),
            "source_segment": item.get("source_segment"),
        } for item in records]
        encoded = json.dumps(compacted, ensure_ascii=False, default=str)
        if len(encoded) <= max_chars:
            return encoded
    # A caller may deliberately request a smaller cap than the bounded
    # ledger can fit. Keep the start/end IDs visible and state that the prompt
    # copy is compacted; no record is removed from the stored ledger.
    ids = [item.get("requirement_id") for item in records]
    return json.dumps({"requirement_ids": ids, "ledger_prompt_compacted": True}, ensure_ascii=False)


def normalize_project_specification(raw_goal, contract, specification):
    """Return the bounded expansion while preserving the authoritative contract."""
    contract = contract if isinstance(contract, dict) else {}
    specification = specification if isinstance(specification, dict) else {}
    has_source_ledger = bool(contract.get("source_requirement_ledger"))
    normalized = {"root_goal": compact_text(
        contract.get("goal") or specification.get("root_goal") or raw_goal, 1100,
    )}
    for field in _PROJECT_SPECIFICATION_FIELDS:
        normalized[field] = _bounded_brain_strings(specification.get(field), MAX_BRAIN_ITEMS, 360)

    # Legacy contracts still receive the v15 authoritative projection.  A v16
    # source ledger is retained separately, so an omitted source item remains
    # visibly UNMAPPED instead of being silently injected into the derived
    # specification and masking the omission.
    if not has_source_ledger:
        normalized["major_functional_areas"] = _bounded_brain_strings(
            list(contract.get("requirements", [])) + normalized["major_functional_areas"],
            MAX_BRAIN_ITEMS, 360,
        )
        normalized["acceptance_criteria"] = _bounded_brain_strings(
            list(contract.get("success_criteria", [])) + normalized["acceptance_criteria"],
            MAX_BRAIN_ITEMS, 360,
        )
        normalized["quality_constraints"] = _bounded_brain_strings(
            list(contract.get("constraints", [])) + normalized["quality_constraints"],
            MAX_BRAIN_ITEMS, 360,
        )

    trim_order = (
        "unresolved_critical_ambiguities", "explicit_assumptions", "important_edge_cases",
        "ui_ux_expectations", "persistence_requirements", "interaction_model",
        "project_specific_coding_constraints", "quality_constraints", "interface_contracts", "non_goals",
        "architecture_invariants", "state_ownership", "acceptance_criteria",
        "major_system_components", "major_functional_areas", "user_visible_behavior",
    )
    encoded = json.dumps(normalized, ensure_ascii=False)
    while len(encoded) > MAX_PROJECT_SPECIFICATION_CHARS:
        removed = False
        for field in trim_order:
            if len(normalized[field]) > 1:
                normalized[field].pop()
                removed = True
                break
        if removed:
            encoded = json.dumps(normalized, ensure_ascii=False)
            continue
        if len(normalized["root_goal"]) > 180:
            normalized["root_goal"] = compact_text(normalized["root_goal"], len(normalized["root_goal"]) - 120)
            encoded = json.dumps(normalized, ensure_ascii=False)
            continue
        changed = False
        for field in trim_order:
            values = normalized[field]
            if not values:
                continue
            item_chars = max(24, max(len(item) for item in values) // 2)
            shortened = _bounded_brain_strings(values, len(values), item_chars)
            if shortened != values:
                normalized[field] = shortened
                changed = True
                break
        if changed:
            encoded = json.dumps(normalized, ensure_ascii=False)
            continue
        normalized["root_goal"] = compact_text(normalized["root_goal"], max(40, MAX_PROJECT_SPECIFICATION_CHARS // 4))
        encoded = json.dumps(normalized, ensure_ascii=False)
        if len(encoded) > MAX_PROJECT_SPECIFICATION_CHARS:
            # All structured fields are already at their smallest useful
            # deterministic representation. Preserve the goal and contract
            # shape rather than returning an over-sized expansion.
            for field in trim_order:
                normalized[field] = []
                encoded = json.dumps(normalized, ensure_ascii=False)
                if len(encoded) <= MAX_PROJECT_SPECIFICATION_CHARS:
                    break
        break
    return normalized


def specification_from_goal_contract(contract):
    """Build a deterministic expansion when a caller already supplied a contract."""
    contract = contract if isinstance(contract, dict) else {}
    return normalize_project_specification(
        contract.get("original_goal", contract.get("goal", "coding task")),
        contract,
        {
            "root_goal": contract.get("goal", "coding task"),
            "major_functional_areas": list(contract.get("requirements", [])),
            "quality_constraints": list(contract.get("constraints", [])),
            "acceptance_criteria": list(contract.get("success_criteria", [])),
        },
    )


def expand_project_specification(raw_goal, contract, structured_call=None, repository_summary=None):
    """Expand a short request into a bounded project specification, never code."""
    RUN["specification_expansions"] = RUN.get("specification_expansions", 0) + 1
    schema = _project_specification_schema()
    prompt_text = f"""You are the SPECIFICATION EXPANDER in a weak-model coding orchestrator.
Translate one user request into a compact implementation-relevant project specification.
Do not write code, decompose tasks, choose worker-level edits, or invent features merely to make the output longer.
Preserve every explicit requirement and constraint. Use empty arrays when a category is not applicable or is not
supported by the request. Put genuinely unresolved blocking ambiguities in unresolved_critical_ambiguities.
For an existing project, CURRENT OBSERVED REPOSITORY FACTS are authoritative only about current state. Keep them
epistemically separate from PROPOSED / DERIVED architecture; do not rewrite observations as user requirements.
Return only the bounded structured specification requested by the schema.

RAW USER REQUEST:
{compact_text(raw_goal, 3600)}

AUTHORITATIVE GOAL CONTRACT:
{compact_contract(contract, max_chars=1800)}

IMMUTABLE SOURCE REQUIREMENT LEDGER:
{_compact_source_ledger_for_prompt(contract.get('source_requirement_ledger'), max_chars=MAX_SOURCE_LEDGER_CHARS)}

USER-CONFIRMED CLARIFICATION DECISIONS:
{json.dumps(contract.get('user_confirmed_requirements', []), ensure_ascii=False, default=str)[:2200] or '(none)'}

DERIVED OPTIONAL DEFAULTS (not user-confirmed):
{json.dumps(contract.get('derived_assumptions', []), ensure_ascii=False, default=str)[:1800] or '(none)'}

CURRENT OBSERVED REPOSITORY FACTS (not user truth; not proposed architecture):
{compact_text(repository_summary or '(none / NEW_PROJECT)', 4200)}"""
    try:
        if structured_call is None:
            data = structured_model_call(
                prompt_text, _project_specification_validator, "specification-expansion", schema,
                role="Specifier",
            )
        else:
            data = structured_call(prompt_text, _project_specification_validator, "specification-expansion", schema)
        if not _project_specification_validator(data):
            raise StructuredOutputError("specification expansion failed semantic validation")
        return normalize_project_specification(raw_goal, contract, data)
    except StructuredOutputError as exc:
        RUN["specification_expansion_failures"] = RUN.get("specification_expansion_failures", 0) + 1
        fallback = specification_from_goal_contract(contract)
        record_run_event(
            "specification_expansion_fallback", label="specification-expansion", error=str(exc),
        )
        return fallback


def _verified_manifests_from_tasks():
    manifests = []
    for task in TASKS.values():
        if not isinstance(task, dict) or task.get("status") != "done":
            continue
        manifest = task.get("integration_manifest")
        if isinstance(manifest, dict):
            manifests.append(compact_manifest(manifest))
    return manifests[-MAX_BRAIN_ITEMS:]


def _initial_verified_project_state(repo_snapshot, repository_evidence=None):
    snapshot = repo_snapshot if isinstance(repo_snapshot, dict) else {}
    try:
        invariants = collect_project_invariants() if WORKSPACE is not None else RUN.get("project_invariants", [])
    except Exception:
        invariants = RUN.get("project_invariants", [])
    manifests = _verified_manifests_from_tasks()
    interfaces = []
    components = []
    integration_facts = []
    for manifest in manifests:
        components.extend(manifest.get("introduced_symbols", []))
        interfaces.extend(manifest.get("interfaces", []))
        integration_facts.extend(manifest.get("invariants", []))
    def accepted_repository_evidence(item):
        if stage2.validate_repository_evidence(item):
            return True
        # A Project Brain refresh may receive its own compact locator record.
        # It was admitted only after full direct-evidence validation; retain it
        # when path, hash, category, location, and provenance remain intact.
        return bool(
            isinstance(item, dict)
            and re.fullmatch(r"REPO-\d{3,}", str(item.get("evidence_id", "")))
            and item.get("category") in stage2.REPOSITORY_EVIDENCE_CATEGORIES
            and item.get("evidence_type") == stage2.DIRECT_OBSERVATION
            and item.get("provenance") == REPOSITORY_EVIDENCE
            and str(item.get("path", "")).strip()
            and str(item.get("fact", "")).strip()
            and str(item.get("file_sha256", "")).strip()
            and int(item.get("line_start", 0) or 0) >= 1
        )

    direct_evidence = [
        copy.deepcopy(item) for item in (repository_evidence or [])
        if accepted_repository_evidence(item)
    ][:MAX_TASK_BRAIN_EVIDENCE]

    def compact_repository_evidence(item):
        return {
            "evidence_id": item.get("evidence_id"),
            "fact": compact_text(item.get("fact", ""), 140),
            "category": item.get("category"),
            "path": compact_text(item.get("path", ""), 140),
            "symbol": compact_text(item.get("symbol", ""), 80) or None,
            "source_kind": item.get("source_kind"),
            "evidence_type": item.get("evidence_type"),
            "provenance": item.get("provenance"),
            "line_start": item.get("line_start"),
            "line_end": item.get("line_end"),
            "file_sha256": item.get("file_sha256"),
            "support": compact_text(item.get("support", "source-located observation"), 100),
        }
    components.extend(
        item.get("symbol") or item.get("path") for item in direct_evidence
        if item.get("category") in {"CURRENT_OWNER", "CURRENT_STATE_OWNER"}
    )
    interfaces.extend(
        item.get("symbol") or item.get("fact") for item in direct_evidence
        if item.get("category") == "CURRENT_INTERFACE"
    )
    return {
        "source": "deterministic_reconnaissance_and_verified_manifests",
        "provenance": VERIFIED,
        "files": _bounded_brain_records(snapshot.get("files", []), 24, 180),
        "languages": _bounded_brain_strings(snapshot.get("languages", []), 12, 80),
        "dependency_manifests": _bounded_brain_strings(snapshot.get("configs", []), 12, 180),
        "verified_components": _bounded_brain_strings(components, MAX_BRAIN_ITEMS, 220),
        "verified_interfaces": _bounded_brain_strings(interfaces, MAX_BRAIN_ITEMS, 260),
        "project_invariants": _bounded_brain_records(invariants, 12, MAX_INTEGRATION_FACT_CHARS),
        "verified_child_manifests": manifests,
        "integration_facts": _bounded_brain_strings(integration_facts, MAX_BRAIN_ITEMS, 260),
        "repository_evidence": [compact_repository_evidence(item) for item in direct_evidence],
        "blocking_failures": _bounded_brain_strings(
            RUN.get("project_brain_blocking_failures", []), MAX_BRAIN_ITEMS, 260,
        ),
    }


def _source_ledger_for_contract(contract):
    """Return a frozen ledger, adapting old v15 contracts without changing them."""
    contract = contract if isinstance(contract, dict) else {}
    supplied = contract.get("source_requirement_ledger")
    if isinstance(supplied, dict) and ledger_requirements(supplied):
        return freeze(thaw(supplied))
    candidates = []
    values = contract.get("source_requirements") or contract.get("requirements") or []
    for index, value in enumerate(values, 1):
        if isinstance(value, dict):
            candidate = dict(value)
            candidate.setdefault("source_segment", None)
        else:
            candidate = {"text": value, "source_segment": None}
        candidate.setdefault("provenance", USER_STATED)
        candidates.append(candidate)
    return build_source_requirement_ledger(candidates)


def _source_contract_for_brain(contract, ledger):
    supplied = contract.get("source_contract") if isinstance(contract, dict) else None
    source_contract = thaw(supplied) if isinstance(supplied, dict) else source_contract_from_ledger(
        contract.get("original_goal", contract.get("goal", "coding task")), ledger,
        confirmed=contract.get("user_confirmed_requirements", []),
        derived=contract.get("derived_assumptions", []),
        questions=contract.get("clarification_questions", []),
        answers=contract.get("clarification_answers", []),
        interaction_style=contract.get("interaction_style"),
    )
    source_contract["user_stated_requirements"] = ledger_requirements(ledger)
    source_contract.setdefault("user_confirmed_requirements", list(contract.get("user_confirmed_requirements", [])))
    source_contract.setdefault("derived_assumptions", list(contract.get("derived_assumptions", [])))
    source_contract["source_requirement_ledger"] = ledger
    source_contract["provenance_policy"] = {
        "USER_STATED": "explicitly present in the user request",
        "USER_CONFIRMED": "selected or written by the user in clarification",
        "DERIVED": "created by HIVO from an unanswered optional choice or planning inference",
        "VERIFIED": "proven by repository/tool/verification evidence",
    }
    return freeze(source_contract)


def build_project_brain(contract, specification, repo_snapshot=None, repository_evidence=None):
    """Create one bounded core plus a separate deterministic verified-state view."""
    contract = contract if isinstance(contract, dict) else {}
    source_ledger = _source_ledger_for_contract(contract)
    specification = normalize_project_specification(
        contract.get("original_goal", contract.get("goal", "coding task")), contract,
        specification or specification_from_goal_contract(contract),
    )
    coverage = specification_coverage(source_ledger, specification)
    retention = retention_summary(source_ledger, ledger_requirements(source_ledger), coverage)
    for key, value in retention.items():
        if key in RUN or key.startswith("source_") or key.startswith("retention_"):
            if key == "retention_numerator":
                RUN["source_requirement_retention_numerator"] = value
                RUN["source_requirement_retention_rate_numerator"] = value
            elif key == "retention_denominator":
                RUN["source_requirement_retention_denominator"] = value
                RUN["source_requirement_retention_rate_denominator"] = value
            else:
                RUN[key] = value
    quality_rules = _bounded_brain_strings(
        list(specification.get("quality_constraints", []))
        + list(specification.get("project_specific_coding_constraints", [])),
        MAX_BRAIN_ITEMS, 360,
    )
    core = {
        "root_goal": specification["root_goal"],
        "product_contract": {
            "goal": compact_text(contract.get("goal") or specification["root_goal"], 900),
            "requirements": _bounded_brain_strings(contract.get("requirements", []), MAX_BRAIN_ITEMS, 320),
            "source_requirement_ids": [
                item.get("requirement_id") for item in ledger_requirements(source_ledger)
            ],
            "constraints": _bounded_brain_strings(contract.get("constraints", []), MAX_BRAIN_ITEMS, 300),
            "user_visible_behavior": _bounded_brain_strings(
                specification.get("user_visible_behavior", []), MAX_BRAIN_ITEMS, 320,
            ),
            "acceptance_criteria": _bounded_brain_strings(
                specification.get("acceptance_criteria", []), MAX_BRAIN_ITEMS, 320,
            ),
            "success_criteria": _bounded_brain_strings(
                contract.get("success_criteria", []), MAX_BRAIN_ITEMS, 320,
            ),
        },
        "major_components": _bounded_brain_strings(
            list(specification.get("major_functional_areas", []))
            + list(specification.get("major_system_components", [])), MAX_BRAIN_ITEMS, 320,
        ),
        "architecture_invariants": _bounded_brain_strings(
            specification.get("architecture_invariants", []), MAX_BRAIN_ITEMS, 360,
        ),
        "state_ownership": _bounded_brain_strings(
            specification.get("state_ownership", []), MAX_BRAIN_ITEMS, 360,
        ),
        "interface_contracts": _bounded_brain_strings(
            specification.get("interface_contracts", []), MAX_BRAIN_ITEMS, 360,
        ),
        "project_specific_quality_rules": quality_rules,
        "interaction_contracts": _bounded_brain_strings(
            list(specification.get("interaction_model", []))
            + list(specification.get("ui_ux_expectations", []))
            + list(specification.get("persistence_requirements", [])),
            MAX_BRAIN_ITEMS, 360,
        ),
        "edge_cases": _bounded_brain_strings(
            specification.get("important_edge_cases", []), MAX_BRAIN_ITEMS, 320,
        ),
        "acceptance_criteria": _bounded_brain_strings(
            list(contract.get("success_criteria", []))
            + list(specification.get("acceptance_criteria", [])), MAX_BRAIN_ITEMS, 360,
        ),
        "non_goals": _bounded_brain_strings(specification.get("non_goals", []), MAX_BRAIN_ITEMS, 300),
        "explicit_assumptions": _bounded_brain_strings(
            specification.get("explicit_assumptions", []), MAX_BRAIN_ITEMS, 300,
        ),
        "derived_assumptions": _bounded_brain_records(
            contract.get("derived_assumptions", []), MAX_BRAIN_ITEMS, 360,
        ),
        "open_ambiguities": _bounded_brain_strings(
            specification.get("unresolved_critical_ambiguities", []), MAX_BRAIN_ITEMS, 300,
        ),
        "user_confirmed_requirements": _bounded_brain_records(
            contract.get("user_confirmed_requirements", []), MAX_BRAIN_ITEMS, 360,
        ),
    }
    verified_state = _initial_verified_project_state(repo_snapshot, repository_evidence)
    source_contract = _source_contract_for_brain(contract, source_ledger)
    RUN["source_requirement_ledger"] = source_ledger
    RUN["source_contract"] = source_contract
    brain = {
        "source_contract": source_contract,
        "source_requirement_ledger": source_ledger,
        "source_requirement_coverage": coverage,
        "derived_project_specification": copy.deepcopy(specification),
        "core": core,
        "verified_state": verified_state,
    }
    bounded = _bound_project_brain(brain)
    # The source contract is the immutable side of the Brain. Dynamic
    # verified-state facts remain mutable and are refreshed independently.
    bounded["source_contract"] = freeze(thaw(bounded.get("source_contract", {})))
    bounded["source_requirement_ledger"] = bounded["source_contract"].get(
        "source_requirement_ledger", source_ledger,
    )
    return bounded


def _bound_project_brain(brain, max_chars=MAX_PROJECT_BRAIN_CHARS):
    """Keep the structured Brain itself bounded, including nested contract lists."""
    brain = copy.deepcopy(brain if isinstance(brain, dict) else {})
    source_contract = brain.get("source_contract") if isinstance(brain.get("source_contract"), dict) else {}
    source_ledger = brain.get("source_requirement_ledger")
    if not isinstance(source_ledger, dict):
        source_ledger = source_contract.get("source_requirement_ledger", {})
    coverage = brain.get("source_requirement_coverage") if isinstance(
        brain.get("source_requirement_coverage"), list
    ) else []
    core = brain.get("core") if isinstance(brain.get("core"), dict) else {}
    state = brain.get("verified_state") if isinstance(brain.get("verified_state"), dict) else {}
    list_paths = [
        (core.get("product_contract", {}), "requirements"),
        (core.get("product_contract", {}), "constraints"),
        (core.get("product_contract", {}), "user_visible_behavior"),
        (core.get("product_contract", {}), "acceptance_criteria"),
        (core.get("product_contract", {}), "success_criteria"),
        (core, "explicit_assumptions"), (core, "derived_assumptions"),
        (core, "open_ambiguities"), (core, "non_goals"),
        (core, "edge_cases"), (core, "interaction_contracts"),
        (core, "project_specific_quality_rules"), (core, "interface_contracts"),
        (core, "state_ownership"), (core, "architecture_invariants"), (core, "major_components"),
        (state, "verified_child_manifests"), (state, "project_invariants"), (state, "files"),
        (state, "languages"), (state, "dependency_manifests"), (state, "verified_components"),
        (state, "verified_interfaces"), (state, "integration_facts"), (state, "blocking_failures"),
        (state, "repository_evidence"),
        (core, "user_confirmed_requirements"),
    ]
    encoded = json.dumps({"core": core, "verified_state": state}, ensure_ascii=False, default=str)
    while len(encoded) > max_chars:
        removed = False
        for section, field in list_paths:
            values = section.get(field) if isinstance(section, dict) else None
            if isinstance(values, list) and len(values) > 1:
                values.pop()
                removed = True
                break
        if removed:
            encoded = json.dumps({"core": core, "verified_state": state}, ensure_ascii=False, default=str)
            continue
        # The item count caps normally make this branch unreachable, but keep
        # the root anchor and first fact deterministic if a caller supplies an
        # unusually large custom record.
        changed = False
        for section, field in list_paths:
            values = section.get(field) if isinstance(section, dict) else None
            if isinstance(values, list) and values:
                shorter = _bounded_brain_strings(values, len(values), 180)
                if shorter != values:
                    section[field] = shorter
                    changed = True
                    break
        if changed:
            encoded = json.dumps({"core": core, "verified_state": state}, ensure_ascii=False, default=str)
            continue
        for section, field in list_paths:
            values = section.get(field) if isinstance(section, dict) else None
            if not isinstance(values, list) or not values:
                continue
            item_chars = max(24, max(len(str(item)) for item in values) // 2)
            if section is state and field in {"files", "project_invariants", "verified_child_manifests"}:
                shortened = _bounded_brain_records(values, len(values), item_chars)
            else:
                shortened = _bounded_brain_strings(values, len(values), item_chars)
            if shortened != values:
                section[field] = shortened
                changed = True
                break
        if changed:
            encoded = json.dumps({"core": core, "verified_state": state}, ensure_ascii=False, default=str)
            continue
        core["root_goal"] = compact_text(core.get("root_goal", "coding task"), max(40, max_chars // 4))
        product = core.get("product_contract")
        if isinstance(product, dict):
            product["goal"] = compact_text(product.get("goal", ""), max(40, max_chars // 5))
        encoded = json.dumps({"core": core, "verified_state": state}, ensure_ascii=False, default=str)
        if len(encoded) > max_chars:
            brain = {
                "source_contract": source_contract,
                "source_requirement_ledger": source_ledger,
                "source_requirement_coverage": coverage,
                "derived_project_specification": brain.get("derived_project_specification", {}),
                "core": {"root_goal": core.get("root_goal", "coding task")},
                "verified_state": {"source": "deterministic_reconnaissance_and_verified_manifests"},
            }
            core = brain["core"]
            state = brain["verified_state"]
        break
    brain["core"] = core
    brain["verified_state"] = state
    # These side channels are bounded at extraction/normalization time and are
    # deliberately kept outside the derived core's lossy item caps.
    brain["source_contract"] = source_contract
    brain["source_requirement_ledger"] = source_ledger
    brain["source_requirement_coverage"] = coverage[:MAX_SOURCE_REQUIREMENTS]
    if not isinstance(brain.get("derived_project_specification"), dict):
        brain["derived_project_specification"] = {}
    return brain


def refresh_project_brain_verified_state(repo_snapshot=None):
    """Refresh only the dynamic verified view; never amend the stable core."""
    brain = RUN.get("project_brain")
    if not isinstance(brain, dict) or not isinstance(brain.get("core"), dict):
        return None
    snapshot = repo_snapshot
    if snapshot is None:
        try:
            snapshot = inspect_repository()
        except Exception:
            snapshot = {}
    previous = brain.get("verified_state") if isinstance(brain.get("verified_state"), dict) else {}
    repository_evidence = RUN.get("repository_evidence")
    if not isinstance(repository_evidence, list):
        repository_evidence = previous.get("repository_evidence", [])
    brain["verified_state"] = _initial_verified_project_state(
        snapshot, repository_evidence,
    )
    return brain["verified_state"]


def prepare_project_brain(raw_goal, contract, repo_snapshot, specification=None, repository_evidence=None):
    """Prepare the recursive shared alignment anchor before decomposition."""
    if specification is None:
        specification = expand_project_specification(raw_goal, contract)
    brain = build_project_brain(
        contract, specification, repo_snapshot, repository_evidence=repository_evidence,
    )
    RUN["project_brain"] = brain
    record_run_event(
        "project_brain_created",
        root_goal=compact_text(brain.get("core", {}).get("root_goal", ""), 500),
        verified_file_count=len(brain.get("verified_state", {}).get("files", [])),
    )
    return brain


def _brain_terms(value):
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or "")).casefold()
    return {
        token for token in re.findall(r"[a-z0-9_$.-]{3,}", normalized)
        if token not in {"the", "and", "for", "with", "from", "use", "using", "current", "task", "one"}
    }


def _select_relevant_brain_items(values, query, max_items=MAX_BRAIN_ITEMS):
    values = list(values or [])
    query_terms = _brain_terms(query)
    if not query_terms:
        return values[:max_items]
    scored = []
    for index, item in enumerate(values):
        item_terms = _brain_terms(json.dumps(item, ensure_ascii=False, default=str))
        overlap = len(query_terms & item_terms)
        if overlap:
            scored.append((overlap, -index, item))
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = [item for _score, _index, item in scored[:max_items]]
    # Preserve source order after deterministic scoring so the projection is
    # stable and easy for a weak Worker to scan.
    selected_keys = {json.dumps(item, ensure_ascii=False, sort_keys=True, default=str) for item in selected}
    return [
        item for item in values
        if json.dumps(item, ensure_ascii=False, sort_keys=True, default=str) in selected_keys
    ][:max_items]


def _compact_brain_projection(projection, max_chars=MAX_BRAIN_PROJECTION_CHARS):
    projection = copy.deepcopy(projection if isinstance(projection, dict) else {})
    encoded = json.dumps(projection, ensure_ascii=False, default=str)
    trim_sections = [
        ("verified_state", "verified_child_manifests"),
        ("verified_state", "project_invariants"),
        ("verified_state", "blocking_failures"),
        ("verified_state", "integration_facts"),
        ("verified_state", "repository_evidence"),
        ("verified_state", "files"),
        ("relevant_core.product_contract", "requirements"),
        ("relevant_core", "source_requirements"),
        ("relevant_core.product_contract", "user_visible_behavior"),
        ("relevant_core.product_contract", "acceptance_criteria"),
        ("relevant_core", "acceptance_criteria"),
        ("relevant_core", "major_components"),
        ("relevant_core", "interaction_contracts"),
        ("relevant_core", "project_specific_quality_rules"),
        ("relevant_core", "interface_contracts"),
        ("relevant_core", "architecture_invariants"),
        ("relevant_core", "derived_assumptions"),
        ("relevant_core", "open_ambiguities"),
    ]
    while len(encoded) > max_chars:
        removed = False
        for section, field in trim_sections:
            section_value = projection
            for part in section.split("."):
                section_value = section_value.get(part, {}) if isinstance(section_value, dict) else {}
            values = section_value.get(field) if isinstance(section_value, dict) else None
            if isinstance(values, list) and len(values) > 1:
                values.pop()
                removed = True
                break
        if removed:
            encoded = json.dumps(projection, ensure_ascii=False, default=str)
            continue
        break
    if len(encoded) > max_chars:
        # A custom caller may provide one very large item per section, leaving
        # no list with length > 1 to trim.  Drop optional facts first and keep
        # the root/task anchors intact.
        for section, field in trim_sections:
            section_value = projection
            for part in section.split("."):
                section_value = section_value.get(part, {}) if isinstance(section_value, dict) else {}
            values = section_value.get(field) if isinstance(section_value, dict) else None
            if isinstance(values, list) and values:
                values.clear()
                encoded = json.dumps(projection, ensure_ascii=False, default=str)
                if len(encoded) <= max_chars:
                    break
        if len(encoded) > max_chars:
            current = projection.get("current_task", {})
            if isinstance(current, dict):
                current["goal"] = compact_text(current.get("goal", ""), 260)
                current["done_when"] = _bounded_brain_strings(current.get("done_when", []), 2, 120)
                current["scope_hint"] = _bounded_brain_strings(current.get("scope_hint", []), 2, 100)
            projection["root_goal_anchor"] = compact_text(projection.get("root_goal_anchor", ""), 420)
            encoded = json.dumps(projection, ensure_ascii=False, default=str)
    if len(encoded) > max_chars:
        projection = {
            "root_goal_anchor": compact_text(projection.get("root_goal_anchor", "coding task"), max(40, max_chars // 4)),
            "current_task": {
                "id": compact_text((projection.get("current_task") or {}).get("id", ""), 80),
                "goal": compact_text((projection.get("current_task") or {}).get("goal", ""), max(40, max_chars // 5)),
            },
            "relevant_core": {},
            "verified_state": {},
        }
    return projection


def build_brain_projection(brain, task, dependency_summaries=None, repo_snapshot=None, record=True):
    """Select only task-relevant core and verified-state facts deterministically."""
    if not isinstance(brain, dict):
        return {}
    core = brain.get("core") if isinstance(brain.get("core"), dict) else {}
    state = brain.get("verified_state") if isinstance(brain.get("verified_state"), dict) else {}
    task = task if isinstance(task, dict) else {}
    query = " ".join([
        str(task.get("goal", "")),
        " ".join(str(item) for item in task.get("done_when", []) or []),
        " ".join(str(item) for item in task.get("scope_hint", []) or []),
    ])
    is_root = str(task.get("id", "")) == "ROOT" or int(task.get("depth", 0) or 0) == 0
    core_projection = {
        "architecture_invariants": _select_relevant_brain_items(
            core.get("architecture_invariants", []), query if not is_root else "", MAX_BRAIN_ITEMS,
        ),
        "state_ownership": _select_relevant_brain_items(
            core.get("state_ownership", []), query if not is_root else "", MAX_BRAIN_ITEMS,
        ),
        "interface_contracts": _select_relevant_brain_items(
            core.get("interface_contracts", []), query if not is_root else "", MAX_BRAIN_ITEMS,
        ),
        "project_specific_quality_rules": _select_relevant_brain_items(
            core.get("project_specific_quality_rules", []), query if not is_root else "", MAX_BRAIN_ITEMS,
        ),
        "interaction_contracts": _select_relevant_brain_items(
            core.get("interaction_contracts", []), query if not is_root else "", MAX_BRAIN_ITEMS,
        ),
        "edge_cases": _select_relevant_brain_items(
            core.get("edge_cases", []), query if not is_root else "", MAX_BRAIN_ITEMS,
        ),
        "major_components": _select_relevant_brain_items(
            core.get("major_components", []), query if not is_root else "", MAX_BRAIN_ITEMS,
        ),
        "acceptance_criteria": _select_relevant_brain_items(
            core.get("acceptance_criteria", []), query if not is_root else "", MAX_BRAIN_ITEMS,
        ),
        "non_goals": _select_relevant_brain_items(
            core.get("non_goals", []), query if not is_root else "", MAX_BRAIN_ITEMS,
        ),
        "explicit_assumptions": _select_relevant_brain_items(
            core.get("explicit_assumptions", []), query if not is_root else "", MAX_BRAIN_ITEMS,
        ),
        "derived_assumptions": _select_relevant_brain_items(
            core.get("derived_assumptions", []), query if not is_root else "", MAX_BRAIN_ITEMS,
        ),
        "open_ambiguities": _select_relevant_brain_items(
            core.get("open_ambiguities", []), query if not is_root else "", MAX_BRAIN_ITEMS,
        ),
    }
    product = core.get("product_contract") if isinstance(core.get("product_contract"), dict) else {}
    selection_query = query if not is_root else ""
    source_records = ledger_requirements(
        brain.get("source_requirement_ledger")
        or (brain.get("source_contract") or {}).get("source_requirement_ledger")
    )
    coverage_by_id = {
        str(item.get("requirement_id")): item for item in brain.get("source_requirement_coverage", [])
        if isinstance(item, dict)
    }
    relevant_source_records = _select_relevant_brain_items(
        source_records, selection_query, 4,
    )
    relevant_source = [{
        "requirement_id": item.get("requirement_id"),
        "text": compact_text(item.get("text", ""), 360),
        "provenance": item.get("provenance", USER_STATED),
        "source_segments": item.get("source_segments", [item.get("source_segment")]),
        "coverage": coverage_by_id.get(str(item.get("requirement_id")), {}).get("status", "UNKNOWN"),
    } for item in relevant_source_records]
    product_projection = {
        "requirements": _select_relevant_brain_items(
            product.get("requirements", []), selection_query, MAX_BRAIN_ITEMS,
        ),
        "user_visible_behavior": _select_relevant_brain_items(
            product.get("user_visible_behavior", []), selection_query, MAX_BRAIN_ITEMS,
        ),
        "acceptance_criteria": _select_relevant_brain_items(
            product.get("acceptance_criteria", []), selection_query, MAX_BRAIN_ITEMS,
        ),
    }
    snapshot = repo_snapshot if isinstance(repo_snapshot, dict) else {}
    state_files = state.get("files", [])
    if not state_files and snapshot:
        state_files = snapshot.get("files", [])
    dependencies = []
    for item in list(dependency_summaries or [])[-MAX_INTEGRATION_MANIFEST_ITEMS:]:
        if isinstance(item, dict) and str(item.get("status", "")).casefold() in {"done", "verified", "passed"}:
            if is_root or _select_relevant_brain_items([item], query, 1):
                dependencies.append(_compact_brain_record(item, 700))
    projection = {
        "root_goal_anchor": compact_text(core.get("root_goal", ""), 1000),
        "current_task": {
            "id": str(task.get("id", ""))[:80],
            "goal": compact_text(task.get("goal", ""), 1100),
            "done_when": _bounded_brain_strings(task.get("done_when", []), 6, 260),
            "scope_hint": _bounded_brain_strings(task.get("scope_hint", []), 5, 180),
        },
        "relevant_core": {
            "product_contract": product_projection,
            "source_requirements": relevant_source,
            **core_projection,
        },
        "verified_state": {
            "files": _select_relevant_brain_items(state_files, query, 12),
            "dependency_manifests": _bounded_brain_strings(state.get("dependency_manifests", []), 8, 180),
            "project_invariants": _select_relevant_brain_items(
                state.get("project_invariants", []), query, 8,
            ),
            "verified_components": _select_relevant_brain_items(
                state.get("verified_components", []), query, 8,
            ),
            "verified_interfaces": _select_relevant_brain_items(
                state.get("verified_interfaces", []), query, 8,
            ),
            "integration_facts": _select_relevant_brain_items(
                state.get("integration_facts", []), query, 8,
            ),
            "repository_evidence": _select_relevant_brain_items(
                state.get("repository_evidence", []), query, 8,
            ),
            "blocking_failures": _bounded_brain_strings(
                state.get("blocking_failures", []), 8, 260,
            ),
            "verified_child_manifests": _select_relevant_brain_items(
                state.get("verified_child_manifests", []), query, 4,
            ),
            "dependencies": dependencies,
        },
    }
    projection = _compact_brain_projection(projection)
    if record:
        RUN["brain_projections_created"] = RUN.get("brain_projections_created", 0) + 1
    return projection


# Clear public aliases make the architecture explicit to deterministic tests
# and callers without introducing another state or memory system.
project_brain_projection = build_brain_projection


def compact_project_brain(brain=None, max_chars=MAX_PROJECT_BRAIN_CHARS):
    """Serialize the bounded brain for planning prompts, never raw history."""
    brain = brain if isinstance(brain, dict) else RUN.get("project_brain")
    if not isinstance(brain, dict):
        return "(project brain not prepared)"
    bounded_brain = _bound_project_brain(brain, max_chars=max_chars)
    raw_source_contract = copy.deepcopy(bounded_brain.get("source_contract", {}))
    if isinstance(raw_source_contract, dict):
        # The nested ledger is retained in the Brain object. The root planner
        # receives all source IDs/text with only the provenance needed to
        # audit them, without repeating variants and status fields.
        source_contract = {
            "root_goal": raw_source_contract.get("root_goal", "coding task"),
            "user_stated_requirements": [
                {"requirement_id": item.get("requirement_id"), "text": item.get("text", ""),
                 "category": item.get("category"), "provenance": item.get("provenance", USER_STATED),
                 "source_segment": item.get("source_segment")}
                for item in raw_source_contract.get("user_stated_requirements", [])
                if isinstance(item, dict)
            ],
            "user_confirmed_requirements": raw_source_contract.get("user_confirmed_requirements", []),
            "derived_assumptions": raw_source_contract.get("derived_assumptions", []),
        }
    else:
        source_contract = {}
    source_coverage = copy.deepcopy(bounded_brain.get("source_requirement_coverage", []))
    core = copy.deepcopy(bounded_brain.get("core", {}))
    state = copy.deepcopy(bounded_brain.get("verified_state", {}))
    for field in ("major_components", "architecture_invariants", "state_ownership", "interface_contracts",
                  "project_specific_quality_rules", "interaction_contracts", "edge_cases", "acceptance_criteria",
                  "non_goals", "explicit_assumptions", "derived_assumptions", "open_ambiguities"):
        if isinstance(core.get(field), list):
            core[field] = _bounded_brain_strings(core[field], MAX_BRAIN_ITEMS, 300)
    for field in ("files", "project_invariants", "verified_child_manifests", "repository_evidence"):
        if isinstance(state.get(field), list):
            state[field] = _bounded_brain_records(state[field], 12, 240)

    def encode_packet():
        return json.dumps({
            "source_contract": source_contract,
            "source_requirement_coverage": source_coverage,
            "core": core, "verified_state": state,
        }, ensure_ascii=False, default=str)

    encoded = encode_packet()
    if len(encoded) > max_chars and isinstance(source_contract, dict):
        # Keep every source ID in the root packet while compacting only the
        # prompt copy. The immutable Brain still retains full source text,
        # variants, provenance, and locations.
        original_source_records = list(source_contract.get("user_stated_requirements", []))
        for text_limit in (300, 180, 100, 60, 30, 0):
            compacted_source = []
            for item in original_source_records:
                if not isinstance(item, dict):
                    continue
                compacted = {"requirement_id": item.get("requirement_id")}
                if text_limit:
                    compacted.update({
                        "text": compact_text(item.get("text", ""), text_limit),
                        "provenance": item.get("provenance", USER_STATED),
                        "source_segment": item.get("source_segment"),
                    })
                compacted_source.append(compacted)
            source_contract["user_stated_requirements"] = compacted_source
            encoded = encode_packet()
            if len(encoded) <= max_chars:
                break
        if len(encoded) > max_chars:
            source_coverage = [{
                "requirement_id": item.get("requirement_id"),
                "status": item.get("status", "UNKNOWN"),
            } for item in source_coverage if isinstance(item, dict)]
            encoded = encode_packet()
    trim_order = [
        (state, "verified_child_manifests"), (state, "project_invariants"),
        (state, "repository_evidence"), (state, "files"),
        (core, "explicit_assumptions"), (core, "derived_assumptions"),
        (core, "open_ambiguities"), (core, "non_goals"),
        (core, "interaction_contracts"), (core, "edge_cases"),
        (core, "project_specific_quality_rules"),
        (core, "interface_contracts"), (core, "state_ownership"), (core, "architecture_invariants"),
        (core, "major_components"), (source_contract, "clarification_questions"),
        (source_contract, "clarification_answers"), (source_contract, "derived_assumptions"),
    ]
    while len(encoded) > max_chars:
        removed = False
        for section, field in trim_order:
            values = section.get(field)
            if isinstance(values, list) and len(values) > 1:
                values.pop()
                removed = True
                break
        if removed:
            encoded = encode_packet()
            continue
        break
    if len(encoded) > max_chars:
        compact_source = [
            {"requirement_id": item.get("requirement_id")}
            for item in source_contract.get("user_stated_requirements", [])
            if isinstance(item, dict)
        ] if isinstance(source_contract, dict) else []
        encoded = json.dumps({
            "source_contract": {
                "root_goal": source_contract.get("root_goal", "coding task"),
                "user_stated_requirements": compact_source,
                "user_confirmed_requirements": source_contract.get("user_confirmed_requirements", []),
            },
            "source_requirement_coverage": [
                {"requirement_id": item.get("requirement_id"), "status": item.get("status", "UNKNOWN")}
                for item in source_coverage if isinstance(item, dict)
            ],
            "core": {"root_goal": compact_text(core.get("root_goal", "coding task"), max(40, max_chars // 4))},
            "verified_state": {"source": state.get("source", "deterministic_reconnaissance_and_verified_manifests")},
        }, ensure_ascii=False, default=str)
    return encoded


def project_brain_planning_packet(max_chars=MAX_PROJECT_BRAIN_CHARS):
    return compact_project_brain(RUN.get("project_brain"), max_chars=max_chars)


def project_brain_task_planning_packet(task, dependency_summaries=None, repo_snapshot=None,
                                      max_chars=MAX_PROJECT_BRAIN_CHARS):
    """Give root planning the full Brain and child planning a task projection."""
    brain = RUN.get("project_brain")
    if not isinstance(brain, dict):
        return "(project brain not prepared)"
    task = task if isinstance(task, dict) else {}
    is_root = str(task.get("id", "")) == "ROOT" or int(task.get("depth", 0) or 0) == 0
    task_brain = RUN.get("task_brain")
    if isinstance(task_brain, dict):
        project_budget = max(600, int(max_chars * 0.52))
        task_budget = max(500, max_chars - project_budget - 500)
        projection = build_brain_projection(
            brain, task, dependency_summaries, repo_snapshot, record=False,
        )
        envelope = {
            "root_goal_anchor": compact_text(brain.get("core", {}).get("root_goal", ""), 800),
            "relevant_source_requirements": projection.get("relevant_core", {}).get(
                "source_requirements", []
            ),
            "project_brain_projection": _compact_brain_projection(
                projection, max_chars=project_budget,
            ),
            "task_brain_slice": stage2.task_brain_projection(
                task_brain, task, max_chars=task_budget,
            ),
            "verified_dependencies": [
                _compact_brain_record(item, 360) for item in list(dependency_summaries or [])[-3:]
                if isinstance(item, dict)
                and str(item.get("status", "")).casefold() in {"done", "verified", "passed"}
            ],
        }
        encoded = json.dumps(envelope, ensure_ascii=False, default=str)
        if len(encoded) > max_chars:
            envelope["verified_dependencies"] = []
            envelope["task_brain_slice"] = stage2.task_brain_projection(
                task_brain, task, max_chars=max(400, task_budget // 2),
            )
            envelope["project_brain_projection"] = _compact_brain_projection(
                projection, max_chars=max(500, project_budget // 2),
            )
            encoded = json.dumps(envelope, ensure_ascii=False, default=str)
        return encoded if len(encoded) <= max_chars else json.dumps({
            "root_goal_anchor": envelope["root_goal_anchor"],
            "task_brain_slice": {
                "task_id": task_brain.get("task_id"),
                "project_mode": task_brain.get("project_mode"),
                "source_requirement_ids": task_brain.get("source_requirement_ids", []),
            },
        }, ensure_ascii=False, default=str)[:max_chars]
    if is_root:
        return compact_project_brain(brain, max_chars=max_chars)
    projection = build_brain_projection(
        brain, task, dependency_summaries, repo_snapshot, record=False,
    )
    return json.dumps(
        _compact_brain_projection(projection, max_chars=max_chars),
        ensure_ascii=False, default=str,
    )


def classify_project_mode(raw_goal, workspace=None, repo_snapshot=None):
    """Public deterministic Stage 2 project/workspace classification."""
    selected_workspace = workspace if workspace is not None else WORKSPACE
    inventory = stage2.inventory_repository(selected_workspace) if selected_workspace is not None else {
        "status": REPOSITORY_EVIDENCE_UNAVAILABLE, "files": [], "meaningful_files": [],
    }
    classification_source = inventory
    if inventory.get("status") == REPOSITORY_EVIDENCE_UNAVAILABLE and isinstance(repo_snapshot, dict):
        classification_source = repo_snapshot
    result = stage2.classify_project_mode(raw_goal, classification_source)
    result["inventory"] = inventory
    return result


def _repository_scout_schema():
    return {
        "type": "object", "properties": {
            "paths": {
                "type": "array", "items": {"type": "string"},
                "maxItems": MAX_TARGETED_RECON_FILES,
            },
        }, "required": ["paths"], "additionalProperties": False,
    }


def _repository_scout_validator(data):
    return bool(
        isinstance(data, dict) and isinstance(data.get("paths"), list)
        and len(data.get("paths", [])) <= MAX_TARGETED_RECON_FILES
        and all(isinstance(item, str) and item.strip() for item in data.get("paths", []))
    )


def _repository_scout_prompt(context):
    return f"""You are RECON AGENT, a narrow read-only repository evidence selector.
Given the current task, Source Requirement terms, a bounded metadata inventory, and deterministic search results,
select only paths that should be inspected to understand current owners, interfaces, state, constraints, or tests.
Do not write code, plan implementation, decide the final change surface, create Worker missions, or invent files.
Return at most {MAX_TARGETED_RECON_FILES} paths that are present in the supplied inventory.

BOUNDED RECONNAISSANCE CONTEXT:
{compact_text(json.dumps(context, ensure_ascii=False, default=str), 5200)}"""


def run_repository_reconnaissance(raw_goal, contract=None, workspace=None, inventory=None,
                                  structured_call=None, use_model_scout=True):
    """Run and account for bounded read-only Stage 2 reconnaissance."""
    selected_workspace = workspace if workspace is not None else WORKSPACE
    contract = contract if isinstance(contract, dict) else {}
    source_records = ledger_requirements(contract.get("source_requirement_ledger"))

    def scout_selector(context):
        if not use_model_scout or RUN.get("recon_agent_calls", 0) >= MAX_RECON_MODEL_CALLS:
            return []
        RUN["recon_agent_calls"] = RUN.get("recon_agent_calls", 0) + 1
        try:
            if structured_call is None:
                data = structured_model_call(
                    _repository_scout_prompt(context), _repository_scout_validator,
                    "repository-scout", _repository_scout_schema(), retries=1, role="ReconAgent",
                )
            else:
                data = structured_call(
                    _repository_scout_prompt(context), _repository_scout_validator,
                    "repository-scout", _repository_scout_schema(),
                )
            if not _repository_scout_validator(data):
                raise StructuredOutputError("ReconAgent returned an invalid path selection")
            allowed = {
                str(item.get("path")) for item in context.get("inventory", []) if isinstance(item, dict)
            }
            return [path for path in data.get("paths", []) if path in allowed]
        except (ProviderError, StructuredOutputError, KeyError, TypeError, ValueError) as exc:
            record_run_event("recon_agent_unavailable", error=str(exc))
            return []

    RUN["repository_reconnaissance_runs"] = RUN.get("repository_reconnaissance_runs", 0) + 1
    result = stage2.run_repository_reconnaissance(
        selected_workspace, raw_goal, source_requirements=source_records,
        inventory=inventory, scout_selector=scout_selector if use_model_scout else None,
    )
    RUN["repository_searches"] = RUN.get("repository_searches", 0) + int(result.get("searches", 0) or 0)
    RUN["repository_files_considered"] = RUN.get("repository_files_considered", 0) + int(
        result.get("files_considered", len((result.get("inventory") or {}).get("files", []))) or 0
    )
    RUN["repository_files_inspected"] = RUN.get("repository_files_inspected", 0) + int(
        result.get("files_inspected", 0) or 0
    )
    RUN["repository_evidence_records"] = RUN.get("repository_evidence_records", 0) + len(
        result.get("evidence", [])
    )
    for metric, result_key in (
        ("repository_evidence_candidates", "evidence_candidates"),
        ("repository_evidence_validated", "evidence_validated"),
        ("repository_evidence_deduplicated", "evidence_deduplicated"),
        ("repository_evidence_selected", "evidence_selected"),
        ("repository_evidence_rejected", "evidence_rejected"),
        ("repository_evidence_rejected_duplicates", "evidence_rejected_duplicates"),
        ("repository_evidence_truncated_valid", "evidence_truncated_valid"),
    ):
        RUN[metric] = RUN.get(metric, 0) + int(result.get(result_key, 0) or 0)
    RUN["repository_reconnaissance"] = result
    RUN["repository_evidence"] = result.get("evidence", [])
    record_run_event(
        "repository_reconnaissance",
        status=result.get("status"), searches=result.get("searches", 0),
        files_considered=result.get("files_considered", 0),
        files_inspected=result.get("files_inspected", 0),
        evidence_count=len(result.get("evidence", [])), read_only=result.get("read_only"),
        operations=result.get("operations", []),
    )
    return result


repository_reconnaissance = run_repository_reconnaissance


def repository_grounded_clarification(raw_goal, contract, reconnaissance):
    """Return only valid evidence-linked Stage 2 questions."""
    contract = contract if isinstance(contract, dict) else {}
    source_records = ledger_requirements(contract.get("source_requirement_ledger"))
    evidence = list((reconnaissance or {}).get("evidence", []) or [])
    valid_requirement_ids = {str(item.get("requirement_id")) for item in source_records}
    valid_evidence_ids = {str(item.get("evidence_id")) for item in evidence}
    questions = []
    for raw_question in stage2.repository_grounded_questions(raw_goal, source_records, evidence):
        if not stage2.validate_repository_question(
            raw_question, valid_requirement_ids, valid_evidence_ids,
        ):
            continue
        normalized = normalize_question(
            raw_question, len(questions) + 1, contract.get("source_requirement_ledger"),
            "PRECISION_SENSITIVE", [],
        )
        if not normalized:
            continue
        normalized["question_id"] = raw_question.get("question_id", normalized.get("question_id"))
        normalized["phase"] = "REPOSITORY_GROUNDED_CLARIFICATION"
        normalized["repository_evidence_ids"] = list(raw_question.get("repository_evidence_ids", []))[:8]
        if stage2.validate_repository_question(
            normalized, valid_requirement_ids, valid_evidence_ids,
        ):
            questions.append(normalized)
    questions = questions[:MAX_CLARIFICATION_QUESTIONS]
    if questions:
        RUN["repo_grounded_clarification_questions"] = RUN.get(
            "repo_grounded_clarification_questions", 0,
        ) + len(questions)
        RUN["user_clarification_rounds"] = RUN.get("user_clarification_rounds", 0) + 1
        RUN["user_clarification_questions"] = RUN.get("user_clarification_questions", 0) + len(questions)
        RUN["clarification_questions"] = RUN.get("clarification_questions", 0) + len(questions)
    envelope = {
        "questions": questions, "conflicts": [],
        "interaction_style": "PRECISION_SENSITIVE",
        "phase": "REPOSITORY_GROUNDED_CLARIFICATION",
    }
    RUN["pending_repository_clarification"] = envelope
    record_run_event(
        "repository_clarification_gate_evaluated",
        question_ids=[item.get("question_id") for item in questions],
        repository_evidence_ids=[
            evidence_id for item in questions
            for evidence_id in item.get("repository_evidence_ids", [])
        ],
    )
    return envelope


def _contract_with_repository_decisions(raw_goal, contract, clarification, resolution):
    updated = copy.deepcopy(contract if isinstance(contract, dict) else {})
    previous_answers = list(updated.get("user_confirmed_requirements", []) or [])
    repo_answers = list(resolution.get("answers", []) or [])
    answers = previous_answers + repo_answers
    ledger = _ledger_with_confirmed_answers(updated.get("source_requirement_ledger"), repo_answers)
    derived = list(updated.get("derived_assumptions", []) or []) + list(resolution.get("derived", []) or [])
    questions = list(updated.get("clarification_questions", []) or []) + list(
        clarification.get("questions", []) or []
    )
    clarification_answers = list(updated.get("clarification_answers", []) or []) + repo_answers
    updated["source_requirement_ledger"] = ledger
    updated["source_requirements"] = ledger_requirements(ledger)
    updated["user_stated_requirements"] = ledger_requirements(ledger)
    updated["user_confirmed_requirements"] = answers
    updated["derived_assumptions"] = derived
    updated["clarification_questions"] = questions
    updated["clarification_answers"] = clarification_answers
    updated["repository_clarification_answers"] = repo_answers
    updated["requirements"] = list(updated.get("requirements", []) or [])
    for answer in repo_answers:
        value = str(answer.get("answer", "")).strip()
        if value and value not in updated["requirements"]:
            updated["requirements"].append(value)
    updated["source_contract"] = source_contract_from_ledger(
        raw_goal, ledger, confirmed=answers, derived=derived,
        questions=questions, answers=clarification_answers,
        interaction_style=updated.get("interaction_style"),
    )
    RUN["source_requirement_ledger"] = ledger
    RUN["source_contract"] = updated["source_contract"]
    RUN["clarification_answers"] = clarification_answers
    return updated


def create_task_brain(task_id, raw_goal, contract, project_brain, project_mode,
                      repository_evidence=None, open_questions=None):
    """Create, validate, and persist exactly one top-level Task Brain."""
    source_contract = contract.get("source_contract") if isinstance(contract, dict) else {}
    task_goal = (
        source_contract.get("root_goal") if isinstance(source_contract, dict) else None
    ) or next((line.strip() for line in str(raw_goal or "").splitlines() if line.strip()), raw_goal)
    projection_task = root_task_from_contract(contract)
    project_projection = build_brain_projection(
        project_brain, projection_task, repo_snapshot={}, record=False,
    )
    brain = stage2.build_task_brain(
        task_id, task_goal, project_mode, contract,
        project_brain_projection=project_projection,
        repository_evidence=repository_evidence,
        open_questions=open_questions,
    )
    valid_requirement_ids = [
        item.get("requirement_id")
        for item in ledger_requirements(contract.get("source_requirement_ledger"), include_confirmed=True)
    ]
    validation = stage2.validate_task_brain(
        brain, valid_requirement_ids=valid_requirement_ids,
        repository_evidence=repository_evidence,
    )
    RUN["task_brain_validation"] = validation
    if not validation.get("valid"):
        RUN["task_brain_creation_failures"] = RUN.get("task_brain_creation_failures", 0) + 1
        record_run_event("task_brain_creation_failure", errors=validation.get("errors", []))
        raise TaskBrainValidationError("; ".join(validation.get("errors", [])))
    RUN["task_brain"] = brain
    RUN["task_brains_created"] = RUN.get("task_brains_created", 0) + 1
    record_run_event(
        "task_brain_created", task_id=task_id, project_mode=project_mode,
        serialized_chars=validation.get("serialized_chars"), task_brain=brain,
    )
    return brain


build_task_brain = create_task_brain
validate_task_brain = stage2.validate_task_brain
task_brain_projection = stage2.task_brain_projection


def _record_project_mode(classification):
    mode = classification.get("project_mode")
    if RUN.get("project_mode") != mode:
        if mode == NEW_PROJECT:
            RUN["project_mode_new"] = RUN.get("project_mode_new", 0) + 1
        elif mode == EXISTING_PROJECT:
            RUN["project_mode_existing"] = RUN.get("project_mode_existing", 0) + 1
    RUN["project_mode"] = mode
    RUN["project_mode_classification"] = {
        key: value for key, value in classification.items() if key != "inventory"
    }


def prepare_stage2_context(raw_goal, contract, repo_snapshot=None, interactive=True,
                           supplied_contract=False, specification_override=None,
                           recon_structured_call=None, terminal_available=None,
                           selector=None, answer_reader=None):
    """Prepare verified current-state evidence and one Task Brain before planning."""
    RUN.setdefault("control_flow", []).append("PROJECT_MODE_CLASSIFICATION")
    classification = classify_project_mode(raw_goal, repo_snapshot=repo_snapshot)
    _record_project_mode(classification)
    mode = classification.get("project_mode")
    inventory = classification.get("inventory") or {}
    if mode == EXISTING_PROJECT:
        RUN.setdefault("control_flow", []).append("REPOSITORY_RECONNAISSANCE")
        reconnaissance = run_repository_reconnaissance(
            raw_goal, contract, inventory=inventory,
            structured_call=recon_structured_call, use_model_scout=True,
        )
        if reconnaissance.get("status") != REPOSITORY_RECONNAISSANCE_COMPLETE:
            return {
                "status": "failed", "failure_type": "ORCHESTRATION_FAILURE",
                "orchestration_failure": reconnaissance.get("status"),
                "summary": reconnaissance.get("error") or (
                    "required existing-project repository evidence is unavailable"
                ),
                "project_mode": mode, "classification": classification,
                "reconnaissance": reconnaissance,
            }
        if reconnaissance.get("read_only") is not True:
            return {
                "status": "failed", "failure_type": "ORCHESTRATION_FAILURE",
                "orchestration_failure": REPOSITORY_RECONNAISSANCE_FAILED,
                "summary": "repository state changed during read-only reconnaissance",
                "project_mode": mode, "classification": classification,
                "reconnaissance": reconnaissance,
            }
        RUN.setdefault("control_flow", []).append("REPOSITORY_GROUNDED_CLARIFICATION")
        clarification = repository_grounded_clarification(raw_goal, contract, reconnaissance)
        resolution = resolve_clarification_questions(
            clarification, interactive=interactive, terminal_available=terminal_available,
            selector=selector, answer_reader=answer_reader,
        )
        if resolution.get("status") == "clarification_required":
            RUN["repository_clarification_required"] = {
                "phase": "REPOSITORY_GROUNDED_CLARIFICATION",
                "questions": clarification.get("questions", []),
                "requirement_ids": [
                    requirement_id for item in clarification.get("questions", [])
                    for requirement_id in item.get("affected_requirement_ids", [])
                ],
                "repository_evidence_ids": [
                    evidence_id for item in clarification.get("questions", [])
                    for evidence_id in item.get("repository_evidence_ids", [])
                ],
            }
            return {
                "status": "clarification_required", "terminal_state": "CLARIFICATION_REQUIRED",
                "phase": "REPOSITORY_GROUNDED_CLARIFICATION",
                "summary": clarification.get("questions", [{}])[0].get(
                    "question", "repository-grounded clarification required",
                ),
                "clarification_questions": clarification.get("questions", []),
                "project_mode": mode, "classification": classification,
                "reconnaissance": reconnaissance, "contract": contract,
            }
        contract = _contract_with_repository_decisions(raw_goal, contract, clarification, resolution)
    else:
        RUN.setdefault("control_flow", []).append("REPOSITORY_RECONNAISSANCE_SKIPPED")
        RUN["repository_reconnaissance_skipped"] = RUN.get("repository_reconnaissance_skipped", 0) + 1
        reconnaissance = {
            "status": REPOSITORY_EMPTY, "inventory": inventory, "evidence": [],
            "operations": [{"operation": "INVENTORY", "result": REPOSITORY_EMPTY}],
            "read_only": True,
        }
        RUN["repository_reconnaissance"] = reconnaissance
        RUN["repository_evidence"] = []
        clarification = {
            "questions": [], "phase": "REPOSITORY_GROUNDED_CLARIFICATION",
            "interaction_style": "LOW_FRICTION",
        }
    repository_summary = stage2.bounded_repository_summary(reconnaissance, mode)
    RUN.setdefault("control_flow", []).append("SPECIFICATION_EXPANSION")
    if specification_override is not None:
        specification = specification_override
    elif supplied_contract:
        specification = specification_from_goal_contract(contract)
    elif mode == EXISTING_PROJECT:
        specification = expand_project_specification(
            raw_goal, contract, repository_summary=repository_summary,
        )
    else:
        specification = expand_project_specification(raw_goal, contract)
    RUN.setdefault("control_flow", []).append("PROJECT_BRAIN")
    project_brain = prepare_project_brain(
        raw_goal, contract, repo_snapshot or {}, specification=specification,
        repository_evidence=reconnaissance.get("evidence", []),
    )
    RUN.setdefault("control_flow", []).append("TASK_BRAIN")
    try:
        task_brain = create_task_brain(
            "ROOT", raw_goal, contract, project_brain, mode,
            repository_evidence=reconnaissance.get("evidence", []),
            open_questions=clarification.get("questions", []),
        )
    except TaskBrainValidationError as exc:
        return {
            "status": "failed", "failure_type": "ORCHESTRATION_FAILURE",
            "orchestration_failure": "TASK_BRAIN_VALIDATION_FAILURE",
            "summary": str(exc), "project_mode": mode,
            "classification": classification, "reconnaissance": reconnaissance,
        }
    return {
        "status": "ready", "project_mode": mode, "classification": classification,
        "reconnaissance": reconnaissance, "repository_summary": repository_summary,
        "contract": contract, "specification": specification,
        "project_brain": project_brain, "task_brain": task_brain,
    }


# ---------------------------------------------------------------------------
# STAGE 3: EVIDENCE-GROUNDED IMPACT PLANNING
# ---------------------------------------------------------------------------

impact_map_schema = stage3.impact_map_schema
impact_challenge_schema = stage3.challenge_schema
canonical_surface_registry_schema = stage3.canonical_surface_registry_schema
build_canonical_surface_registry = stage3.build_canonical_surface_registry
build_impact_seeds = stage3.build_impact_seeds
surface_bound_impact_seeds = stage3.surface_bound_impact_seeds
select_task_relevant_surfaces = stage3.select_task_relevant_surfaces
validate_impact_seeds = stage3.validate_impact_seeds
normalize_impact_id = stage3.normalize_impact_id
build_canonical_planning_packet = stage3.build_canonical_planning_packet
build_complete_planning_packet = stage3.build_complete_planning_packet
build_planner_packet = stage3.build_planner_packet
validate_planning_packet = stage3.validate_planning_packet
bind_impact_decisions_to_seeds = stage3.bind_impact_decisions_to_seeds
hydrate_impact_map = stage3.hydrate_impact_map
audit_impact_surfaces = stage3.audit_impact_surfaces
derive_do_not_touch_surface_ids = stage3.derive_do_not_touch_surface_ids
validate_impact_map = stage3.validate_impact_map
validate_impact_challenges = stage3.validate_challenges
validate_change_plan = stage3.validate_change_plan
plan_content_hash = stage3.plan_content_hash
approval_is_current = stage3.approval_is_current


def _active_stage3_requirements(contract):
    contract = contract if isinstance(contract, dict) else {}
    ledger = contract.get("source_requirement_ledger")
    records = ledger_requirements(ledger, include_confirmed=True)
    if records:
        return stage3.active_requirements(records)
    # Compatibility contracts used by deterministic architecture tests may
    # predate the Source Requirement Ledger.  Give them stable local IDs
    # without changing Stage 1 production semantics.
    values = list(contract.get("requirements", []) or [])
    return stage3.active_requirements([
        {
            "requirement_id": f"REQ-{index:03d}", "text": value,
            "provenance": USER_STATED, "status": "active",
        }
        for index, value in enumerate(values, 1) if str(value).strip()
    ])


def _impact_project_invariants(task_brain):
    values = []
    for item in list((task_brain or {}).get("relevant_project_brain_projection", []) or []):
        if isinstance(item, dict) and str(item.get("text", "")).strip():
            values.append(item.get("text"))
    return values[:8]


def _impact_planner_prompt(context):
    return f"""You are IMPACT PLANNER, a narrow read-only role in a weak-model coding orchestrator.
Propose one COMPLETE bounded semantic decision set for the deterministic impact slots in the packet below.
The orchestrator has already bound every existing slot to a canonical surface. For each known existing
impact, decide only its disposition: MUST_CHANGE, INTERFACE_REUSE, TEST_CHANGE, PRESERVATION_ONLY,
VERIFY_ONLY, or INSUFFICIENT_EVIDENCE. Return the impact_id, valid Source Requirement IDs, and a concise
action/reason. Optionally return canonical INTERFACE surface IDs to reuse, preservation promises, and
verification/test contracts. Do not author or infer paths, symbols, owners, repository evidence IDs, or
existing surface bindings. surface_id is unnecessary; if you return one it is non-authoritative and must
match the supplied seed. Relevant does not mean MUST_CHANGE. A preservation surface remains unmodified
unless requirements and evidence prove mutation necessary. If no existing surface can safely represent a
responsibility, emit a separate justified NEW_SURFACE_PROPOSAL rather than using a fake existing identity.
Do not write code, execute tests, decompose Workers, call tools, or reproduce
raw source. Return only the requested structured map.

COMPLETE CANONICAL PLANNING PACKET:
{json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)}"""


def create_impact_map(task_brain, contract, repository_evidence, structured_call=None):
    """Invoke one bounded ImpactPlanner call and deterministically gate its map."""
    if RUN.get("impact_planner_calls", 0) >= 1:
        raise ImpactPlanningError("only one top-level ImpactPlanner invocation is allowed")
    requirements = _active_stage3_requirements(contract)
    RUN["task_brain"] = copy.deepcopy(task_brain or {})
    registry = stage3.build_canonical_surface_registry(task_brain, repository_evidence)
    registry_validation = stage3.validate_canonical_surface_registry(registry, repository_evidence)
    if not registry_validation.get("valid"):
        raise ImpactPlanningError(
            "IMPACT_MAP_INVALID: canonical surface registry is invalid: "
            + "; ".join(registry_validation.get("errors", []))
        )
    planning_packet = stage3.build_canonical_planning_packet(
        task_brain, requirements, repository_evidence,
        project_invariants=_impact_project_invariants(task_brain),
        surface_registry=registry,
    )
    packet = planning_packet.get("packet", planning_packet)
    packet_observability = planning_packet.get("observability", {})
    RUN["canonical_surface_registry"] = registry
    seeds = copy.deepcopy(planning_packet.get("impact_seeds", []))
    RUN["impact_seeds"] = seeds
    RUN["impact_planning_packet"] = copy.deepcopy(packet)
    RUN["impact_planning_packet_observability"] = copy.deepcopy(packet_observability)
    for metric, key in (
        ("impact_planning_surfaces_selected", "selected_surface_ids"),
        ("impact_planning_surfaces_serialized", "serialized_surface_ids"),
        ("impact_planning_surfaces_dropped", "dropped_surface_ids"),
    ):
        RUN[metric] = len(packet_observability.get(key, []) or [])
    record_run_event(
        "impact_planning_packet_created", **packet_observability,
        packet_status=planning_packet.get("status"),
    )
    if not planning_packet.get("packet_complete"):
        RUN["impact_planning_context_incomplete"] = RUN.get(
            "impact_planning_context_incomplete", 0,
        ) + 1
        RUN["orchestration_failure"] = stage3.IMPACT_PLANNING_CONTEXT_INCOMPLETE
        record_run_event(
            "impact_planning_context_incomplete",
            errors=planning_packet.get("errors", []),
            packet_observability=packet_observability,
        )
        raise ImpactPlanningError(
            f"{stage3.IMPACT_PLANNING_CONTEXT_INCOMPLETE}: "
            + "; ".join(planning_packet.get("errors", []))
        )
    record_run_event(
        "canonical_surface_registry_created", surface_count=len(registry.get("surfaces", [])),
        evidence_count=len(registry.get("evidence_ids", [])), registry=registry,
    )
    packet_validation = stage3.validate_planning_packet(
        planning_packet, registry=registry, requirements=requirements, impact_seeds=seeds,
    )
    if not packet_validation.get("valid"):
        RUN["impact_planning_context_incomplete"] = RUN.get(
            "impact_planning_context_incomplete", 0,
        ) + 1
        RUN["orchestration_failure"] = stage3.IMPACT_PLANNING_CONTEXT_INCOMPLETE
        raise ImpactPlanningError(
            f"{stage3.IMPACT_PLANNING_CONTEXT_INCOMPLETE}: "
            + "; ".join(packet_validation.get("errors", []))
        )
    context = packet
    RUN.setdefault("control_flow", []).append("IMPACT_PLANNER")
    RUN["impact_planner_calls"] = RUN.get("impact_planner_calls", 0) + 1
    RUN["impact_planner_context"] = context
    prompt_text = _impact_planner_prompt(context)

    def validator(data):
        return stage3.validate_planner_output(
            data, requirements, allow_legacy=structured_call is not None,
            impact_seeds=seeds,
        )

    try:
        if structured_call is None:
            candidate = structured_model_call(
                prompt_text, validator, "impact-map", stage3.impact_map_schema(),
                retries=1, role="ImpactPlanner",
            )
        else:
            candidate = structured_call(
                prompt_text, validator, "impact-map", stage3.impact_map_schema(),
            )
        raw_artifact = stage3.normalize_impact_map(candidate)
        RUN["raw_impact_planner_output"] = copy.deepcopy(raw_artifact)
        RUN["raw_impact_map"] = copy.deepcopy(raw_artifact)
        record_run_event("impact_planner_output_captured", raw_impact_map=raw_artifact)
        impact_map = stage3.hydrate_impact_map(
            candidate, registry, requirements, repository_evidence,
            allow_legacy_exact=structured_call is not None,
            impact_seeds=seeds,
        )
        RUN["impact_map_hydration"] = impact_map
        for metric in (
            "impact_unknown_surface_references", "impact_surface_evidence_mismatches",
            "impact_invented_existing_paths_rejected", "impact_invented_interfaces_rejected",
            "impact_unknown_impact_seed_references", "impact_invalid_optional_fields_rejected",
            "impact_invalid_requirement_references_rejected", "impact_seed_surface_binding_conflicts",
        ):
            RUN[metric] = RUN.get(metric, 0) + int(impact_map.get(metric, 0) or 0)
        for metric, fallback in (
            ("impact_seed_decisions_received", "impact_decisions_received"),
            ("impact_seed_decisions_validated", "impact_decisions_validated"),
            ("impact_seed_decisions_rejected", "impact_decisions_rejected"),
        ):
            RUN[metric] = RUN.get(metric, 0) + int(impact_map.get(metric, impact_map.get(fallback, 0)) or 0)
        if not impact_map.get("hydration_valid") or not impact_map.get("impacts"):
            RUN["impact_map_failures"] = RUN.get("impact_map_failures", 0) + 1
            raise ImpactPlanningError(
                "IMPACT_MAP_INVALID: " + "; ".join(impact_map.get("hydration_errors", []))
            )
        validation = stage3.validate_impact_map(
            impact_map, requirements, repository_evidence, EXISTING_PROJECT,
            surface_registry=registry,
        )
        if not validation.get("valid"):
            RUN["impact_map_failures"] = RUN.get("impact_map_failures", 0) + 1
            raise ImpactPlanningError(
                "IMPACT_MAP_INVALID: " + "; ".join(validation.get("errors", []))
            )
    except StructuredOutputError as exc:
        RUN["impact_map_failures"] = RUN.get("impact_map_failures", 0) + 1
        record_run_event("impact_planner_invalid", error=str(exc))
        raise ImpactPlanningError("IMPACT_MAP_INVALID: " + str(exc)) from exc
    if not validation.get("valid"):
        raise ImpactPlanningError("IMPACT_MAP_INCOMPLETE: " + "; ".join(validation.get("errors", [])))
    RUN.setdefault("control_flow", []).append("IMPACT_MAP")
    RUN["impact_map"] = impact_map
    RUN["canonical_impact_map"] = impact_map
    RUN["impact_map_validation"] = validation
    RUN["impact_maps_created"] = RUN.get("impact_maps_created", 0) + 1
    RUN["impact_candidates"] = RUN.get("impact_candidates", 0) + validation.get("impact_candidates", 0)
    RUN["impact_supported"] = RUN.get("impact_supported", 0) + validation.get("impact_supported", 0)
    RUN["impact_preservation_only"] = RUN.get("impact_preservation_only", 0) + validation.get(
        "impact_preservation_only", 0,
    )
    record_run_event(
        "impact_map_created", impact_count=len(impact_map.get("impacts", [])),
        serialized_chars=validation.get("serialized_chars"), impact_map=impact_map,
    )
    return impact_map


def _impact_challenger_output_valid(data):
    if not isinstance(data, dict) or not isinstance(data.get("challenges"), list):
        return False
    if len(data.get("challenges", [])) > MAX_IMPACT_CHALLENGES:
        return False
    return all(
        isinstance(item, dict)
        and str(item.get("challenge_type", "")).upper() in stage3.CHALLENGE_TYPES
        and isinstance(item.get("impact_ids"), list)
        and isinstance(item.get("requirement_ids"), list)
        and isinstance(item.get("repository_evidence_ids"), list)
        for item in data.get("challenges", [])
    )


def _impact_challenger_prompt(context):
    return f"""You are IMPACT CHALLENGER, a narrow read-only adversarial planning role.
Try to falsify the candidate Impact Map using only the bounded requirements, accepted repository facts,
ownership, interfaces, tests, and preservation constraints below. Ask whether each MUST_CHANGE surface is
actually necessary, whether ownership is duplicated or wrong, whether a verified interface was missed,
whether a required surface/test/dependency is absent, and whether unrelated scope was introduced.
Use only canonical impact/surface IDs from the supplied map and registry; do not invent paths, symbols,
owners, interfaces, or evidence. Every challenge must cite its impact IDs (except a true missing-impact gap),
Source Requirement IDs, and applicable REPO evidence IDs. Unsupported criticism is not authoritative.
Deterministically evaluate unsupported necessity, wrong owner, duplicate ownership, missing impact, unrelated
change, preservation risk, missed interface reuse, test/dependency/requirement gaps. Do not review code, write
code, call tools, inspect the full repository, or claim perfect correctness. Return only structured challenges.

COMPLETE BOUNDED FALSIFICATION PACKET:
{json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)}"""


def challenge_impact_map(impact_map, task_brain, contract, repository_evidence,
                         structured_call=None):
    """Run exactly one normal weak-model challenge round plus deterministic checks."""
    if RUN.get("impact_challenger_calls", 0) >= MAX_IMPACT_CHALLENGE_ROUNDS:
        raise ImpactPlanningError("only one top-level ImpactChallenger round is allowed")
    requirements = _active_stage3_requirements(contract)
    registry = RUN.get("canonical_surface_registry") or stage3.build_canonical_surface_registry(
        task_brain, repository_evidence,
    )
    context = stage3.build_challenger_context(
        impact_map, requirements, repository_evidence, task_brain,
        surface_registry=registry,
    )
    if not context.get("packet_complete", True):
        RUN["impact_challenger_context_incomplete"] = RUN.get(
            "impact_challenger_context_incomplete", 0,
        ) + 1
        RUN["orchestration_failure"] = stage3.IMPACT_CHALLENGER_CONTEXT_INCOMPLETE
        record_run_event(
            "impact_challenger_context_incomplete",
            errors=context.get("errors", []),
            packet_observability=context.get("packet_observability", {}),
        )
        raise ImpactPlanningError(
            f"{stage3.IMPACT_CHALLENGER_CONTEXT_INCOMPLETE}: "
            + "; ".join(context.get("errors", []))
        )
    RUN.setdefault("control_flow", []).append("IMPACT_CHALLENGER")
    RUN["impact_challenger_calls"] = RUN.get("impact_challenger_calls", 0) + 1
    RUN["impact_challenger_context"] = context
    prompt_text = _impact_challenger_prompt(context)
    try:
        if structured_call is None:
            data = structured_model_call(
                prompt_text, _impact_challenger_output_valid, "impact-challenge",
                stage3.challenge_schema(), retries=1, role="ImpactChallenger",
            )
        else:
            data = structured_call(
                prompt_text, _impact_challenger_output_valid, "impact-challenge",
                stage3.challenge_schema(),
            )
        model_challenges = stage3.normalize_challenges(data, source="MODEL")
        RUN["raw_impact_challenger_output"] = copy.deepcopy(model_challenges)
        record_run_event("impact_challenger_output_captured", raw_challenges=model_challenges)
    except StructuredOutputError as exc:
        model_challenges = []
        RUN["raw_impact_challenger_output"] = []
        record_run_event("impact_challenger_structured_fallback", error=str(exc))
    deterministic = stage3.deterministic_challenges(
        impact_map, requirements, repository_evidence, surface_registry=registry,
    )
    challenges = stage3.merge_challenges(model_challenges, deterministic)
    validation = stage3.validate_challenges(
        challenges, impact_map, requirements, repository_evidence,
        surface_registry=registry,
    )
    RUN["impact_challenges"] = RUN.get("impact_challenges", 0) + len(challenges)
    RUN["impact_challenges_validated"] = RUN.get("impact_challenges_validated", 0) + len(
        validation.get("validated", []),
    )
    RUN["impact_challenges_rejected"] = RUN.get("impact_challenges_rejected", 0) + len(
        validation.get("rejected", []),
    )
    RUN["impact_challenge_rounds"] = 1
    RUN["impact_challenges_output"] = challenges
    RUN["impact_challenge_validation"] = validation
    RUN["validated_impact_challenges"] = validation.get("validated", [])
    RUN["rejected_impact_challenges"] = validation.get("rejected", [])
    record_run_event(
        "impact_challenges_validated", challenge_count=len(challenges),
        validated_count=len(validation.get("validated", [])),
        rejected_count=len(validation.get("rejected", [])),
    )
    return validation


def _bounded_impact_revision_context(context):
    """Bound revision metadata without truncating the canonical packet."""
    value = copy.deepcopy(context) if isinstance(context, dict) else {}
    candidate = value.get("candidate_impact_map")
    if isinstance(candidate, dict):
        impact_keys = (
            "impact_id", "surface_id", "canonical_surface_id", "disposition",
            "impact_kind", "necessity_status", "requirement_ids",
            "repository_evidence_ids", "action", "reason", "interfaces_to_reuse",
            "existing_interfaces_to_reuse", "preserve", "verification",
            "surface_kind", "surface_role", "owner_surface_id",
        )
        candidate["impacts"] = [
            {
                key: copy.deepcopy(impact.get(key))
                for key in impact_keys
                if impact.get(key) not in (None, "", [], {})
            }
            for impact in list(candidate.get("impacts", []) or [])
            if isinstance(impact, dict)
        ]
        for impact in list(candidate.get("impacts", []) or []):
            if not isinstance(impact, dict):
                continue
            for field in ("action", "reason", "candidate_change"):
                if isinstance(impact.get(field), str):
                    impact[field] = compact_text(impact[field], 360)
    challenges = value.get("validated_challenges")
    if isinstance(challenges, list):
        for challenge in challenges:
            if not isinstance(challenge, dict):
                continue
            for field in ("claim", "proposed_resolution"):
                if isinstance(challenge.get(field), str):
                    challenge[field] = compact_text(challenge[field], 260)
    if isinstance(value.get("user_confirmed_revision"), dict):
        value["user_confirmed_revision"] = {
            key: compact_text(item, 320) if isinstance(item, str) else copy.deepcopy(item)
            for key, item in value["user_confirmed_revision"].items()
        }
    planning_packet = value.get("planning_packet")
    if isinstance(planning_packet, dict):
        # The dedicated packet's requirements, surfaces, seeds,
        # preservation constraints, and rules are authoritative.  Optional
        # prose/fact projections are safe to omit from a revision envelope
        # when the already-complete packet must share the budget with the
        # candidate and challenges.
        planning_packet.pop("task_facts", None)
        planning_packet.pop("project_context", None)
        planning_packet.pop("accepted_repository_evidence", None)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return value, len(encoded) <= stage3.MAX_REVISION_CONTEXT_CHARS


def _impact_revision_prompt(context):
    bounded_context, _ = _bounded_impact_revision_context(context)
    return f"""You are IMPACT PLAN REVISER. Perform the single allowed bounded revision of an existing-project
Impact Map. Use only the current candidate map, validated challenges, explicit USER_CONFIRMED revision (if
present), Source Requirements, and accepted repository facts below. Resolve supported criticism without
inventing surfaces, preserve verified ownership, reuse verified interfaces, retain preservation-only surfaces,
and keep explicit test responsibility. Every concrete impact still requires valid requirement and REPO evidence
IDs. Do not write code, call tools, inspect raw files, or debate. Return only one complete Impact Map.

COMPLETE BOUNDED REVISION CONTEXT:
{json.dumps(bounded_context, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)}"""


def revise_impact_map(impact_map, validated_challenges, task_brain, contract,
                      repository_evidence, user_revision=None, structured_call=None):
    if RUN.get("impact_plan_revision_calls", 0) >= MAX_IMPACT_PLAN_REVISION_ROUNDS:
        raise ImpactPlanningError("the bounded Impact Plan revision round is already exhausted")
    requirements = _active_stage3_requirements(contract)
    registry = RUN.get("canonical_surface_registry") or stage3.build_canonical_surface_registry(
        task_brain, repository_evidence,
    )
    planning_packet = stage3.build_canonical_planning_packet(
        task_brain, requirements, repository_evidence,
        project_invariants=_impact_project_invariants(task_brain),
        surface_registry=registry,
    )
    planner_context = planning_packet.get("packet", planning_packet)
    if not planning_packet.get("packet_complete"):
        RUN["orchestration_failure"] = stage3.IMPACT_PLANNING_CONTEXT_INCOMPLETE
        raise ImpactPlanningError(
            f"{stage3.IMPACT_PLANNING_CONTEXT_INCOMPLETE}: "
            + "; ".join(planning_packet.get("errors", []))
        )
    context = {
        "candidate_impact_map": impact_map,
        "validated_challenges": list(validated_challenges or [])[:MAX_IMPACT_CHALLENGES],
        "user_confirmed_revision": _compact_brain_record(user_revision, 900)
        if isinstance(user_revision, dict) else None,
        "planning_packet": planner_context,
    }
    context, context_complete = _bounded_impact_revision_context(context)
    if not context_complete:
        RUN["impact_planning_context_incomplete"] = RUN.get(
            "impact_planning_context_incomplete", 0,
        ) + 1
        RUN["orchestration_failure"] = stage3.IMPACT_PLANNING_CONTEXT_INCOMPLETE
        record_run_event(
            "impact_plan_revision_context_incomplete",
            errors=["complete bounded revision context exceeds the serialized-size bound"],
        )
        raise ImpactPlanningError(
            f"{stage3.IMPACT_PLANNING_CONTEXT_INCOMPLETE}: "
            "complete bounded revision context exceeds the serialized-size bound"
        )
    RUN["impact_plan_revision_calls"] = RUN.get("impact_plan_revision_calls", 0) + 1
    prompt_text = _impact_revision_prompt(context)

    def validator(data):
        return stage3.validate_planner_output(
            data, requirements, allow_legacy=structured_call is not None,
            impact_seeds=RUN.get("impact_seeds", []),
        )

    try:
        if structured_call is None:
            data = structured_model_call(
                prompt_text, validator, "impact-plan-revision", stage3.impact_map_schema(),
                retries=1, role="ImpactPlanReviser",
            )
        else:
            data = structured_call(
                prompt_text, validator, "impact-plan-revision", stage3.impact_map_schema(),
            )
        revised = stage3.hydrate_impact_map(
            data, registry, requirements, repository_evidence,
            allow_legacy_exact=structured_call is not None,
            impact_seeds=RUN.get("impact_seeds", []),
        )
        for metric in (
            "impact_unknown_surface_references", "impact_surface_evidence_mismatches",
            "impact_invented_existing_paths_rejected", "impact_invented_interfaces_rejected",
            "impact_unknown_impact_seed_references", "impact_invalid_optional_fields_rejected",
            "impact_invalid_requirement_references_rejected", "impact_seed_surface_binding_conflicts",
        ):
            RUN[metric] = RUN.get(metric, 0) + int(revised.get(metric, 0) or 0)
        for metric, fallback in (
            ("impact_seed_decisions_received", "impact_decisions_received"),
            ("impact_seed_decisions_validated", "impact_decisions_validated"),
            ("impact_seed_decisions_rejected", "impact_decisions_rejected"),
        ):
            RUN[metric] = RUN.get(metric, 0) + int(revised.get(metric, revised.get(fallback, 0)) or 0)
        if not revised.get("hydration_valid"):
            raise StructuredOutputError("; ".join(revised.get("hydration_errors", [])))
        validation = stage3.validate_impact_map(
            revised, requirements, repository_evidence, EXISTING_PROJECT,
            surface_registry=registry,
        )
        if not validation.get("valid"):
            raise StructuredOutputError("; ".join(validation.get("errors", [])))
    except StructuredOutputError as exc:
        record_run_event("impact_plan_revision_fallback", error=str(exc))
        revised = stage3.deterministic_impact_map(
            (task_brain or {}).get("task_goal", {}).get("text", "coding task"),
            requirements, repository_evidence, registry=registry,
        )
    return revised


def reconcile_minimal_change_plan(impact_map, challenge_validation, contract,
                                  repository_evidence):
    requirements = _active_stage3_requirements(contract)
    task_brain = RUN.get("task_brain") or {}
    registry = RUN.get("canonical_surface_registry") or stage3.build_canonical_surface_registry(
        task_brain, repository_evidence,
    )
    RUN.setdefault("control_flow", []).append("PLAN_RECONCILIATION")
    reconciled, resolved, unresolved = stage3.reconcile_impact_map(
        impact_map, challenge_validation.get("validated", []),
        requirements, repository_evidence, surface_registry=registry,
        impact_seeds=RUN.get("impact_seeds", []),
    )
    RUN.setdefault("control_flow", []).append("MINIMAL_EFFECTIVE_CHANGE_PLAN")
    plan = stage3.build_minimal_change_plan(
        reconciled, requirements, repository_evidence,
        resolved_challenges=resolved, unresolved_challenges=unresolved,
        project_mode=EXISTING_PROJECT,
        surface_registry=registry,
    )
    RUN.setdefault("control_flow", []).append("PLAN_GATE")
    gate = stage3.validate_change_plan(
        plan, requirements, repository_evidence, EXISTING_PROJECT,
        surface_registry=registry,
    )
    RUN["change_plans_created"] = RUN.get("change_plans_created", 0) + 1
    RUN["plan_nodes"] = RUN.get("plan_nodes", 0) + gate.get("plan_nodes", 0)
    RUN["plan_requirements_covered"] = RUN.get("plan_requirements_covered", 0) + gate.get(
        "requirements_covered", 0,
    )
    RUN["plan_requirements_unassigned"] = RUN.get("plan_requirements_unassigned", 0) + gate.get(
        "requirements_unassigned", 0,
    )
    if not gate.get("valid"):
        RUN["change_plan_gate_failures"] = RUN.get("change_plan_gate_failures", 0) + 1
    RUN["reconciled_impact_map"] = reconciled
    RUN["resolved_impact_challenges"] = resolved
    RUN["unresolved_impact_challenges"] = unresolved
    RUN["minimal_effective_change_plan"] = plan
    RUN["change_plan_gate"] = gate
    RUN["plan_gate"] = gate
    record_run_event(
        "minimal_effective_change_plan", plan_id=plan.get("plan_id"),
        plan_hash=plan.get("plan_hash"), gate=gate, plan=plan,
    )
    return plan, gate


def plan_approval_option_labels(allow_revision=True):
    labels = ["Approve plan                         Recommended"]
    if allow_revision:
        labels.append("Review/change scope")
    labels.append("Cancel")
    if allow_revision:
        labels.append("Other...")
    return labels


def navigate_plan_approval_options(key_sequence, initial_index=0, allow_revision=True):
    return navigate_clarification_options(
        plan_approval_option_labels(allow_revision), key_sequence, initial_index,
    )


def format_plan_approval_summary(plan):
    summary = stage3.plan_summary(plan)
    lines = ["\nHIVO reviewed the existing project.\n", "Proposed change plan:"]
    for index, item in enumerate(summary.get("changes", []), 1):
        component = item.get("component") or "Project responsibility"
        mode = "change" if item.get("mutation_required") else "reuse/verify"
        lines.append(f"{index}. {component} [{mode}]\n   {item.get('behavior', '')}")
    if summary.get("preserve"):
        lines.append("\nPreserve:")
        lines.extend(f"- {item}" for item in summary["preserve"])
    if summary.get("tests"):
        lines.append("\nTests:")
        lines.extend(f"- {item}" for item in summary["tests"])
    if summary.get("do_not_touch"):
        lines.append("\nNo change planned:")
        lines.extend(f"- {item}" for item in summary["do_not_touch"])
    return "\n".join(lines)


def select_plan_approval_option(plan, key_sequence=None, output_fn=print,
                                terminal_available=None, allow_revision=True):
    labels = plan_approval_option_labels(allow_revision)
    if key_sequence is not None:
        return navigate_plan_approval_options(key_sequence, allow_revision=allow_revision)
    if terminal_available is None:
        terminal_available = bool(sys.stdin.isatty() and sys.stdout.isatty())
    if not terminal_available:
        return None
    output_fn(format_plan_approval_summary(plan))
    if PROMPT_TOOLKIT_AVAILABLE:
        try:
            from prompt_toolkit.shortcuts import radiolist_dialog
            selected = radiolist_dialog(
                title="HIVO change plan", text="Use Up/Down and Enter to select.",
                values=[(index, label) for index, label in enumerate(labels)],
                ok_text="Select", cancel_text="Cancel",
            ).run()
            return int(selected) if selected is not None else None
        except (ImportError, EOFError, KeyboardInterrupt, TypeError, ValueError):
            return None
    if os.name == "nt":
        try:
            import msvcrt
            index = 0
            while True:
                key = msvcrt.getwch()
                if key in {"\r", "\n"}:
                    return index
                if key == "\x1b":
                    return None
                if key in {"\x00", "\xe0"}:
                    arrow = msvcrt.getwch()
                    if arrow == "H":
                        index = max(0, index - 1)
                    elif arrow == "P":
                        index = min(len(labels) - 1, index + 1)
        except (ImportError, EOFError, KeyboardInterrupt):
            return None
    output_fn("Use arrow keys and Enter; Esc cancels.")
    return None


def _plan_approval_record(plan, status, source, user_revision=None):
    return {
        "plan_id": plan.get("plan_id"),
        "plan_hash": plan.get("plan_hash"),
        "approval_status": status,
        "approved_at": datetime.now().isoformat(timespec="seconds") if status == "APPROVED" else None,
        "approval_source": source,
        "user_revision": copy.deepcopy(user_revision) if isinstance(user_revision, dict) else None,
    }


def request_plan_approval(plan, interactive=True, terminal_available=None, selector=None,
                          answer_reader=None, allow_revision=True):
    RUN.setdefault("control_flow", []).append("USER_PLAN_APPROVAL")
    RUN["plan_approval_requests"] = RUN.get("plan_approval_requests", 0) + 1
    RUN["plan_approval_required"] = RUN.get("plan_approval_required", 0) + 1
    if terminal_available is None:
        terminal_available = bool(sys.stdin.isatty() and sys.stdout.isatty())
    payload = {
        "terminal_state": PLAN_APPROVAL_REQUIRED,
        "plan_id": plan.get("plan_id"), "plan_hash": plan.get("plan_hash"),
        "summary": stage3.plan_summary(plan), "plan": plan,
    }
    RUN["plan_approval_payload"] = payload
    if not interactive or not terminal_available:
        record = _plan_approval_record(plan, "REQUIRED", "NON_INTERACTIVE")
        RUN["plan_approval"] = record
        record_run_event("plan_approval_required", **{
            key: value for key, value in payload.items() if key != "plan"
        })
        return {
            "status": "plan_approval_required", "terminal_state": PLAN_APPROVAL_REQUIRED,
            "summary": "A valid existing-project change plan requires user approval before mutation.",
            "plan": plan, "plan_summary": payload["summary"],
            "approval_payload": payload, "approval": record,
        }
    choose = selector or select_plan_approval_option
    try:
        selected = choose(
            plan, terminal_available=terminal_available, allow_revision=allow_revision,
        )
    except TypeError:
        try:
            selected = choose(plan, terminal_available=terminal_available)
        except TypeError:
            selected = choose(plan)
    labels = plan_approval_option_labels(allow_revision)
    if selected is None:
        selected_label = "Cancel"
    else:
        selected = min(max(int(selected), 0), len(labels) - 1)
        selected_label = labels[selected]
    if selected_label.startswith("Approve plan"):
        record = _plan_approval_record(plan, "APPROVED", "TERMINAL_ARROW_SELECTION")
        RUN["plan_approval"] = record
        RUN["plan_approval_granted"] = RUN.get("plan_approval_granted", 0) + 1
        record_run_event(
            "plan_approved", plan_id=plan.get("plan_id"), plan_hash=plan.get("plan_hash"),
        )
        return {"status": "approved", "plan": plan, "approval": record}
    if allow_revision and selected_label in {"Review/change scope", "Other..."}:
        reader = answer_reader or read_user_prompt
        try:
            text = reader("Plan revision> ")
        except TypeError:
            text = reader()
        if str(text or "").strip():
            return {"status": "revision_requested", "revision_text": str(text).strip(), "plan": plan}
    record = _plan_approval_record(plan, "REJECTED", "TERMINAL_ARROW_SELECTION")
    RUN["plan_approval"] = record
    RUN["plan_approval_rejected"] = RUN.get("plan_approval_rejected", 0) + 1
    record_run_event(
        "plan_rejected", plan_id=plan.get("plan_id"), plan_hash=plan.get("plan_hash"),
    )
    return {
        "status": "plan_rejected", "terminal_state": PLAN_REJECTED,
        "summary": "The proposed change plan was rejected; no subject files were mutated.",
        "plan": plan, "approval": record,
    }


def apply_plan_user_revision(contract, revision_text):
    """Add one explicit plan-scope decision without overwriting USER_STATED facts."""
    updated = copy.deepcopy(contract if isinstance(contract, dict) else {})
    text = str(revision_text or "").strip()
    if not text:
        return updated, None
    ledger = updated.get("source_requirement_ledger")
    ledger = append_confirmed_requirement(
        ledger, text, question_id="PLAN-REVISION-001", category="plan_scope",
        affected_requirement_ids=[
            item.get("requirement_id") for item in ledger_requirements(ledger)
        ][:8],
        repository_evidence_ids=[], phase="USER_PLAN_REVISION",
    )
    new_requirement = ledger_requirements(ledger, include_confirmed=True)[-1]
    decision = {
        "decision_id": "PLAN-DEC-001",
        "question_id": "PLAN-REVISION-001",
        "answer": compact_text(text, 700),
        "selected_option": "Review/change scope",
        "affected_requirement_ids": list(new_requirement.get("affected_requirement_ids", [])),
        "repository_evidence_ids": [],
        "phase": "USER_PLAN_REVISION",
        "provenance": USER_CONFIRMED,
        "requirement_id": new_requirement.get("requirement_id"),
    }
    updated["source_requirement_ledger"] = ledger
    updated["source_requirements"] = ledger_requirements(ledger)
    updated["user_stated_requirements"] = ledger_requirements(ledger)
    updated["user_confirmed_requirements"] = list(
        updated.get("user_confirmed_requirements", []) or []
    ) + [decision]
    updated["requirements"] = list(updated.get("requirements", []) or []) + [text]
    updated["source_contract"] = source_contract_from_ledger(
        updated.get("original_goal") or updated.get("goal") or text,
        ledger, confirmed=updated.get("user_confirmed_requirements", []),
        derived=updated.get("derived_assumptions", []),
        questions=updated.get("clarification_questions", []),
        answers=updated.get("clarification_answers", []),
        interaction_style=updated.get("interaction_style"),
    )
    RUN["source_requirement_ledger"] = ledger
    RUN["source_contract"] = updated["source_contract"]
    RUN["plan_user_revision"] = decision
    return updated, decision


def _stage3_workspace_fingerprint():
    if WORKSPACE is None:
        return None
    return stage2.inventory_repository(WORKSPACE).get("fingerprint")


def prepare_stage3_context(understanding, contract, interactive=True, terminal_available=None,
                           planner_structured_call=None, challenger_structured_call=None,
                           reviser_structured_call=None, approval_selector=None,
                           approval_answer_reader=None):
    """Create, challenge, gate, and approve the task-scoped existing-project plan."""
    understanding = understanding if isinstance(understanding, dict) else {}
    mode = understanding.get("project_mode")
    if mode in {NEW_PROJECT, EXISTING_PROJECT}:
        RUN["project_mode"] = mode
    if mode != EXISTING_PROJECT:
        RUN.setdefault("control_flow", []).append("IMPACT_PLANNING_SKIPPED_GREENFIELD")
        RUN["impact_planning_required"] = False
        return {"status": "ready", "contract": contract, "project_mode": mode}
    RUN["impact_planning_required"] = True
    fingerprint_before = _stage3_workspace_fingerprint()
    task_brain = understanding.get("task_brain") or RUN.get("task_brain") or {}
    RUN["task_brain"] = copy.deepcopy(task_brain)
    repository_evidence = list(
        (understanding.get("reconnaissance") or {}).get("evidence", [])
        or RUN.get("repository_evidence", []) or []
    )
    try:
        impact_map = create_impact_map(
            task_brain, contract, repository_evidence,
            structured_call=planner_structured_call,
        )
        challenge_validation = challenge_impact_map(
            impact_map, task_brain, contract, repository_evidence,
            structured_call=challenger_structured_call,
        )
        plan, gate = reconcile_minimal_change_plan(
            impact_map, challenge_validation, contract, repository_evidence,
        )
    except ImpactPlanningError as exc:
        return {
            "status": "plan_incomplete", "terminal_state": PLAN_INCOMPLETE,
            "summary": str(exc), "project_mode": mode,
            "orchestration_failure": RUN.get("orchestration_failure"),
        }
    if not gate.get("valid"):
        fingerprint_after = _stage3_workspace_fingerprint()
        RUN["stage3_workspace_fingerprint_before"] = fingerprint_before
        RUN["stage3_workspace_fingerprint_after"] = fingerprint_after
        return {
            "status": "plan_incomplete", "terminal_state": PLAN_INCOMPLETE,
            "summary": "; ".join(gate.get("errors", [])),
            "project_mode": mode, "impact_map": impact_map,
            "plan": plan, "plan_gate": gate,
        }
    approval = request_plan_approval(
        plan, interactive=interactive, terminal_available=terminal_available,
        selector=approval_selector, answer_reader=approval_answer_reader,
        allow_revision=True,
    )
    if approval.get("status") == "revision_requested":
        contract, decision = apply_plan_user_revision(
            contract, approval.get("revision_text", ""),
        )
        try:
            impact_map = revise_impact_map(
                impact_map, challenge_validation.get("validated", []), task_brain,
                contract, repository_evidence, user_revision=decision,
                structured_call=reviser_structured_call,
            )
            # The one model Challenger is not invoked again. Deterministic
            # falsification still checks the revised map against the same facts.
            revised_challenges = stage3.deterministic_challenges(
                impact_map, _active_stage3_requirements(contract), repository_evidence,
                surface_registry=RUN.get("canonical_surface_registry"),
            )
            revised_validation = stage3.validate_challenges(
                revised_challenges, impact_map, _active_stage3_requirements(contract),
                repository_evidence,
                surface_registry=RUN.get("canonical_surface_registry"),
            )
            plan, gate = reconcile_minimal_change_plan(
                impact_map, revised_validation, contract, repository_evidence,
            )
        except ImpactPlanningError as exc:
            return {
                "status": "plan_incomplete", "terminal_state": PLAN_INCOMPLETE,
                "summary": str(exc), "project_mode": mode,
                "orchestration_failure": RUN.get("orchestration_failure"),
            }
        if not gate.get("valid"):
            return {
                "status": "plan_incomplete", "terminal_state": PLAN_INCOMPLETE,
                "summary": "; ".join(gate.get("errors", [])),
                "project_mode": mode, "impact_map": impact_map,
                "plan": plan, "plan_gate": gate, "contract": contract,
            }
        approval = request_plan_approval(
            plan, interactive=interactive, terminal_available=terminal_available,
            selector=approval_selector, answer_reader=approval_answer_reader,
            allow_revision=False,
        )
    fingerprint_after = _stage3_workspace_fingerprint()
    RUN["stage3_workspace_fingerprint_before"] = fingerprint_before
    RUN["stage3_workspace_fingerprint_after"] = fingerprint_after
    RUN["stage3_read_only_before_approval"] = fingerprint_before == fingerprint_after
    if approval.get("status") != "approved":
        result = dict(approval)
        result.update({
            "project_mode": mode, "impact_map": impact_map,
            "plan": plan, "plan_gate": gate, "contract": contract,
            "read_only": fingerprint_before == fingerprint_after,
        })
        return result
    RUN["approved_change_plan"] = plan
    RUN["plan_approval"] = approval.get("approval")
    return {
        "status": "ready", "project_mode": mode, "contract": contract,
        "impact_map": impact_map, "plan": plan, "plan_gate": gate,
        "approval": approval.get("approval"),
        "read_only": fingerprint_before == fingerprint_after,
    }


def current_approved_change_plan():
    plan = RUN.get("approved_change_plan")
    approval = RUN.get("plan_approval")
    if stage3.approval_is_current(plan, approval):
        return plan
    return None


def approved_plan_node_contract_for_task(task):
    plan = current_approved_change_plan()
    if not isinstance(plan, dict):
        return None
    task = task if isinstance(task, dict) else {}
    node_ids = list(task.get("plan_node_ids", []) or [])
    return stage3.approved_plan_node_contract(plan, node_ids or None)


def attach_approved_plan_to_task(task, plan, node_ids=None):
    if not isinstance(task, dict) or not isinstance(plan, dict):
        return task
    selected = list(node_ids or []) or [
        item.get("node_id") for item in plan.get("approved_change_nodes", [])
    ]
    contract = stage3.approved_plan_node_contract(plan, selected)
    task["approved_plan_id"] = plan.get("plan_id")
    task["approved_plan_hash"] = plan.get("plan_hash")
    task["plan_node_ids"] = selected
    task["plan_requirement_ids"] = _bounded_brain_strings([
        value for node in contract.get("nodes", []) for value in node.get("requirement_ids", [])
    ], 24, 80)
    task["plan_impact_ids"] = _bounded_brain_strings([
        value for node in contract.get("nodes", []) for value in node.get("impact_ids", [])
    ], 16, 80)
    task["plan_evidence_ids"] = _bounded_brain_strings([
        value for node in contract.get("nodes", []) for value in node.get("evidence_ids", [])
    ], 24, 80)
    task["verification_only"] = bool(contract.get("nodes")) and all(
        node.get("verification_only") for node in contract.get("nodes", [])
    )
    return task


def _stage3_execution_gate(task=None):
    if not RUN.get("impact_planning_required") or RUN.get("project_mode") != EXISTING_PROJECT:
        return {"allowed": True, "plan": None, "contract": None}
    plan = current_approved_change_plan()
    if not isinstance(plan, dict):
        return {"allowed": False, "terminal_state": PLAN_APPROVAL_REQUIRED}
    task = task if isinstance(task, dict) else {}
    if task.get("approved_plan_hash") and task.get("approved_plan_hash") != plan.get("plan_hash"):
        return {"allowed": False, "terminal_state": PLAN_APPROVAL_REQUIRED}
    return {
        "allowed": True, "plan": plan,
        "contract": stage3.approved_plan_node_contract(plan, task.get("plan_node_ids") or None),
    }


def _active_plan_tool_contract_fields(task):
    gate = _stage3_execution_gate(task)
    if not gate.get("allowed") or not isinstance(gate.get("contract"), dict):
        return {
            "impact_plan_required": bool(RUN.get("impact_planning_required")),
            "approved_plan_id": None, "approved_plan_hash": None,
            "approved_targets": [], "inspect_only_targets": [], "do_not_touch": [],
            "verification_only": False,
        }
    plan_contract = gate["contract"]
    scope = stage3.mutation_scope(plan_contract)
    return {
        "impact_plan_required": True,
        "approved_plan_id": plan_contract.get("plan_id"),
        "approved_plan_hash": plan_contract.get("plan_hash"),
        **scope,
    }


_WORKER_MISSION_FIELDS = (
    "goal_anchor", "task", "expected_outcome", "targets", "existing_facts", "implementation_plan",
    "interfaces_to_reuse", "invariants", "project_specific_quality_rules", "do_not",
    "verification_plan", "done_when",
)


def worker_mission_schema():
    array_schema = {"type": "array", "items": {"type": "string"}, "maxItems": 6}
    properties = {field: (array_schema if field not in {"goal_anchor", "task", "expected_outcome"}
                          else {"type": "string"}) for field in _WORKER_MISSION_FIELDS}
    for field in ("targets", "implementation_plan", "verification_plan", "done_when"):
        properties[field]["minItems"] = 1
    return {
        "type": "object", "properties": properties,
        "required": list(_WORKER_MISSION_FIELDS), "additionalProperties": False,
    }


def _worker_mission_validator(data):
    if not isinstance(data, dict):
        return False
    for field in ("goal_anchor", "task", "expected_outcome"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            return False
    for field in _WORKER_MISSION_FIELDS[3:]:
        if not isinstance(data.get(field), list) or not all(
            isinstance(item, str) and item.strip() for item in data.get(field, [])
        ):
            return False
    if any(not data.get(field) for field in ("targets", "implementation_plan", "verification_plan", "done_when")):
        return False
    return True


def normalize_worker_mission(task, brain_projection, mission):
    task = task if isinstance(task, dict) else {}
    mission = mission if isinstance(mission, dict) else {}
    normalized = {
        "goal_anchor": compact_text(
            (brain_projection or {}).get("root_goal_anchor") or mission.get("goal_anchor", ""), 900,
        ),
        "task": compact_text(task.get("goal") or mission.get("task", ""), 1000),
        "expected_outcome": compact_text(mission.get("expected_outcome") or "the current node is verified", 900),
    }
    for field in _WORKER_MISSION_FIELDS[3:]:
        normalized[field] = _bounded_brain_strings(mission.get(field), 6, 360)
    normalized["done_when"] = _bounded_brain_strings(
        task.get("done_when", []) or normalized["done_when"], 6, 300,
    )
    return _bound_worker_mission(normalized)


def _bound_worker_mission(mission, max_chars=MAX_WORKER_MISSION_CHARS):
    """Keep the Worker contract compact without returning invalid JSON text."""
    mission = copy.deepcopy(mission if isinstance(mission, dict) else {})
    encoded = json.dumps(mission, ensure_ascii=False, default=str)
    trim_order = (
        "do_not", "existing_facts", "interfaces_to_reuse", "invariants",
        "project_specific_quality_rules", "targets", "implementation_plan",
        "verification_plan", "done_when",
    )
    while len(encoded) > max_chars:
        removed = False
        for field in trim_order:
            values = mission.get(field)
            if isinstance(values, list) and len(values) > 1:
                values.pop()
                removed = True
                break
        if removed:
            encoded = json.dumps(mission, ensure_ascii=False, default=str)
            continue
        changed = False
        for field in trim_order:
            values = mission.get(field)
            if not isinstance(values, list) or not values:
                continue
            item_chars = max(24, max(len(str(item)) for item in values) // 2)
            shortened = _bounded_brain_strings(values, len(values), item_chars)
            if shortened != values:
                mission[field] = shortened
                changed = True
                break
        if changed:
            encoded = json.dumps(mission, ensure_ascii=False, default=str)
            continue
        for field, limit in (("goal_anchor", 420), ("task", 480), ("expected_outcome", 420)):
            if isinstance(mission.get(field), str) and len(mission[field]) > limit:
                mission[field] = compact_text(mission[field], limit)
                changed = True
        if changed:
            encoded = json.dumps(mission, ensure_ascii=False, default=str)
            continue
        break
    if len(encoded) > max_chars:
        approved_contract = mission.get("approved_plan_node_contract")
        mission = {
            "goal_anchor": compact_text(mission.get("goal_anchor", "coding task"), 240),
            "task": compact_text(mission.get("task", "complete the current node"), 280),
            "expected_outcome": compact_text(mission.get("expected_outcome", "the current node is verified"), 240),
            "targets": _bounded_brain_strings(mission.get("targets"), 1, 180) or ["the current node scope"],
            "existing_facts": [],
            "implementation_plan": _bounded_brain_strings(mission.get("implementation_plan"), 1, 220)
            or ["implement the stated bounded task"],
            "interfaces_to_reuse": [], "invariants": [],
            "project_specific_quality_rules": [], "do_not": [],
            "verification_plan": _bounded_brain_strings(mission.get("verification_plan"), 1, 220)
            or ["run the deterministic verification"],
            "done_when": _bounded_brain_strings(mission.get("done_when"), 1, 220)
            or ["the current node is verified"],
        }
        if isinstance(approved_contract, dict):
            mission["approved_plan_node_contract"] = approved_contract
    return mission


def _compact_approved_plan_node_contract(contract, max_chars=2400):
    """Keep every assigned node visible while deduplicating repeated fields."""
    contract = contract if isinstance(contract, dict) else {}
    nodes = list(contract.get("nodes", []) or [])[:MAX_PLAN_NODES]
    result = {
        "plan_id": contract.get("plan_id"),
        "plan_hash": contract.get("plan_hash"),
        "node_responsibilities": [{
            "node_id": node.get("node_id"),
            "goal": compact_text(node.get("goal", ""), 180),
            "objective": compact_text(node.get("objective") or node.get("goal", ""), 180),
            "current_owner": compact_text(node.get("current_owner", ""), 100),
            "surface_ids": _bounded_brain_strings(node.get("surface_ids"), 8, 80),
            "target_surface_ids": _bounded_brain_strings(node.get("target_surface_ids"), 8, 80),
            "inspect_surface_ids": _bounded_brain_strings(node.get("inspect_surface_ids"), 8, 80),
            "new_surface_proposal_ids": _bounded_brain_strings(
                node.get("new_surface_proposal_ids"), 4, 80,
            ),
            "target_new_surface_proposal_ids": _bounded_brain_strings(
                node.get("target_new_surface_proposal_ids"), 4, 80,
            ),
            "parent_scopes": _bounded_brain_strings(node.get("parent_scopes"), 4, 140),
            "interface_surface_ids": _bounded_brain_strings(node.get("interface_surface_ids"), 8, 80),
            "candidate_targets": _bounded_brain_strings(node.get("candidate_targets"), 2, 140),
            "target_paths": _bounded_brain_strings(node.get("target_paths", node.get("candidate_targets")), 2, 140),
            "inspect_targets": _bounded_brain_strings(node.get("inspect_targets"), 2, 140),
            "mutation_required": bool(node.get("mutation_required")),
            "verification_only": bool(node.get("verification_only")),
            "test_contract": _bounded_brain_strings(node.get("test_contract"), 4, 160),
        } for node in nodes],
        "requirement_ids": _bounded_brain_strings([
            item for node in nodes for item in node.get("requirement_ids", [])
        ], 24, 80),
        "impact_ids": _bounded_brain_strings([
            item for node in nodes for item in node.get("impact_ids", [])
        ], 16, 80),
        "evidence_ids": _bounded_brain_strings([
            item for node in nodes for item in node.get("evidence_ids", [])
        ], 24, 80),
        "interfaces_to_reuse": _bounded_brain_strings([
            item for node in nodes for item in node.get("interfaces_to_reuse", [])
        ], 8, 140),
        "interface_surface_ids": _bounded_brain_strings([
            item for node in nodes for item in node.get("interface_surface_ids", [])
        ], 8, 80),
        "preservation_constraints": _bounded_brain_strings([
            item for node in nodes for item in node.get("preservation_constraints", [])
        ], 8, 180),
        "local_test_contract": _bounded_brain_strings([
            item for node in nodes for item in node.get("local_test_contract", [])
        ], 8, 180),
        "done_when": _bounded_brain_strings([
            item for node in nodes for item in node.get("done_when", [])
        ], 8, 180),
        "do_not_touch": _bounded_brain_strings(contract.get("do_not_touch"), 8, 140),
    }
    encoded = json.dumps(result, ensure_ascii=False, default=str)
    while len(encoded) > max_chars:
        removed = False
        for field in (
            "done_when", "preservation_constraints", "interfaces_to_reuse",
            "impact_ids", "evidence_ids", "requirement_ids",
        ):
            values = result.get(field)
            if isinstance(values, list) and len(values) > 1:
                values.pop()
                removed = True
                break
        if not removed:
            for node in result.get("node_responsibilities", []):
                if len(node.get("goal", "")) > 90:
                    node["goal"] = compact_text(node.get("goal", ""), 90)
                    removed = True
                    break
        if not removed:
            break
        encoded = json.dumps(result, ensure_ascii=False, default=str)
    return result


def _compact_mission_compiler_context(context, max_chars=MAX_MISSION_COMPILER_CONTEXT_CHARS):
    """Trim compiler input by fields while preserving valid structured context."""
    context = copy.deepcopy(context if isinstance(context, dict) else {})
    encoded = json.dumps(context, ensure_ascii=False, default=str)
    while len(encoded) > max_chars:
        dependencies = context.get("verified_dependencies")
        if isinstance(dependencies, list) and len(dependencies) > 1:
            dependencies.pop()
        elif isinstance(context.get("relevant_task_context"), str) and context["relevant_task_context"]:
            current_context = context["relevant_task_context"]
            next_limit = max(120, len(current_context) // 2)
            if next_limit >= len(current_context):
                context.pop("relevant_task_context", None)
            else:
                context["relevant_task_context"] = compact_text(current_context, next_limit)
        elif isinstance(context.get("repository_hints"), str) and context["repository_hints"]:
            current_hints = context["repository_hints"]
            next_limit = max(240, len(current_hints) // 2)
            if next_limit >= len(current_hints):
                context.pop("repository_hints", None)
            else:
                context["repository_hints"] = compact_text(current_hints, next_limit)
        elif isinstance(context.get("project_brain_projection"), dict):
            projection = context["project_brain_projection"]
            current_size = len(json.dumps(projection, ensure_ascii=False, default=str))
            next_limit = max(600, current_size // 2)
            if next_limit >= current_size:
                context.pop("project_brain_projection", None)
            else:
                context["project_brain_projection"] = _compact_brain_projection(
                    projection, max_chars=next_limit,
                )
        elif isinstance(context.get("bounded_strategy"), dict):
            context.pop("bounded_strategy", None)
        elif isinstance(context.get("approved_plan_node_contract"), dict):
            # This is the execution authority, so compact it rather than
            # dropping it like optional discovery context.
            current_contract = context["approved_plan_node_contract"]
            current_size = len(json.dumps(current_contract, ensure_ascii=False, default=str))
            context["approved_plan_node_contract"] = _compact_approved_plan_node_contract(
                current_contract, max_chars=max(1000, current_size // 2),
            )
        else:
            current = context.get("current_node") if isinstance(context.get("current_node"), dict) else {}
            projection = context.get("project_brain_projection")
            context = {
                "current_node": {
                    "id": compact_text(current.get("id", ""), 80),
                    "goal": compact_text(current.get("goal", ""), 500),
                    "done_when": _bounded_brain_strings(current.get("done_when", []), 2, 160),
                },
                "project_brain_projection": _compact_brain_projection(
                    projection if isinstance(projection, dict) else {}, max_chars=max(1200, max_chars // 2),
                ),
            }
        updated = json.dumps(context, ensure_ascii=False, default=str)
        if updated == encoded:
            break
        encoded = updated
    return encoded


def compile_worker_mission(task, brain_projection, dependency_summaries=None, repo_snapshot=None,
                           strategy_context=None, task_context=None, structured_call=None,
                           plan_node_contract=None):
    """Compile one node into a small mission before any Worker tool call."""
    RUN["mission_compilations"] = RUN.get("mission_compilations", 0) + 1
    task = task if isinstance(task, dict) else {}
    projection = brain_projection if isinstance(brain_projection, dict) else {}
    dependencies = [
        _compact_brain_record(item, 420) for item in list(dependency_summaries or [])[-3:]
        if isinstance(item, dict) and str(item.get("status", "")).casefold() in {"done", "verified", "passed"}
    ]
    strategy = {}
    if isinstance(strategy_context, dict):
        strategy = {
            "name": compact_text(strategy_context.get("strategy", {}).get("name", ""), 100),
            "approach": compact_text(strategy_context.get("strategy", {}).get("approach", ""), 700),
            "scope": _bounded_brain_strings(strategy_context.get("strategy", {}).get("scope", []), 4, 220),
        }
    context = {
        "current_node": {
            "id": str(task.get("id", ""))[:80],
            "goal": compact_text(task.get("goal", ""), 1100),
            "done_when": _bounded_brain_strings(task.get("done_when", []), 6, 300),
            "scope_hint": _bounded_brain_strings(task.get("scope_hint", []), 5, 180),
        },
        "project_brain_projection": _compact_brain_projection(projection, max_chars=2600),
        "verified_dependencies": dependencies,
        "repository_hints": repository_hints(repo_snapshot or {}, task.get("scope_hint"), max_chars=900),
    }
    if strategy:
        context["bounded_strategy"] = strategy
    if isinstance(task_context, dict):
        context["relevant_task_context"] = compact_text(
            json.dumps(task_context, ensure_ascii=False, default=str), 1600,
        )
    if isinstance(plan_node_contract, dict):
        context["approved_plan_node_contract"] = _compact_approved_plan_node_contract(
            plan_node_contract,
        )
    prompt_text = f"""You are the MISSION COMPILER for exactly one bounded node in a weak-model coding orchestrator.
Use only the current node, its relevant Project Brain projection, verified dependencies, repository hints, approved
plan-node execution contract, and any bounded strategy/task context below. Do not mutate files, call tools,
decompose siblings, expand approved scope, or return conversation.
Prepare the Worker so it can execute the stated plan without rediscovering the whole project architecture.
State what to implement, where it belongs, which verified interfaces/facts to reuse, concrete project-specific rules,
mistakes to avoid, and how deterministic verification will establish completion. Do not invent unsupported features.
The goal anchor must remain compatible with the root project goal. Return only the compact structured mission.

BOUNDED COMPILER CONTEXT:
{_compact_mission_compiler_context(context)}"""
    schema = worker_mission_schema()
    try:
        if structured_call is None:
            data = structured_model_call(
                prompt_text, _worker_mission_validator, "mission-compilation", schema,
                role="MissionCompiler",
            )
        else:
            data = structured_call(prompt_text, _worker_mission_validator, "mission-compilation", schema)
        if not _worker_mission_validator(data):
            raise StructuredOutputError("mission compiler returned an invalid mission")
        mission = normalize_worker_mission(task, projection, data)
        if not _worker_mission_validator(mission):
            raise StructuredOutputError("normalized mission is incomplete")
        if isinstance(plan_node_contract, dict):
            mission["approved_plan_node_contract"] = _compact_approved_plan_node_contract(
                plan_node_contract,
            )
            mission = _bound_worker_mission(mission)
        return mission
    except StructuredOutputError as exc:
        RUN["mission_compilation_failures"] = RUN.get("mission_compilation_failures", 0) + 1
        record_run_event(
            "mission_compilation_failure", task_id=task.get("id"), error=str(exc),
        )
        raise MissionCompilationError(
            f"MISSION_COMPILATION_FAILURE for node {task.get('id', '')}: {exc}"
        ) from exc


implementation_mission = compile_worker_mission


def normalize_execution_choice(choice, contract):
    """Normalize routing without a cohesive/single-file recursion guard."""
    decision = str((choice or {}).get("decision") or (choice or {}).get("mode") or "recursive").lower()
    mode = "baseline" if decision in {"execute", "baseline"} else "recursive"
    return {
        "mode": mode,
        "decision": decision,
        "reason": str((choice or {}).get("reason", "model × task fit")),
    }


def decide_execution_mode(raw_goal, contract, repo_snapshot=None):
    """Decide auto routing after a Goal Contract and bounded reconnaissance."""
    repo_snapshot = repo_snapshot or inspect_repository()
    task = root_task_from_contract(contract)
    return normalize_execution_choice(decide_task_fit(task, 0, contract, repo_snapshot), contract)


def compact_contract(contract, max_chars=8000, include_source_ledger=False):
    contract = contract if isinstance(contract, dict) else {}
    source_ledger = contract.get("source_requirement_ledger")
    source_records = ledger_requirements(source_ledger)
    projection = {
        "goal": compact_text(contract.get("goal", ""), 900),
        # Workers receive the current node and relevant Brain projection, not
        # the complete immutable source ledger. Root planning gets the full
        # ledger through compact_project_brain instead.
        "requirements": bounded_list(
            contract.get("requirements", []), 8 if source_records else 20, 320,
        ),
        "constraints": bounded_list(contract.get("constraints", []), 12, 260),
        "success_criteria": bounded_list(contract.get("success_criteria", []), 12, 260),
    }
    if source_records:
        projection["source_requirement_count"] = len(source_records)
        projection["source_requirement_ids"] = [
            item.get("requirement_id") for item in source_records[:12]
        ]
        projection["source_requirement_ids_truncated"] = len(source_records) > 12
        projection["user_confirmed_requirements"] = bounded_list(
            [json.dumps(item, ensure_ascii=False, default=str)
             for item in contract.get("user_confirmed_requirements", [])], 4, 300,
        )
        projection["derived_assumptions"] = bounded_list(
            [json.dumps(item, ensure_ascii=False, default=str)
             for item in contract.get("derived_assumptions", [])], 4, 300,
        )
        if include_source_ledger:
            projection["source_requirements"] = [
                {"requirement_id": item.get("requirement_id"), "text": item.get("text", ""),
                 "source_segments": item.get("source_segments", [])}
                for item in source_records
            ]
    max_chars = max(256, int(max_chars))

    def size():
        return len(json.dumps(projection, ensure_ascii=False))

    while size() > max_chars:
        removed = False
        for field in ("requirements", "success_criteria", "constraints"):
            if projection[field]:
                projection[field].pop()
                removed = True
                break
        if not removed:
            goal = projection["goal"]
            if len(goal) > 120:
                projection["goal"] = compact_text(goal, max(120, len(goal) - 120))
                continue
            break
    return json.dumps(projection, ensure_ascii=False)


def contract_for_task(task, root_contract):
    """Build the small semantic verifier contract for one node."""
    if str(task.get("id")) == "ROOT":
        return dict(root_contract)
    done_when = list(task.get("done_when") or [])
    return {
        "status": "ready",
        "goal": compact_text(task.get("goal", ""), 1400),
        "requirements": bounded_list(done_when or [task.get("goal", "")], 8, 600),
        "constraints": bounded_list(root_contract.get("constraints", []), 8, 500),
        "success_criteria": bounded_list(done_when or ["the current node is executable and verified"], 8, 600),
        "original_goal": root_contract.get("original_goal", root_contract.get("goal", "")),
    }


# ---------------------------------------------------------------------------
# TASK CONTRACTS / NODE PACKETS / ADAPTIVE GRANULARITY
# ---------------------------------------------------------------------------

def make_task(task_id, goal, depth=0, parent=None, done_when=None, scope_hint=None,
              kind="implementation", integration_conflicts=None, integration_context=None):
    return {
        "id": str(task_id), "parent": parent, "depth": int(depth), "goal": compact_text(goal, 1800),
        "done_when": bounded_list(done_when or [], 12, 700), "scope_hint": bounded_list(scope_hint or [], 10, 300),
        "kind": str(kind or "implementation"),
        "integration_conflicts": list(integration_conflicts or []) if kind == "integration" else [],
        "integration_context": integration_context if kind == "integration" else None,
        "integration_split_boundary": False,
        "integration_resplit_attempts": 0,
        "integration_too_broad": False,
        "status": "pending", "children": [], "summary": "", "verification_status": "unknown",
        "changed_files": [], "failure_evidence": [],
        # The first failed execution is retained independently from the final
        # node status.  A re-split node can therefore finish PASS without
        # erasing the evidence that motivated the granularity change.
        "initial_result": None, "initial_status": None, "initial_failure_type": None,
        "initial_failure_evidence": [], "initial_failure_diagnosis": None,
        "attempts": [], "failure_diagnosis": None,
        "last_failure_type": None,
        "fit_before_execution": None,
        "execution_outcome": None,
        "execution_budget_exhausted": False,
        "repair_history": [],
        "budget_exhaustion_routing": None,
        "resplit": None,
        "decomposition_history": [],
        "failed_decompositions": [],
        "active_decomposition_id": None,
        "decomposition_alternatives": [],
        "decomposition_backtracks": 0,
        "alternative_decomposition_rescued": False,
        "terminal_too_broad": None,
        "decomposition_search_exhausted": False,
        "strategy_search": None,
        "strategy_attempts": [],
        "integration_manifest": None,
        "integration_preflight": None,
    }


def root_task_from_contract(contract):
    done_when = list(contract.get("requirements", [])) + list(contract.get("success_criteria", []))
    return make_task("ROOT", contract.get("goal", "coding task"), 0, None, done_when, [])


def _fit_validator(data):
    if not isinstance(data, dict) or str(data.get("decision", "")).lower() not in {"execute", "split"}:
        return False
    # Accept the old direct-test shape only when it is internally consistent;
    # the live schema below intentionally asks for the decision alone.
    if "subtasks" in data:
        subtasks = data.get("subtasks")
        if not isinstance(subtasks, list):
            return False
        if str(data["decision"]).lower() == "execute":
            return not subtasks
        return len(subtasks) >= 2
    return True


def task_fit_schema():
    return {
        "type": "object", "properties": {"decision": {"type": "string", "enum": ["execute", "split"]}},
        "required": ["decision"], "additionalProperties": False,
    }


def deterministic_fit_fallback(task, depth, contract, force_smaller=False):
    remaining = MAX_TOTAL_TASKS - RUN.get("tasks_created", 0)
    if depth >= MAX_DEPTH or remaining < 2:
        return {"decision": "execute", "reason": "hard recursion/task budget reached"}
    plan = current_approved_change_plan()
    planned_nodes = (
        stage3.approved_plan_node_contract(plan, task.get("plan_node_ids") or None).get("nodes", [])
        if isinstance(plan, dict) else []
    )
    responsibilities = planned_nodes or task.get("done_when") or list(contract.get("requirements", [])) + list(contract.get("success_criteria", []))
    # A proven scope assessment may force a smaller decomposition.  A raw
    # TASK_TOO_BROAD execution marker is not a scope assessment.
    if (force_smaller and _has_positive_scope_evidence(task, task.get("initial_result"))) or len(responsibilities) >= 3:
        return {"decision": "split", "reason": "deterministic bounded fallback"}
    text = task.get("goal", "")
    separators = len(re.findall(r"\b(?:and|plus|with|then)\b|[,;]", text, re.IGNORECASE))
    if separators >= 3 and MODEL_TASK_CAPACITY <= 2:
        return {"decision": "split", "reason": "multiple responsibilities under weak-model prior"}
    return {"decision": "execute", "reason": "coarsest deterministic fallback"}


def decide_task_fit(task, depth, contract, repo_snapshot=None, parent_summary="", dependency_summaries=None,
                    force_smaller=False):
    # Keep the public helper convenient for deterministic callers that do not
    # need to prepare reconnaissance themselves.
    if repo_snapshot is None:
        repo_snapshot = inspect_repository()
    elif isinstance(repo_snapshot, list) and dependency_summaries is None and not parent_summary:
        dependency_summaries, repo_snapshot = repo_snapshot, inspect_repository()
    dependency_summaries = dependency_summaries or []
    if str(task.get("id", "")) == "ROOT" and "TASK_FIT" not in RUN.setdefault("control_flow", []):
        RUN["control_flow"].append("TASK_FIT")
    remaining = MAX_TOTAL_TASKS - RUN.get("tasks_created", 0)
    if depth >= MAX_DEPTH or remaining < 2:
        return {"decision": "execute", "reason": "hard budget reached"}
    failure = task.get("failure_evidence", [])[-3:]
    approved_plan = current_approved_change_plan()
    if isinstance(approved_plan, dict) and not approved_plan.get("approved_change_nodes"):
        return {
            "decision": "execute",
            "reason": "approved plan contains preservation/verification only",
        }
    approved_plan_packet = (
        stage3.decomposition_plan_packet(approved_plan)
        if isinstance(approved_plan, dict) else "(not applicable / NEW_PROJECT)"
    )
    prompt_text = f"""Decide TASK GRANULARITY FIT, not generic complexity.
Question: Is CURRENT NODE small and explicit enough that THIS pinned local model is likely to implement AND verify it reliably in ONE focused Builder execution?
Return only EXECUTE or SPLIT in the schema. Find the coarsest reliable granularity; more splitting is not automatically better.
Consider responsibilities, likely files/interfaces, context needed, independent verification boundaries, dependency complexity, ambiguity, previous failure evidence, model-capacity heuristic, depth, and remaining task budget.
Sequential milestones MAY edit the same file; cohesive/single-file work is NOT a reason to force EXECUTE.
{('The previous focused execution exceeded capacity. SPLIT into materially smaller scope if budget permits.' if force_smaller else '')}
MODEL={MODEL}; CAPACITY_HINT={MODEL_TASK_CAPACITY}/4 heuristic only; DEPTH={depth}/{MAX_DEPTH}; REMAINING={remaining}
ROOT CONTRACT: {compact_contract(contract)}
APPROVED PLAN EXECUTION CONTRACT: {json.dumps(approved_plan_packet, ensure_ascii=False, default=str)}
PROJECT BRAIN (expanded specification + verified state): {project_brain_task_planning_packet(task, dependency_summaries, repo_snapshot, max_chars=4200)}
CURRENT NODE: {json.dumps({k: task.get(k) for k in ('goal','done_when','scope_hint')}, ensure_ascii=False)}
PARENT VERIFIED SUMMARY: {compact_text(parent_summary or '(none)', 900)}
VERIFIED DEPENDENCIES: {json.dumps(dependency_summaries[-4:], ensure_ascii=False)[:2600]}
FAILURE EVIDENCE: {json.dumps(failure, ensure_ascii=False)[:1800]}
REPOSITORY SNAPSHOT: {repository_hints(repo_snapshot, task.get('scope_hint'))}"""
    try:
        data = structured_model_call(prompt_text, _fit_validator, "task-fit", task_fit_schema())
        decision = str(data["decision"]).lower()
        return {"decision": decision, "reason": "model × task fit"}
    except StructuredOutputError as exc:
        fallback = deterministic_fit_fallback(task, depth, contract, force_smaller=force_smaller)
        print(f"[STRUCTURED RETRY] task-fit fallback | {exc}")
        record_run_event("structured_fallback", label="task-fit", error=str(exc), fallback=fallback)
        return fallback
    except (KeyError, TypeError, ValueError) as exc:
        # A malformed orchestration envelope is recoverable planning noise, not
        # a reason to kill the root task or to misclassify it as too broad.
        fallback = deterministic_fit_fallback(task, depth, contract, force_smaller=force_smaller)
        print(f"[STRUCTURED RETRY] task-fit fallback | {exc}")
        record_run_event("structured_fallback", label="task-fit", error=str(exc), fallback=fallback)
        return fallback


def _children_validator(data):
    if not isinstance(data, dict) or not isinstance(data.get("children"), list):
        return False
    children = data["children"]
    if not 2 <= len(children) <= MAX_CHILDREN:
        return False
    for child in children:
        if not isinstance(child, dict) or not isinstance(child.get("goal"), str) or not child["goal"].strip():
            return False
        if (not isinstance(child.get("done_when"), list) or not child.get("done_when")
                or not all(isinstance(item, str) and item.strip() for item in child.get("done_when", []))
                or not isinstance(child.get("scope_hint"), list)):
            return False
    return True


def children_schema():
    child = {
        "type": "object", "properties": {
            "goal": {"type": "string"}, "done_when": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 6},
            "scope_hint": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        },
        "required": ["goal", "done_when", "scope_hint"], "additionalProperties": False,
    }
    return {"type": "object", "properties": {
        "children": {"type": "array", "items": child, "minItems": 2, "maxItems": MAX_CHILDREN}},
        "required": ["children"], "additionalProperties": False}


def fallback_child_contracts(task):
    items = list(task.get("done_when", []))
    if len(items) >= 2:
        count = min(MAX_CHILDREN, len(items))
        buckets = [[] for _ in range(count)]
        for index, item in enumerate(items):
            buckets[index % count].append(item)
        return [{"goal": "; ".join(bucket), "done_when": bucket, "scope_hint": list(task.get("scope_hint", []))}
                for bucket in buckets if bucket]
    goal = task.get("goal", "task")
    return [
        {"goal": f"Establish a minimal verified foundation for: {goal}",
         "done_when": ["foundation executes and exposes required interfaces"], "scope_hint": task.get("scope_hint", [])},
        {"goal": f"Complete and verify the remaining behavior for: {goal}",
         "done_when": task.get("done_when", []) or ["parent goal behavior is complete"], "scope_hint": task.get("scope_hint", [])},
    ]


def bind_decomposition_to_approved_plan(specs):
    """Deterministically enforce the approved Stage 3 responsibility graph."""
    plan = current_approved_change_plan()
    if not isinstance(plan, dict):
        return list(specs or [])
    bound = stage3.bind_decomposition_to_plan(specs, plan)
    expansions = list(bound.get("scope_expansions", []) or [])
    if expansions:
        RUN["unapproved_scope_expansions"] = RUN.get("unapproved_scope_expansions", 0) + len(expansions)
        record_run_event(
            "unapproved_scope_expansion", paths=expansions,
            plan_id=plan.get("plan_id"), plan_hash=plan.get("plan_hash"),
        )
    if not bound.get("valid"):
        raise ImpactPlanningError(
            "DECOMPOSITION_PLAN_COVERAGE_FAILURE: "
            + ", ".join(bound.get("unassigned_plan_node_ids", []))
        )
    RUN["decomposition_plan_coverage"] = {
        "plan_id": plan.get("plan_id"), "plan_hash": plan.get("plan_hash"),
        "covered_plan_node_ids": sorted({
            item for spec in bound.get("specs", []) for item in spec.get("plan_node_ids", [])
        }),
        "scope_expansions_rejected": expansions,
    }
    return bound.get("specs", [])


def decompose_task(task, contract, repo_snapshot, parent_summary="", dependency_summaries=None, force_smaller=False):
    if str(task.get("id", "")) == "ROOT" and "DECOMPOSITION" not in RUN.setdefault("control_flow", []):
        RUN["control_flow"].append("DECOMPOSITION")
    if task.get("kind") == "integration":
        integration_children = decompose_integration_task(
            task, contract, repo_snapshot, parent_summary, dependency_summaries, force_smaller,
        )
        plan = current_approved_change_plan()
        if isinstance(plan, dict):
            for child in integration_children:
                attach_approved_plan_to_task(
                    child, plan, task.get("plan_node_ids") or None,
                )
        return integration_children
    remaining = MAX_TOTAL_TASKS - RUN.get("tasks_created", 0)
    if remaining < 2:
        return []
    approved_plan = current_approved_change_plan()
    if isinstance(approved_plan, dict) and not approved_plan.get("approved_change_nodes"):
        return []
    approved_plan_packet = (
        stage3.decomposition_plan_packet(approved_plan)
        if isinstance(approved_plan, dict) else "(not applicable / NEW_PROJECT)"
    )
    prompt_text = f"""Split CURRENT NODE into 2-4 SMALL STRUCTURED SEQUENTIAL child contracts for the pinned weak local model.
Each child supplies only goal, done_when, scope_hint. Children together must preserve the parent goal.
Prefer independently verifiable milestones. Sequential children MAY touch the same file; never create parallel ownership assumptions.
Do not create arbitrary microtasks like 'write import' or 'create variable' unless previous failure proves larger scope is still too broad.
For an approved existing-project plan, every child must stay inside its plan nodes; do not invent mutation surfaces.
{('The failed parent still exceeded capacity: make each child materially smaller in simultaneous reasoning/context.' if force_smaller else '')}
ROOT CONTRACT: {compact_contract(contract)}
APPROVED PLAN EXECUTION CONTRACT: {json.dumps(approved_plan_packet, ensure_ascii=False, default=str)}
PROJECT BRAIN (expanded specification + verified state): {project_brain_task_planning_packet(task, dependency_summaries, repo_snapshot, max_chars=5200)}
PARENT NODE: {json.dumps({k: task.get(k) for k in ('goal','done_when','scope_hint')}, ensure_ascii=False)}
PARENT VERIFIED SUMMARY: {compact_text(parent_summary or '(none)', 700)}
DEPENDENCIES: {json.dumps((dependency_summaries or [])[-4:], ensure_ascii=False)[:2000]}
REPOSITORY HINTS: {repository_hints(repo_snapshot, task.get('scope_hint'))}"""
    try:
        data = structured_model_call(prompt_text, _children_validator, "decompose-task", children_schema())
        specs = data["children"]
    except (StructuredOutputError, KeyError, TypeError, ValueError) as exc:
        specs = fallback_child_contracts(task)
        record_run_event("structured_fallback", label="decompose-task", error=str(exc))
    specs = specs[:min(MAX_CHILDREN, remaining)]
    if isinstance(approved_plan, dict):
        specs = bind_decomposition_to_approved_plan(specs)
        if len(specs) > min(MAX_CHILDREN, remaining):
            specs = bind_decomposition_to_approved_plan(
                specs[:min(MAX_CHILDREN, remaining)],
            )
    if len(specs) < 2:
        return []
    children = []
    for index, spec in enumerate(specs, 1):
        child_id = str(index) if task["id"] == "ROOT" else f"{task['id']}.{index}"
        child = make_task(child_id, spec["goal"], task["depth"] + 1, task["id"],
                          spec.get("done_when", []), spec.get("scope_hint", []))
        if isinstance(approved_plan, dict):
            attach_approved_plan_to_task(child, approved_plan, spec.get("plan_node_ids"))
            child["plan_requirement_ids"] = list(spec.get("requirement_ids", []))
            child["plan_impact_ids"] = list(spec.get("impact_ids", []))
            child["plan_evidence_ids"] = list(spec.get("evidence_ids", []))
            child["verification_only"] = bool(spec.get("verification_only"))
        TASKS[child_id] = child
        task["children"].append(child_id)
        RUN["tasks_created"] += 1
        RUN["max_depth"] = max(RUN["max_depth"], child["depth"])
        update_task_ledger(child)
        children.append(child)
    _record_decomposition_branch(
        task, specs, children, kind="resplit" if force_smaller else "initial",
    )
    return children


def _compact_decomposition_spec(spec):
    spec = spec if isinstance(spec, dict) else {}
    return {
        "goal": compact_text(spec.get("goal", ""), 420),
        "done_when": bounded_list(spec.get("done_when", []), 6, 220),
        "scope_hint": bounded_list(spec.get("scope_hint", []), 6, 140),
    }


def _record_decomposition_branch(task, specs, children, kind="initial", branch_id=None):
    """Record one decomposition boundary before its children execute."""
    if not isinstance(task, dict):
        return None
    history = task.setdefault("decomposition_history", [])
    branch_id = branch_id or f"{kind}-{len(history) + 1}"
    branch = {
        "branch_id": str(branch_id),
        "kind": str(kind),
        "child_ids": [str(child.get("id", "")) for child in children if isinstance(child, dict)],
        "children": [_compact_decomposition_spec(spec) for spec in (specs or [])],
        "status": "running",
        "children_result": [],
        "failure_evidence": [],
        "terminal_child_ids": [],
    }
    history.append(branch)
    task["active_decomposition_id"] = branch["branch_id"]
    return branch


def _decomposition_tokens(value):
    stop_words = {
        "a", "an", "and", "are", "as", "at", "be", "by", "complete", "create", "do",
        "for", "from", "implement", "make", "of", "one", "the", "then", "to", "with",
        "verify", "verified", "use", "using", "existing", "minimal", "remaining", "behavior",
    }
    return {
        token for token in re.findall(r"[a-z0-9_$]+", str(value).casefold())
        if len(token) > 2 and token not in stop_words
    }


def _decomposition_spec_tokens(spec):
    spec = spec if isinstance(spec, dict) else {}
    values = [spec.get("goal", ""), *list(spec.get("done_when", []) or []), *list(spec.get("scope_hint", []) or [])]
    tokens = set()
    for value in values:
        tokens.update(_decomposition_tokens(value))
    return tokens


def _materially_different_decomposition(specs, failed_decompositions):
    """Reject alternatives that are only lexical paraphrases of failed branches."""
    specs = list(specs or [])
    failed_specs = []
    for branch in failed_decompositions or []:
        if not isinstance(branch, dict):
            continue
        failed_specs.extend(branch.get("children", []) or [])
    if not specs or not failed_specs:
        return bool(specs)
    old_tokens = [_decomposition_spec_tokens(spec) for spec in failed_specs]
    new_tokens = [_decomposition_spec_tokens(spec) for spec in specs]
    similarities = []
    for current in new_tokens:
        if not current:
            similarities.append(1.0)
            continue
        similarities.append(max(
            len(current & previous) / max(1, len(current | previous))
            for previous in old_tokens
        ))
    # A branch is invalid when every new child is effectively the same boundary
    # as something that already failed.  One genuinely new observable boundary
    # is enough to keep a useful mixed decomposition.
    return not all(score >= 0.78 for score in similarities)


def _alternative_fallback_child_contracts(task):
    """Produce generic observable boundaries if structured planning is unavailable."""
    goal = compact_text(task.get("goal", "task"), 520)
    requirements = list(task.get("done_when", []) or [])
    if requirements:
        return [
            {
                "goal": f"Define the smallest observable state or input boundary for: {goal}",
                "done_when": [f"one explicit state/input boundary for {requirements[0]} is observable"],
                "scope_hint": list(task.get("scope_hint", [])),
            },
            {
                "goal": f"Implement one deterministic transition at that boundary for: {goal}",
                "done_when": [f"the transition for {requirements[min(1, len(requirements) - 1)]} is observable"],
                "scope_hint": list(task.get("scope_hint", [])),
            },
            {
                "goal": f"Verify one end-to-end observable outcome for: {goal}",
                "done_when": ["one deterministic outcome is verified without relying on narrative claims"],
                "scope_hint": list(task.get("scope_hint", [])),
            },
        ]
    return [
        {
            "goal": f"Expose one observable state boundary for: {goal}",
            "done_when": ["one state boundary is observable and deterministic"],
            "scope_hint": list(task.get("scope_hint", [])),
        },
        {
            "goal": f"Implement one deterministic transition for: {goal}",
            "done_when": ["one transition is observable and deterministic"],
            "scope_hint": list(task.get("scope_hint", [])),
        },
        {
            "goal": f"Verify one observable outcome for: {goal}",
            "done_when": ["one executable outcome is verified"],
            "scope_hint": list(task.get("scope_hint", [])),
        },
    ]


def compact_failed_decompositions(task):
    """Project prior failed boundaries into a bounded parent/Node Packet."""
    if not isinstance(task, dict):
        return []
    result = []
    for branch in task.get("decomposition_history", []) or []:
        if not isinstance(branch, dict) or branch.get("status") not in {"failed", "exhausted", "blocked"}:
            continue
        result.append({
            "branch_id": str(branch.get("branch_id", "")),
            "kind": str(branch.get("kind", "")),
            "children": list(branch.get("children", []) or [])[:MAX_CHILDREN],
            "children_result": list(branch.get("children_result", []) or [])[:MAX_CHILDREN],
            "terminal_child_ids": list(branch.get("terminal_child_ids", []) or [])[:MAX_CHILDREN],
            "why_failed": compact_text(branch.get("why_failed", ""), 420),
            "failure_evidence": list(branch.get("failure_evidence", []) or [])[:4],
        })
    return result[-MAX_DECOMPOSITION_ALTERNATIVES - 1:]


def decompose_alternative_task(task, contract, repo_snapshot, parent_summary="", dependency_summaries=None,
                               terminal_failure=None):
    """Ask for a materially different decomposition after a terminal broad failure."""
    failed_decompositions = compact_failed_decompositions(task)
    goal = compact_text(task.get("goal", "task"), 1000)
    terminal_failure = terminal_failure if isinstance(terminal_failure, dict) else {}
    prompt_text = f"""Create 2-4 ALTERNATIVE structured child contracts for the current parent node.
This is decomposition BACKTRACKING after a terminal child remained unresolved
after a bounded focused execution (including TASK_TOO_BROAD or
EXECUTION_BUDGET_EXHAUSTED).
Do NOT continue the same decomposition direction and do NOT paraphrase a failed child.
The new children must be materially smaller in simultaneous reasoning load and use
different observable boundaries. Prefer one state transition, one input/output,
one interface, or one deterministic behavior per child. Each child must have a
concrete executable done_when condition. Children together must preserve the parent goal.

FAILED DECOMPOSITIONS (a new child is invalid if it merely restates one of these):
{json.dumps(failed_decompositions, ensure_ascii=False)[:5200] or '(none)'}

TERMINAL FAILURE:
{json.dumps(terminal_failure, ensure_ascii=False)[:2200] or '(none)'}
ROOT CONTRACT: {compact_contract(contract)}
PROJECT BRAIN (expanded specification + verified state): {project_brain_task_planning_packet(task, dependency_summaries, repo_snapshot, max_chars=5200)}
PARENT NODE: {json.dumps({k: task.get(k) for k in ('goal','done_when','scope_hint')}, ensure_ascii=False)}
PARENT VERIFIED SUMMARY: {compact_text(parent_summary or '(none)', 700)}
DEPENDENCIES: {json.dumps((dependency_summaries or [])[-4:], ensure_ascii=False)[:2000]}
REPOSITORY HINTS: {repository_hints(repo_snapshot, task.get('scope_hint'))}"""

    def validator(data):
        return _children_validator(data) and _materially_different_decomposition(
            data.get("children", []), failed_decompositions,
        )

    try:
        data = structured_model_call(prompt_text, validator, "alternative-decompose-task", children_schema())
        specs = data["children"]
    except (StructuredOutputError, KeyError, TypeError, ValueError) as exc:
        specs = _alternative_fallback_child_contracts(task)
        record_run_event("structured_fallback", label="alternative-decompose-task", error=str(exc))
    if not _materially_different_decomposition(specs, failed_decompositions):
        record_run_event(
            "alternative_decomposition_rejected", task_id=task.get("id"),
            reason="candidate boundaries paraphrased a failed decomposition",
        )
        return []
    specs = list(specs)[:MAX_CHILDREN]
    if isinstance(current_approved_change_plan(), dict):
        specs = bind_decomposition_to_approved_plan(specs)
        if len(specs) > MAX_CHILDREN:
            specs = bind_decomposition_to_approved_plan(specs[:MAX_CHILDREN])
    return specs


def alternate_strategy_schema():
    strategy = {
        "type": "object", "properties": {
            "name": {"type": "string"},
            "approach": {"type": "string"},
            "scope": {
                "type": "array", "items": {"type": "string"},
                "minItems": 1, "maxItems": 4,
            },
            "why_different": {"type": "string"},
            "verification_plan": {"type": "string"},
        },
        "required": ["name", "approach", "scope", "why_different"],
        "additionalProperties": False,
    }
    return {
        "type": "object", "properties": {
            "strategies": {"type": "array", "items": strategy,
                           "minItems": MAX_STRATEGY_ALTERNATIVES,
                           "maxItems": MAX_STRATEGY_ALTERNATIVES},
        },
        "required": ["strategies"], "additionalProperties": False,
    }


def _normalize_alternate_strategy(strategy):
    """Normalize the v5 strategy contract without preserving model chatter."""
    if not isinstance(strategy, dict):
        return None
    legacy = "label" in strategy
    name = strategy.get("name") or (strategy.get("label") if legacy else "")
    approach = strategy.get("approach", "")
    scope = strategy.get("scope")
    why_different = strategy.get("why_different")
    if legacy and scope is None:
        scope = "the current bounded node"
    if legacy and not why_different:
        why_different = "changes the implementation boundary instead of repeating the failed path"
    if isinstance(scope, (list, tuple)):
        scope = "; ".join(str(item) for item in scope)
    values = (name, approach, scope, why_different)
    if not all(isinstance(value, str) and value.strip() for value in values):
        return None
    normalized = {
        "name": compact_text(name, 100),
        "approach": compact_text(approach, 900),
        "scope": compact_text(scope, 360),
        "why_different": compact_text(why_different, 500),
    }
    verification_plan = strategy.get("verification_plan", "")
    if isinstance(verification_plan, str) and verification_plan.strip():
        normalized["verification_plan"] = compact_text(verification_plan, 420)
    return normalized


def _normalized_alternate_strategies(value):
    if not isinstance(value, list):
        return []
    normalized = [_normalize_alternate_strategy(item) for item in value]
    return normalized if all(item is not None for item in normalized) else []


def _strategy_tokens(strategy):
    strategy = strategy if isinstance(strategy, dict) else {}
    return _decomposition_tokens(" ".join(
        str(strategy.get(key, "")) for key in ("approach", "scope")
    ))


def _strategies_are_materially_different(strategies):
    strategies = _normalized_alternate_strategies(strategies)
    if len(strategies) != MAX_STRATEGY_ALTERNATIVES:
        return False
    first_name = re.sub(r"[^a-z0-9]+", "", strategies[0]["name"].casefold())
    second_name = re.sub(r"[^a-z0-9]+", "", strategies[1]["name"].casefold())
    if not first_name or first_name == second_name:
        return False
    first = _strategy_tokens(strategies[0])
    second = _strategy_tokens(strategies[1])
    if not first or not second:
        return False
    overlap = len(first & second) / max(1, len(first | second))
    return overlap < 0.78


def _alternate_strategy_validator(data):
    if not isinstance(data, dict):
        return False
    strategies = data.get("strategies")
    return bool(
        isinstance(strategies, list)
        and len(strategies) == MAX_STRATEGY_ALTERNATIVES
        and _strategies_are_materially_different(strategies)
    )


def _strategy_failure_summaries(task, failure_result):
    failure_result = failure_result if isinstance(failure_result, dict) else {}
    attempts = []
    for item in list(task.get("attempts", []) or [])[-3:]:
        if isinstance(item, dict):
            attempts.append({
                "phase": str(item.get("phase", ""))[:40],
                "summary": compact_text(item.get("summary", ""), 360),
                "failure_type": str(item.get("failure_type", ""))[:60],
            })
    failed_approach = compact_text(
        f"The current implementation approach for '{task.get('goal', '')}' ended with: "
        f"{failure_result.get('summary', 'deterministic verification failure')}", 1000,
    )
    previous_repair = compact_text(json.dumps(attempts, ensure_ascii=False), 900) if attempts else "(none)"
    return failed_approach, previous_repair


def search_alternate_strategies(task, contract, failure_result, memory, repo_snapshot,
                                parent_summary="", dependency_summaries=None):
    """Generate at most two non-mutating, materially different v5 strategies."""
    RUN["strategy_searches"] = RUN.get("strategy_searches", 0) + 1
    if (
        task.get("capability_floor_blocked_by") == "strategy_search_not_attempted"
        and not task.get("_capability_floor_routed_to_strategy_counted")
    ):
        RUN["capability_floor_routed_to_strategy"] = RUN.get(
            "capability_floor_routed_to_strategy", 0,
        ) + 1
        task["_capability_floor_routed_to_strategy_counted"] = True
        record_run_event(
            "capability_floor_routed_to_strategy", task_id=task.get("id"),
            route="strategy_search",
        )
    evidence = _failure_evidence_from_result(failure_result)
    failed_approach, previous_repair = _strategy_failure_summaries(task, failure_result)
    node_packet = build_node_context(
        task, contract, get_memory_store(), repo_snapshot, parent_summary, dependency_summaries, evidence,
    )
    prompt_text = f"""Generate exactly TWO materially different implementation strategies for this SMALL failed implementation node.
This is a planning-only call. Do not edit files, call tools, or change the workspace. Do not propose another
decomposition. Execute candidates later in fixed order: Strategy A first, then Strategy B only if A fails.
Each strategy must change the implementation boundary or mechanism materially, stay within the current node scope,
and include a cheap executable verification plan. Do not return a minor patch, a renamed version, or a paraphrase
of the failed approach.

CURRENT NODE: {json.dumps({k: task.get(k) for k in ('goal', 'done_when', 'scope_hint')}, ensure_ascii=False)}
FAILED APPROACH SUMMARY: {failed_approach}
FAILED DETERMINISTIC EVIDENCE: {json.dumps(evidence, ensure_ascii=False)[:3600]}
PREVIOUS REPAIR SUMMARY: {previous_repair}
NODE PACKET: {node_packet[:5200]}
Return only the two candidates in the schema with name, approach, scope, and why_different."""
    rejected_candidates = []
    generation_attempts = []

    def request_candidates(prompt, label):
        nonlocal rejected_candidates
        attempt = {"label": label}
        try:
            data = structured_model_call(
                prompt, _alternate_strategy_validator, label, alternate_strategy_schema(),
            )
            raw_candidates = data.get("strategies") if isinstance(data, dict) else None
            attempt["candidate_count"] = len(raw_candidates) if isinstance(raw_candidates, list) else 0
            candidates = _normalized_alternate_strategies(raw_candidates)
            if _strategies_are_materially_different(candidates):
                attempt["status"] = "valid"
                generation_attempts.append(attempt)
                return candidates
            if candidates:
                rejected_candidates = candidates[:MAX_STRATEGY_ALTERNATIVES]
            elif isinstance(raw_candidates, list):
                rejected_candidates = list(raw_candidates)[:MAX_STRATEGY_ALTERNATIVES]
            if not isinstance(data, dict) or not isinstance(raw_candidates, list):
                attempt["reason"] = "invalid_strategy_shape"
            elif len(raw_candidates) != MAX_STRATEGY_ALTERNATIVES:
                attempt["reason"] = "requires_exactly_two_strategies"
            elif not candidates:
                attempt["reason"] = "invalid_strategy_fields"
            else:
                attempt["reason"] = "strategies_not_materially_different"
            attempt["status"] = "rejected"
            generation_attempts.append(attempt)
            return None
        except (ProviderError, StructuredOutputError, KeyError, TypeError, ValueError, StopIteration) as exc:
            attempt["status"] = "error"
            attempt["error_type"] = type(exc).__name__
            attempt["error"] = compact_text(str(exc), 180)
            generation_attempts.append(attempt)
            record_run_event("structured_strategy_error", label=label, error=str(exc))
            return None

    strategies = request_candidates(prompt_text, "alternate-strategy-search")
    if strategies is None:
        record_run_event(
            "strategy_candidates_rejected", task_id=task.get("id"),
            reason="invalid, duplicate, or paraphrased candidates",
        )
        replacement_prompt = f"""Replace the rejected strategy pair for this bounded implementation node.
Planning only: do not edit files or call tools. Return exactly TWO candidates. Keep the current node scope,
but make the two mechanisms and ownership boundaries visibly different. The replacement must not be a minor patch
or paraphrase of the failed approach or of the rejected pair. Strategy A is executed first; B is only a fallback.

CURRENT NODE: {json.dumps({k: task.get(k) for k in ('goal', 'done_when', 'scope_hint')}, ensure_ascii=False)}
FAILED APPROACH SUMMARY: {failed_approach}
FAILED DETERMINISTIC EVIDENCE: {json.dumps(evidence, ensure_ascii=False)[:3000]}
PREVIOUS REPAIR SUMMARY: {previous_repair}
REJECTED PAIR: {json.dumps(rejected_candidates, ensure_ascii=False)[:3200]}
Return only the schema fields name, approach, scope, and why_different, plus an optional verification_plan."""
        strategies = request_candidates(replacement_prompt, "alternate-strategy-replacement")
    if strategies is None:
        if not task.get("_strategy_generation_failure_counted"):
            RUN["strategy_generation_failures"] = RUN.get("strategy_generation_failures", 0) + 1
            task["_strategy_generation_failure_counted"] = True
        task["strategy_search"] = {
            "status": "generation_unavailable",
            "outcome": "generation_unavailable",
            "failure_type": STRATEGY_SEARCH_UNAVAILABLE,
            "strategies": [],
            "execution_order": [],
            "failed_approach_summary": failed_approach,
            "previous_repair_summary": previous_repair,
            "failure_evidence": evidence[-4:],
            "generation_attempts": generation_attempts[-2:],
            "attempts": [],
        }
        record_run_event(
            "strategy_search_unavailable", task_id=task.get("id"),
            failure_type=STRATEGY_SEARCH_UNAVAILABLE,
            generation_attempts=generation_attempts[-2:],
        )
        return []

    strategies = strategies[:MAX_STRATEGY_ALTERNATIVES]
    task["strategy_search"] = {
        "status": "planned",
        "strategies": strategies,
        "execution_order": [item["name"] for item in strategies],
        "failed_approach_summary": failed_approach,
        "previous_repair_summary": previous_repair,
        "failure_evidence": evidence[-4:],
        "generation_attempts": generation_attempts[-2:],
        "attempts": [],
    }
    task.setdefault("strategy_attempts", [])
    record_run_event(
        "strategy_search", task_id=task.get("id"),
        strategies=[compact_text(item.get("name", ""), 80) for item in strategies],
    )
    return strategies


def select_alternate_strategy(task, strategies, failure_result=None):
    """Compatibility helper: v5 always executes Strategy A before Strategy B.

    This intentionally performs no Challenger/model call.  The real execution
    path does not use a selector; keeping the helper avoids breaking callers of
    the v3 prototype while making the fixed order explicit.
    """
    strategies = _normalized_alternate_strategies(list(strategies or []))
    index = 0
    if not isinstance(task.get("strategy_search"), dict):
        task["strategy_search"] = {}
    task["strategy_search"]["selected_index"] = index
    task["strategy_search"]["selection"] = "deterministic_order"
    record_run_event("strategy_order", task_id=task.get("id"), first_index=index)
    return index


def _strategy_task_snapshot(task):
    excluded = {"strategy_search", "strategy_attempts"}
    return {
        key: copy.deepcopy(value) for key, value in task.items() if key not in excluded
    }


def _restore_strategy_task_snapshot(task, snapshot):
    excluded = {"strategy_search", "strategy_attempts"}
    for key in list(task):
        if key not in excluded and key not in snapshot:
            task.pop(key, None)
    for key, value in snapshot.items():
        task[key] = copy.deepcopy(value)


def _record_strategy_attempt(task, strategy, result, attempt_index):
    strategy = _normalize_alternate_strategy(strategy) or {"name": "alternative"}
    result = result if isinstance(result, dict) else {}
    attempt = {
        "index": int(attempt_index),
        "name": strategy.get("name", "alternative"),
        "status": "PASS" if result.get("status") == "done" else "FAIL",
        "failure_type": str(result.get("failure_type", ""))[:80],
        "summary": compact_text(result.get("summary", ""), MAX_NODE_SUMMARY_CHARS),
        "changed_files": bounded_list(result.get("changed_files", []), 8, 140),
        "failure_evidence": _failure_evidence_from_result(result)[-4:],
    }
    task.setdefault("strategy_attempts", []).append(attempt)
    if not isinstance(task.get("strategy_search"), dict):
        task["strategy_search"] = {}
    search = task["strategy_search"]
    search.setdefault("attempts", []).append(attempt)
    record_run_event("strategy_attempt", task_id=task.get("id"), **attempt)
    return attempt


def _strategy_context(strategy, task, failure_result):
    failed_approach, previous_repair = _strategy_failure_summaries(task, failure_result)
    return {
        "failed_approach_summary": failed_approach,
        "current_deterministic_failure": _failure_evidence_from_result(failure_result)[-4:],
        "previous_repair_summary": previous_repair,
        "strategy": _normalize_alternate_strategy(strategy) or {},
    }


def execute_strategy_attempt(task, contract, strategy, failure_result, memory, repo_snapshot,
                             parent_summary="", dependency_summaries=None, attempt_index=0):
    """Run one candidate through the normal leaf Builder/repair/verification engine."""
    strategy = _normalize_alternate_strategy(strategy) or {}
    RUN["alternate_strategies_attempted"] = RUN.get("alternate_strategies_attempted", 0) + 1
    baseline_task = _strategy_task_snapshot(task)
    baseline_memory = copy.deepcopy(memory)
    baseline_repo = copy.deepcopy(repo_snapshot)
    baseline_dependencies = copy.deepcopy(list(dependency_summaries or []))
    label = compact_text(strategy.get("name", f"strategy_{attempt_index + 1}"), 80)
    event(
        f"[STRATEGY {chr(65 + int(attempt_index))} {task.get('id')}] execute {label}",
        role="Builder", task=task.get("id"), action="bounded alternate strategy",
    )
    try:
        result = execute_leaf(
            task, contract, baseline_memory, baseline_repo, parent_summary, baseline_dependencies,
            strategy_context=_strategy_context(strategy, task, failure_result),
        )
    except ProviderError as exc:
        if ACTIVE_TRANSACTION is not None:
            rollback_transaction()
        result = {
            "status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": str(exc),
            "memory": baseline_memory,
        }
    except (RuntimeError, TypeError) as exc:
        # A failed candidate must never leave a live transaction that can bleed
        # into candidate B.  The production leaf engine accepts strategy_context;
        # TypeError remains a bounded failure for injected test engines.
        if ACTIVE_TRANSACTION is not None:
            rollback_transaction()
        result = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": f"alternate strategy execution failed: {exc}", "memory": baseline_memory,
        }
    if not isinstance(result, dict):
        result = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "alternate strategy returned no result", "memory": baseline_memory,
        }
    if result.get("status") == "done":
        if ACTIVE_TRANSACTION is not None:
            changed = commit_transaction()
            result.setdefault("changed_files", changed)
    else:
        # The normal leaf engine already rolls back on failure. Calling the
        # idempotent guard here also protects the A -> B boundary when a test
        # or injected leaf engine reports failure after managing its own state.
        rollback_transaction()

    result["strategy"] = strategy
    result["strategy_attempt_index"] = int(attempt_index)
    _record_strategy_attempt(task, strategy, result, attempt_index)
    if result.get("status") != "done":
        _restore_strategy_task_snapshot(task, baseline_task)
    return result


def execute_selected_strategy(task, contract, strategy, failure_result, memory, repo_snapshot,
                              parent_summary="", dependency_summaries=None, attempt_index=0):
    """Compatibility wrapper for one fixed-order v5 strategy attempt."""
    return execute_strategy_attempt(
        task, contract, strategy, failure_result, memory, repo_snapshot,
        parent_summary, dependency_summaries, attempt_index,
    )


def _maybe_search_alternate_strategy(task, contract, leaf_result, memory, repo_snapshot,
                                     parent_summary="", dependency_summaries=None,
                                     diagnosis=None):
    if not isinstance(task, dict) or not isinstance(leaf_result, dict):
        return None
    if task.get("kind", "implementation") != "implementation":
        return None
    evidence = _failure_evidence_from_result(leaf_result)
    diagnosis = diagnosis if isinstance(diagnosis, dict) and diagnosis.get("category") else diagnose_failure(
        task, leaf_result, evidence,
    )
    task["failure_diagnosis"] = diagnosis
    blocked_categories = {
        "scope_too_broad", "dependency_error", "verifier_builder_mismatch",
        "local_integration_state_corruption", "model_capability_floor", "environment_failure",
        "provider_failure", "unknown", "decomposition_error",
    }
    if (
        not (
            leaf_result.get("failure_type") == "IMPLEMENTATION_ERROR"
            or leaf_result.get("failure_type") == "TASK_TOO_BROAD"
            or _is_execution_budget_exhausted(leaf_result)
        )
        or diagnosis.get("category") != "implementation_strategy_wrong"
        or diagnosis.get("category") in blocked_categories
        or not _strategy_scope_is_bounded(task, leaf_result)
        or not evidence
        or not _has_concrete_executable_failure(evidence)
    ):
        return None
    if isinstance(task.get("strategy_search"), dict):
        # One search per failed node. A completed search must not turn into a
        # new recursion or strategy loop.
        if task["strategy_search"].get("outcome") == "generation_unavailable":
            unavailable_result = dict(leaf_result)
            unavailable_result["strategy_search_status"] = STRATEGY_SEARCH_UNAVAILABLE
            unavailable_result["strategy_search"] = copy.deepcopy(task["strategy_search"])
            if isinstance(task.get("failure_diagnosis"), dict):
                unavailable_result["failure_diagnosis"] = task["failure_diagnosis"]
            return unavailable_result
        return None
    strategies = search_alternate_strategies(
        task, contract, leaf_result, memory, repo_snapshot, parent_summary, dependency_summaries,
    )
    if len(strategies) != MAX_STRATEGY_ALTERNATIVES:
        final_evidence = _failure_evidence_from_result(leaf_result)
        final_diagnosis = diagnose_failure(task, leaf_result, final_evidence)
        if final_diagnosis.get("category") == "implementation_strategy_wrong":
            final_diagnosis = dict(final_diagnosis)
            final_diagnosis["next_action"] = "strategy_search_unavailable"
            final_diagnosis["strategy_search_unavailable"] = STRATEGY_SEARCH_UNAVAILABLE
            final_diagnosis["rationale"] = compact_text(
                f"{final_diagnosis.get('rationale', '')} The bounded strategy-generation budget produced no "
                "valid pair of materially different alternatives, so no strategy was executed.", 900,
            )
        task["failure_evidence"] = final_evidence
        task["failure_diagnosis"] = final_diagnosis
        search = task.get("strategy_search")
        if not isinstance(search, dict):
            search = {
                "status": "generation_unavailable",
                "outcome": "generation_unavailable",
                "failure_type": STRATEGY_SEARCH_UNAVAILABLE,
                "strategies": [], "execution_order": [], "attempts": [],
            }
            task["strategy_search"] = search
        search["fresh_diagnosis"] = final_diagnosis
        search["result"] = compact_text(
            "No valid materially different alternative strategies were generated; no strategy was executed.",
            MAX_NODE_SUMMARY_CHARS,
        )
        unavailable_result = dict(leaf_result)
        unavailable_result["strategy_search_status"] = STRATEGY_SEARCH_UNAVAILABLE
        unavailable_result["strategy_search"] = copy.deepcopy(search)
        unavailable_result["failure_evidence"] = final_evidence
        unavailable_result["failure_diagnosis"] = final_diagnosis
        record_run_event(
            "strategy_search_unavailable_routed", task_id=task.get("id"),
            failure_type=STRATEGY_SEARCH_UNAVAILABLE,
            diagnosis=final_diagnosis.get("category"),
        )
        recompute_search_metrics()
        return unavailable_result
    task["strategy_search"]["status"] = "running"
    task["strategy_search"]["execution_order"] = [item["name"] for item in strategies]
    base_memory = copy.deepcopy(memory)
    base_repo = copy.deepcopy(repo_snapshot)
    base_dependencies = copy.deepcopy(list(dependency_summaries or []))
    last_result = None
    for index, strategy in enumerate(strategies):
        last_result = execute_strategy_attempt(
            task, contract, strategy, leaf_result, copy.deepcopy(base_memory), copy.deepcopy(base_repo),
            parent_summary, copy.deepcopy(base_dependencies), attempt_index=index,
        )
        if last_result.get("status") == "done":
            task["strategy_search"]["status"] = "completed"
            task["strategy_search"]["outcome"] = "rescued"
            task["strategy_search"]["selected_strategy"] = strategy.get("name")
            task["strategy_search"]["result"] = compact_text(last_result.get("summary", ""), MAX_NODE_SUMMARY_CHARS)
            RUN["strategy_rescues"] = RUN.get("strategy_rescues", 0) + 1
            record_run_event(
                "strategy_rescue", task_id=task.get("id"), strategy=strategy.get("name"),
                changed_files=last_result.get("changed_files", []), attempt_index=index,
            )
            recompute_search_metrics()
            return last_result
        if index == 0:
            record_run_event(
                "strategy_attempt_rolled_back", task_id=task.get("id"),
                strategy=strategy.get("name"), next_attempt="B",
            )

    RUN["strategy_search_failures"] = RUN.get("strategy_search_failures", 0) + 1
    task["strategy_search"]["status"] = "completed"
    task["strategy_search"]["outcome"] = "failed"
    final_evidence = _failure_evidence_from_result(last_result)
    final_diagnosis = diagnose_failure(task, last_result, final_evidence)
    if final_diagnosis.get("category") == "implementation_strategy_wrong":
        floor_state = _capability_floor_recovery_state(
            task, "model_capability_floor", final_evidence, last_result,
        )
        if floor_state["allowed"]:
            final_diagnosis = {
                "category": "model_capability_floor",
                "confidence": "medium",
                "rationale": compact_text(
                    "Two materially different bounded implementation strategies failed fresh deterministic verification; "
                    "do not keep splitting this node automatically.", 900,
                ),
                "next_action": "declare_limit",
                "depth": int(task.get("depth", 0) or 0),
                "at_max_depth": int(task.get("depth", 0) or 0) >= MAX_DEPTH,
                "automatic_resplit_blocked": True,
                "decomposition_search_exhausted": bool(task.get("decomposition_search_exhausted")),
                "evidence": final_evidence,
                "capability_floor_evidence": {
                    "failure_class": floor_state.get("failure_class", "unknown"),
                    "applicable_recoveries": list(floor_state.get("applicable_recoveries", [])),
                    "exhausted_recoveries": list(floor_state.get("exhausted_recoveries", [])),
                    "non_applicable_recoveries": list(floor_state.get("non_applicable_recoveries", [])),
                },
            }
        else:
            _record_capability_floor_guard_block(task, floor_state)
            final_diagnosis = dict(final_diagnosis)
            final_diagnosis["capability_floor_blocked_by"] = floor_state.get("blocked_by")
            final_diagnosis["capability_floor_guard_evidence"] = {
                "failure_class": floor_state.get("failure_class", "unknown"),
                "applicable_recoveries": list(floor_state.get("applicable_recoveries", [])),
                "exhausted_recoveries": list(floor_state.get("exhausted_recoveries", [])),
                "non_applicable_recoveries": list(floor_state.get("non_applicable_recoveries", [])),
            }
    task["failure_evidence"] = final_evidence
    task["failure_diagnosis"] = final_diagnosis
    task["strategy_search"]["result"] = compact_text((last_result or {}).get("summary", ""), MAX_NODE_SUMMARY_CHARS)
    task["strategy_search"]["final_diagnosis"] = final_diagnosis
    if isinstance(last_result, dict):
        last_result["failure_diagnosis"] = final_diagnosis
        last_result["strategy_search"] = task["strategy_search"]
    recompute_search_metrics()
    return last_result


def route_recovery_from_diagnosis(task, contract, leaf_result, diagnosis, memory, repo_snapshot,
                                  parent_summary="", dependency_summaries=None):
    """Invoke one existing recovery mechanism from the final diagnosis.

    This is deliberately a small post-diagnosis router. It does not plan or
    execute recovery itself; the existing bounded strategy-search path remains
    responsible for generation, transactions, candidate execution, and metrics.
    """
    if not isinstance(task, dict) or not isinstance(leaf_result, dict):
        return None
    if not isinstance(diagnosis, dict) or not diagnosis.get("category"):
        return None
    if task.get("kind", "implementation") != "implementation":
        return None
    if diagnosis.get("category") != "implementation_strategy_wrong":
        return None
    result = _maybe_search_alternate_strategy(
        task, contract, leaf_result, memory, repo_snapshot,
        parent_summary, dependency_summaries, diagnosis=diagnosis,
    )
    if result is not None:
        record_run_event(
            "diagnosis_recovery_route", task_id=task.get("id"),
            diagnosis=diagnosis.get("category"), route="strategy_search",
        )
    return result


def build_node_context(task, root_contract, memory_store, repo_snapshot, parent_summary="",
                       dependency_summaries=None, failure_evidence=None, strategy_context=None,
                       brain_projection=None, worker_mission=None):
    dependency_summaries = dependency_summaries or []
    failure_evidence = failure_evidence or task.get("failure_evidence", [])
    if brain_projection is None and isinstance(RUN.get("project_brain"), dict):
        brain_projection = build_brain_projection(
            RUN["project_brain"], task, dependency_summaries, repo_snapshot, record=False,
        )
    if task.get("kind") == "integration":
        return build_integration_node_packet(
            task, root_contract, repo_snapshot, parent_summary,
            dependency_summaries, failure_evidence, brain_projection=brain_projection,
        )
    try:
        project_invariants = collect_project_invariants() if WORKSPACE is not None else RUN.get("project_invariants", [])
    except Exception:
        project_invariants = RUN.get("project_invariants", [])
    if isinstance(brain_projection, dict):
        projected_state = brain_projection.get("verified_state")
        if isinstance(projected_state, dict) and "project_invariants" in projected_state:
            project_invariants = projected_state.get("project_invariants", [])
    memory_excerpt = ""
    if memory_store:
        try:
            memory_excerpt = memory_store.context_for(
                f"{task.get('goal','')} {' '.join(task.get('scope_hint', []))}", max_items=5,
                max_chars=MAX_MEMORY_CONTEXT_CHARS,
            )
        except Exception:
            memory_excerpt = ""
    current_node = {
        "kind": str(task.get("kind", "implementation")),
        "depth": int(task.get("depth", 0) or 0),
        "goal": compact_text(task.get("goal", ""), 1100),
        "done_when": bounded_list(task.get("done_when", []), 6, 260),
        "scope_hint": bounded_list(task.get("scope_hint", []), 5, 180),
        "fit_before_execution": task.get("fit_before_execution"),
        "execution_outcome": task.get("execution_outcome"),
        "repair_history": list(task.get("repair_history", []) or [])[-MAX_REPAIRS_PER_LEAF:],
    }
    dependencies = []
    for item in dependency_summaries[-4:]:
        if isinstance(item, dict):
            dependency_status = str(item.get("status", "")).casefold()
            if dependency_status and dependency_status not in {"done", "verified", "passed"}:
                continue
            dependencies.append({
                "task_id": str(item.get("task_id", ""))[:80],
                "goal": compact_text(item.get("goal", ""), 260),
                "status": str(item.get("status", ""))[:40],
                "summary": compact_text(item.get("summary", ""), 420),
                "changed_files": bounded_list(item.get("changed_files", []), 8, 120),
                "evidence": compact_text(item.get("evidence", ""), 520),
                "integration_manifest": compact_manifest(item.get("integration_manifest")),
            })
        else:
            dependencies.append(compact_text(item, 500))
    failure_projection = [compact_text(item, 450) if not isinstance(item, dict) else {
        "tool": str(item.get("tool", ""))[:60],
        "target": str(item.get("target", ""))[:180],
        "result": compact_text(item.get("result", ""), 500),
    } for item in failure_evidence[-4:]]
    failed_decompositions = compact_failed_decompositions(task)
    brain_section = (
        f"PROJECT BRAIN PROJECTION (relevant core + verified state):\n"
        f"{json.dumps(_compact_brain_projection(brain_projection), ensure_ascii=False, default=str)[:MAX_BRAIN_PROJECTION_CHARS]}\n\n"
        if isinstance(brain_projection, dict) and brain_projection else ""
    )
    mission_section = (
        f"WORKER MISSION (compiled for this node only):\n"
        f"{json.dumps(worker_mission, ensure_ascii=False, default=str)[:MAX_WORKER_MISSION_CHARS]}\n\n"
        if isinstance(worker_mission, dict) and worker_mission else ""
    )
    packet = (
        f"ROOT CONTRACT:\n{compact_contract(root_contract, max_chars=MAX_ROOT_PACKET_CHARS)}\n\n"
        f"CURRENT NODE:\n{json.dumps(current_node, ensure_ascii=False)}\n\n"
        f"{brain_section}"
        f"{mission_section}"
        f"PARENT (goal + short verified summary):\n{compact_text(parent_summary or '(none)', 700)}\n\n"
        f"DEPENDENCIES (verified summaries only):\n{json.dumps(dependencies, ensure_ascii=False)[:1900] or '(none)'}\n\n"
        f"PROJECT INVARIANTS (canonical facts; extend, do not redefine):\n"
        f"{json.dumps(bounded_list(project_invariants, 12, MAX_INTEGRATION_FACT_CHARS), ensure_ascii=False)[:1500] or '(none)'}\n\n"
        f"RELEVANT PROJECT MEMORY:\n{memory_excerpt[:1200] or '(none)'}\n\n"
        f"FAILURE EVIDENCE:\n{json.dumps(failure_projection, ensure_ascii=False)[:1500] if failure_projection else '(none)'}\n\n"
        f"FAILED DECOMPOSITIONS (do not paraphrase these boundaries):\n"
        f"{json.dumps(failed_decompositions, ensure_ascii=False)[:2600] if failed_decompositions else '(none)'}\n\n"
        f"REPOSITORY HINTS:\n{repository_hints(repo_snapshot, task.get('scope_hint'), max_chars=1900)}\n\n"
        "The real filesystem is the shared source of truth. Inspect files with tools. Do not assume sibling chat history."
    )
    if isinstance(strategy_context, dict):
        strategy = _normalize_alternate_strategy(strategy_context.get("strategy", {})) or {}
        strategy_section = (
            "\n\nFAILED APPROACH SUMMARY:\n"
            f"{compact_text(strategy_context.get('failed_approach_summary', ''), 900) or '(none)'}\n\n"
            "CURRENT DETERMINISTIC FAILURE:\n"
            f"{json.dumps(_compact_failure_evidence(strategy_context.get('current_deterministic_failure', [])), ensure_ascii=False)[:1800] or '(none)'}\n\n"
            "PREVIOUS REPAIR SUMMARY:\n"
            f"{compact_text(strategy_context.get('previous_repair_summary', ''), 900) or '(none)'}\n\n"
            "ALTERNATIVE STRATEGY ATTEMPT:\n"
            "Previous approach failed. Do NOT continue the previous implementation strategy.\n"
            "Use this strategy:\n"
            f"{json.dumps(strategy, ensure_ascii=False)[:2400]}\n"
            "Failure evidence:\n"
            f"{json.dumps(_compact_failure_evidence(strategy_context.get('current_deterministic_failure', [])), ensure_ascii=False)[:1800] or '(none)'}\n"
            "Inspect the CURRENT real workspace before editing.\n\n"
            "CURRENT ALTERNATIVE STRATEGY:\n"
            f"{json.dumps(strategy, ensure_ascii=False)[:2400]}\n"
            "Execute only this bounded strategy through the current node's existing entry point; do not broaden scope."
        )
        packet = packet[:max(256, MAX_NODE_PACKET_CHARS - len(strategy_section) - 2)] + strategy_section
    return packet[:MAX_NODE_PACKET_CHARS]


# ---------------------------------------------------------------------------
# ONE REUSABLE MODEL/TOOL LOOP FOR BUILDER, REPAIRER, FALSIFIER
# ---------------------------------------------------------------------------

def tool_recovery_hint(tool_name, result, repeated_failures):
    lower = str(result).casefold()
    if tool_name == "edit_file" and repeated_failures >= 2 and ("exact replacement" in lower or "found 0" in lower):
        return "Stop repeating the exact edit. Read numbered lines, then use one small edit_file_range."
    if "incomplete or truncated" in lower and repeated_failures >= 2:
        return "Tool JSON is being truncated. Make the next edit substantially smaller."
    if tool_name == "edit_file_range" and repeated_failures >= 2 and "invalid line range" in lower:
        return "Line numbers are stale or invalid. Re-read a current bounded range and confirm the reported total before editing."
    if repeated_failures >= 2 and "syntax validation failed" in lower:
        return "Re-read the enclosing block and submit one smaller syntactically complete replacement; avoid a syntactically incomplete fragment and include its closing delimiter."
    return ""


def verification_failure_signature(result):
    try:
        payload = json.loads(str(result))
    except (TypeError, ValueError):
        return ()
    if not isinstance(payload, dict) or payload.get("passed"):
        return ()
    if payload.get("failure_type") == VERIFICATION_TARGET_UNRESOLVED:
        return ()
    if payload.get("environment_error"):
        return ("environment",)
    signatures = []
    for item in payload.get("interaction_checks", []):
        if not isinstance(item, dict) or item.get("passed"):
            continue
        name = str(item.get("name", "interaction"))
        if name == "timer_phase_switches_and_counts_session":
            before_phase = item.get("before_phase")
            after_phase = item.get("after_phase")
            if before_phase and after_phase and before_phase == after_phase:
                signatures.append("phase_not_changed")
            if item.get("before_count") is None or item.get("after_count") is None:
                signatures.append("completed_count_missing")
            if not signatures:
                signatures.append(f"interaction:{name}")
        else:
            signatures.append(f"interaction:{name}")
    if signatures:
        return tuple(sorted(set(signatures)))
    codes = [str(item.get("code")) for item in payload.get("failures", [])
             if isinstance(item, dict) and item.get("code")]
    return tuple(sorted(set(codes)))


def verification_failure_digest(result, limit=1800):
    """Project browser observations into compact, executable repair evidence."""
    try:
        payload = json.loads(str(result))
    except (TypeError, ValueError):
        return compact_text(result, limit)
    if not isinstance(payload, dict):
        return compact_text(payload, limit)
    lines = ["DETERMINISTIC BROWSER FAILURE EVIDENCE:"]
    for item in payload.get("interaction_checks", []):
        if not isinstance(item, dict) or item.get("passed"):
            continue
        name = str(item.get("name", "interaction"))
        lines.append(f"- {name}: " + compact_text(json.dumps(item, ensure_ascii=False), 900))
        if name == "timer_start_changes_visible_time":
            lines.append(
                "  The deterministic browser clock observed no change. Expose one visible combined MM:SS clock and inspect its markup before changing button or interval logic."
            )
        if name == "timer_phase_switches_and_counts_session":
            before_phase, after_phase = item.get("before_phase"), item.get("after_phase")
            if before_phase and after_phase and before_phase != after_phase:
                lines.append(
                    "  Preserve the working phase transition; add a dedicated visible Completed Sessions: 0 counter."
                )
            elif before_phase == after_phase:
                lines.append("  The phase did not change after the deterministic clock advance.")
            else:
                lines.append(
                    "  Expose a visible phase label and Completed Sessions: 0 before changing timer logic."
                )
    for failure in payload.get("failures", []):
        if isinstance(failure, dict):
            lines.append(f"- failure {failure.get('code', 'unknown')}: {failure.get('evidence', '')}")
    if payload.get("environment_error"):
        lines.append(f"- environment: {payload.get('evidence', 'browser environment unavailable')}")
    return compact_text("\n".join(lines), limit)


def execute_agent_task(task_text, memory, messages=None, role="Builder", task_id="ROOT", extra_context="",
                       tool_policy=None, max_steps=None):
    if messages is None:
        messages = [{"role": "system", "content": ROLE_SYSTEM_PROMPTS.get(role, SYSTEM_PROMPT)}]
    durable = relevant_memory_context(f"{role} {task_text}", role=role, memory=memory, max_chars=1200)
    context = "\n\n".join(item for item in (extra_context, durable) if item)
    if context:
        task_text = f"{context}\n\nCURRENT TASK:\n{task_text}"
    messages.append({"role": "user", "content": task_text})
    evidence = []
    # Keep syntax-validation outcomes local to this focused execution.  A
    # rejected source mutation is not a workspace mutation, but it still
    # invalidates a browser opportunity later in the same verification cycle
    # until a fresh source check or valid source mutation clears it.
    verification_cycle = {"syntax_failures": {}}
    repeated_failures = {}
    mutation_failure_counts = {}
    mutation_failure_records = []
    last_verification_signature = ()
    stagnant_verifications = 0
    provider_error = None
    summary = ""
    status = "unknown"
    execution_budget_exhausted = False
    offered_tools = tools_for_role(role, tool_policy=tool_policy)
    offered_names = {item["function"]["name"] for item in offered_tools}
    if role == "Builder":
        RUN["builder_calls"] = RUN.get("builder_calls", 0) + 1
    event(f"[{role.upper()}] {task_id} executing", role=role, task=task_id, action="focused tool loop")

    step_budget = max_steps if max_steps is not None else {
        "Falsifier": MAX_FALSIFIER_STEPS,
    }.get(role, MAX_TOOL_STEPS)
    for _step in range(max(1, int(step_budget))):
        try:
            assistant_message = ask_ollama(messages, tools=offered_tools, role=role, think=False)
        except ProviderError as exc:
            provider_error = str(exc)
            status = "provider_failure"
            summary = provider_error
            break
        messages.append(assistant_message)
        tool_calls = assistant_message.get("tool_calls", [])
        if not tool_calls:
            content = assistant_message.get("content", "") or ""
            previous = messages[-2] if len(messages) >= 2 else {}
            last_evidence = evidence[-1] if evidence else {}
            last_tool_verified = (
                last_evidence.get("tool") in {"run_file", "run_command", "verify_web_app"}
                and not evidence_result_failed(last_evidence.get("result", ""))
                and not result_is_tool_rejection(last_evidence.get("result", ""))
                and not result_not_applicable(last_evidence.get("result", ""))
            )
            if (
                role in {"Builder", "Repairer"}
                and not content.strip()
                and isinstance(previous, dict)
                and previous.get("role") == "tool"
                and not last_tool_verified
            ):
                messages.append({
                    "role": "user",
                    "content": (
                        "The previous tool action completed, but this focused node has no successful executable "
                        "verification yet. Continue the current task now; inspect the workspace, finish the scoped "
                        "implementation, and run a relevant verification before stopping."
                    ),
                })
                continue
            summary = content or "done"
            if role in {"Builder", "Repairer"} and not evidence:
                status = "failed"
                summary = "No tool evidence was produced; implementation cannot be marked done. " + summary
            else:
                status = "done"
            break
        stop = False
        for call in tool_calls:
            try:
                name = call["function"]["name"]
                args = call["function"].get("arguments", {})
            except (KeyError, TypeError) as exc:
                RUN["invalid_tool_calls"] = RUN.get("invalid_tool_calls", 0) + 1
                result = f"error: malformed tool call: {exc}"
                evidence.append({"tool": "malformed", "target": "-", "result": result})
                messages.append({"role": "tool", "tool_name": "malformed", "content": result})
                continue
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            if not isinstance(args, dict):
                RUN["invalid_tool_calls"] = RUN.get("invalid_tool_calls", 0) + 1
                args = {}
            target = args.get("path") or args.get("command") or "-"
            RUN["tool_calls"] += 1
            if name not in offered_names:
                RUN["invalid_tool_calls"] = RUN.get("invalid_tool_calls", 0) + 1
                if tool_policy == "coherent_rewrite":
                    result = f"error: tool {name!r} is unavailable under the active coherent rewrite policy"
                else:
                    result = f"error: tool {name!r} is unavailable for role {role}"
            else:
                issue = tool_argument_error(name, args)
                if issue:
                    result = issue
                elif _browser_tool_request(name, args):
                    current_syntax_failures = _cycle_syntax_failures_for_target(
                        verification_cycle, args.get("path")
                    )
                    if current_syntax_failures:
                        result = json.dumps(
                            _verification_cycle_syntax_failure(
                                args.get("path"), task_id, current_syntax_failures,
                            ),
                            ensure_ascii=False,
                        )
                    else:
                        result = run_tool(name, args, role=role)
                else:
                    result = run_tool(name, args, role=role)
            _update_verification_cycle(verification_cycle, name, args, result)
            mutation_record = mutation_failure_record(name, target, result, role=role)
            if mutation_record is not None:
                RUN["mutation_failures_recorded"] = RUN.get("mutation_failures_recorded", 0) + 1
                record_run_event(
                    "mutation_failure_recorded", role=role, task_id=task_id,
                    tool=mutation_record.get("tool"), target=mutation_record.get("target"),
                    category=mutation_record.get("category"), deterministic=True,
                    summary=mutation_record.get("summary", ""),
                )
                mutation_failure_records = _merge_mutation_failure_records(
                    mutation_failure_records, [mutation_record],
                )
                result, recovery_packet = _enrich_mutation_result(name, args, mutation_record, result)
                if recovery_packet is not None:
                    RUN["mutation_recovery_packets_emitted"] = RUN.get(
                        "mutation_recovery_packets_emitted", 0,
                    ) + 1
                    record_run_event(
                        "mutation_recovery_packet_emitted", role=role, task_id=task_id,
                        tool=name, target=recovery_packet.get("target"),
                        category=recovery_packet.get("category"),
                        context_source=recovery_packet.get("context_source"),
                        current_file_exists=recovery_packet.get("current_file_exists"),
                    )
            projected = str(result)[:1600]
            evidence.append({"tool": name, "target": target, "result": projected})
            memory = update_memory(memory, name, args, result, role=role, task_id=task_id)
            messages.append({"role": "tool", "tool_name": name, "content": str(result)})
            event(f"[TOOL] {name} {compact_text(target, 80)}", role=role, task=task_id, tool=name)

            failure_key = (name, str(target))
            repeated_failures[failure_key] = repeated_failures.get(failure_key, 0) + 1 if tool_result_failed(result) else 0
            hint = tool_recovery_hint(name, result, repeated_failures[failure_key])
            if hint:
                messages.append({"role": "user", "content": hint})

            if role == "Builder" and name in {"write_file", "edit_file", "edit_file_range"} and tool_result_failed(result):
                mutation_failure_counts[str(target)] = mutation_failure_counts.get(str(target), 0) + 1
                if mutation_failure_counts[str(target)] >= 4:
                    status = "too_broad"
                    summary = "TASK_TOO_BROAD: repeated invalid mutations show the current node exceeds reliable focused capacity"
                    stop = True
                    break

            if role == "Builder" and name == "verify_web_app" and tool_result_failed(result):
                signature = verification_failure_signature(result)
                if signature and signature == last_verification_signature:
                    stagnant_verifications += 1
                else:
                    last_verification_signature = signature
                    stagnant_verifications = 1 if signature else 0
                if stagnant_verifications >= 3:
                    status = "too_broad"
                    summary = "TASK_TOO_BROAD: the same executable browser failure survived three focused verification cycles"
                    stop = True
                    break

            if role in {"Builder", "Repairer"} and name == "verify_web_app" and not tool_result_failed(result):
                status = "done"
                summary = "Deterministic browser verification passed; stop-on-proof completed this focused execution."
                stop = True
                break
        if stop:
            break
    else:
        # The v6 neutral outcome applies to implementation executions. Keep
        # the separate Falsifier loop's historical exhaustion behavior intact.
        if role in {"Builder", "Repairer"}:
            status = "budget_exhausted"
            execution_budget_exhausted = True
            summary = (
                f"{EXECUTION_BUDGET_EXHAUSTED}: focused tool-step budget was used "
                "without verified completion"
            )
            RUN["execution_budget_exhaustions"] = RUN.get("execution_budget_exhaustions", 0) + 1
            record_run_event(
                "execution_budget_exhausted", role=role, task_id=task_id,
                step_budget=int(step_budget), tool_steps_used=len(evidence),
            )
        else:
            status = "too_broad"
            summary = "TASK_TOO_BROAD: maximum focused tool-step budget reached"

    record_run_event("agent_finished", role=role, task_id=task_id, status=status,
                     summary=compact_text(summary, MAX_NODE_SUMMARY_CHARS), evidence_count=len(evidence))
    return {
        "status": status, "summary": compact_text(summary, MAX_NODE_SUMMARY_CHARS), "messages": messages,
        "memory": memory, "tool_evidence": evidence, "provider_error": provider_error,
        "execution_outcome": EXECUTION_BUDGET_EXHAUSTED if execution_budget_exhausted else None,
        "step_budget": int(step_budget), "tool_steps_used": len(evidence),
        "syntax_validation_failures": list(verification_cycle["syntax_failures"].values()),
        "mutation_failures": mutation_failure_records,
        "failure_type": (
            "TASK_TOO_BROAD" if status == "too_broad" else
            EXECUTION_BUDGET_EXHAUSTED if execution_budget_exhausted else
            ("ENVIRONMENT_ERROR" if status == "provider_failure" else None)
        ),
    }


# ---------------------------------------------------------------------------
# BROWSER VERIFICATION
# ---------------------------------------------------------------------------

def browser_launch_kwargs():
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(name)
        if path:
            return {"headless": True, "executable_path": path}
    return {"headless": True}


def ensure_browser(install_if_missing=False):
    if not PLAYWRIGHT_AVAILABLE:
        return False, "Playwright Python package is unavailable"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**browser_launch_kwargs())
            browser.close()
        return True, "Chromium available"
    except Exception as exc:
        if not install_if_missing:
            return False, str(exc)
        result = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], text=True)
        return (result.returncode == 0, "Chromium installed" if result.returncode == 0 else "Chromium install failed")


def browser_snapshot(url, task_id="ROOT", profile=None):
    RUN["browser_checks"] += 1
    ok, detail = ensure_browser(False)
    if not ok:
        return {"passed": False, "environment_error": True, "evidence": detail}
    evidence_dir = WORKSPACE / EVIDENCE_DIR
    evidence_dir.mkdir(parents=True, exist_ok=True)
    screenshot = evidence_dir / f"task_{re.sub(r'[^A-Za-z0-9_.-]+', '_', task_id)}.png"
    console_errors, page_errors, network_errors = [], [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**browser_launch_kwargs())
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            if profile and profile.kind == "timer":
                page.clock.install()
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on("response", lambda response: network_errors.append(f"{response.status} {response.url}")
                    if response.status >= 400 and not response.url.endswith("/favicon.ico") else None)
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(500)
            title = page.title()
            text = page.locator("body").inner_text(timeout=5000)[:4000]
            runtime_state = page.evaluate(f"""() => {{
                const bridge = {GAME_BRIDGE_EXPRESSION} || null;
                const state = bridge && typeof bridge.getState === 'function' ? bridge.getState() : null;
                return {{canvasCount: document.querySelectorAll('canvas').length,
                        gameBridge: bridge ? {{name: {json.dumps(GAME_BRIDGE_NAME)}, state}} : null,
                        debugState: state}};
            }}""")
            interaction_checks = []
            has_game_probe = bool(runtime_state.get("gameBridge"))
            if has_game_probe:
                bridge_expr = GAME_BRIDGE_EXPRESSION
                page.evaluate(f"() => {{ const game={bridge_expr}; if (game.start) game.start(); }}")
                page.wait_for_timeout(100)
                before_move = page.evaluate(f"() => ({bridge_expr}).getState()")
                moved_with_bridge = page.evaluate(
                    f"() => {{ const game={bridge_expr}; if (typeof game.move === 'function') "
                    "{ game.move('up'); return true; } return false; }"
                )
                if not moved_with_bridge:
                    page.keyboard.press("ArrowUp")
                page.wait_for_timeout(650)
                moved_state = page.evaluate(f"() => ({bridge_expr}).getState()")
                moved = moved_state != before_move and (
                    moved_state.get("score", 0) > (before_move or {}).get("score", -1)
                    or moved_state.get("player") != (before_move or {}).get("player")
                    or moved_state.get("position") != (before_move or {}).get("position")
                )
                interaction_checks.append({"name": "keyboard_movement", "passed": bool(moved),
                                           "before": before_move, "after": moved_state})

                if page.evaluate(f"() => typeof ({bridge_expr}).forceCollect === 'function'"):
                    before_collect = page.evaluate(f"() => ({bridge_expr}).getState()")
                    page.evaluate(f"() => ({bridge_expr}).forceCollect()")
                    page.wait_for_timeout(100)
                    after_collect = page.evaluate(f"() => ({bridge_expr}).getState()")
                    collected = (
                        after_collect.get("score", 0) > (before_collect or {}).get("score", -1)
                        or after_collect.get("collected") != (before_collect or {}).get("collected")
                        or after_collect.get("energy") != (before_collect or {}).get("energy")
                    )
                    interaction_checks.append({"name": "collection_updates_state", "passed": bool(collected),
                                               "before": before_collect, "after": after_collect})

                if page.evaluate(f"() => typeof ({bridge_expr}).forceCollision === 'function'"):
                    page.evaluate(f"() => ({bridge_expr}).forceCollision()")
                    page.wait_for_timeout(150)
                    state = page.evaluate(f"() => ({bridge_expr}).getState()")
                    interaction_checks.append({
                        "name": "collision_game_over",
                        "passed": str(state.get("status", "")).lower() in {"gameover", "game-over", "lost", "dead"},
                        "after": state,
                    })

                if page.evaluate(f"() => typeof ({bridge_expr}).restart === 'function'"):
                    page.evaluate(f"() => ({bridge_expr}).restart()")
                    page.wait_for_timeout(150)
                    state = page.evaluate(f"() => ({bridge_expr}).getState()")
                    interaction_checks.append({
                        "name": "restart_resets_state",
                        "passed": str(state.get("status", "")).lower() not in {"gameover", "game-over", "lost", "dead"}
                                  and state.get("score") == 0,
                        "after": state,
                    })

                if page.evaluate(f"() => typeof ({bridge_expr}).forceWin === 'function'"):
                    page.evaluate(f"() => ({bridge_expr}).forceWin()")
                    page.wait_for_timeout(150)
                    win_state = page.evaluate(f"() => ({bridge_expr}).getState()")
                    interaction_checks.append({
                        "name": "goal_win_state",
                        "passed": str(win_state.get("status", "")).lower() in {"won", "win", "complete", "completed"},
                        "after": win_state,
                    })
                    best_before = win_state.get("best")
                    if best_before is not None:
                        page.reload(wait_until="domcontentloaded", timeout=15000)
                        page.wait_for_timeout(350)
                        persisted = page.evaluate(f"""() => {{
                            const game = {GAME_BRIDGE_EXPRESSION};
                            return game && typeof game.getState === 'function' ? game.getState() : null;
                        }}""")
                        best_after = (persisted or {}).get("best")
                        interaction_checks.append({
                            "name": "score_persistence",
                            "passed": best_after is not None and best_after >= best_before,
                            "before": best_before, "after": best_after,
                        })

                touch_required = bool(profile and "touch_control" in profile.required_interactions)
                if touch_required:
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_timeout(200)
                    selector = (
                        "[data-direction], [data-move], [data-action='up'], "
                        "button[aria-label*='forward' i], button[aria-label*='up' i], .touch-controls button"
                    )
                    button = page.locator(selector).first
                    available = button.count() > 0 and button.is_visible()
                    if available:
                        page.evaluate(f"""() => {{
                            const game = {GAME_BRIDGE_EXPRESSION};
                            if (game && typeof game.restart === 'function') game.restart();
                            if (game && typeof game.start === 'function') game.start();
                        }}""")
                        before_touch = page.evaluate(f"""() => {{
                            const game = {GAME_BRIDGE_EXPRESSION};
                            return game && game.getState ? game.getState() : null;
                        }}""")
                        button.click(); page.wait_for_timeout(650)
                        after_touch = page.evaluate(f"""() => {{
                            const game = {GAME_BRIDGE_EXPRESSION};
                            return game && game.getState ? game.getState() : null;
                        }}""")
                        interaction_checks.append({"name": "touch_control", "passed": after_touch != before_touch,
                                                   "before": before_touch, "after": after_touch})
                    else:
                        interaction_checks.append({"name": "touch_control", "passed": False,
                                                   "evidence": "no visible touch control"})
            if profile:
                interaction_checks.extend(run_profile_interactions(page, profile))
            page.set_viewport_size({"width": 1440, "height": 900})
            page.screenshot(path=str(screenshot), full_page=True)
            browser.close()
        snapshot = {"passed": False, "environment_error": False, "title": title, "url": url, "text": text,
                    "console_errors": console_errors, "page_errors": page_errors, "network_errors": network_errors,
                    "runtime_state": runtime_state, "interaction_checks": interaction_checks,
                    "screenshot": str(screenshot.relative_to(WORKSPACE))}
        effective = profile or infer_web_profile("web", {})
        return evaluate_web_snapshot(snapshot, effective)
    except Exception as exc:
        return {"passed": False, "environment_error": True, "evidence": str(exc)}


def browser_workspace_snapshot(path="index.html", task_id="ROOT", profile=None):
    target = safe_path(path)
    if target is None:
        return {"passed": False, "environment_error": False, "evidence": f"path escapes workspace: {path}"}
    if not target.exists() or target.suffix.lower() not in {".html", ".htm"}:
        return {"passed": False, "environment_error": False, "evidence": f"HTML entry not found: {path}"}
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    relative = target.relative_to(WORKSPACE).as_posix()
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], cwd=WORKSPACE,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )
    try:
        time.sleep(0.25)
        result = browser_snapshot(f"http://127.0.0.1:{port}/{relative}", task_id, profile=profile)
        result["entry_path"] = relative
        return result
    finally:
        server.terminate()
        try:
            server.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server.kill(); server.wait(timeout=3)


_BROWSER_HTML_SUFFIXES = {".html", ".htm"}
_BROWSER_SOURCE_SUFFIXES = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".css"}


def _browser_workspace_path(workspace, raw_path):
    """Resolve one evidence path without allowing it to escape the workspace."""
    if raw_path is None or not str(raw_path).strip():
        return None
    root = Path(workspace).resolve()
    try:
        candidate = Path(str(raw_path))
        candidate = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        candidate.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate


def _browser_html_candidates(workspace):
    root = Path(workspace).resolve()
    candidates = []
    for current, dirs, names in os.walk(root):
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(root).parts)
        except ValueError:
            continue
        dirs[:] = [name for name in sorted(dirs)
                   if name not in _SKIP_DIRS and depth < MAX_RECON_DEPTH]
        for name in sorted(names):
            path = current_path / name
            if path.suffix.casefold() not in _BROWSER_HTML_SUFFIXES:
                continue
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            if relative.startswith((".agent_", ".hivo/")):
                continue
            candidates.append(path)
            if len(candidates) >= MAX_RECON_FILES:
                return candidates
    return candidates


def _local_html_asset_references(workspace, html_path):
    """Return deterministic local script/style references from one HTML file."""
    root = Path(workspace).resolve()
    try:
        text = Path(html_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    patterns = (
        ("script", r"<script\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]"),
        ("stylesheet", r"<link\b[^>]*\bhref\s*=\s*['\"]([^'\"]+)['\"]"),
    )
    references = []
    for kind, pattern in patterns:
        for raw in re.findall(pattern, text, flags=re.IGNORECASE):
            clean = str(raw).split("#", 1)[0].split("?", 1)[0].strip()
            if not clean or clean.startswith("//") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", clean):
                continue
            try:
                if clean.startswith("/"):
                    target = (root / clean.lstrip("/\\")).resolve()
                else:
                    target = (Path(html_path).parent / clean).resolve()
                target.relative_to(root)
            except (OSError, RuntimeError, ValueError):
                continue
            references.append({"kind": kind, "path": target})
    return references


_SOURCE_MUTATION_TOOLS = frozenset({"write_file", "edit_file", "edit_file_range"})


def _browser_relative_path(raw_path):
    if raw_path is None or not str(raw_path).strip() or WORKSPACE is None:
        return None
    resolved = _browser_workspace_path(WORKSPACE, raw_path)
    if resolved is None:
        return str(raw_path)
    try:
        return resolved.relative_to(Path(WORKSPACE).resolve()).as_posix()
    except ValueError:
        return str(raw_path)


def _node_check_target(command):
    try:
        parts = shlex.split(str(command), posix=(os.name != "nt"))
    except ValueError:
        return None
    for index, part in enumerate(parts):
        if str(part).casefold() in {"--check", "-c"} and index + 1 < len(parts):
            candidate = parts[index + 1]
            if not str(candidate).startswith("-"):
                return candidate
    return None


def _syntax_validation_failures_from_result(name, args, result):
    """Extract only deterministic source-syntax failures from one tool result."""
    payload = None
    raw = str(result)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            payload = parsed
    except (TypeError, ValueError):
        pass
    if isinstance(payload, dict) and payload.get("syntax_failure"):
        entries = payload.get("syntax_errors") or []
        normalized = []
        for item in entries:
            if isinstance(item, dict):
                path = item.get("path") or args.get("path")
                error = item.get("error") or item.get("evidence") or raw
            else:
                path = args.get("path")
                error = item
            normalized.append({
                "path": _browser_relative_path(path) or str(path or "unknown"),
                "error": compact_text(error, 700),
            })
        if normalized:
            return normalized

    lower = raw.casefold()
    deterministic_syntax = "syntax validation failed" in lower
    if name == "run_command" and re.search(r"(?:^|\s)node(?:\.exe)?\s+--check(?:\s|$)", str(args.get("command", "")), re.IGNORECASE):
        deterministic_syntax = deterministic_syntax or (
            "syntaxerror" in lower and tool_result_failed(result)
        )
        target = _node_check_target(args.get("command", "")) or args.get("path")
    else:
        target = args.get("path")
    if name == "run_file" and Path(str(target or "")).suffix.casefold() in {".js", ".mjs", ".cjs"}:
        deterministic_syntax = deterministic_syntax or (
            "syntaxerror" in lower and tool_result_failed(result)
        )
    if not deterministic_syntax:
        return []
    return [{
        "path": _browser_relative_path(target) or str(target or "unknown"),
        "error": compact_text(raw, 700),
    }]


def _browser_tool_request(name, args):
    if name == "verify_web_app":
        return True
    if name != "run_file":
        return False
    return Path(str((args or {}).get("path", ""))).suffix.casefold() in _BROWSER_HTML_SUFFIXES


def _browser_relevant_paths(requested_path):
    """Return source/entrypoint paths that one browser request would exercise."""
    if WORKSPACE is None:
        return set()
    root = Path(WORKSPACE).resolve()
    relevant = set()
    requested = _browser_workspace_path(root, requested_path)

    def add(path):
        if path is None:
            return
        try:
            relevant.add(path.relative_to(root).as_posix())
        except ValueError:
            return

    def add_html_assets(html_path):
        add(html_path)
        for reference in _local_html_asset_references(root, html_path):
            add(reference.get("path"))

    if requested is not None:
        add(requested)
        if requested.suffix.casefold() in _BROWSER_HTML_SUFFIXES:
            if requested.is_file():
                add_html_assets(requested)
        elif requested.suffix.casefold() in _BROWSER_SOURCE_SUFFIXES:
            for html_path in _browser_html_candidates(root):
                references = _local_html_asset_references(root, html_path)
                if any(reference.get("path") == requested for reference in references):
                    add_html_assets(html_path)
                    break
        return relevant

    details = _resolve_browser_entrypoint_details(root, {"requested_from_node": None})
    resolved = details.get("resolved_entrypoint") if isinstance(details, dict) else None
    resolved_path = _browser_workspace_path(root, resolved)
    if resolved_path is not None and resolved_path.is_file():
        add_html_assets(resolved_path)
    return relevant


def _syntax_failures_for_target(failures, requested_path):
    relevant_paths = _browser_relevant_paths(requested_path)
    if not relevant_paths:
        return []
    selected = []
    for item in failures or []:
        if not isinstance(item, dict):
            continue
        path = _browser_relative_path(item.get("path")) or str(item.get("path", "unknown"))
        if path in relevant_paths:
            selected.append({
                "path": path,
                "error": compact_text(item.get("error", item.get("evidence", "syntax validation failed")), 700),
            })
    return selected


def _combined_syntax_validation_failures(*results):
    combined = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        for item in result.get("syntax_validation_failures", []) or []:
            if not isinstance(item, dict):
                continue
            key = _browser_relative_path(item.get("path")) or str(item.get("path", "unknown"))
            combined[key] = item
    return list(combined.values())


def _cycle_syntax_failures_for_target(cycle, requested_path):
    failures = (cycle or {}).get("syntax_failures", {})
    return _syntax_failures_for_target(list(failures.values()), requested_path)


def _verification_cycle_syntax_failure(
    requested_path, task_id, syntax_failures, compact_target=None, evidence=None,
):
    target = dict(compact_target or {
        "requested_from_node": requested_path,
        "resolved_entrypoint": None,
        "resolution_source": "syntax_gate",
        "resolution_status": "NOT_ATTEMPTED_SYNTAX_FAILURE",
    })
    failures = list(syntax_failures or [])
    RUN["browser_checks_skipped_for_syntax_failure"] = RUN.get(
        "browser_checks_skipped_for_syntax_failure", 0,
    ) + 1
    record_run_event(
        "browser_verification_syntax_failure", task_id=task_id,
        syntax_errors=failures,
    )
    record_run_event("browser_verification_target", task_id=task_id, **target)
    return {
        **target,
        "passed": False,
        "environment_error": False,
        "failure_type": "IMPLEMENTATION_ERROR",
        "syntax_failure": True,
        "syntax_errors": failures,
        "verification_cycle": {
            "requested_source": requested_path,
            "syntax_status": "FAIL",
            "syntax_evidence": failures,
            "browser_skipped": True,
            "browser_skip_reason": "syntax_failure",
        },
        "evidence": evidence or "Syntax validation failed before browser behavior verification; browser launch skipped.",
    }


def _update_verification_cycle(cycle, name, args, result):
    if not isinstance(cycle, dict):
        return
    failures = _syntax_validation_failures_from_result(name, args or {}, result)
    if failures:
        for item in failures:
            key = _browser_relative_path(item.get("path")) or str(item.get("path", "unknown"))
            cycle.setdefault("syntax_failures", {})[key] = item
        return

    if name in _SOURCE_MUTATION_TOOLS and not tool_result_failed(result):
        key = _browser_relative_path((args or {}).get("path"))
        if key:
            cycle.setdefault("syntax_failures", {}).pop(key, None)
        return

    if name == "run_file" and not result_not_applicable(result) and not tool_result_failed(result):
        key = _browser_relative_path((args or {}).get("path"))
        if key and Path(key).suffix.casefold() in {".js", ".mjs", ".cjs", ".py", ".json"}:
            cycle.setdefault("syntax_failures", {}).pop(key, None)
        return

    if name == "run_command" and re.search(
        r"(?:^|\s)node(?:\.exe)?\s+--check(?:\s|$)",
        str((args or {}).get("command", "")), re.IGNORECASE,
    ) and not tool_result_failed(result):
        key = _browser_relative_path(_node_check_target((args or {}).get("command", "")))
        if key:
            cycle.setdefault("syntax_failures", {}).pop(key, None)


def _trusted_entrypoint_value(container):
    if isinstance(container, str):
        return container
    if not isinstance(container, dict):
        return None
    for key in ("browser_entrypoint", "web_entrypoint", "entrypoint", "path"):
        value = container.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _explicit_browser_resolution(workspace, evidence):
    """Resolve only evidence-backed explicit entrypoints, in trust order."""
    evidence = evidence if isinstance(evidence, dict) else {}
    groups = []
    harness = evidence.get("harness_config")
    harness_value = _trusted_entrypoint_value(harness)
    if harness_value:
        groups.append(("harness_config", [harness_value]))

    verified = evidence.get("verified_entrypoint")
    verified_value = _trusted_entrypoint_value(verified)
    if verified_value:
        groups.append(("verified_metadata", [verified_value]))

    invariant_values = []
    for item in evidence.get("project_invariants", []) or []:
        if not isinstance(item, dict) or item.get("kind") != "browser_entrypoint":
            continue
        source = str(item.get("source", "")).casefold()
        if not (source.startswith("deterministic") or source.startswith("verified") or source == "harness"):
            continue
        invariant_values.append(_trusted_entrypoint_value(item))
    if invariant_values:
        groups.append(("verified_invariant", invariant_values))

    metadata = evidence.get("metadata")
    if isinstance(metadata, dict):
        source = str(metadata.get("source", "")).casefold()
        metadata_value = _trusted_entrypoint_value(metadata)
        if metadata_value and (
            metadata.get("verified") is True or source.startswith(("deterministic", "verified", "harness"))
        ):
            groups.append(("verified_metadata", [metadata_value]))

    for key in ("reconnaissance", "repository_snapshot"):
        snapshot = evidence.get(key)
        if not isinstance(snapshot, dict):
            continue
        html_entries = [
            str(value) for value in snapshot.get("entrypoints", []) or []
            if Path(str(value)).suffix.casefold() in _BROWSER_HTML_SUFFIXES
        ]
        if len(set(html_entries)) == 1:
            groups.append(("deterministic_reconnaissance", html_entries))

    for source, raw_values in groups:
        raw_values = [value for value in raw_values if value]
        if not raw_values:
            return {
                "resolution_status": VERIFICATION_TARGET_UNRESOLVED,
                "resolution_source": f"invalid_{source}",
                "resolved_entrypoint": None,
            }
        valid = []
        invalid = []
        for raw in raw_values:
            path = _browser_workspace_path(workspace, raw)
            if path is None or not path.is_file() or path.suffix.casefold() not in _BROWSER_HTML_SUFFIXES:
                invalid.append(str(raw))
            else:
                valid.append(path)
        unique = {path.resolve() for path in valid}
        if invalid or len(unique) != 1:
            return {
                "resolution_status": VERIFICATION_TARGET_UNRESOLVED,
                "resolution_source": f"conflicting_{source}" if len(unique) > 1 else f"invalid_{source}",
                "resolved_entrypoint": None,
                "candidates": sorted(set(invalid + [path.as_posix() for path in unique]))[:8],
            }
        selected = next(iter(unique))
        return {
            "resolution_status": "RESOLVED",
            "resolution_source": source,
            "resolved_entrypoint": selected.relative_to(Path(workspace).resolve()).as_posix(),
        }
    return None


def _resolve_browser_entrypoint_details(workspace, evidence):
    root = Path(workspace).resolve()
    explicit = _explicit_browser_resolution(root, evidence)
    if explicit is not None:
        return explicit

    requested = (evidence or {}).get("requested_from_node") if isinstance(evidence, dict) else None
    requested_path = _browser_workspace_path(root, requested)
    html_candidates = _browser_html_candidates(root)
    if requested_path is not None and requested_path.suffix.casefold() in _BROWSER_SOURCE_SUFFIXES:
        matches = []
        match_kinds = set()
        for html_path in html_candidates:
            for reference in _local_html_asset_references(root, html_path):
                if reference["path"] == requested_path:
                    matches.append(html_path)
                    match_kinds.add(reference["kind"])
                    break
        unique_matches = sorted(set(matches), key=lambda item: item.as_posix().casefold())
        if len(unique_matches) == 1:
            if match_kinds == {"script"}:
                source = "script_reference"
            elif match_kinds == {"stylesheet"}:
                source = "stylesheet_reference"
            else:
                source = "asset_reference"
            return {
                "resolution_status": "RESOLVED", "resolution_source": source,
                "resolved_entrypoint": unique_matches[0].relative_to(root).as_posix(),
            }
        if len(unique_matches) > 1:
            return {
                "resolution_status": VERIFICATION_TARGET_UNRESOLVED,
                "resolution_source": "ambiguous_asset_references",
                "resolved_entrypoint": None,
                "candidates": [path.relative_to(root).as_posix() for path in unique_matches[:8]],
            }

    root_html = sorted(
        [path for path in html_candidates if path.parent == root],
        key=lambda item: item.name.casefold(),
    )
    if len(root_html) == 1:
        return {
            "resolution_status": "RESOLVED", "resolution_source": "unique_root_html",
            "resolved_entrypoint": root_html[0].relative_to(root).as_posix(),
        }
    conventional = root / "index.html"
    if conventional.is_file():
        return {
            "resolution_status": "RESOLVED", "resolution_source": "conventional_index_html",
            "resolved_entrypoint": "index.html",
        }
    return {
        "resolution_status": VERIFICATION_TARGET_UNRESOLVED,
        "resolution_source": "ambiguous_html_candidates" if html_candidates else "missing_html_entrypoint",
        "resolved_entrypoint": None,
        "candidates": [path.relative_to(root).as_posix() for path in html_candidates[:8]],
    }


def resolve_browser_entrypoint(workspace, evidence):
    """Return an evidence-backed HTML entrypoint or a neutral unresolved marker.

    ``evidence`` is also populated with the compact resolution facts needed by
    the run ledger. The resolver never accepts a source file as an entrypoint.
    """
    details = _resolve_browser_entrypoint_details(workspace, evidence)
    if isinstance(evidence, dict):
        evidence.update(details)
    if details["resolution_status"] == "RESOLVED":
        return details["resolved_entrypoint"]
    return VERIFICATION_TARGET_UNRESOLVED


def _browser_syntax_failures(workspace, entrypoint, requested_from_node=None):
    root = Path(workspace).resolve()
    paths = []
    entry_path = _browser_workspace_path(root, entrypoint)
    requested_path = _browser_workspace_path(root, requested_from_node)
    for path in (entry_path, requested_path):
        if path is not None and path.is_file() and path not in paths:
            paths.append(path)
    if entry_path is not None and entry_path.is_file():
        for reference in _local_html_asset_references(root, entry_path):
            path = reference["path"]
            if path.is_file() and path.suffix.casefold() in {".js", ".mjs", ".cjs"} and path not in paths:
                paths.append(path)
    failures = []
    for path in paths:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        issue = source_validation_error(path, content)
        if issue:
            failures.append({"path": path.relative_to(root).as_posix(), "error": compact_text(issue, 700)})
    return failures


def verify_browser_application(requested_path=None, task_id="ROOT", profile=None, evidence=None):
    """Syntax-gate, resolve, then verify the application through its HTML entrypoint."""
    target_evidence = dict(evidence or {})
    target_evidence["requested_from_node"] = requested_path
    requested_syntax_failures = _browser_syntax_failures(WORKSPACE, None, requested_path)
    if requested_syntax_failures:
        return _verification_cycle_syntax_failure(
            requested_path, task_id, requested_syntax_failures,
            evidence="Syntax validation failed before entrypoint resolution and browser behavior verification.",
        )

    resolved = resolve_browser_entrypoint(WORKSPACE, target_evidence)
    compact_target = {
        "requested_from_node": requested_path,
        "resolved_entrypoint": target_evidence.get("resolved_entrypoint"),
        "resolution_source": target_evidence.get("resolution_source"),
        "resolution_status": target_evidence.get("resolution_status"),
    }
    if resolved == VERIFICATION_TARGET_UNRESOLVED:
        record_run_event("browser_verification_target", task_id=task_id, **compact_target)
        RUN["browser_entrypoint_resolution_failures"] = RUN.get(
            "browser_entrypoint_resolution_failures", 0,
        ) + 1
        return {
            **compact_target,
            "passed": False,
            "environment_error": False,
            "failure_type": VERIFICATION_TARGET_UNRESOLVED,
            "evidence": "Browser application entrypoint could not be resolved deterministically.",
        }

    RUN["browser_entrypoint_resolutions"] = RUN.get("browser_entrypoint_resolutions", 0) + 1
    syntax_failures = _browser_syntax_failures(WORKSPACE, resolved, requested_path)
    if syntax_failures:
        return _verification_cycle_syntax_failure(
            requested_path, task_id, syntax_failures, compact_target=compact_target,
        )

    record_run_event("browser_verification_target", task_id=task_id, **compact_target)
    browser_result = browser_workspace_snapshot(resolved, task_id, profile=profile)
    return {**compact_target, **browser_result}


def _web_verification_applicable(task, contract=None):
    combined = task.get("goal", "") + " " + compact_contract(contract or {})
    return any(word in combined.lower() for word in ("web", "browser", "html", "ui", "game", "timer", "frontend"))


def _task_browser_requested_path(task):
    for raw in task.get("scope_hint", []) or []:
        path = _browser_workspace_path(WORKSPACE, raw)
        if path is not None and path.is_file() and path.suffix.casefold() in (
            _BROWSER_SOURCE_SUFFIXES | _BROWSER_HTML_SUFFIXES
        ):
            return path.relative_to(WORKSPACE.resolve()).as_posix()
    return None


def discover_web_entrypoint(task, contract=None):
    if not _web_verification_applicable(task, contract):
        return None
    evidence = {
        "requested_from_node": _task_browser_requested_path(task),
        "project_invariants": RUN.get("project_invariants", []),
        "repository_snapshot": inspect_repository(WORKSPACE),
    }
    resolved = resolve_browser_entrypoint(WORKSPACE, evidence)
    return {"path": resolved} if resolved != VERIFICATION_TARGET_UNRESOLVED else None


def optional_browser_check(task, contract=None, syntax_failures=None):
    if not _web_verification_applicable(task, contract):
        return None
    profile = infer_web_profile(task.get("goal", ""), contract or {})
    requested = _task_browser_requested_path(task)
    current_syntax_failures = _syntax_failures_for_target(syntax_failures, requested)
    if current_syntax_failures:
        return _verification_cycle_syntax_failure(
            requested, task["id"], current_syntax_failures,
        )
    return verify_browser_application(
        requested, task["id"], profile=profile,
        evidence={
            "requested_from_node": requested,
            "project_invariants": RUN.get("project_invariants", []),
            "repository_snapshot": inspect_repository(WORKSPACE),
        },
    )


# ---------------------------------------------------------------------------
# EVIDENCE GATE / FALSIFIER / REPAIR
# ---------------------------------------------------------------------------

def task_risk(task_text):
    lower = task_text.lower()
    high = ("auth", "security", "migration", "database", "architecture", "refactor", "payment", "game",
            "physics", "collision", "3d", "webgl", "ui", "responsive")
    if any(word in lower for word in high) or len(task_text) > 900:
        return "high"
    low = ("rename", "comment", "typo", "readme", "documentation", "format")
    if any(word in lower for word in low) and len(task_text) < 400:
        return "low"
    return "normal"


def falsify_task(task, contract, memory, builder_result, repo_snapshot, node_context=""):
    if task_risk(task.get("goal", "")) == "low" or builder_result.get("status") != "done":
        return {"status": "skipped", "summary": "low-risk leaf", "tool_evidence": [], "memory": memory}
    RUN["falsifier_calls"] += 1
    event(f"[FALSIFY {task['id']}]", role="Falsifier", task=task["id"], action="adversarial verification")
    instruction = (
        f"BUILDER SUMMARY: {compact_text(builder_result.get('summary', ''), 700)}\n"
        "Actively try to falsify success using current files. Run relevant tests/commands/browser interactions. "
        "For normal/high risk, attempt at most 1-2 cheap edge-case probes (boundary/invalid/reload/repeated action/alternate viewport) when useful. "
        "Do not modify application files. Concrete executable failures matter; narrative suspicion is advisory."
    )
    result = execute_agent_task(
        instruction, memory, role="Falsifier", task_id=task["id"], extra_context=node_context,
    )
    if unresolved_tool_failures(result.get("tool_evidence", [])):
        RUN["falsifier_detected_failures"] += 1
    return result


def merged_verification_evidence(builder_result, falsifier_result=None):
    return list(builder_result.get("tool_evidence", [])) + list((falsifier_result or {}).get("tool_evidence", []))


def _legacy_quality_projection(value):
    return isinstance(value, dict) and "checks" in value and "tool_evidence" not in value and "status" not in value


def _current_verification_failures(builder_result, falsifier_result=None, browser_result=None):
    builder_evidence = list(builder_result.get("tool_evidence", []))
    falsifier_evidence = list((falsifier_result or {}).get("tool_evidence", []))
    merged = builder_evidence + falsifier_evidence
    failures = unresolved_tool_failures(merged)
    # A separately executed browser check is newer evidence for the Builder's
    # earlier browser probe. It must never erase a concrete Falsifier failure.
    if browser_result and browser_result.get("passed"):
        entry = str(browser_result.get("resolved_entrypoint") or browser_result.get("entry_path") or "index.html")
        def superseded_builder_browser_failure(item):
            if item not in builder_evidence or item.get("tool") != "verify_web_app":
                return False
            raw_result = str(item.get("result", ""))
            try:
                payload = json.loads(raw_result)
            except (TypeError, ValueError):
                payload = {}
            # A later behavioral pass can supersede stale behavior evidence for
            # the same normalized app target, but never a syntax-gate failure.
            syntax_failure = bool(isinstance(payload, dict) and payload.get("syntax_failure"))
            if not syntax_failure:
                syntax_failure = bool(re.search(r'"syntax_failure"\s*:\s*true', raw_result, re.IGNORECASE))
            if syntax_failure:
                return False
            normalized = payload.get("resolved_entrypoint") if isinstance(payload, dict) else None
            if not normalized:
                match = re.search(r'"resolved_entrypoint"\s*:\s*"([^"\\]+)"', raw_result)
                normalized = match.group(1) if match else None
            if not normalized and Path(str(item.get("target", ""))).suffix.casefold() in _BROWSER_HTML_SUFFIXES:
                normalized = str(item.get("target"))
            return str(normalized or "") == entry
        failures = [item for item in failures if not (
            superseded_builder_browser_failure(item)
        )]
    return failures


def deterministic_quality_checks(builder_result, falsifier_result=None, browser_result=None,
                                 model_checks=None, vision_review=None, integration_preflight=None):
    # The second positional parameter used to be a model-quality projection.
    # Keep it advisory for callers while the live path uses it for the
    # read-only Falsifier result.
    if _legacy_quality_projection(falsifier_result):
        model_checks = list(falsifier_result.get("checks", []))
        falsifier_result = None
    merged = merged_verification_evidence(builder_result, falsifier_result)
    checks = []
    if builder_result.get("status") != "done":
        checks.append({"name": "builder_completion", "status": "FAIL", "source": "deterministic",
                       "evidence": f"builder status={builder_result.get('status')}"})
    if not builder_result.get("tool_evidence"):
        checks.append({"name": "builder_tool_evidence", "status": "FAIL", "source": "deterministic",
                       "evidence": "Builder produced no tool evidence"})
    failures = _current_verification_failures(builder_result, falsifier_result, browser_result)
    if failures:
        checks.append({"name": "executable_failures", "status": "FAIL", "source": "deterministic",
                       "evidence": compact_text(json.dumps(failures, ensure_ascii=False), 900)})
    verification_tools = {"run_file", "run_command", "verify_web_app"}
    verification_ran = any(
        item.get("tool") in verification_tools
        and not result_is_tool_rejection(item.get("result", ""))
        for item in merged
    ) or browser_result is not None
    if not verification_ran:
        checks.append({"name": "executable_verification", "status": "FAIL", "source": "deterministic",
                       "evidence": "no executable verification was attempted"})
    if browser_result is not None and not browser_result.get("passed"):
        checks.append({"name": "browser_contract", "status": "FAIL", "source": "deterministic",
                       "evidence": compact_text(json.dumps(browser_result, ensure_ascii=False), 900)})
    if isinstance(integration_preflight, dict) and not integration_preflight.get("passed"):
        checks.append({"name": "integration_preflight", "status": "FAIL", "source": "deterministic",
                       "evidence": compact_text(json.dumps({
                           "current_syntax": integration_preflight.get("current_syntax"),
                           "conflicts": integration_preflight.get("conflicts", []),
                           "warnings": integration_preflight.get("warnings", []),
                       }, ensure_ascii=False), 1200)})
    # Model/vision opinions are intentionally returned separately by the gate;
    # they never become deterministic code-failure checks.
    return checks


def evidence_gate(builder_result, falsifier_result=None, browser_result=None, model_checks=None,
                  integration_preflight=None):
    if _legacy_quality_projection(falsifier_result):
        model_checks = list(falsifier_result.get("checks", []))
        falsifier_result = None
    deterministic = deterministic_quality_checks(
        builder_result, falsifier_result, browser_result, model_checks=model_checks,
        integration_preflight=integration_preflight,
    )
    advisory = list(model_checks or [])
    passed = builder_result.get("status") == "done" and not deterministic
    if not passed:
        RUN["verification_failures"] += 1
    return {"passed": passed, "checks": deterministic + advisory,
            "deterministic_failures": deterministic, "advisory_checks": advisory,
            "advisory_failures": [item for item in advisory
                                  if isinstance(item, dict) and str(item.get("status", "")).upper() == "FAIL"]}


def _is_execution_budget_exhausted(result):
    if not isinstance(result, dict):
        return False
    return (
        str(result.get("execution_outcome", "")) == EXECUTION_BUDGET_EXHAUSTED
        or str(result.get("status", "")).casefold() == "budget_exhausted"
        or (
            str(result.get("failure_type", "")) == EXECUTION_BUDGET_EXHAUSTED
            and not isinstance(result.get("children"), list)
        )
    )


def _verification_target_is_unresolved(value):
    if isinstance(value, dict):
        if (
            value.get("failure_type") == VERIFICATION_TARGET_UNRESOLVED
            or value.get("resolution_status") == VERIFICATION_TARGET_UNRESOLVED
        ):
            return True
        return any(_verification_target_is_unresolved(value.get(key)) for key in (
            "result", "evidence", "browser", "failure_evidence", "deterministic_failures",
            "tool_evidence", "execution_evidence",
        ) if key in value)
    if isinstance(value, (list, tuple)):
        return any(_verification_target_is_unresolved(item) for item in value)
    if isinstance(value, str):
        text = value.strip()
        if text == VERIFICATION_TARGET_UNRESOLVED:
            return True
        if text.startswith(("{", "[")):
            try:
                return _verification_target_is_unresolved(json.loads(text))
            except ValueError:
                pass
        return VERIFICATION_TARGET_UNRESOLVED in text
    return False


def _concrete_environment_failure(value):
    """Require positive provider/runtime evidence; false JSON flags are not failures."""
    if isinstance(value, dict):
        if value.get("environment_error") is True:
            return True
        if (
            str(value.get("kind", "")).casefold() == "mutation_failure"
            and str(value.get("category", "")).upper() == "ENVIRONMENT_FAILURE"
        ):
            return True
        if str(value.get("failure_type", "")).upper() == "ENVIRONMENT_ERROR":
            return True
        if str(value.get("status", "")).casefold() == "provider_failure":
            return True
        if str(value.get("kind", "")).casefold() in {"browser_environment", "provider_failure"}:
            return True
        if value.get("provider_error"):
            return True
        return any(_concrete_environment_failure(value.get(key)) for key in (
            "result", "evidence", "browser", "failure_evidence", "deterministic_failures",
            "tool_evidence", "execution_evidence",
        ) if key in value)
    if isinstance(value, (list, tuple)):
        return any(_concrete_environment_failure(item) for item in value)
    if not isinstance(value, str):
        return False
    text = value.strip()
    if text.startswith(("{", "[")):
        try:
            return _concrete_environment_failure(json.loads(text))
        except ValueError:
            pass
    lower = text.casefold()
    if re.search(r'["\']environment_error["\']\s*:\s*true', lower):
        return True
    if re.search(r'["\']environment_error["\']\s*:\s*false', lower):
        return False
    return any(term in lower for term in (
        "provider unavailable", "provider failure", "ollama unavailable",
        "ollama worker failure", "ollama transport failure", "transport failure",
        "connection refused", "browser executable not found", "browser executable missing",
        "browser executable unavailable", "playwright launch failed", "cuda out of memory",
        "cuda initialization failed",
    ))


def classify_failure(builder_result, gate, browser_result=None, falsifier_result=None, vision_review=None):
    if vision_review is None and isinstance(falsifier_result, dict) and "tool_evidence" not in falsifier_result:
        # Compatibility with the old (builder, gate, browser, vision) call.
        vision_review, falsifier_result = falsifier_result, None
    if builder_result.get("status") == "provider_failure":
        return "ENVIRONMENT_ERROR"
    if falsifier_result and falsifier_result.get("status") == "provider_failure":
        return "ENVIRONMENT_ERROR"
    if browser_result and browser_result.get("environment_error"):
        return "ENVIRONMENT_ERROR"
    if vision_review and vision_review.get("environment_error"):
        return "ENVIRONMENT_ERROR"
    if _verification_target_is_unresolved(browser_result) or _verification_target_is_unresolved(gate):
        return VERIFICATION_TARGET_UNRESOLVED
    preflight = _effective_preflight(builder_result.get("integration_preflight"))
    gate_has_preflight_failure = any(
        isinstance(item, dict) and item.get("name") == "integration_preflight"
        for item in (gate or {}).get("deterministic_failures", [])
    )
    if (preflight and not preflight.get("passed")) or gate_has_preflight_failure:
        return "INTEGRATION_TOO_BROAD" if builder_result.get("status") == "too_broad" else "INTEGRATION_FAILURE"
    if _is_execution_budget_exhausted(builder_result) and _concrete_environment_failure(
        gate.get("deterministic_failures", [])
    ):
        return "ENVIRONMENT_ERROR"
    if _is_execution_budget_exhausted(builder_result):
        return EXECUTION_BUDGET_EXHAUSTED
    if builder_result.get("status") == "too_broad":
        return "TASK_TOO_BROAD"
    if _concrete_environment_failure(gate.get("deterministic_failures", [])):
        return "ENVIRONMENT_ERROR"
    return "IMPLEMENTATION_ERROR"


def _compact_failure_evidence(evidence, max_items=6, item_chars=900):
    """Keep deterministic failure facts without copying model conversations."""
    all_items = list(evidence or [])
    selected = all_items[-max_items:]
    # Structured mutation failures are compact diagnosis facts, not raw model
    # history. Keep them visible even when later verification records fill the
    # normal evidence window.
    for item in all_items:
        if (
            isinstance(item, dict)
            and item.get("kind") == "mutation_failure"
            and item not in selected
        ):
            if len(selected) >= max_items:
                selected.pop(0)
            selected.append(item)
    compacted = []
    for item in selected:
        if not isinstance(item, dict):
            compacted.append(compact_text(item, item_chars))
            continue
        projected = {}
        for key in (
            "tool", "target", "kind", "name", "code", "status", "source", "evidence", "result",
            "failure_type", "requested_from_node", "resolved_entrypoint", "resolution_source",
            "resolution_status", "environment_error", "category", "deterministic", "summary",
            "count", "role",
        ):
            if key not in item:
                continue
            value = item.get(key)
            if isinstance(value, (dict, list)):
                value = compact_text(json.dumps(value, ensure_ascii=False), item_chars)
            else:
                value = compact_text(value, item_chars)
            projected[key] = value
        compacted.append(projected or {"evidence": compact_text(item, item_chars)})
    return compacted


def _mutation_failure_records(value):
    if not isinstance(value, dict):
        return []
    return [
        copy.deepcopy(item)
        for item in (value.get("mutation_failures", []) or [])
        if isinstance(item, dict) and item.get("kind") == "mutation_failure"
    ]


def _failure_evidence_key(item):
    if isinstance(item, dict) and item.get("kind") == "mutation_failure":
        return (
            "mutation_failure", item.get("category"), item.get("tool"),
            item.get("target"), item.get("role"),
        )
    if isinstance(item, dict):
        return ("dict", json.dumps(item, ensure_ascii=False, sort_keys=True, default=str))
    return ("value", str(item))


def _unique_failure_evidence(items):
    unique = []
    seen = set()
    for item in items or []:
        key = _failure_evidence_key(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _merge_mutation_failure_records(*groups):
    """Aggregate a bounded mutation-failure history without retaining payloads."""
    merged = []
    positions = {}
    for group in groups:
        for item in group or []:
            if not isinstance(item, dict) or item.get("kind") != "mutation_failure":
                continue
            key = (
                item.get("category"), item.get("tool"), item.get("target"), item.get("role"),
            )
            try:
                count = max(1, int(item.get("count", 1) or 1))
            except (TypeError, ValueError):
                count = 1
            if key in positions:
                current = merged[positions[key]]
                current["count"] = int(current.get("count", 1) or 1) + count
                if item.get("summary"):
                    current["summary"] = item["summary"]
                continue
            if len(merged) >= MAX_MUTATION_FAILURE_RECORDS:
                continue
            current = copy.deepcopy(item)
            current["count"] = count
            merged.append(current)
            positions[key] = len(merged) - 1
    return merged


def _worker_failure_evidence(worker_result):
    if not isinstance(worker_result, dict):
        return []
    return _unique_failure_evidence(
        list(evidence_for_review(worker_result.get("tool_evidence", [])))
        + _mutation_failure_records(worker_result)
    )


def _effective_preflight(value):
    if not isinstance(value, dict):
        return {}
    after = value.get("after")
    if isinstance(after, dict):
        return after
    before = value.get("before")
    if isinstance(before, dict):
        return before
    return value


def _failure_evidence_from_result(result):
    """Extract the strongest available deterministic evidence for one node."""
    if not isinstance(result, dict):
        return []
    preflight = _effective_preflight(result.get("integration_preflight"))
    if preflight and not preflight.get("passed"):
        return _compact_failure_evidence(
            _unique_failure_evidence(
                _integration_failure_evidence(preflight)
                + list(result.get("failure_evidence", []) or [])
                + _mutation_failure_records(result)
            ),
            max_items=6,
        )
    candidates = []
    direct = result.get("failure_evidence")
    if isinstance(direct, list):
        candidates.extend(direct)
    candidates.extend(_mutation_failure_records(result))
    gate = result.get("gate")
    if isinstance(gate, dict):
        candidates.extend(gate.get("deterministic_failures", []) or [])
    for source_name in ("builder", "repairer", "falsifier"):
        source = result.get(source_name)
        if isinstance(source, dict):
            candidates.extend(_worker_failure_evidence(source))
    browser = result.get("browser")
    if isinstance(browser, dict) and not browser.get("passed"):
        if browser.get("environment_error"):
            candidates.append({
                "kind": "browser_environment", "status": "FAIL", "source": "deterministic",
                "environment_error": True,
                "evidence": compact_text(browser.get("evidence", "browser environment unavailable"), 900),
            })
        else:
            candidates.append({
                "kind": "browser_verification", "status": "FAIL", "source": "deterministic",
                "failure_type": browser.get("failure_type"),
                "requested_from_node": browser.get("requested_from_node"),
                "resolved_entrypoint": browser.get("resolved_entrypoint"),
                "resolution_source": browser.get("resolution_source"),
                "resolution_status": browser.get("resolution_status"),
                "evidence": compact_text(browser.get("evidence", "browser verification failed"), 900),
            })
    syntax_failures = result.get("syntax_validation_failures") or result.get("syntax_errors")
    if syntax_failures:
        candidates.append({
            "kind": "syntax_failure", "status": "FAIL", "source": "deterministic",
            "evidence": compact_text(json.dumps(syntax_failures, ensure_ascii=False, default=str), 900),
        })
    evidence = result.get("tool_evidence")
    if isinstance(evidence, list):
        candidates.extend(evidence_for_review(evidence) or evidence)
    execution_evidence = result.get("execution_evidence")
    if isinstance(execution_evidence, list):
        candidates.extend(execution_evidence)
    return _compact_failure_evidence(_unique_failure_evidence(candidates))


def _looks_like_tiny_scope(task):
    goal = str(task.get("goal", ""))
    done_when = list(task.get("done_when", []) or [])
    lower = goal.casefold()
    broad_terms = ("build", "create", "complete", "system", "application", "all ")
    separators = len(re.findall(r"\b(?:and|plus|with|then)\b|[,;]", goal, re.IGNORECASE))
    return (
        len(goal) <= 260
        and len(done_when) <= 2
        and separators <= 1
        and not any(term in lower for term in broad_terms)
    )


def _fit_assessment(task, result=None):
    """Return the controller's bounded fit evidence without inventing facts."""
    result = result if isinstance(result, dict) else {}
    resplit = task.get("resplit") if isinstance(task, dict) else None
    resplit_fit = resplit.get("fit_decision") if isinstance(resplit, dict) else None
    for candidate in (
        result.get("fresh_fit_assessment"), result.get("fit_after_execution"),
        result.get("fit_decision"), task.get("fresh_fit_assessment"),
        task.get("fit_after_execution"), resplit_fit, task.get("fit_before_execution"),
    ):
        if isinstance(candidate, dict) and str(candidate.get("decision", "")).casefold() in {"execute", "split"}:
            return candidate
    return {}


def _provenanced_scope_signal(value):
    """Accept a TASK_TOO_BROAD marker only when it names a scope assessor."""
    if not isinstance(value, dict):
        return False
    containers = [value]
    for key in ("scope_provenance", "task_too_broad_provenance", "provenance"):
        nested = value.get(key)
        if isinstance(nested, dict):
            containers.append({
                **nested,
                "signal": nested.get("signal") or value.get("signal") or value.get("failure_type"),
                "decision": nested.get("decision") or nested.get("fit_decision") or value.get("decision"),
            })
    for container in containers:
        signal = str(container.get("signal") or container.get("failure_type") or "").casefold()
        if signal != "task_too_broad":
            continue
        source = container.get("source") or container.get("source_kind")
        decision = container.get("decision") or container.get("fit_decision")
        source = str(source or "").casefold().replace("-", "_").replace(" ", "_")
        decision = str(decision or "").casefold()
        if source in {
            "task_fit", "fit", "fit_assessment", "fresh_fit", "fresh_fit_reassessment",
            "scope_assessment", "decomposition", "decomposition_analysis",
        } and decision == "split":
            return True
    return False


def _has_positive_scope_evidence(task, result=None):
    """Return only explicit evidence that the current node is too broad."""
    result = result if isinstance(result, dict) else {}
    fit = _fit_assessment(task, result)
    if str(fit.get("decision", "")).casefold() == "split":
        return True
    for source in (task, result):
        if _provenanced_scope_signal(source):
            return True
        for key in ("scope_assessment", "fit_assessment", "task_fit"):
            assessment = source.get(key)
            if (
                isinstance(assessment, dict)
                and (
                    str(assessment.get("decision", "")).casefold() == "split"
                    or _provenanced_scope_signal(assessment)
                )
            ):
                return True
        for key in ("scope_evidence", "responsibilities", "substantial_responsibilities"):
            values = source.get(key)
            if isinstance(values, (list, tuple)) and len([item for item in values if str(item).strip()]) >= 2:
                return True
    # A completion-condition count is not scope evidence by itself. A bounded
    # node can legitimately have several acceptance checks, and the v10 live
    # failure showed that treating that count as width masked implementation
    # evidence.
    return False


def _has_concrete_executable_failure(evidence):
    """Return concrete implementation evidence, excluding neutral budget facts."""
    def implementation_failure_text(value):
        lower = str(value or "").casefold()
        lower = lower.replace(EXECUTION_BUDGET_EXHAUSTED.casefold(), "")
        return bool(re.search(
            r"syntax(?:error| failure| validation failed)|parse (?:error|failure)|unexpected token|unexpected identifier|"
            r"assertion(?:error| failure| failed)|uncaught exception|typeerror|referenceerror|runtime(?:error| error)|"
            r"application error|\"passed\"\s*:\s*false|'passed'\s*:\s*false|"
            r"missing required|missing_game_bridge|missing interaction|browser contract",
            lower,
        ))

    def neutral_budget_text(value):
        lower = str(value or "").casefold()
        return any(marker in lower for marker in (
            EXECUTION_BUDGET_EXHAUSTED.casefold(), "execution budget", "focused execution ended",
            "tool-step budget", "tool step budget", "budget exhausted", "budget ended",
        ))

    for item in evidence or []:
        if not isinstance(item, dict):
            if implementation_failure_text(item) or evidence_result_failed(item):
                return True
            continue
        kind = str(item.get("kind", "")).casefold()
        failure_type = str(item.get("failure_type", "")).casefold()
        if item.get("environment_error") is True or kind in {"browser_environment", "provider_failure", "environment"}:
            continue
        if kind == "mutation_failure":
            category = str(item.get("category", "")).upper()
            try:
                mutation_count = max(1, int(item.get("count", 1) or 1))
            except (TypeError, ValueError):
                mutation_count = 1
            if category in {"SAFETY_REJECTED_MUTATION", "ENVIRONMENT_FAILURE", "MISSING_TARGET"}:
                continue
            if category == "STALE_TARGET" and mutation_count < 2:
                continue
            if category in {"INVALID_MUTATION", "SYNTAX_INVALID_MUTATION", "STALE_TARGET"}:
                return True
            continue
        if failure_type in {VERIFICATION_TARGET_UNRESOLVED.casefold(), "environment_error"}:
            continue
        nested_text = " ".join(
            str(item.get(key, "")) for key in ("result", "evidence", "summary", "failure_type")
        )
        if neutral_budget_text(nested_text) and not implementation_failure_text(nested_text):
            continue
        if kind in {"scope", "task_status"}:
            continue
        if kind in {"budget", "execution_outcome"} and not implementation_failure_text(nested_text):
            continue
        if item.get("syntax_failure") is True or failure_type == "implementation_error":
            return True
        if kind in {
            "browser_verification", "syntax_failure", "parse_failure", "test_assertion",
            "runtime_error", "executable_failure", "falsifier_failure",
        }:
            return True
        tool = item.get("tool")
        if tool in {"run_file", "run_command", "verify_web_app"} and evidence_result_failed(item.get("result", "")):
            return True
        if str(item.get("status", "")).upper() in {"FAIL", "FAILED", "ERROR"}:
            return True
        if implementation_failure_text(nested_text):
            return True
    return False


def _has_only_non_implementation_mutation_evidence(evidence):
    records = [
        item for item in evidence or []
        if isinstance(item, dict) and item.get("kind") == "mutation_failure"
    ]
    if not records or _has_concrete_executable_failure(evidence):
        return False
    return all(str(item.get("category", "")).upper() in {
        "SAFETY_REJECTED_MUTATION", "ENVIRONMENT_FAILURE", "MISSING_TARGET",
    } for item in records)


def _has_failed_repair_history(task, result=None):
    result = result if isinstance(result, dict) else {}
    history = result.get("repair_history")
    if not isinstance(history, list):
        history = task.get("repair_history", [])
    return any(
        isinstance(item, dict)
        and str(item.get("status", "")).casefold() not in {"done", "pass", "passed"}
        for item in history
    )


def _strategy_scope_is_bounded(task, result=None):
    """Use the existing fit decision to decide whether strategy search fits."""
    fit = _fit_assessment(task, result)
    if isinstance(fit, dict) and fit.get("decision"):
        if str(fit.get("decision", "")).casefold() != "execute":
            return False
        # A recorded EXECUTE decision is the existing bounded-fit evidence.
        # The hard depth/task boundary limits decomposition; it is not new
        # scope evidence and must not suppress implementation recovery.
        return True
    # Direct compatibility callers may not have passed through solve_task yet.
    # Production nodes carry fit_before_execution before final routing.
    return _looks_like_tiny_scope(task)


def _budget_evidence_is_environmental(searchable, result=None, evidence=None):
    return (
        _concrete_environment_failure(result)
        or _concrete_environment_failure(evidence)
        or _concrete_environment_failure(searchable)
    )


def _strategy_search_state(task, result=None):
    """Return the existing bounded strategy-search state for one node."""
    result = result if isinstance(result, dict) else {}
    search = result.get("strategy_search")
    if not isinstance(search, dict):
        search = task.get("strategy_search") if isinstance(task, dict) else None
    attempts = result.get("strategy_attempts")
    if not isinstance(attempts, list):
        attempts = task.get("strategy_attempts", []) if isinstance(task, dict) else []
    if not isinstance(attempts, list) and isinstance(search, dict):
        attempts = search.get("attempts", [])
    attempts = [item for item in list(attempts or []) if isinstance(item, dict)]
    if not attempts and isinstance(search, dict):
        attempts = [item for item in list(search.get("attempts", []) or []) if isinstance(item, dict)]
    return search if isinstance(search, dict) else {}, attempts[-MAX_STRATEGY_ALTERNATIVES:]


def _is_bounded_implementation_failure(task, result, evidence):
    """Identify a focused implementation failure eligible for strategy search."""
    if not isinstance(task, dict) or not isinstance(result, dict):
        return False
    if task.get("kind", "implementation") != "implementation":
        return False
    failure_type = str(result.get("failure_type", ""))
    if failure_type not in {"IMPLEMENTATION_ERROR", "TASK_TOO_BROAD", EXECUTION_BUDGET_EXHAUSTED}:
        return False
    if (
        str(result.get("status", "")).casefold() == "too_broad"
        and _has_positive_scope_evidence(task, result)
    ):
        return False
    if failure_type == "TASK_TOO_BROAD" and _has_positive_scope_evidence(task, result):
        return False
    preflight = _effective_preflight(result.get("integration_preflight"))
    if preflight and preflight.get("passed") is False:
        return False
    searchable = " ".join((
        str(result.get("summary", "")),
        json.dumps(evidence or [], ensure_ascii=False, default=str),
    )).casefold()
    if (
        _budget_evidence_is_environmental(searchable, result, evidence)
        or _verification_target_is_unresolved(result)
        or _verification_target_is_unresolved(evidence)
    ):
        return False
    if _has_positive_scope_evidence(task, result):
        return False
    fit = _fit_assessment(task, result)
    if isinstance(fit, dict) and fit.get("decision"):
        if str(fit.get("decision", "")).casefold() != "execute":
            return False
    return _strategy_scope_is_bounded(task, result) and _has_concrete_executable_failure(evidence)


def _capability_floor_recovery_state(task, diagnosis=None, evidence=None, result=None):
    """Compute deterministic recovery exhaustion before accepting a floor."""
    task = task if isinstance(task, dict) else {}
    result = result if isinstance(result, dict) else {}
    if not result:
        result = copy.deepcopy(task.get("initial_result") or {})
        if not result:
            result = {
                "status": task.get("status", "failed"),
                "failure_type": task.get("last_failure_type", ""),
                "failure_evidence": task.get("failure_evidence", []),
                "repair_history": task.get("repair_history", []),
            }
        elif task.get("repair_history") and not result.get("repair_history"):
            result["repair_history"] = copy.deepcopy(task.get("repair_history", []))
    evidence = list(evidence or [])
    if not evidence:
        evidence = _failure_evidence_from_result(result)
    category = diagnosis.get("category") if isinstance(diagnosis, dict) else diagnosis
    category = str(category or "").casefold()
    failure_type = str(result.get("failure_type", ""))
    searchable = " ".join((
        str(result.get("summary", "")),
        json.dumps(evidence, ensure_ascii=False, default=str),
        str(result.get("provider_error", "")),
    )).casefold()
    state = {
        "allowed": False,
        "failure_class": category or "unknown",
        "applicable_recoveries": [],
        "exhausted_recoveries": [],
        "non_applicable_recoveries": [],
        "blocked_by": None,
    }

    if _budget_evidence_is_environmental(searchable, result, evidence):
        state["blocked_by"] = "environment_failure"
        state["non_applicable_recoveries"] = ["capability_floor"]
        return state
    if category in {
        "environment_failure", "provider_failure", "verifier_builder_mismatch",
        "dependency_error", "local_integration_state_corruption", "decomposition_error",
    }:
        state["blocked_by"] = f"{category}_recovery_unresolved"
        state["applicable_recoveries"] = [f"{category}_recovery"]
        return state

    bounded_failure = (
        category not in {"scope_too_broad", "dependency_error", "verifier_builder_mismatch"}
        and _is_bounded_implementation_failure(task, result, evidence)
    )
    positive_scope_evidence = _has_positive_scope_evidence(task, result)
    scope_failure = (
        positive_scope_evidence
        or failure_type == "INTEGRATION_TOO_BROAD"
    )

    if bounded_failure:
        state["failure_class"] = "bounded_implementation_failure"
        state["applicable_recoveries"] = [
            "normal_implementation", "repair", "strategy_search",
        ]
        state["exhausted_recoveries"] = ["normal_implementation"]

        repair_history = result.get("repair_history")
        if not isinstance(repair_history, list):
            repair_history = task.get("repair_history", [])
        repair_history = [item for item in list(repair_history or []) if isinstance(item, dict)]
        if repair_history:
            repair_failed = all(
                str(item.get("status", "failed")).casefold() not in {"done", "pass", "passed"}
                for item in repair_history[-MAX_REPAIRS_PER_LEAF:]
            )
            if len(repair_history) >= MAX_REPAIRS_PER_LEAF and repair_failed:
                state["exhausted_recoveries"].append("repair")
            else:
                state["blocked_by"] = "repair_not_exhausted"
                return state
        else:
            # Direct compatibility callers may enter the existing strategy
            # path without the normal leaf loop. In that case no repair route
            # was actually started, so it is not a pending recovery.
            state["non_applicable_recoveries"].append("repair")

        search, attempts = _strategy_search_state(task, result)
        outcome = str(search.get("outcome", "")).casefold()
        if (
            outcome == "failed"
            and len(attempts) >= MAX_STRATEGY_ALTERNATIVES
            and all(str(item.get("status", "")).upper() != "PASS" for item in attempts)
        ):
            state["exhausted_recoveries"].extend(
                ["strategy_search", "strategy_A", "strategy_B"],
            )
            state["allowed"] = True
            return state
        if outcome == "generation_unavailable":
            state["blocked_by"] = "strategy_generation_unavailable"
        elif outcome == "rescued":
            state["blocked_by"] = "strategy_rescued"
        elif not search:
            state["blocked_by"] = "strategy_search_not_attempted"
        else:
            state["blocked_by"] = "strategy_search_incomplete"
        return state

    if scope_failure and task.get("kind", "implementation") != "integration":
        state["failure_class"] = "scope_failure"
        state["applicable_recoveries"] = [
            "normal_decomposition", "decomposition_backtracking",
        ]
        if task.get("decomposition_search_exhausted") or result.get("decomposition_search_exhausted"):
            state["exhausted_recoveries"] = list(state["applicable_recoveries"])
            state["allowed"] = True
        else:
            state["blocked_by"] = "decomposition_search_not_exhausted"
        return state

    state["blocked_by"] = "no_applicable_recovery_exhaustion"
    return state


def can_declare_capability_floor(task, diagnosis=None, evidence=None, result=None):
    """Return whether deterministic node state permits a capability-floor conclusion."""
    return bool(_capability_floor_recovery_state(task, diagnosis, evidence, result)["allowed"])


def _record_capability_floor_guard_block(task, state):
    if state.get("allowed"):
        return
    blocked_by = state.get("blocked_by") or "recovery_not_exhausted"
    task["capability_floor_blocked_by"] = blocked_by
    task["capability_floor_guard_evidence"] = {
        "failure_class": state.get("failure_class", "unknown"),
        "applicable_recoveries": list(state.get("applicable_recoveries", [])),
        "exhausted_recoveries": list(state.get("exhausted_recoveries", [])),
        "non_applicable_recoveries": list(state.get("non_applicable_recoveries", [])),
    }
    if task.get("_capability_floor_guard_block_recorded"):
        return
    RUN["capability_floor_guard_blocks"] = RUN.get("capability_floor_guard_blocks", 0) + 1
    task["_capability_floor_guard_block_recorded"] = True
    record_run_event(
        "capability_floor_guard_blocked", task_id=task.get("id"),
        blocked_by=blocked_by,
        applicable_recoveries=state.get("applicable_recoveries", []),
        exhausted_recoveries=state.get("exhausted_recoveries", []),
    )


def _has_strong_capability_floor_evidence(task, result=None):
    """Only accept a capability-floor diagnosis after actual bounded search."""
    result = result if isinstance(result, dict) else {}
    if result.get("capability_floor_evidence") is True:
        return True
    search = result.get("strategy_search")
    if not isinstance(search, dict):
        search = task.get("strategy_search")
    attempts = result.get("strategy_attempts")
    if not isinstance(attempts, list):
        attempts = task.get("strategy_attempts", [])
    attempts = [item for item in list(attempts or []) if isinstance(item, dict)][-MAX_STRATEGY_ALTERNATIVES:]
    if not isinstance(search, dict) or search.get("outcome") != "failed" or len(attempts) < MAX_STRATEGY_ALTERNATIVES:
        return False
    return all(str(item.get("status", "")).upper() != "PASS" for item in attempts)


def diagnose_failure(task, result, evidence=None):
    """Classify why a node failed and choose the next mechanism.

    This is intentionally a conservative, evidence-based routing hint.  At
    ``MAX_DEPTH`` it records uncertainty instead of silently converting a
    capability or verifier problem into another recursive split.
    """
    result = result if isinstance(result, dict) else {}
    status = str(result.get("status", "failed")).casefold()
    failure_type = str(result.get("failure_type", "UNKNOWN_FAILURE"))
    evidence = _compact_failure_evidence(evidence if evidence is not None else _failure_evidence_from_result(result))
    summary = compact_text(result.get("summary", ""), 900)
    searchable = " ".join((
        summary,
        json.dumps(evidence, ensure_ascii=False, default=str),
        str(result.get("provider_error", "")),
        str(result.get("environment_error", "")),
        str(result.get("verification_status", "")),
        str(result.get("dependency_error", "")),
        str(result.get("missing_dependencies", "")),
        str(result.get("verifier_mismatch", "")),
    )).casefold()
    depth = int(task.get("depth", 0) or 0)
    at_max_depth = depth >= MAX_DEPTH
    repeated = (
        len(task.get("attempts", []) or []) >= 1
        or "after repair limit" in searchable
        or "fresh verification failed" in searchable
    )

    category = "unknown"
    confidence = "low"
    rationale = "The available evidence does not distinguish scope, strategy, dependency, or verifier failure."
    capability_floor_state = None

    effective_preflight = _effective_preflight(result.get("integration_preflight"))
    has_integration_preflight = (
        bool(effective_preflight) and not effective_preflight.get("passed")
    ) or any(item.get("kind") == "integration_preflight" for item in evidence if isinstance(item, dict))

    budget_exhausted = _is_execution_budget_exhausted(result)
    positive_scope_evidence = _has_positive_scope_evidence(task, result)
    implementation_evidence = _has_concrete_executable_failure(evidence)
    target_unresolved = (
        failure_type == VERIFICATION_TARGET_UNRESOLVED
        or _verification_target_is_unresolved(result)
        or _verification_target_is_unresolved(evidence)
    )
    if budget_exhausted and _budget_evidence_is_environmental(searchable, result, evidence):
        category = "environment_failure"
        confidence = "high"
        rationale = (
            "The focused execution budget ended alongside provider/runtime evidence; preserve the neutral outcome "
            "and repair the environment before considering implementation routing."
        )
    elif budget_exhausted and target_unresolved:
        category = "verifier_builder_mismatch"
        confidence = "high"
        rationale = (
            "The browser verifier could not resolve an evidence-backed application entrypoint; preserve the neutral "
            "execution outcome and inspect the verifier target contract."
        )
    elif budget_exhausted and (has_integration_preflight or failure_type in {"INTEGRATION_FAILURE", "INTEGRATION_TOO_BROAD"}):
        category = "local_integration_state_corruption"
        confidence = "high" if has_integration_preflight else "medium"
        rationale = "The neutral execution outcome was accompanied by a concrete parent integration conflict; use the integration repair path."
    elif budget_exhausted and any(term in searchable for term in (
        "module not found", "importerror", "undefined", "not defined", "cannot read", "dependency",
        "interface", "api mismatch", "missing symbol", "no such file",
    )):
        category = "dependency_error"
        confidence = "medium"
        rationale = "The neutral execution outcome was accompanied by a missing or incompatible dependency/interface."
    elif budget_exhausted and any(term in searchable for term in (
        "builder_tool_evidence", "executable_verification", "no executable verification",
    )):
        category = "verifier_builder_mismatch"
        confidence = "medium"
        rationale = "The neutral execution outcome did not produce the executable proof required by the verifier contract."
    elif budget_exhausted and _is_bounded_implementation_failure(task, result, evidence):
        capability_floor_state = _capability_floor_recovery_state(
            task, "model_capability_floor", evidence, result,
        )
        if capability_floor_state["allowed"]:
            category = "model_capability_floor"
            confidence = "medium"
            rationale = (
                "A bounded strategy search recorded materially different implementation attempts that all failed; "
                "the budget observation alone is not being used as capability-floor evidence."
            )
        else:
            _record_capability_floor_guard_block(task, capability_floor_state)
            category = "implementation_strategy_wrong"
            confidence = "medium"
            rationale = compact_text(
                "The focused implementation failure still has an applicable recovery that has not been exhausted; "
                f"capability-floor declaration is blocked by {capability_floor_state['blocked_by']}.", 900,
            )
    elif budget_exhausted and positive_scope_evidence:
        category = "scope_too_broad"
        confidence = "medium"
        rationale = (
            "The focused budget ended, but the node has positive evidence of multiple substantial responsibilities "
            "or a fit assessment that rejects one focused execution; route to existing decomposition."
        )
    elif (
        budget_exhausted
        and _looks_like_tiny_scope(task)
        and _has_concrete_executable_failure(evidence)
        and _has_failed_repair_history(task, result)
    ):
        category = "implementation_strategy_wrong"
        confidence = "medium"
        rationale = (
            "The node was accepted as focused, made meaningful executable progress, and still has a concrete "
            "failure after failed repair attempts; treat implementation strategy as the hypothesis."
        )
    elif budget_exhausted:
        category = "unknown"
        confidence = "low"
        rationale = (
            "The focused execution budget ended without enough positive scope, dependency, verifier, environment, "
            "or strategy evidence to choose a recovery mechanism."
        )
    elif target_unresolved:
        category = "verifier_builder_mismatch"
        confidence = "high"
        rationale = (
            "The browser verifier could not resolve an evidence-backed HTML application entrypoint; this is a "
            "verification-target mismatch, not an implementation, scope, or environment diagnosis."
        )
    elif has_integration_preflight or failure_type in {"INTEGRATION_FAILURE", "INTEGRATION_TOO_BROAD"}:
        category = "local_integration_state_corruption"
        confidence = "high" if has_integration_preflight else "medium"
        rationale = "Verified child work reached a parent integration boundary with concrete shared-state or interface conflicts."
    elif result.get("decomposition_search_exhausted") and not any(term in searchable for term in (
        "module not found", "importerror", "undefined", "not defined", "cannot read", "dependency",
        "interface", "api mismatch", "missing symbol", "no such file",
        "builder_tool_evidence", "executable_verification", "no executable verification",
    )):
        capability_floor_state = _capability_floor_recovery_state(
            task, "model_capability_floor", evidence, result,
        )
        if capability_floor_state["allowed"]:
            category = "model_capability_floor"
            confidence = "low"
            rationale = (
                "The original decomposition and the bounded alternative decomposition attempts all remained too broad; "
                "this is evidence for a capability floor or a non-decomposition mechanism, not proof of either."
            )
        elif _is_bounded_implementation_failure(task, result, evidence):
            _record_capability_floor_guard_block(task, capability_floor_state)
            category = "implementation_strategy_wrong"
            confidence = "medium"
            rationale = compact_text(
                "Decomposition is exhausted, but this node is bounded and still has an applicable recovery; "
                f"capability-floor declaration is blocked by {capability_floor_state['blocked_by']}.", 900,
            )
        elif task.get("kind", "implementation") == "integration":
            category = "local_integration_state_corruption"
            confidence = "medium"
            rationale = "Integration decomposition is exhausted; preserve the existing integration recovery semantics."
        else:
            _record_capability_floor_guard_block(task, capability_floor_state)
            category = "unknown"
            confidence = "low"
            rationale = compact_text(
                "Decomposition search is exhausted, but the recorded failure does not establish that all applicable "
                f"recovery mechanisms are exhausted ({capability_floor_state['blocked_by']}).", 900,
            )
    elif (status == "too_broad" or failure_type == "TASK_TOO_BROAD") and positive_scope_evidence:
        category = "scope_too_broad"
        confidence = "high"
        if at_max_depth and (task.get("terminal_too_broad") or result.get("terminal_too_broad")):
            rationale = (
                "The Builder reported a capacity/scope overflow at the depth limit; backtrack to the parent and try "
                "a materially different decomposition before considering a capability floor."
            )
        else:
            rationale = "The Builder explicitly reported a capacity/scope overflow."
    elif status == "too_broad" or failure_type == "TASK_TOO_BROAD":
        if task.get("kind", "implementation") == "implementation" and implementation_evidence:
            category = "implementation_strategy_wrong"
            confidence = "medium"
            rationale = (
                "The execution reported TASK_TOO_BROAD without scope-assessment provenance, but concrete executable "
                "implementation evidence keeps the node on the implementation recovery path."
            )
        else:
            category = "unknown"
            confidence = "low"
            rationale = (
                "The execution reported TASK_TOO_BROAD without task-fit or scope-assessment provenance; do not treat "
                "the marker itself as positive scope evidence."
            )
    elif failure_type == "ORCHESTRATION_FAILURE" or result.get("orchestration_failure"):
        category = "orchestration_failure"
        confidence = "high"
        rationale = (
            "A bounded orchestration contract failed before Worker implementation; do not classify this as an "
            "implementation, scope, strategy, or capability failure."
        )
    elif _concrete_environment_failure(evidence):
        category = "environment_failure"
        confidence = "high"
        rationale = "The mutation evidence identifies an external runtime or filesystem failure; keep it separate from implementation strategy evidence."
    elif _has_only_non_implementation_mutation_evidence(evidence):
        category = "unknown"
        confidence = "low"
        rationale = "The recorded mutation was rejected by a tool/safety or target contract, not by the application; do not infer an implementation strategy failure."
    elif failure_type == "ENVIRONMENT_ERROR":
        category = "environment_failure"
        confidence = "high"
        rationale = "The provider, browser runtime, or execution environment failed before application evidence could be trusted."
    elif failure_type == "CHILD_FAILURE":
        child_results = result.get("children", [])
        child_statuses = [str(item.get("status", "failed")).casefold() for item in child_results
                          if isinstance(item, dict)]
        if any(item == "done" for item in child_statuses) and any(item != "done" for item in child_statuses):
            category = "decomposition_error"
            confidence = "medium"
            rationale = "Sibling outcomes are mixed; ordering, boundaries, or the decomposition may be wrong."
        else:
            category = "dependency_error"
            confidence = "low"
            rationale = "The parent was blocked by a child result; dependency/order evidence needs inspection."
    elif any(term in searchable for term in (
        "module not found", "importerror", "undefined", "not defined", "cannot read", "dependency",
        "interface", "api mismatch", "missing symbol", "no such file",
    )):
        category = "dependency_error"
        confidence = "medium"
        rationale = "The deterministic failure mentions a missing or incompatible dependency/interface."
    elif any(term in searchable for term in ("builder_tool_evidence", "executable_verification", "no executable verification")):
        category = "verifier_builder_mismatch"
        confidence = "medium"
        rationale = "The evidence gate could not observe the executable proof required to judge the implementation."
    elif failure_type == "IMPLEMENTATION_ERROR":
        if at_max_depth and _is_bounded_implementation_failure(task, result, evidence):
            capability_floor_state = _capability_floor_recovery_state(
                task, "model_capability_floor", evidence, result,
            )
            if capability_floor_state["allowed"]:
                category = "model_capability_floor"
                confidence = "medium"
                rationale = (
                    "A tiny bounded implementation still failed after the existing recovery mechanisms, including "
                    "the bounded strategy search; this is evidence for a capability floor."
                )
            else:
                _record_capability_floor_guard_block(task, capability_floor_state)
                category = "implementation_strategy_wrong"
                confidence = "medium"
                rationale = compact_text(
                    "The node is a bounded implementation failure, but capability-floor declaration is blocked by "
                    f"{capability_floor_state['blocked_by']}; use the existing strategy-search route.", 900,
                )
        elif at_max_depth and _looks_like_tiny_scope(task) and repeated:
            capability_floor_state = _capability_floor_recovery_state(
                task, "model_capability_floor", evidence, result,
            )
            _record_capability_floor_guard_block(task, capability_floor_state)
            category = "unknown"
            confidence = "low"
            rationale = compact_text(
                "A tiny leaf failed at the depth limit, but the evidence is insufficient to establish that all "
                f"applicable recovery mechanisms are exhausted ({capability_floor_state['blocked_by']}).", 900,
            )
        elif at_max_depth:
            category = "unknown"
            confidence = "low"
            rationale = "The leaf is at the depth limit, but the evidence is insufficient to separate strategy, dependency, verifier, and capability causes."
        else:
            category = "implementation_strategy_wrong"
            confidence = "medium"
            rationale = "The node had executable implementation evidence but did not satisfy verification; try a different implementation strategy."

    # Orchestration failures are never implementation evidence, even if a
    # caller supplied stale task metadata that would otherwise match a lower
    # branch above.
    if failure_type == "ORCHESTRATION_FAILURE" or result.get("orchestration_failure"):
        category = "orchestration_failure"
        confidence = "high"
        rationale = (
            "A bounded orchestration contract failed before Worker implementation; do not classify this as an "
            "implementation, scope, strategy, or capability failure."
        )
        capability_floor_state = None

    actions = {
        "scope_too_broad": (
            "backtrack_decomposition"
            if at_max_depth and (
                task.get("terminal_too_broad") or result.get("terminal_too_broad")
                or (budget_exhausted and category == "scope_too_broad")
            )
            else ("split" if not at_max_depth else "manual_decomposition_or_budget_review")
        ),
        "implementation_strategy_wrong": "search_or_mutate",
        "local_integration_state_corruption": "parent_repair",
        "model_capability_floor": "declare_limit",
        "verifier_builder_mismatch": "inspect_verifier_contract",
        "dependency_error": "inspect_dependencies_and_interfaces",
        "decomposition_error": "revisit_decomposition_and_order",
        "orchestration_failure": "recompile_mission",
        "environment_failure": "environment_retry",
        "unknown": "collect_more_failure_evidence",
    }
    mutation_evidence = [
        copy.deepcopy(item) for item in evidence
        if isinstance(item, dict) and item.get("kind") == "mutation_failure"
    ]
    diagnosis = {
        "category": category,
        "confidence": confidence,
        "rationale": compact_text(rationale, 900),
        "next_action": actions.get(category, "collect_more_failure_evidence"),
        "depth": depth,
        "at_max_depth": at_max_depth,
        "automatic_resplit_blocked": at_max_depth,
        "decomposition_search_exhausted": bool(result.get("decomposition_search_exhausted") or task.get("decomposition_search_exhausted")),
        "evidence": evidence,
        "diagnosis_evidence": {
            "execution_observation": EXECUTION_BUDGET_EXHAUSTED if budget_exhausted else None,
            "fit_before_execution": copy.deepcopy(task.get("fit_before_execution")),
            "positive_scope_evidence": bool(positive_scope_evidence),
            "implementation_evidence": bool(implementation_evidence),
            "mutation_evidence": mutation_evidence,
            "environment_healthy": not (
                _concrete_environment_failure(result) or _concrete_environment_failure(evidence)
            ),
        },
    }
    if category == "model_capability_floor":
        if capability_floor_state is None:
            capability_floor_state = _capability_floor_recovery_state(
                task, category, evidence, result,
            )
        if capability_floor_state.get("allowed"):
            diagnosis["capability_floor_evidence"] = {
                "failure_class": capability_floor_state.get("failure_class", "unknown"),
                "applicable_recoveries": list(capability_floor_state.get("applicable_recoveries", [])),
                "exhausted_recoveries": list(capability_floor_state.get("exhausted_recoveries", [])),
                "non_applicable_recoveries": list(capability_floor_state.get("non_applicable_recoveries", [])),
            }
        else:
            # No floor-producing branch should bypass the guard. Keep a
            # defensive fallback for future callers that add a candidate
            # classification without adding its exhaustion check.
            _record_capability_floor_guard_block(task, capability_floor_state)
            diagnosis["category"] = "unknown"
            diagnosis["confidence"] = "low"
            diagnosis["next_action"] = "collect_more_failure_evidence"
            diagnosis["rationale"] = compact_text(
                "Capability-floor declaration was rejected because an applicable recovery remains available.", 900,
            )
    if task.get("capability_floor_blocked_by"):
        diagnosis["capability_floor_blocked_by"] = task["capability_floor_blocked_by"]
        diagnosis["capability_floor_guard_evidence"] = copy.deepcopy(
            task.get("capability_floor_guard_evidence", {}),
        )
    return diagnosis


def _bounded_execution_context(task, dependency_summaries=None):
    """Persist node facts needed for later diagnosis, never model reasoning."""
    return {
        "node_kind": str(task.get("kind", "implementation")),
        "depth": int(task.get("depth", 0) or 0),
        "contract": {
            "goal": compact_text(task.get("goal", ""), 500),
            "done_when": bounded_list(task.get("done_when", []), 6, 300),
            "scope_hint": bounded_list(task.get("scope_hint", []), 6, 180),
        },
        "fit_before_execution": copy.deepcopy(task.get("fit_before_execution")),
        "dependency_summaries": [
            compact_text(json.dumps(item, ensure_ascii=False, default=str), 700)
            if isinstance(item, (dict, list)) else compact_text(item, 700)
            for item in list(dependency_summaries or [])[-4:]
        ],
        "project_invariants": [
            compact_text(json.dumps(item, ensure_ascii=False, default=str), 500)
            if isinstance(item, (dict, list)) else compact_text(item, 500)
            for item in list(RUN.get("project_invariants", []) or [])[:8]
        ],
    }


def _record_task_failure(task, result, phase="execution"):
    """Attach a bounded failed attempt and diagnosis to the durable node ledger."""
    if not isinstance(task, dict) or not isinstance(result, dict):
        return None
    if str(result.get("status", "failed")).casefold() == "done":
        return task.get("failure_diagnosis")
    evidence = _failure_evidence_from_result(result)
    projection = {
        "status": str(result.get("status", "failed")),
        "failure_type": str(result.get("failure_type", "UNKNOWN_FAILURE")),
        "summary": compact_text(result.get("summary", ""), MAX_NODE_SUMMARY_CHARS),
        "failure_evidence": evidence,
    }
    if result.get("mutation_failures"):
        projection["mutation_failures"] = _compact_failure_evidence(
            result.get("mutation_failures", []), max_items=MAX_MUTATION_FAILURE_RECORDS,
        )
    if _is_execution_budget_exhausted(result):
        projection.update({
            "execution_outcome": EXECUTION_BUDGET_EXHAUSTED,
            "step_budget": int(result.get("step_budget", 0) or 0),
            "tool_steps_used": int(result.get("tool_steps_used", 0) or 0),
            "changed_files": bounded_list(result.get("changed_files", []), 8, 140),
        })
        if result.get("repair_history"):
            projection["repair_history"] = list(result.get("repair_history", []))[-MAX_REPAIRS_PER_LEAF:]
        if result.get("execution_evidence"):
            projection["execution_evidence"] = _compact_failure_evidence(
                result.get("execution_evidence", []), max_items=8,
            )
        if isinstance(result.get("execution_context"), dict):
            projection["execution_context"] = copy.deepcopy(result["execution_context"])
    signature = json.dumps(projection, ensure_ascii=False, sort_keys=True, default=str)
    if task.get("_last_failure_signature") == signature and task.get("_last_failure_phase") == phase:
        return task.get("failure_diagnosis")
    task["_last_failure_signature"] = signature
    task["_last_failure_phase"] = phase
    task.setdefault("attempts", []).append({"phase": phase, **projection})
    task["failure_evidence"] = evidence
    task["last_failure_type"] = projection["failure_type"]
    if task.get("initial_result") is None:
        task["initial_result"] = projection
        task["initial_status"] = projection["status"]
        task["initial_failure_type"] = projection["failure_type"]
        task["initial_failure_evidence"] = list(evidence)
    diagnosis = result.get("failure_diagnosis")
    if not isinstance(diagnosis, dict) or not diagnosis.get("category"):
        diagnosis = diagnose_failure(task, result, evidence)
    elif diagnosis.get("category") == "model_capability_floor":
        floor_state = _capability_floor_recovery_state(
            task, diagnosis, evidence, result,
        )
        if not floor_state["allowed"]:
            _record_capability_floor_guard_block(task, floor_state)
            diagnosis = diagnose_failure(task, result, evidence)
        elif not diagnosis.get("capability_floor_evidence"):
            diagnosis = dict(diagnosis)
            diagnosis["capability_floor_evidence"] = {
                "failure_class": floor_state.get("failure_class", "unknown"),
                "applicable_recoveries": list(floor_state.get("applicable_recoveries", [])),
                "exhausted_recoveries": list(floor_state.get("exhausted_recoveries", [])),
                "non_applicable_recoveries": list(floor_state.get("non_applicable_recoveries", [])),
            }
    task["failure_diagnosis"] = diagnosis
    if _is_execution_budget_exhausted(result):
        task["execution_outcome"] = EXECUTION_BUDGET_EXHAUSTED
        task["execution_budget_exhausted"] = True
        if result.get("repair_history"):
            task["repair_history"] = list(result.get("repair_history", []))[-MAX_REPAIRS_PER_LEAF:]
        route_key = {
            "scope_too_broad": "budget_exhaustion_routed_to_scope",
            "implementation_strategy_wrong": "budget_exhaustion_routed_to_strategy",
            "dependency_error": "budget_exhaustion_routed_to_dependency",
        }.get(diagnosis.get("category"), "budget_exhaustion_routed_to_other")
        if not task.get("_budget_exhaustion_route_counted"):
            RUN[route_key] = RUN.get(route_key, 0) + 1
            task["_budget_exhaustion_route_counted"] = True
            task["budget_exhaustion_routing"] = route_key.replace("budget_exhaustion_routed_to_", "", 1)
            record_run_event(
                "budget_exhaustion_routed", task_id=task.get("id"),
                diagnosis=diagnosis.get("category"), route=task["budget_exhaustion_routing"],
            )
    if task.get("initial_failure_diagnosis") is None:
        task["initial_failure_diagnosis"] = diagnosis
    if diagnosis.get("at_max_depth") and not task.get("_max_depth_failure_counted"):
        RUN["max_depth_failures"] = RUN.get("max_depth_failures", 0) + 1
        task["_max_depth_failure_counted"] = True
        event(
            f"[DEPTH LIMIT {task.get('id')}] {diagnosis.get('category')} -> {diagnosis.get('next_action')}",
            role="Coordinator", task=task.get("id"), action="terminal failure diagnosis",
        )
    if not task.get("_failure_diagnosis_counted"):
        counts = RUN.setdefault("failure_diagnosis_counts", {})
        category = diagnosis.get("category", "unknown")
        counts[category] = counts.get(category, 0) + 1
        task["_failure_diagnosis_counted"] = True
    record_run_event(
        "node_failure", task_id=task.get("id"), depth=task.get("depth", 0), phase=phase,
        status=projection["status"], failure_type=projection["failure_type"],
        summary=projection["summary"], failure_evidence=evidence, diagnosis=diagnosis,
    )
    return diagnosis


def _resplit_children_snapshot(completed):
    snapshot = []
    for item in completed or []:
        child_task = item.get("task", {}) if isinstance(item, dict) else {}
        child_result = item.get("result", {}) if isinstance(item, dict) else {}
        if not isinstance(child_task, dict):
            child_task = {"id": str(child_task)}
        if not isinstance(child_result, dict):
            child_result = {"status": "failed", "summary": str(child_result)}
        snapshot.append({
            "task_id": str(child_task.get("id", "")),
            "status": str(child_result.get("status", "failed")),
            "verification_status": str(child_task.get("verification_status", "unknown")),
            "summary": compact_text(child_result.get("summary", ""), MAX_NODE_SUMMARY_CHARS),
            "failure_type": str(child_result.get("failure_type", "")),
            "execution_outcome": child_result.get("execution_outcome"),
            "integration_manifest": compact_manifest(
                child_result.get("integration_manifest") or child_task.get("integration_manifest")
            ),
            "evidence": _failure_evidence_from_result(child_result),
        })
    return snapshot


def recompute_resplit_metrics():
    """Compute rescue rates from node outcomes, not from model-call counts."""
    records = [task.get("resplit") for task in TASKS.values()
               if isinstance(task.get("resplit"), dict)]
    any_child = sum(1 for item in records if item.get("any_verified_child"))
    fully_recovered = sum(1 for item in records if item.get("fully_recovered"))
    failed_nodes_resplit = len(records)
    RUN["failed_nodes_resplit"] = failed_nodes_resplit
    RUN["resplit_nodes_with_any_verified_child"] = any_child
    RUN["resplit_nodes_fully_recovered"] = fully_recovered
    RUN["granularity_rescue_rate"] = round((any_child / failed_nodes_resplit) * 100, 2) if failed_nodes_resplit else 0.0
    return {
        "failed_nodes_resplit": failed_nodes_resplit,
        "resplit_nodes_with_any_verified_child": any_child,
        "resplit_nodes_fully_recovered": fully_recovered,
        "granularity_rescue_rate": RUN["granularity_rescue_rate"],
    }


def recompute_search_metrics():
    """Compute bounded decomposition/strategy search outcomes from task state."""
    tasks = [task for task in TASKS.values() if isinstance(task, dict)]
    terminal = sum(1 for task in tasks if isinstance(task.get("terminal_too_broad"), dict))
    backtracks = sum(int(task.get("decomposition_backtracks", 0) or 0) for task in tasks)
    alternatives = sum(len(task.get("decomposition_alternatives", []) or []) for task in tasks)
    alternative_rescues = sum(1 for task in tasks if task.get("alternative_decomposition_rescued"))
    capability_floor = sum(
        1 for task in tasks
        if str(task.get("status", "")).casefold() != "done"
        and isinstance(task.get("failure_diagnosis"), dict)
        and task["failure_diagnosis"].get("category") == "model_capability_floor"
    )
    searches = int(RUN.get("strategy_searches", 0) or 0)
    rescues = int(RUN.get("strategy_rescues", 0) or 0)
    RUN["terminal_too_broad_nodes"] = terminal
    RUN["decomposition_backtracks"] = backtracks
    RUN["alternative_decompositions"] = alternatives
    RUN["alternative_decomposition_rescues"] = alternative_rescues
    RUN["decomposition_backtrack_rescue_rate"] = (
        round((alternative_rescues / backtracks) * 100, 2) if backtracks else None
    )
    RUN["capability_floor_nodes"] = capability_floor
    RUN["strategy_rescue_rate"] = round((rescues / searches) * 100, 2) if searches else None
    return {
        "terminal_too_broad_nodes": terminal,
        "decomposition_backtracks": backtracks,
        "alternative_decompositions": alternatives,
        "alternative_decomposition_rescues": alternative_rescues,
        "decomposition_backtrack_rescue_rate": RUN["decomposition_backtrack_rescue_rate"],
        "strategy_searches": searches,
        "strategy_generation_failures": int(RUN.get("strategy_generation_failures", 0) or 0),
        "alternate_strategies_attempted": int(RUN.get("alternate_strategies_attempted", 0) or 0),
        "strategy_rescues": rescues,
        "strategy_search_failures": int(RUN.get("strategy_search_failures", 0) or 0),
        "strategy_rescue_rate": RUN["strategy_rescue_rate"],
        "capability_floor_nodes": capability_floor,
        "capability_floor_guard_blocks": int(RUN.get("capability_floor_guard_blocks", 0) or 0),
        "capability_floor_routed_to_strategy": int(
            RUN.get("capability_floor_routed_to_strategy", 0) or 0
        ),
        "execution_budget_exhaustions": int(RUN.get("execution_budget_exhaustions", 0) or 0),
        "budget_exhaustion_routed_to_scope": int(RUN.get("budget_exhaustion_routed_to_scope", 0) or 0),
        "budget_exhaustion_routed_to_strategy": int(RUN.get("budget_exhaustion_routed_to_strategy", 0) or 0),
        "budget_exhaustion_routed_to_dependency": int(RUN.get("budget_exhaustion_routed_to_dependency", 0) or 0),
        "budget_exhaustion_routed_to_other": int(RUN.get("budget_exhaustion_routed_to_other", 0) or 0),
    }


def recompute_integration_metrics():
    """Keep composition metrics derived from parent integration outcomes."""
    attempted = int(RUN.get("parent_integrations_attempted", 0) or 0)
    passed = int(RUN.get("parent_integrations_passed", 0) or 0)
    RUN["integration_success_rate"] = round((passed / attempted) * 100, 2) if attempted else 0.0
    integration_tasks = [
        task for task in TASKS.values()
        if isinstance(task, dict) and task.get("kind") == "integration"
    ]
    RUN["integration_tasks_created"] = len(integration_tasks)
    RUN["integration_splits"] = sum(
        1 for task in TASKS.values()
        if isinstance(task, dict) and task.get("integration_split_boundary")
    )
    RUN["integration_resplits"] = sum(
        int(task.get("integration_resplit_attempts", 0) or 0) for task in integration_tasks
    )
    RUN["integration_verified_nodes"] = sum(
        1 for task in integration_tasks if str(task.get("status", "")).casefold() == "done"
    )
    RUN["integration_too_broad_nodes"] = sum(
        1 for task in integration_tasks if task.get("integration_too_broad")
    )
    RUN["integration_granularity_rescues"] = sum(
        1 for task in integration_tasks
        if task.get("integration_too_broad") and str(task.get("status", "")).casefold() == "done"
    )
    _update_unique_preflight_conflict_metrics()
    detected = RUN["preflight_blocking_conflicts_detected"]
    resolved = RUN["preflight_blocking_conflicts_resolved"]
    return {
        "parent_integrations_attempted": attempted,
        "parent_integrations_passed": passed,
        "parent_integrations_failed": int(RUN.get("parent_integrations_failed", 0) or 0),
        "parent_integrations_recovered": int(RUN.get("parent_integrations_recovered", 0) or 0),
        "integration_preflight_conflicts": int(RUN.get("integration_preflight_conflicts", 0) or 0),
        "integration_conflicts_resolved": int(RUN.get("integration_conflicts_resolved", 0) or 0),
        "invariant_violations_detected": int(RUN.get("invariant_violations_detected", 0) or 0),
        "integration_milestone_runs": int(RUN.get("integration_milestone_runs", 0) or 0),
        "integration_tasks_created": RUN["integration_tasks_created"],
        "integration_splits": RUN["integration_splits"],
        "integration_resplits": RUN["integration_resplits"],
        "integration_verified_nodes": RUN["integration_verified_nodes"],
        "integration_too_broad_nodes": RUN["integration_too_broad_nodes"],
        "integration_granularity_rescues": RUN["integration_granularity_rescues"],
        "preflight_blocking_conflicts_detected": detected,
        "preflight_blocking_conflicts_resolved": resolved,
        "integration_conflict_resolution": RUN["integration_conflict_resolution"],
        "integration_success_rate": RUN["integration_success_rate"],
    }


def print_integration_metrics():
    recompute_integration_metrics()
    print("\n[INTEGRATION METRICS]")
    for key in (
        "parent_integrations_attempted", "parent_integrations_passed", "parent_integrations_failed",
        "parent_integrations_recovered", "integration_preflight_conflicts",
        "integration_conflicts_resolved", "invariant_violations_detected", "integration_milestone_runs",
        "integration_tasks_created", "integration_splits", "integration_resplits",
        "integration_verified_nodes", "integration_too_broad_nodes", "integration_granularity_rescues",
        "preflight_blocking_conflicts_detected", "preflight_blocking_conflicts_resolved",
    ):
        print(f"{key}: {RUN.get(key, 0)}")
    print(f"integration_success_rate: {RUN.get('integration_success_rate', 0):g}%")
    resolution = RUN.get("integration_conflict_resolution")
    print(
        "integration_conflict_resolution: "
        f"{RUN.get('preflight_blocking_conflicts_resolved', 0)}/"
        f"{RUN.get('preflight_blocking_conflicts_detected', 0)} "
        f"({'N/A' if resolution is None else f'{resolution:g}%'})"
    )


def _register_resplit(task, leaf_result, trigger, decision=None):
    if task.get("resplit") is not None:
        return task["resplit"]
    task["resplit"] = {
        "trigger": trigger,
        "source_failure_type": str(leaf_result.get("failure_type", "")),
        "source_status": str(leaf_result.get("status", "failed")),
        "source_summary": compact_text(leaf_result.get("summary", ""), MAX_NODE_SUMMARY_CHARS),
        "source_failure_evidence": _failure_evidence_from_result(leaf_result),
        "fit_decision": {
            "decision": str((decision or {}).get("decision", "split")),
            "reason": compact_text((decision or {}).get("reason", ""), 500),
        },
        "child_ids": list(task.get("children", [])),
        "children_result": [],
        "any_verified_child": False,
        "fully_recovered": False,
        "outcome": "pending",
        "final_status": "pending",
    }
    recompute_resplit_metrics()
    record_run_event("node_resplit", task_id=task.get("id"), depth=task.get("depth", 0),
                     trigger=trigger, source_failure_evidence=task["resplit"]["source_failure_evidence"],
                     child_ids=task["resplit"]["child_ids"])
    return task["resplit"]


def _update_resplit_outcome(task, expected_children, completed, final_result=None):
    expected_ids = [str(child.get("id")) for child in (expected_children or []) if isinstance(child, dict)]
    children_result = _resplit_children_snapshot(completed)
    statuses = [str(item.get("status", "failed")).casefold() for item in children_result]
    final_status = str((final_result or {}).get("status", task.get("status", "pending")))
    all_children_returned = len(children_result) == len(expected_ids) and bool(expected_ids)
    branch_status = "verified" if all_children_returned and all(status == "done" for status in statuses) and final_status == "done" else "failed"
    terminal_child_ids = [
        item.get("task", {}).get("id") for item in (completed or [])
        if isinstance(item, dict)
        and isinstance(item.get("task"), dict)
        and int(item["task"].get("depth", 0) or 0) >= MAX_DEPTH
        and isinstance(item.get("result"), dict)
        and _is_terminal_too_broad_child(item["task"], item["result"])
    ]
    terminal_budget_child_ids = [
        item.get("task", {}).get("id") for item in (completed or [])
        if isinstance(item, dict)
        and isinstance(item.get("task"), dict)
        and isinstance(item.get("result"), dict)
        and _is_execution_budget_exhausted(item["result"])
        and int(item["task"].get("depth", 0) or 0) >= MAX_DEPTH
    ]
    failure_evidence = []
    for item in completed or []:
        result = item.get("result", {}) if isinstance(item, dict) else {}
        if isinstance(result, dict) and result.get("status") != "done":
            failure_evidence.extend(_failure_evidence_from_result(result))
    if isinstance(final_result, dict):
        failure_evidence.extend(_failure_evidence_from_result(final_result))
    branch = None
    history = task.setdefault("decomposition_history", []) if isinstance(task, dict) else []
    active_id = str(task.get("active_decomposition_id", "")) if isinstance(task, dict) else ""
    for item in reversed(history):
        if isinstance(item, dict) and (not active_id or str(item.get("branch_id")) == active_id):
            branch = item
            break
    if branch is None and expected_children:
        # Keep deterministic test/custom decomposers and older callers
        # auditable even when they do not call decompose_task's recorder.
        branch = _record_decomposition_branch(
            task,
            [{"goal": child.get("goal", ""), "done_when": child.get("done_when", []),
              "scope_hint": child.get("scope_hint", [])}
             for child in expected_children if isinstance(child, dict)],
            expected_children,
            kind="legacy",
        )
    if branch is not None:
        branch["child_ids"] = expected_ids or list(branch.get("child_ids", []))
        branch["children_result"] = children_result
        branch["status"] = branch_status
        branch["terminal_child_ids"] = terminal_child_ids
        branch["failure_evidence"] = failure_evidence[-4:]
        branch["why_failed"] = (
            (
                "terminal child remained EXECUTION_BUDGET_EXHAUSTED"
                if terminal_budget_child_ids and len(terminal_budget_child_ids) == len(terminal_child_ids)
                else (
                    "terminal child remained TASK_TOO_BROAD"
                    if not terminal_budget_child_ids
                    else "terminal child remained unresolved after bounded execution"
                )
            )
            if terminal_child_ids else
            compact_text((final_result or {}).get("summary", "decomposition branch failed"), 420)
        ) if branch_status != "verified" else ""
        task["failed_decompositions"] = [
            item for item in history if isinstance(item, dict) and item.get("status") in {"failed", "exhausted", "blocked"}
        ][-MAX_DECOMPOSITION_ALTERNATIVES - 1:]
        for attempt in task.get("decomposition_alternatives", []) or []:
            if isinstance(attempt, dict) and str(attempt.get("branch_id", "")) == str(branch.get("branch_id", "")):
                attempt["status"] = branch_status
                attempt["children_result"] = children_result
                attempt["terminal_child_ids"] = terminal_child_ids
                attempt["why_failed"] = branch.get("why_failed", "")
                break
    if branch is not None and branch.get("kind") == "alternative" and branch_status == "verified":
        task["alternative_decomposition_rescued"] = True

    record = task.get("resplit") if isinstance(task, dict) else None
    if not isinstance(record, dict):
        return
    record["child_ids"] = expected_ids or list(record.get("child_ids", []))
    record["children_result"] = children_result
    record["decomposition_branches"] = [
        {
            "branch_id": item.get("branch_id"), "kind": item.get("kind"),
            "child_ids": list(item.get("child_ids", [])), "status": item.get("status"),
            "children_result": list(item.get("children_result", [])),
            "terminal_child_ids": list(item.get("terminal_child_ids", [])),
            "why_failed": item.get("why_failed", ""),
        }
        for item in history if isinstance(item, dict)
    ][-MAX_DECOMPOSITION_ALTERNATIVES - 2:]
    all_branch_statuses = [str(item.get("status", "failed")) for item in history if isinstance(item, dict)]
    any_verified = any(
        any(str(child.get("status", "")).casefold() == "done" for child in item.get("children_result", []))
        for item in history if isinstance(item, dict)
    )
    fully_recovered = any(item == "verified" for item in all_branch_statuses)
    record["any_verified_child"] = any_verified
    record["fully_recovered"] = fully_recovered
    record["final_status"] = final_status
    if fully_recovered:
        record["outcome"] = "fully_recovered"
    elif any_verified:
        record["outcome"] = "partial_child_rescue"
    elif statuses:
        record["outcome"] = "no_verified_child"
    else:
        record["outcome"] = "pending"
    recompute_resplit_metrics()
    record_run_event(
        "resplit_outcome", task_id=task.get("id"), child_ids=record["child_ids"],
        children_result=record["children_result"], any_verified_child=record["any_verified_child"],
        fully_recovered=record["fully_recovered"], outcome=record["outcome"], final_status=final_status,
        decomposition_branches=record.get("decomposition_branches", []),
    )


def _scope_label(depth):
    return {
        0: "root",
        1: "broad",
        2: "medium-small",
        3: "small",
        4: "small",
        5: "very small",
        6: "terminal leaf",
    }.get(int(depth or 0), "beyond configured depth")


def _report_status(status):
    return {"done": "PASS", "failed": "FAIL", "too_broad": "TOO_BROAD",
            "budget_exhausted": EXECUTION_BUDGET_EXHAUSTED,
            "running": "RUN", "pending": "PENDING"}.get(str(status).casefold(), str(status).upper())


def build_node_diagnosis():
    """Return the run-level table used to explain failed and re-split nodes."""
    rows = []
    ordered = sorted(TASKS.values(), key=lambda item: (int(item.get("depth", 0)), str(item.get("id", ""))))
    for task in ordered:
        initial = task.get("initial_result") or {}
        diagnosis = task.get("initial_failure_diagnosis") or task.get("failure_diagnosis")
        record = task.get("resplit") if isinstance(task.get("resplit"), dict) else None
        if not initial and diagnosis is None and record is None:
            continue
        children_result = list(record.get("children_result", [])) if record else []
        rows.append({
            "node": str(task.get("id", "")),
            "scope": _scope_label(task.get("depth", 0)),
            "goal": compact_text(task.get("goal", ""), 420),
            "initial_result": _report_status(initial.get("status", task.get("status", "failed"))),
            "initial_failure_type": initial.get("failure_type", ""),
            "fit_before_execution": task.get("fit_before_execution"),
            "execution_outcome": task.get("execution_outcome"),
            "repair_history": list(task.get("repair_history", []) or [])[-MAX_REPAIRS_PER_LEAF:],
            "budget_exhaustion_routing": task.get("budget_exhaustion_routing"),
            "resplit": bool(record),
            "children_result": children_result,
            "why_failed": (diagnosis or {}).get("category", "unknown"),
            "confidence": (diagnosis or {}).get("confidence", "low"),
            "rationale": (diagnosis or {}).get("rationale", ""),
            "next_action": (diagnosis or {}).get("next_action", "collect_more_failure_evidence"),
            "at_max_depth": bool((diagnosis or {}).get("at_max_depth", False)),
            "final_result": _report_status(task.get("status", "failed")),
            "final_failure_type": str(task.get("last_failure_type", "")),
            "final_failure_diagnosis": str(task.get("failure_diagnosis", {}).get("category", ""))
            if isinstance(task.get("failure_diagnosis"), dict) else "",
            "failure_evidence": list(task.get("initial_failure_evidence", [])) or list(task.get("failure_evidence", [])),
            "execution_evidence": list(initial.get("execution_evidence", []) or []),
            "terminal_too_broad": task.get("terminal_too_broad"),
            "decomposition_backtracks": int(task.get("decomposition_backtracks", 0) or 0),
            "alternative_decompositions": list(task.get("decomposition_alternatives", []) or [])[-MAX_DECOMPOSITION_ALTERNATIVES:],
            "failed_decompositions": compact_failed_decompositions(task),
            "decomposition_search_exhausted": bool(task.get("decomposition_search_exhausted")),
            "strategy_search": task.get("strategy_search"),
            "capability_floor_blocked_by": task.get("capability_floor_blocked_by"),
            "capability_floor_guard_evidence": task.get("capability_floor_guard_evidence"),
            "capability_floor_evidence": (diagnosis or {}).get("capability_floor_evidence"),
            "integration_preflight": task.get("integration_preflight"),
            "integration_conflicts": list(
                ((task.get("integration_preflight") or {}).get("after") or
                 (task.get("integration_preflight") or {}).get("before") or
                 task.get("integration_preflight") or {}).get("conflicts", [])
            ),
        })
    return rows


def print_resplit_metrics():
    recompute_resplit_metrics()
    print("\n[RESPLIT METRICS]")
    print(f"failed_nodes_resplit: {RUN.get('failed_nodes_resplit', 0)}")
    print(f"resplit_nodes_with_any_verified_child: {RUN.get('resplit_nodes_with_any_verified_child', 0)}")
    print(f"resplit_nodes_fully_recovered: {RUN.get('resplit_nodes_fully_recovered', 0)}")
    print(f"granularity_rescue_rate: {RUN.get('granularity_rescue_rate', 0):g}%")


def print_search_metrics():
    recompute_search_metrics()
    print("\n[DECOMPOSITION / STRATEGY SEARCH METRICS]")
    for key in (
        "terminal_too_broad_nodes", "decomposition_backtracks", "alternative_decompositions",
        "alternative_decomposition_rescues", "strategy_searches", "strategy_generation_failures",
        "alternate_strategies_attempted",
        "strategy_rescues", "strategy_search_failures", "capability_floor_nodes",
        "capability_floor_guard_blocks", "capability_floor_routed_to_strategy",
        "execution_budget_exhaustions", "budget_exhaustion_routed_to_scope",
        "budget_exhaustion_routed_to_strategy", "budget_exhaustion_routed_to_dependency",
        "budget_exhaustion_routed_to_other", "mutation_failures_recorded",
        "mutation_recovery_packets_emitted",
    ):
        print(f"{key}: {RUN.get(key)}")
    backtrack_rate = RUN.get("decomposition_backtrack_rescue_rate")
    strategy_rate = RUN.get("strategy_rescue_rate")
    print(f"decomposition_backtrack_rescue_rate: {'N/A' if backtrack_rate is None else f'{backtrack_rate:g}%'}")
    print(f"strategy_rescue_rate: {'N/A' if strategy_rate is None else f'{strategy_rate:g}%'}")


def print_node_diagnosis():
    rows = RUN.get("node_diagnosis") or build_node_diagnosis()
    if not rows:
        return
    print("\n[NODE DIAGNOSIS]")
    print("node | scope | initial | re-split | children | why failed | next action")
    for row in rows:
        children = row.get("children_result") or []
        child_text = ", ".join(
            f"{item.get('task_id', '?')}:{_report_status(item.get('status', 'failed'))}"
            for item in children if isinstance(item, dict)
        ) or "-"
        print(
            f"{row.get('node')} | {row.get('scope')} | {row.get('initial_result')} | "
            f"{'yes' if row.get('resplit') else 'no'} | {child_text} | "
            f"{row.get('why_failed')} ({row.get('confidence')}) | {row.get('next_action')}"
        )
        rationale = compact_text(row.get("rationale", ""), 220)
        if rationale:
            print(f"  diagnosis: {rationale}")
        if row.get("terminal_too_broad"):
            print(
                f"  terminal too broad: depth={row['terminal_too_broad'].get('depth')} "
                f"next={'exhausted' if row.get('decomposition_search_exhausted') else 'backtrack'}"
            )
        if row.get("alternative_decompositions"):
            alternatives = ", ".join(
                f"#{item.get('attempt')}:{_report_status(item.get('status', 'failed'))}"
                for item in row["alternative_decompositions"] if isinstance(item, dict)
            )
            print(f"  alternative decompositions: {alternatives or '-'}")
        if row.get("strategy_search"):
            strategy = row["strategy_search"]
            print(f"  strategy search: {strategy.get('outcome', strategy.get('status', 'unknown'))}")
        if row.get("capability_floor_blocked_by"):
            print(f"  capability floor guard: blocked by {row['capability_floor_blocked_by']}")
        evidence = compact_text(json.dumps(row.get("failure_evidence", []), ensure_ascii=False), 320)
        if evidence and evidence != "[]":
            print(f"  evidence: {evidence}")
        conflicts = row.get("integration_conflicts") or []
        if conflicts:
            labels = ", ".join(str(item.get("kind", "conflict")) for item in conflicts if isinstance(item, dict))
            print(f"  integration preflight: {labels or 'FAIL'}")


def repair_task(task, contract, failure_evidence, memory, node_context):
    RUN["repairer_calls"] += 1
    event(f"[REPAIR {task['id']}]", role="Repairer", task=task["id"], action="focused repair")
    context = (
        f"{node_context}\n\nCURRENT DETERMINISTIC FAILURE EVIDENCE:\n"
        f"{json.dumps(failure_evidence, ensure_ascii=False)[:5000]}\n"
        "Repair only demonstrated implementation defects. Run fresh executable verification after the edit."
    )
    return execute_agent_task(task["goal"], memory, role="Repairer", task_id=task["id"], extra_context=context)


def _neutral_budget_result(task, worker_result, memory, dependency_summaries=None,
                           repair_history=None, failure_evidence=None, **extra):
    evidence = list(failure_evidence or [])
    evidence.extend(_worker_failure_evidence(worker_result))
    if not evidence:
        evidence = [{
            "kind": "execution_outcome", "status": "FAIL", "source": "deterministic",
            "evidence": EXECUTION_BUDGET_EXHAUSTED,
        }]
    mutation_records = _mutation_failure_records(worker_result)
    result = {
        "status": "budget_exhausted",
        "failure_type": EXECUTION_BUDGET_EXHAUSTED,
        "execution_outcome": EXECUTION_BUDGET_EXHAUSTED,
        "summary": worker_result.get(
            "summary", f"{EXECUTION_BUDGET_EXHAUSTED}: focused execution ended without verified completion",
        ),
        "memory": memory,
        "failure_evidence": _compact_failure_evidence(_unique_failure_evidence(evidence)),
        "execution_evidence": _compact_failure_evidence(_worker_failure_evidence(worker_result), max_items=8),
        "mutation_failures": mutation_records,
        "changed_files": bounded_list(worker_result.get("changed_files", []), 8, 140),
        "repair_history": list(repair_history or [])[-MAX_REPAIRS_PER_LEAF:],
        "step_budget": int(worker_result.get("step_budget", 0) or 0),
        "tool_steps_used": int(worker_result.get("tool_steps_used", 0) or 0),
        "execution_context": _bounded_execution_context(task, dependency_summaries),
    }
    result.update(extra)
    return result


def prepare_worker_mission_context(task, contract, repo_snapshot, parent_summary="",
                                   dependency_summaries=None, strategy_context=None,
                                   task_context=None):
    """Prepare one clean Worker context when recursive Project Brain is active."""
    brain = RUN.get("project_brain")
    if not isinstance(brain, dict):
        return None, None
    execution_gate = _stage3_execution_gate(task)
    if not execution_gate.get("allowed"):
        raise PlanApprovalRequiredError(
            "existing-project mutation cannot begin before approval of the current plan hash"
        )
    refresh_project_brain_verified_state()
    projection = build_brain_projection(
        brain, task, dependency_summaries, repo_snapshot, record=True,
    )
    plan_node_contract = execution_gate.get("contract")
    if task_context is None and isinstance(plan_node_contract, dict):
        # Stage 3 carries the explicit node/test contract.  Do not depend on a
        # relevance-ranked Task Brain tail to preserve that responsibility.
        task_context = {
            "approved_plan_id": plan_node_contract.get("plan_id"),
            "approved_plan_hash": plan_node_contract.get("plan_hash"),
            "plan_node_ids": [
                item.get("node_id") for item in plan_node_contract.get("nodes", [])
            ],
        }
    elif task_context is None and isinstance(RUN.get("task_brain"), dict):
        task_context = stage2.task_brain_projection(
            RUN["task_brain"], task, max_chars=MAX_TASK_BRAIN_PROJECTION_CHARS,
        )
    mission = compile_worker_mission(
        task, projection, dependency_summaries, repo_snapshot,
        strategy_context=strategy_context, task_context=task_context,
        plan_node_contract=plan_node_contract,
    )
    RUN["worker_missions_executed"] = RUN.get("worker_missions_executed", 0) + 1
    record_run_event(
        "worker_mission_ready", task_id=task.get("id"),
        goal_anchor=compact_text(mission.get("goal_anchor", ""), 300),
        target_count=len(mission.get("targets", [])),
    )
    return projection, mission


def execute_leaf(task, contract, memory, repo_snapshot, parent_summary="", dependency_summaries=None,
                 strategy_context=None):
    if task.get("kind") == "integration":
        return execute_integration_leaf(
            task, contract, memory, repo_snapshot, parent_summary, dependency_summaries,
        )
    dependency_summaries = dependency_summaries or []
    RUN["leaf_tasks"] += 1
    try:
        brain_projection, worker_mission = prepare_worker_mission_context(
            task, contract, repo_snapshot, parent_summary, dependency_summaries,
            strategy_context=strategy_context,
        )
    except (MissionCompilationError, PlanApprovalRequiredError) as exc:
        if ACTIVE_TRANSACTION is not None:
            rollback_transaction()
        orchestration_failure = (
            PLAN_APPROVAL_REQUIRED if isinstance(exc, PlanApprovalRequiredError)
            else "MISSION_COMPILATION_FAILURE"
        )
        return {
            "status": "failed", "failure_type": "ORCHESTRATION_FAILURE",
            "orchestration_failure": orchestration_failure,
            "summary": str(exc), "memory": memory,
            "failure_evidence": [{
                "kind": "orchestration_failure", "status": "FAIL", "source": "mission_compiler",
                "evidence": compact_text(str(exc), 700),
            }],
        }
    node_context = build_node_context(task, contract, get_memory_store(), repo_snapshot,
                                      parent_summary, dependency_summaries, task.get("failure_evidence"),
                                      strategy_context=strategy_context,
                                      brain_projection=brain_projection,
                                      worker_mission=worker_mission)
    context_tokens = max(1, int(len(node_context) / 4))
    RUN["peak_leaf_context_tokens"] = max(RUN["peak_leaf_context_tokens"], context_tokens)
    RUN["_leaf_context_samples"].append(context_tokens)
    begin_transaction(task["id"])
    global ACTIVE_TOOL_CONTRACT
    ACTIVE_TOOL_CONTRACT = {
        "goal": task["goal"], "requirements": task.get("done_when", []),
        "constraints": contract.get("constraints", []), "success_criteria": task.get("done_when", []),
        "task_id": task["id"], "project_invariants": RUN.get("project_invariants", []),
    }
    ACTIVE_TOOL_CONTRACT.update(_active_plan_tool_contract_fields(task))
    builder = execute_agent_task(task["goal"], memory, role="Builder", task_id=task["id"], extra_context=node_context)
    memory = builder["memory"]
    if _is_execution_budget_exhausted(builder):
        rollback_transaction()
        return _neutral_budget_result(
            task, builder, memory, dependency_summaries,
            builder=builder,
        )
    if builder["status"] == "too_broad":
        RUN["task_too_broad_count"] += 1
        rollback_transaction()
        failure_evidence = _worker_failure_evidence(builder)
        failure_evidence.append({"kind": "task_status", "result": builder.get("summary", "TASK_TOO_BROAD")})
        return {"status": "too_broad", "failure_type": "TASK_TOO_BROAD", "summary": builder["summary"],
                "memory": memory, "builder": builder,
                "failure_evidence": _compact_failure_evidence(
                    _unique_failure_evidence(failure_evidence), max_items=8,
                ),
                "mutation_failures": _mutation_failure_records(builder)}
    if builder["status"] == "provider_failure":
        rollback_transaction()
        return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": builder["summary"],
                "memory": memory, "builder": builder}

    falsifier = falsify_task(task, ACTIVE_TOOL_CONTRACT, memory, builder, repo_snapshot, node_context)
    memory = falsifier.get("memory", memory)
    if falsifier.get("status") == "provider_failure":
        rollback_transaction()
        return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": falsifier.get("summary", "falsifier provider failure"),
                "memory": memory, "builder": builder, "falsifier": falsifier}
    browser = optional_browser_check(
        task, ACTIVE_TOOL_CONTRACT,
        syntax_failures=_combined_syntax_validation_failures(builder, falsifier),
    )
    gate = evidence_gate(builder, falsifier, browser)
    verify_label = "ROOT VERIFIED" if task.get("id") == "ROOT" and gate["passed"] else "VERIFY " + task["id"]
    event(f"[{verify_label}] {'PASS' if gate['passed'] else 'FAIL'}", role="Quality Review",
          task=task["id"], action="deterministic evidence gate")
    if gate["passed"]:
        changed = commit_transaction()
        task["changed_files"] = [str(Path(path).relative_to(WORKSPACE)) if Path(path).is_relative_to(WORKSPACE) else str(path)
                                 for path in changed]
        remember_verified_outcome(task, contract, builder["summary"], changed)
        result = {"status": "done", "summary": builder["summary"], "memory": memory, "builder": builder,
                  "falsifier": falsifier, "browser": browser, "gate": gate, "changed_files": changed}
        attach_verified_manifest(task, result)
        return result

    failure_type = classify_failure(builder, gate, browser, falsifier)
    if failure_type != "IMPLEMENTATION_ERROR":
        rollback_transaction()
        return {"status": "failed", "failure_type": failure_type, "summary": f"verification failed: {failure_type}",
                "memory": memory, "builder": builder, "falsifier": falsifier, "browser": browser, "gate": gate}

    current_gate = gate
    current_browser = browser
    repair_history = []
    repair_mutation_failures = _mutation_failure_records(builder)
    for _ in range(MAX_REPAIRS_PER_LEAF):
        repaired = repair_task(task, ACTIVE_TOOL_CONTRACT, current_gate["deterministic_failures"], memory, node_context)
        memory = repaired["memory"]
        repair_mutation_failures = _merge_mutation_failure_records(
            repair_mutation_failures, _mutation_failure_records(repaired),
        )
        repair_history.append({
            "status": str(repaired.get("status", "failed")),
            "failure_type": str(repaired.get("failure_type", "")),
            "summary": compact_text(repaired.get("summary", ""), MAX_NODE_SUMMARY_CHARS),
            "tool_steps_used": int(repaired.get("tool_steps_used", 0) or 0),
        })
        if repaired["status"] == "provider_failure":
            rollback_transaction()
            return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": repaired["summary"],
                    "memory": memory, "repair_history": repair_history,
                    "repairer": repaired, "mutation_failures": repair_mutation_failures,
                    "failure_evidence": _compact_failure_evidence(repair_mutation_failures)}
        if _is_execution_budget_exhausted(repaired):
            rollback_transaction()
            return _neutral_budget_result(
                task, repaired, memory, dependency_summaries,
                repair_history=repair_history,
                failure_evidence=_unique_failure_evidence(
                    current_gate.get("deterministic_failures", []) + repair_mutation_failures,
                ),
                builder=repaired, repairer=repaired, falsifier=falsifier,
                browser=current_browser, gate=current_gate,
                mutation_failures=repair_mutation_failures,
            )
        if repaired["status"] == "too_broad":
            RUN["task_too_broad_count"] += 1
            rollback_transaction()
            return {"status": "too_broad", "failure_type": "TASK_TOO_BROAD", "summary": repaired["summary"],
                    "memory": memory,
                    "failure_evidence": _compact_failure_evidence(_unique_failure_evidence(
                        current_gate["deterministic_failures"] + repair_mutation_failures,
                    )),
                    "repair_history": repair_history, "repairer": repaired,
                    "mutation_failures": repair_mutation_failures}
        # Fresh verification only: do not carry stale Builder/Falsifier failures into the post-repair gate.
        current_browser = optional_browser_check(
            task, ACTIVE_TOOL_CONTRACT,
            syntax_failures=_combined_syntax_validation_failures(repaired),
        )
        current_gate = evidence_gate(repaired, None, current_browser)
        verify_label = "ROOT VERIFIED" if task.get("id") == "ROOT" and current_gate["passed"] else "VERIFY " + task["id"]
        event(f"[{verify_label}] {'PASS' if current_gate['passed'] else 'FAIL'} (fresh)",
              role="Quality Review", task=task["id"], action="fresh post-repair verification")
        if current_gate["passed"]:
            changed = commit_transaction()
            remember_verified_outcome(task, contract, repaired["summary"], changed)
            result = {"status": "done", "summary": repaired["summary"], "memory": memory, "builder": repaired,
                      "falsifier": falsifier, "browser": current_browser, "gate": current_gate, "changed_files": changed,
                      "repair_history": repair_history, "mutation_failures": repair_mutation_failures}
            attach_verified_manifest(task, result)
            return result
        failure_type = classify_failure(repaired, current_gate, current_browser, None)
        if failure_type != "IMPLEMENTATION_ERROR":
            rollback_transaction()
            return {"status": "failed", "failure_type": failure_type, "summary": f"fresh verification failed: {failure_type}",
                    "memory": memory, "repair_history": repair_history, "repairer": repaired,
                    "mutation_failures": repair_mutation_failures,
                    "failure_evidence": _compact_failure_evidence(repair_mutation_failures)}
    rollback_transaction()
    return {"status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "failed deterministic evidence gate after repair limit", "memory": memory,
            "failure_evidence": _compact_failure_evidence(_unique_failure_evidence(
                current_gate["deterministic_failures"] + repair_mutation_failures,
            )),
            "repair_history": repair_history, "repairer": repaired,
            "mutation_failures": repair_mutation_failures}


def _integration_blocking_conflicts(preflight):
    result = []
    for item in (preflight or {}).get("conflicts", []):
        severity = item.get("severity", "error") if isinstance(item, dict) else "error"
        if str(severity).casefold() not in {"warning", "info"}:
            result.append(_normalize_integration_conflict(item))
    return result


def _integration_owned_conflicts(task, preflight):
    owned_keys = {
        _integration_conflict_group_key(item)
        for item in task.get("integration_conflicts", [])
    }
    if not owned_keys:
        return _integration_blocking_conflicts(preflight)
    return [
        conflict for conflict in _integration_blocking_conflicts(preflight)
        if _integration_conflict_group_key(conflict) in owned_keys
    ]


def _integration_child_preflight_check(task, preflight):
    preflight = preflight if isinstance(preflight, dict) else {}
    owned_remaining = _integration_owned_conflicts(task, preflight)
    passed = preflight.get("current_syntax", "PASS") != "FAIL" and not owned_remaining
    return {
        "passed": bool(passed),
        "current_syntax": preflight.get("current_syntax", "PASS"),
        "owned_conflicts_remaining": owned_remaining,
        "owned_conflicts_resolved": max(
            0,
            len(task.get("integration_conflicts", [])) - len(owned_remaining),
        ),
        "preflight": preflight,
    }


def _integration_child_gate(builder, falsifier, browser, preflight_check):
    """Gate one integration concern without blocking on unrelated conflicts."""
    deterministic = deterministic_quality_checks(
        builder, falsifier, browser, integration_preflight=None,
    )
    if not preflight_check.get("passed"):
        deterministic.append({
            "name": "integration_task_preflight", "status": "FAIL", "source": "deterministic",
            "evidence": compact_text(json.dumps({
                "current_syntax": preflight_check.get("current_syntax"),
                "owned_conflicts_remaining": preflight_check.get("owned_conflicts_remaining", []),
            }, ensure_ascii=False), 1200),
        })
    passed = builder.get("status") == "done" and not deterministic
    if not passed:
        RUN["verification_failures"] += 1
    return {
        "passed": passed, "checks": deterministic,
        "deterministic_failures": deterministic, "advisory_checks": [], "advisory_failures": [],
    }


def _integration_child_info_from_context(task):
    context = task.get("integration_context") if isinstance(task.get("integration_context"), dict) else {}
    return list(context.get("verified_child_manifests", []) or [])


def _commit_verified_integration_leaf(task, contract, result, summary, memory, gate,
                                      falsifier=None, browser=None, preflight=None):
    changed = commit_transaction()
    task["changed_files"] = [
        str(Path(path).relative_to(WORKSPACE)) if WORKSPACE is not None and Path(path).is_relative_to(WORKSPACE)
        else str(path)
        for path in changed
    ]
    remember_verified_outcome(task, contract, summary, changed)
    result = {
        "status": "done", "summary": summary, "memory": memory, "builder": result,
        "falsifier": falsifier, "browser": browser, "gate": gate,
        "changed_files": changed, "integration_preflight": preflight,
    }
    attach_verified_manifest(task, result)
    return result


def execute_integration_leaf(task, contract, memory, repo_snapshot, parent_summary="", dependency_summaries=None):
    """Execute one bounded integration concern through the normal leaf engine."""
    dependency_summaries = dependency_summaries or []
    RUN["leaf_tasks"] += 1
    try:
        brain_projection, worker_mission = prepare_worker_mission_context(
            task, contract, repo_snapshot, parent_summary, dependency_summaries,
            task_context={
                "integration_conflicts": task.get("integration_conflicts", [])[:MAX_INTEGRATION_MANIFEST_ITEMS],
                "integration_context": task.get("integration_context", {}),
            },
        )
    except MissionCompilationError as exc:
        if ACTIVE_TRANSACTION is not None:
            rollback_transaction()
        return {
            "status": "failed", "failure_type": "ORCHESTRATION_FAILURE",
            "orchestration_failure": "MISSION_COMPILATION_FAILURE",
            "summary": str(exc), "memory": memory,
            "failure_evidence": [{
                "kind": "orchestration_failure", "status": "FAIL", "source": "mission_compiler",
                "evidence": compact_text(str(exc), 700),
            }],
        }
    node_context = build_node_context(
        task, contract, get_memory_store(), repo_snapshot,
        parent_summary, dependency_summaries, task.get("failure_evidence"),
        brain_projection=brain_projection, worker_mission=worker_mission,
    )
    context_tokens = max(1, int(len(node_context) / 4))
    RUN["peak_leaf_context_tokens"] = max(RUN["peak_leaf_context_tokens"], context_tokens)
    RUN["_leaf_context_samples"].append(context_tokens)
    begin_transaction(task["id"])
    global ACTIVE_TOOL_CONTRACT
    ACTIVE_TOOL_CONTRACT = {
        "goal": task["goal"], "requirements": task.get("done_when", []),
        "constraints": contract.get("constraints", []), "success_criteria": task.get("done_when", []),
        "task_id": task["id"], "project_invariants": RUN.get("project_invariants", []),
    }
    ACTIVE_TOOL_CONTRACT.update(_active_plan_tool_contract_fields(task))
    builder = execute_agent_task(
        task["goal"], memory, role="Builder", task_id=task["id"], extra_context=node_context,
    )
    memory = builder.get("memory", memory)
    if _is_execution_budget_exhausted(builder):
        rollback_transaction()
        return _neutral_budget_result(
            task, builder, memory, dependency_summaries,
            builder=builder,
        )
    if builder.get("status") == "too_broad":
        RUN["task_too_broad_count"] += 1
        task["integration_too_broad"] = True
        rollback_transaction()
        return {
            "status": "too_broad", "failure_type": "INTEGRATION_TOO_BROAD",
            "summary": builder.get("summary", "integration task exceeds capacity"),
            "memory": memory, "builder": builder,
            "failure_evidence": _compact_failure_evidence(_worker_failure_evidence(builder)),
            "mutation_failures": _mutation_failure_records(builder),
        }
    if builder.get("status") == "provider_failure":
        rollback_transaction()
        return {
            "status": "failed", "failure_type": "ENVIRONMENT_ERROR",
            "summary": builder.get("summary", "integration provider failure"),
            "memory": memory, "builder": builder,
        }

    preflight = run_integration_preflight(
        task, _integration_child_info_from_context(task), contract,
    )
    task["integration_preflight"] = {"after": preflight}
    preflight_check = _integration_child_preflight_check(task, preflight)
    if preflight_check["passed"]:
        falsifier = falsify_task(task, ACTIVE_TOOL_CONTRACT, memory, builder, repo_snapshot, node_context)
    else:
        falsifier = {"status": "skipped", "summary": "blocked by owned integration conflict",
                     "tool_evidence": [], "memory": memory}
    memory = falsifier.get("memory", memory)
    if falsifier.get("status") == "provider_failure":
        rollback_transaction()
        return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR",
                "summary": falsifier.get("summary", "integration falsifier provider failure"),
                "memory": memory, "builder": builder, "falsifier": falsifier,
                "integration_preflight": task["integration_preflight"]}
    browser = (
        optional_browser_check(
            task, contract,
            syntax_failures=_combined_syntax_validation_failures(builder, falsifier),
        )
        if preflight_check["passed"] else None
    )
    gate = _integration_child_gate(builder, falsifier, browser, preflight_check)
    event(f"[VERIFY {task['id']}] {'PASS' if gate['passed'] else 'FAIL'}",
          role="Quality Review", task=task["id"], action="integration task evidence gate")
    if gate["passed"]:
        return _commit_verified_integration_leaf(
            task, contract, builder, builder.get("summary", "integration concern verified"), memory,
            gate, falsifier, browser, preflight,
        )

    current_gate = gate
    current_preflight = preflight
    current_browser = browser
    repair_history = []
    repair_mutation_failures = []
    for _ in range(MAX_REPAIRS_PER_LEAF):
        repaired = repair_task(task, contract, current_gate["deterministic_failures"], memory, node_context)
        memory = repaired.get("memory", memory)
        repair_mutation_failures = _merge_mutation_failure_records(
            repair_mutation_failures, _mutation_failure_records(repaired),
        )
        repair_history.append({
            "status": str(repaired.get("status", "failed")),
            "failure_type": str(repaired.get("failure_type", "")),
            "summary": compact_text(repaired.get("summary", ""), MAX_NODE_SUMMARY_CHARS),
            "tool_steps_used": int(repaired.get("tool_steps_used", 0) or 0),
        })
        if repaired.get("status") == "provider_failure":
            rollback_transaction()
            return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR",
                    "summary": repaired.get("summary", "integration repair provider failure"), "memory": memory,
                    "repair_history": repair_history, "repairer": repaired,
                    "mutation_failures": repair_mutation_failures,
                    "failure_evidence": _compact_failure_evidence(repair_mutation_failures)}
        if _is_execution_budget_exhausted(repaired):
            rollback_transaction()
            return _neutral_budget_result(
                task, repaired, memory, dependency_summaries,
                repair_history=repair_history,
                failure_evidence=_unique_failure_evidence(
                    current_gate.get("deterministic_failures", []) + repair_mutation_failures,
                ),
                builder=repaired, repairer=repaired, browser=current_browser,
                gate=current_gate, integration_preflight=task.get("integration_preflight"),
                mutation_failures=repair_mutation_failures,
            )
        if repaired.get("status") == "too_broad":
            RUN["task_too_broad_count"] += 1
            task["integration_too_broad"] = True
            rollback_transaction()
            return {"status": "too_broad", "failure_type": "INTEGRATION_TOO_BROAD",
                    "summary": repaired.get("summary", "integration repair exceeds capacity"),
                    "memory": memory,
                    "failure_evidence": _compact_failure_evidence(_unique_failure_evidence(
                        current_gate["deterministic_failures"] + repair_mutation_failures,
                    )),
                    "repair_history": repair_history, "repairer": repaired,
                    "mutation_failures": repair_mutation_failures}
        current_preflight = run_integration_preflight(
            task, _integration_child_info_from_context(task), contract,
        )
        task["integration_preflight"]["after"] = current_preflight
        current_check = _integration_child_preflight_check(task, current_preflight)
        current_browser = (
            optional_browser_check(
                task, contract,
                syntax_failures=_combined_syntax_validation_failures(repaired),
            )
            if current_check["passed"] else None
        )
        current_gate = _integration_child_gate(repaired, None, current_browser, current_check)
        event(f"[VERIFY {task['id']}] {'PASS' if current_gate['passed'] else 'FAIL'} (fresh)",
              role="Quality Review", task=task["id"], action="fresh integration task verification")
        if current_gate["passed"]:
            return _commit_verified_integration_leaf(
                task, contract, repaired, repaired.get("summary", "integration concern verified"), memory,
                current_gate, None, current_browser, current_preflight,
            )
        if current_preflight.get("current_syntax") == "PASS" and not _integration_owned_conflicts(task, current_preflight):
            failure_type = classify_failure(repaired, current_gate, current_browser, None)
            if failure_type != "IMPLEMENTATION_ERROR":
                rollback_transaction()
                return {"status": "failed", "failure_type": failure_type,
                        "summary": "fresh integration task verification failed", "memory": memory,
                        "gate": current_gate, "integration_preflight": task["integration_preflight"]}
    rollback_transaction()
    failure_type = "INTEGRATION_FAILURE" if _integration_owned_conflicts(task, current_preflight) else "IMPLEMENTATION_ERROR"
    return {"status": "failed", "failure_type": failure_type,
            "summary": "integration task failed after repair limit", "memory": memory,
            "gate": current_gate, "integration_preflight": task["integration_preflight"],
            "failure_evidence": _compact_failure_evidence(_unique_failure_evidence(
                current_gate.get("deterministic_failures", []) + repair_mutation_failures,
            )),
            "repair_history": repair_history, "repairer": repaired,
            "mutation_failures": repair_mutation_failures}


# ---------------------------------------------------------------------------
# HIERARCHICAL INTEGRATION CONTRACT / PREFLIGHT
# ---------------------------------------------------------------------------

_MANIFEST_FIELDS = (
    "introduced_symbols", "modified_symbols", "interfaces", "assumptions", "invariants", "verification",
)

# Persistence ownership is detected from identifier semantics and actual
# storage use, rather than from one application's constant name.  This keeps
# the preflight useful across projects while avoiding a model-authored symbol
# list masquerading as project truth.
_PERSISTENCE_SEMANTIC_TOKENS = frozenset({
    "cache", "local", "persist", "persistence", "preference", "preferences", "remember",
    "save", "saved", "session", "setting", "settings", "storage",
})


def _identifier_tokens(name):
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name))
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z]+|\d+", normalized)
    }


def _looks_like_persistence_symbol(name):
    tokens = _identifier_tokens(name)
    return bool(tokens & _PERSISTENCE_SEMANTIC_TOKENS) or (
        "key" in tokens and bool(tokens & _PERSISTENCE_SEMANTIC_TOKENS)
    )


def _compact_manifest_values(values, max_items=MAX_INTEGRATION_MANIFEST_ITEMS,
                             item_chars=MAX_INTEGRATION_FACT_CHARS):
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        values = [values]
    elif not isinstance(values, (list, tuple, set)):
        values = [values]
    result = []
    seen = set()
    for value in values:
        if isinstance(value, (dict, list, tuple)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        value = compact_text(value, item_chars)
        if value and value not in seen:
            result.append(value)
            seen.add(value)
        if len(result) >= max_items:
            break
    return result


def compact_manifest(manifest, max_chars=1800):
    """Return the bounded interface contract a verified child exposes upward."""
    if not isinstance(manifest, dict):
        return {}
    projected = {"status": "verified" if manifest.get("status") in {None, "done", "verified"} else str(manifest.get("status"))}
    if manifest.get("task_id") is not None:
        projected["task_id"] = str(manifest.get("task_id"))[:80]
    projected["changed_files"] = _compact_manifest_values(manifest.get("changed_files"), 12, 140)
    for field in _MANIFEST_FIELDS:
        projected[field] = _compact_manifest_values(manifest.get(field))
    encoded = json.dumps(projected, ensure_ascii=False)
    while len(encoded) > max_chars:
        removed = False
        for field in ("verification", "assumptions", "invariants", "interfaces", "modified_symbols",
                      "introduced_symbols", "changed_files"):
            if projected.get(field):
                projected[field].pop()
                removed = True
                break
        if not removed:
            break
        encoded = json.dumps(projected, ensure_ascii=False)
    return projected


def _workspace_relative_path(raw_path):
    if raw_path is None:
        return ""
    try:
        candidate = Path(str(raw_path))
        if WORKSPACE is not None and candidate.is_absolute():
            try:
                return candidate.resolve().relative_to(WORKSPACE.resolve()).as_posix()
            except ValueError:
                return candidate.as_posix()
        return candidate.as_posix()
    except Exception:
        return compact_text(raw_path, 180)


def _workspace_source_files(max_files=MAX_RECON_FILES):
    if WORKSPACE is None or not WORKSPACE.exists():
        return []
    files = []
    for current, dirs, names in os.walk(WORKSPACE):
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(WORKSPACE).parts)
        except ValueError:
            continue
        dirs[:] = [name for name in sorted(dirs)
                   if name not in _SKIP_DIRS and depth < MAX_RECON_DEPTH]
        for name in sorted(names):
            path = Path(current) / name
            if path.suffix.casefold() not in {".js", ".mjs", ".cjs", ".html", ".htm", ".ts", ".tsx", ".jsx", ".py"}:
                continue
            try:
                relative = path.relative_to(WORKSPACE).as_posix()
            except ValueError:
                continue
            files.append((relative, path))
            if len(files) >= max_files:
                return files
    return files


def _read_source_file(path, max_chars=120000):
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except OSError:
        return ""


def _is_javascript_source(path):
    return Path(path).suffix.casefold() in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".htm"}


def _line_number(text, offset):
    return int(text.count("\n", 0, offset)) + 1


def _source_declarations(text):
    pattern = re.compile(
        r"(?m)^\s*(?:(?:export|default|async)\s+)*(const|let|var|class|function)\s+"
        r"([A-Za-z_$][\w$]*)\b"
    )
    declarations = {}
    for match in pattern.finditer(text):
        name = match.group(2)
        declarations.setdefault(name, []).append({
            "kind": match.group(1), "line": _line_number(text, match.start()),
        })
    return declarations


def _source_interfaces(text):
    values = []
    for pattern in (
        r"\bexport\s+(?:default\s+)?(?:const|let|var|class|function)\s+([A-Za-z_$][\w$]*)",
        r"\b(?:gameState|appState|state)\.([A-Za-z_$][\w$]*)",
        r"\bwindow\.(__AGENT_GAME__|__HOPLINE__|[A-Za-z_$][\w$]*)",
    ):
        values.extend(match.group(1) for match in re.finditer(pattern, text))
    return _compact_manifest_values(values)


def _manifest_from_result_source(task, result):
    """Build a child manifest mostly from deterministic artifacts.

    Models may supply richer fields in a result, but the parent never depends
    on a free-form model summary to discover obvious symbols or interfaces.
    """
    result = result if isinstance(result, dict) else {}
    explicit = result.get("integration_manifest") or result.get("manifest")
    if not explicit and isinstance(result.get("builder"), dict):
        explicit = result["builder"].get("integration_manifest") or result["builder"].get("manifest")
    explicit = explicit if isinstance(explicit, dict) else {}
    changed = []
    for value in (list(result.get("changed_files", [])) + list(task.get("changed_files", []))
                  + list(explicit.get("changed_files", []))):
        relative = _workspace_relative_path(value)
        if relative and relative not in changed:
            changed.append(relative)
    introduced = _compact_manifest_values(explicit.get("introduced_symbols"))
    modified = _compact_manifest_values(explicit.get("modified_symbols"))
    interfaces = _compact_manifest_values(explicit.get("interfaces"))
    previous_files = (LAST_COMMITTED_TRANSACTION or {}).get("files", {}) if isinstance(LAST_COMMITTED_TRANSACTION, dict) else {}
    if not introduced or not interfaces or not modified:
        for relative in changed[:12]:
            path = safe_path(relative) if WORKSPACE is not None else None
            text = _read_source_file(path) if path else ""
            if not path or not _is_javascript_source(path):
                continue
            declarations = _source_declarations(text)
            old_snapshot = previous_files.get(str(path))
            old_text = ""
            has_old_snapshot = isinstance(old_snapshot, dict)
            if has_old_snapshot and old_snapshot.get("existed") and old_snapshot.get("content") is not None:
                try:
                    old_text = old_snapshot["content"].decode("utf-8", errors="replace")
                except (AttributeError, UnicodeError):
                    old_text = ""
            old_declarations = _source_declarations(old_text) if old_text else {}
            if not introduced:
                if has_old_snapshot:
                    introduced.extend(name for name in declarations if name not in old_declarations and name not in introduced)
                elif not previous_files:
                    introduced.extend(name for name in declarations if name not in introduced)
            if not modified and has_old_snapshot and old_text != text:
                modified.extend(name for name in declarations if name in old_declarations and name not in modified)
            if not interfaces:
                for name in _source_interfaces(text):
                    if name not in interfaces:
                        interfaces.append(name)
    verification = _compact_manifest_values(explicit.get("verification"))
    if not verification:
        gate = result.get("gate")
        if isinstance(gate, dict):
            passed_checks = [item.get("name") for item in gate.get("checks", [])
                             if isinstance(item, dict) and str(item.get("status", "")).upper() == "PASS"]
            verification.extend(passed_checks)
        verification.append(compact_text(result.get("summary", "verified"), MAX_INTEGRATION_FACT_CHARS))
    manifest = {
        "status": "verified",
        "task_id": str(task.get("id", "")),
        "changed_files": changed,
        "introduced_symbols": introduced,
        "modified_symbols": modified,
        "interfaces": interfaces,
        "assumptions": _compact_manifest_values(explicit.get("assumptions")),
        "invariants": _compact_manifest_values(explicit.get("invariants")),
        "verification": verification,
    }
    return compact_manifest(manifest)


def attach_verified_manifest(task, result):
    if not isinstance(task, dict) or not isinstance(result, dict) or result.get("status") != "done":
        return None
    manifest = _manifest_from_result_source(task, result)
    task["integration_manifest"] = manifest
    result["integration_manifest"] = manifest
    merge_project_invariants(str(task.get("id", "")), manifest)
    return manifest


def _fact_key(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def merge_project_invariants(owner, manifest):
    """Promote only verified child facts with a bounded evidence projection.

    Free-form child assumptions are kept in the child manifest for audit, but
    they are deliberately not promoted to canonical project invariants.
    """
    if not isinstance(manifest, dict):
        return list(RUN.get("project_invariants", []))
    if str(manifest.get("status", "")).casefold() not in {"done", "verified"}:
        return list(RUN.get("project_invariants", []))
    if not _compact_manifest_values(manifest.get("verification")):
        return list(RUN.get("project_invariants", []))
    facts = list(RUN.get("project_invariants", []))
    existing = {_fact_key(item) for item in facts}
    for field, kind in (("interfaces", "verified_interface"), ("invariants", "verified_invariant")):
        for fact in _compact_manifest_values(manifest.get(field)):
            candidate = {"kind": kind, "owner": str(owner)[:80], "fact": fact,
                         "source": "verified_child_manifest"}
            if _fact_key(candidate) not in existing:
                facts.append(candidate)
                existing.add(_fact_key(candidate))
    RUN["project_invariants"] = facts[-24:]
    refresh_project_brain_verified_state()
    return RUN["project_invariants"]


def _scan_project_facts(source_files):
    declarations_by_name = {}
    persistence_refs = []
    loop_refs = []
    input_refs = []
    root_refs = []
    for relative, path in source_files:
        text = _read_source_file(path)
        if _is_javascript_source(path):
            declarations = _source_declarations(text)
            for name, occurrences in declarations.items():
                declarations_by_name.setdefault(name, []).extend(
                    [{"file": relative, **occurrence} for occurrence in occurrences]
                )
            string_constants = {}
            for match in re.finditer(
                r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*['\"]([^'\"]+)['\"]",
                text,
            ):
                string_constants.setdefault(match.group(1), []).append({
                    "name": match.group(1), "value": match.group(2), "file": relative,
                    "line": _line_number(text, match.start()), "kind": "constant",
                })
            for values in string_constants.values():
                for ref in values:
                    if _looks_like_persistence_symbol(ref["name"]):
                        persistence_refs.append(ref)
            storage_identifier_names = set()
            for match in re.finditer(
                r"\b(?:localStorage|sessionStorage)\.(?:getItem|setItem|removeItem)\(\s*['\"]([^'\"]+)['\"]",
                text,
            ):
                persistence_refs.append({"name": "storage-call", "value": match.group(1), "file": relative,
                                         "line": _line_number(text, match.start()), "kind": "storage-call"})
            for match in re.finditer(
                r"\b(?:localStorage|sessionStorage)\.(?:getItem|setItem|removeItem)\(\s*([A-Za-z_$][\w$]*)",
                text,
            ):
                storage_identifier_names.add(match.group(1))
                if match.group(1) not in string_constants:
                    persistence_refs.append({"name": match.group(1), "value": None, "file": relative,
                                             "line": _line_number(text, match.start()), "kind": "storage-reference"})
            for name in sorted(storage_identifier_names):
                for ref in string_constants.get(name, []):
                    if not any(item.get("kind") == "constant" and item.get("name") == name
                               and item.get("file") == relative and item.get("line") == ref.get("line")
                               for item in persistence_refs):
                        persistence_refs.append(ref)
        raf_count = len(re.findall(r"\brequestAnimationFrame\s*\(", text))
        interval_count = len(re.findall(r"\bsetInterval\s*\(", text))
        if raf_count or interval_count:
            loop_refs.append({"file": relative, "request_animation_frame": raf_count,
                              "set_interval": interval_count})
        if re.search(r"addEventListener\s*\(\s*['\"](?:keydown|keyup|keypress|pointer|click|touch)", text):
            input_refs.append(relative)
        if path.suffix.casefold() in {".html", ".htm"}:
            for match in re.finditer(r"\bid\s*=\s*['\"]([^'\"]+)['\"]", text, flags=re.IGNORECASE):
                if match.group(1).casefold() in {"game", "app", "root", "canvas"}:
                    root_refs.append({"selector": "#" + match.group(1), "file": relative,
                                      "line": _line_number(text, match.start())})
    return declarations_by_name, persistence_refs, loop_refs, input_refs, root_refs


def collect_project_invariants(source_files=None):
    source_files = source_files if source_files is not None else _workspace_source_files()
    declarations, persistence_refs, loop_refs, input_refs, root_refs = _scan_project_facts(source_files)
    facts = []
    for ref in persistence_refs:
        if ref.get("kind") == "constant" and ref.get("value") is not None and len(
            [item for item in persistence_refs if item.get("kind") == "constant" and item.get("name") == ref.get("name")]
        ) == 1:
            facts.append({"kind": "persistence_owner", "owner": ref["file"], "symbol": ref["name"],
                          "value": ref["value"], "source": "deterministic_scan",
                          "rule": f"reuse {ref['name']}; do not create another persistence constant"})
    if len(loop_refs) == 1:
        facts.append({"kind": "main_loop_owner", "owner": loop_refs[0]["file"],
                      "source": "deterministic_scan",
                      "rule": "extend the existing loop; do not create a second animation/timer loop"})
    if len(set(input_refs)) == 1:
        facts.append({"kind": "input_owner", "owner": input_refs[0],
                      "source": "deterministic_scan",
                      "rule": "extend the existing input owner"})
    if len(root_refs) == 1:
        facts.append({"kind": "root_dom", "owner": root_refs[0]["file"],
                      "selector": root_refs[0]["selector"], "source": "deterministic_scan",
                      "rule": "preserve the canonical root DOM/canvas"})
    for item in RUN.get("project_invariants", []):
        # Re-scan source-owned facts on every pass so a child that changes the
        # canonical owner cannot leave a stale invariant behind. Verified child
        # facts remain durable and are still shown to later parents.
        if isinstance(item, dict) and str(item.get("kind", "")).startswith("verified_") and item not in facts:
            facts.append(item)
    deduped = []
    seen = set()
    for fact in facts:
        key = _fact_key(fact)
        if key not in seen:
            deduped.append(fact)
            seen.add(key)
    RUN["project_invariants"] = deduped[-24:]
    return RUN["project_invariants"]


def _preflight_conflict(kind, message, files=None, severity="error", **extra):
    # ``kind`` is retained for compatibility with v2/v3 ledgers.  ``type``
    # and ``evidence`` make the small conflict contract self-describing to
    # integration-task grouping without introducing application-specific rules.
    result = {
        "kind": kind, "type": kind, "severity": severity,
        "message": compact_text(message, 500),
        "evidence": compact_text(message, 500),
    }
    if files:
        result["files"] = _compact_manifest_values(files, 8, 180)
        result["locations"] = _compact_manifest_values(files, 8, 180)
    result.update(extra)
    return result


def _stable_conflict_identity_value(value, *, file_like=False):
    """Canonicalize structured conflict data while ignoring volatile evidence."""
    if isinstance(value, dict):
        return {
            str(key): _stable_conflict_identity_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in {"line", "lines", "column", "columns"}
        }
    if isinstance(value, (list, tuple, set)):
        values = [_stable_conflict_identity_value(item, file_like=file_like) for item in value]
        return sorted(values, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str))
    text = str(value).strip().replace("\\", "/")
    if file_like:
        # A duplicate declaration currently arrives as ``file:line``.  Keep
        # the source identity, but do not make a line number the conflict ID.
        text = re.sub(r":\d+(?::\d+)?$", "", text)
        text = text.casefold()
    return text


def _preflight_conflict_fingerprint(conflict):
    """Return a stable ID for one blocking conflict observation.

    The ID is intentionally built from the conflict type, structured target,
    and normalized source identity.  Messages, parser text, and line numbers
    are evidence, not logical conflict identity.
    """
    normalized = _normalize_integration_conflict(conflict)
    identity = {"type": _integration_conflict_type(normalized)}
    target_fields = (
        "symbol", "id", "owner", "identifier", "target", "conflict_target",
        "state_owner", "entry_point", "symbols", "keys", "owners", "entry_points",
    )
    for key in target_fields:
        value = conflict.get(key) if isinstance(conflict, dict) else None
        if value in (None, [], ""):
            value = normalized.get(key)
        if value not in (None, [], ""):
            identity[key] = _stable_conflict_identity_value(value)

    files = None
    if isinstance(conflict, dict):
        files = conflict.get("files") or conflict.get("locations")
    if files in (None, [], ""):
        files = normalized.get("files") or normalized.get("locations")
    if files not in (None, [], ""):
        identity["files"] = _stable_conflict_identity_value(files, file_like=True)

    # Unknown conflict kinds still get a deterministic type-level identity.
    # We never fall back to message/evidence because those are transient.
    return json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _update_unique_preflight_conflict_metrics():
    registry = PREFLIGHT_CONFLICT_STATE.get("registry", {})
    if not isinstance(registry, dict):
        registry = {}
    detected = len(registry)
    resolved = sum(
        1 for item in registry.values()
        if isinstance(item, dict) and item.get("status") == "resolved"
    )
    RUN["preflight_blocking_conflicts_detected"] = detected
    RUN["preflight_blocking_conflicts_resolved"] = resolved
    RUN["integration_conflict_resolution"] = (
        round((resolved / detected) * 100, 2) if detected else None
    )


def _record_preflight_conflict_snapshot(preflight):
    """Update unique conflict state from one fresh deterministic preflight."""
    if not isinstance(preflight, dict) or "conflicts" not in preflight:
        return
    registry = PREFLIGHT_CONFLICT_STATE.setdefault("registry", {})
    previous_active = set(PREFLIGHT_CONFLICT_STATE.get("active", set()))
    current = {}
    for item in preflight.get("conflicts", []):
        severity = item.get("severity", "error") if isinstance(item, dict) else "error"
        if str(severity).casefold() in {"warning", "info"}:
            continue
        fingerprint = _preflight_conflict_fingerprint(item)
        current[fingerprint] = _normalize_integration_conflict(item)

    PREFLIGHT_CONFLICT_STATE["sequence"] = int(PREFLIGHT_CONFLICT_STATE.get("sequence", 0)) + 1
    sequence = PREFLIGHT_CONFLICT_STATE["sequence"]
    for fingerprint, conflict in current.items():
        record = registry.setdefault(
            fingerprint,
            {"first_observed": sequence, "observations": 0, "status": "unresolved"},
        )
        record["observations"] = int(record.get("observations", 0) or 0) + 1
        record["last_observed"] = sequence
        record["conflict"] = conflict
        # A reappearing conflict is active again and therefore not finally
        # resolved, even if an earlier preflight had cleared it.
        record["status"] = "unresolved"
    for fingerprint in previous_active - set(current):
        record = registry.get(fingerprint)
        if isinstance(record, dict):
            record["status"] = "resolved"
            record["resolved_after"] = sequence
    PREFLIGHT_CONFLICT_STATE["active"] = set(current)
    _update_unique_preflight_conflict_metrics()


_INVARIANT_CONFLICT_KINDS = frozenset({
    "conflicting_entry_points", "conflicting_persistence_ownership", "duplicate_declaration",
    "duplicate_html_id", "duplicate_child_symbol", "multiple_obvious_game_loops",
    "invariant_violation",
})


def _preflight_invariant_violation_count(preflight):
    return sum(
        1 for item in (preflight or {}).get("conflicts", [])
        if isinstance(item, dict) and item.get("kind") in _INVARIANT_CONFLICT_KINDS
    )


def run_integration_preflight(task=None, child_info=None, contract=None):
    """Run cheap deterministic checks before a parent integration mutation."""
    RUN["integration_preflight_checks"] = RUN.get("integration_preflight_checks", 0) + 1
    source_files = _workspace_source_files()
    _declarations, persistence_refs, loop_refs, _input_refs, _root_refs = _scan_project_facts(source_files)
    conflicts = []
    warnings = []
    syntax_errors = []
    for relative, path in source_files:
        text = _read_source_file(path)
        error = source_validation_error(path, text)
        if error:
            syntax_errors.append({"file": relative, "error": compact_text(error, 500)})
            conflicts.append(_preflight_conflict("syntax_error", error, [relative], error=compact_text(error, 500)))
        if _is_javascript_source(path):
            for name, occurrences in _source_declarations(text).items():
                if len(occurrences) > 1:
                    locations = [f"{relative}:{item['line']}" for item in occurrences]
                    conflicts.append(_preflight_conflict(
                        "duplicate_declaration", f"duplicate {name} declaration in one source file",
                        locations, symbol=name, declarations=occurrences,
                    ))
        if path.suffix.casefold() in {".html", ".htm"}:
            ids = {}
            for match in re.finditer(r"\bid\s*=\s*['\"]([^'\"]+)['\"]", text, flags=re.IGNORECASE):
                ids.setdefault(match.group(1), []).append(_line_number(text, match.start()))
            for value, lines in ids.items():
                if len(lines) > 1:
                    conflicts.append(_preflight_conflict(
                        "duplicate_html_id", f"duplicate HTML id '{value}'", [relative],
                        id=value, lines=lines,
                    ))
    constant_refs = [item for item in persistence_refs if item.get("kind") == "constant"]
    key_values = sorted({str(item["value"]) for item in persistence_refs if item.get("value") is not None})
    key_names = sorted({str(item["name"]) for item in constant_refs if item.get("name")})
    if len(key_values) > 1 or len(key_names) > 1:
        warnings.append(_preflight_conflict(
            "multiple_persistence_keys",
            "multiple persistence constants or literal keys are active; preserve one canonical owner per persisted state",
            [f"{item['file']}:{item['line']}" for item in persistence_refs], severity="warning",
            keys=key_values, symbols=key_names,
        ))
    names_by_owner = {}
    values_by_owner = {}
    for item in constant_refs:
        names_by_owner.setdefault(str(item.get("name", "")), set()).add(str(item.get("file", "")))
        if item.get("value") is not None:
            values_by_owner.setdefault(str(item.get("value")), set()).add(str(item.get("file", "")))
    conflicting_names = sorted(name for name, owners in names_by_owner.items() if name and len(owners) > 1)
    conflicting_values = sorted(value for value, owners in values_by_owner.items() if value and len(owners) > 1)
    if conflicting_names or conflicting_values:
        conflict_files = sorted({
            item.get("file") for item in constant_refs
            if item.get("name") in conflicting_names or item.get("value") in conflicting_values
        })
        conflicts.append(_preflight_conflict(
            "conflicting_persistence_ownership",
            "the same persistence symbol or literal key has multiple source owners",
            conflict_files,
            symbols=conflicting_names, keys=conflicting_values,
        ))
    raf_files = sorted({item["file"] for item in loop_refs if item["request_animation_frame"]})
    interval_files = sorted({item["file"] for item in loop_refs if item["set_interval"]})
    if len(raf_files) > 1 or len(interval_files) > 1 or (raf_files and interval_files and set(raf_files) != set(interval_files)):
        conflicts.append(_preflight_conflict(
            "multiple_obvious_game_loops", "more than one obvious animation/timer loop owner is present",
            sorted(set(raf_files + interval_files)), loops=loop_refs,
        ))
    entry_candidates = []
    for relative, _path in source_files:
        name = Path(relative).name.casefold()
        if "/" not in relative and name in {"index.html", "main.html", "app.html"}:
            entry_candidates.append(relative)
    if len(entry_candidates) > 1:
        conflicts.append(_preflight_conflict(
            "conflicting_entry_points", "multiple top-level browser entry points are present",
            entry_candidates, entry_points=entry_candidates,
        ))
    child_symbol_owners = {}
    for item in child_info or []:
        if not isinstance(item, dict):
            continue
        manifest = item.get("integration_manifest") or {}
        if not isinstance(manifest, dict):
            continue
        for symbol in _compact_manifest_values(manifest.get("introduced_symbols")):
            child_symbol_owners.setdefault(symbol, set()).add(str(item.get("task_id", "")))
    duplicate_child_symbols = sorted(
        symbol for symbol, owners in child_symbol_owners.items() if symbol and len(owners) > 1
    )
    if duplicate_child_symbols:
        conflicts.append(_preflight_conflict(
            "duplicate_child_symbol",
            "verified children introduce the same top-level symbol; preserve one canonical owner",
            sorted({owner for symbol in duplicate_child_symbols for owner in child_symbol_owners[symbol]}),
            symbols=duplicate_child_symbols,
        ))
    # Contract prose is authoritative task input, but it is not evidence that
    # a project already has an invariant.  Keep the canonical ledger limited
    # to deterministic scans and verified child manifests.
    project_invariants = collect_project_invariants(source_files)
    RUN["project_invariants"] = project_invariants[-24:]
    errors = [item for item in conflicts if item.get("severity", "error") == "error"]
    if errors:
        RUN["integration_preflight_failures"] = RUN.get("integration_preflight_failures", 0) + 1
        RUN["integration_conflicts_detected"] = RUN.get("integration_conflicts_detected", 0) + len(errors)
    result = {
        "passed": not errors,
        "status": "PASS" if not errors else "FAIL",
        "checked_files": [relative for relative, _path in source_files],
        "syntax_errors": syntax_errors,
        "conflicts": conflicts[:MAX_INTEGRATION_CONFLICTS],
        "warnings": warnings[:MAX_INTEGRATION_CONFLICTS],
        "error_count": len(errors),
        "warning_count": len(warnings),
        "invariant_violation_count": sum(
            1 for item in errors if item.get("kind") in _INVARIANT_CONFLICT_KINDS
        ),
        "project_invariants": project_invariants,
        "current_syntax": "FAIL" if syntax_errors else "PASS",
    }
    _record_preflight_conflict_snapshot(result)
    record_run_event(
        "integration_preflight", task_id=(task or {}).get("id") if isinstance(task, dict) else None,
        passed=result["passed"], current_syntax=result["current_syntax"],
        conflicts=result["conflicts"], warnings=result["warnings"],
    )
    return result


def _integration_conflict_type(conflict):
    if not isinstance(conflict, dict):
        return "integration_conflict"
    return str(conflict.get("type") or conflict.get("kind") or "integration_conflict")


def _normalize_integration_conflict(conflict):
    """Project one deterministic preflight conflict into a small task fact."""
    if not isinstance(conflict, dict):
        message = compact_text(conflict, 500)
        return {"type": "integration_conflict", "kind": "integration_conflict",
                "severity": "blocking", "evidence": message, "message": message}
    kind = _integration_conflict_type(conflict)
    normalized = {
        "type": kind, "kind": kind,
        "severity": str(conflict.get("severity", "error")),
        "evidence": compact_text(conflict.get("evidence") or conflict.get("message") or kind, 500),
    }
    for key in ("message", "symbol", "id", "keys", "symbols", "files", "locations", "lines", "declarations"):
        if key not in conflict or conflict.get(key) in (None, [], ""):
            continue
        value = conflict.get(key)
        if isinstance(value, (list, tuple, set)):
            normalized[key] = _compact_manifest_values(value, 8, 180)
        elif isinstance(value, dict):
            normalized[key] = compact_text(json.dumps(value, ensure_ascii=False, sort_keys=True), 700)
        else:
            normalized[key] = compact_text(value, 500)
    locations = normalized.get("locations") or []
    if not locations:
        declarations = normalized.get("declarations") or []
        if declarations and normalized.get("files"):
            locations = [
                f"{file}:{item.get('line')}"
                for file, item in zip(normalized.get("files", []), declarations)
                if isinstance(item, dict) and item.get("line") is not None
            ]
        elif normalized.get("lines") and normalized.get("files"):
            locations = [
                f"{file}:{line}"
                for file in normalized.get("files", [])
                for line in normalized.get("lines", [])
            ]
    if locations:
        normalized["locations"] = _compact_manifest_values(locations, 8, 180)
    return normalized


def _integration_conflict_subject(conflict):
    conflict = _normalize_integration_conflict(conflict)
    for key in ("symbol", "id"):
        if conflict.get(key):
            return compact_text(conflict[key], 180)
    for key in ("symbols", "keys"):
        values = conflict.get(key) or []
        if values:
            return ", ".join(_compact_manifest_values(values, 4, 100))
    locations = conflict.get("locations") or conflict.get("files") or []
    if locations:
        return ", ".join(_compact_manifest_values(locations, 2, 120))
    return compact_text(conflict.get("evidence") or conflict.get("message") or "the detected conflict", 180)


def _integration_conflict_group_key(conflict):
    conflict = _normalize_integration_conflict(conflict)
    kind = _integration_conflict_type(conflict)
    if kind == "duplicate_declaration":
        return kind, str(conflict.get("symbol") or _integration_conflict_subject(conflict))
    if kind == "duplicate_html_id":
        return kind, str(conflict.get("id") or _integration_conflict_subject(conflict))
    if kind in {"conflicting_persistence_ownership", "multiple_persistence_owners", "multiple_persistence_keys"}:
        return kind, _integration_conflict_subject(conflict)
    if kind in {"syntax_error", "invariant_violation"}:
        return kind, _integration_conflict_subject(conflict)
    if kind in {"multiple_obvious_game_loops", "conflicting_entry_points", "multiple_state_owners"}:
        return kind, "shared-owner"
    if kind == "duplicate_child_symbol":
        return kind, _integration_conflict_subject(conflict)
    return kind, compact_text(conflict.get("message") or conflict.get("evidence") or kind, 180)


def _group_integration_conflicts(conflicts, max_groups=None):
    """Group blocking facts by one deterministic integration concern."""
    blocking = []
    for item in conflicts or []:
        severity = item.get("severity", "error") if isinstance(item, dict) else "error"
        if str(severity).casefold() not in {"warning", "info"}:
            blocking.append(_normalize_integration_conflict(item))
    buckets = {}
    for conflict in sorted(
        blocking,
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str),
    ):
        buckets.setdefault(_integration_conflict_group_key(conflict), []).append(conflict)
    groups = [buckets[key] for key in sorted(buckets, key=lambda value: repr(value))]
    limit = int(max_groups or MAX_CHILDREN)
    limit = max(1, min(MAX_CHILDREN, limit))
    if len(groups) <= limit:
        return groups
    # Keep the first concerns independent and make the final bounded task own
    # the remainder. No conflict is silently dropped; an oversized final group
    # can itself use the same integration resplit path.
    remainder = [conflict for group in groups[limit - 1:] for conflict in group]
    return groups[:limit - 1] + [remainder]


def _integration_task_spec(group, parent_scope=None):
    group = [_normalize_integration_conflict(item) for item in (group or [])]
    kinds = sorted({_integration_conflict_type(item) for item in group})
    subject = _integration_conflict_subject(group[0]) if len(group) == 1 else "the grouped blocking conflicts"
    kind = kinds[0] if len(kinds) == 1 else "mixed_integration_conflict"
    if kind == "duplicate_declaration":
        goal = f"Resolve the duplicate declaration of {subject}; preserve one canonical definition and current callers."
    elif kind in {"conflicting_persistence_ownership", "multiple_persistence_owners", "multiple_persistence_keys"}:
        goal = f"Normalize persistence ownership for {subject}; reuse one canonical owner without changing unrelated behavior."
    elif kind == "duplicate_html_id":
        goal = f"Resolve the duplicate HTML id {subject}; preserve the intended control and its consumers."
    elif kind == "multiple_obvious_game_loops":
        goal = "Preserve one canonical animation/timer loop and reconnect existing behavior to it."
    elif kind == "conflicting_entry_points":
        goal = "Preserve one canonical browser entry point and remove conflicting top-level entry ownership."
    elif kind == "syntax_error":
        goal = f"Repair the reported syntax error at {subject} with the smallest valid edit."
    elif kind == "duplicate_child_symbol":
        goal = f"Resolve duplicate child ownership for {subject}; preserve one canonical symbol owner."
    elif kind == "invariant_violation":
        goal = f"Resolve the detected project invariant violation at {subject} without redefining the invariant."
    else:
        goal = "Resolve the bounded integration conflict group using the deterministic evidence below."
    labels = ", ".join(kinds)
    done_when = [
        f"Fresh preflight has no blocking {labels} conflict owned by this task.",
        "Relevant syntax/build or executable verification passes after the repair.",
    ]
    scope = []
    for conflict in group:
        scope.extend(conflict.get("files", []))
        scope.extend(conflict.get("locations", []))
        if conflict.get("symbol"):
            scope.append(str(conflict["symbol"]))
    if not scope:
        scope = list(parent_scope or [])
    return {
        "goal": compact_text(goal, 900),
        "done_when": bounded_list(done_when, 4, 500),
        "scope_hint": _compact_manifest_values(scope, 8, 180),
        "conflicts": group,
    }


def _compact_integration_child_info(child_info):
    projected = []
    for item in list(child_info or [])[:MAX_INTEGRATION_MANIFEST_ITEMS]:
        if not isinstance(item, dict):
            continue
        projected.append({
            "task_id": str(item.get("task_id", ""))[:80],
            "goal": compact_text(item.get("goal", ""), 280),
            "status": str(item.get("status", ""))[:40],
            "summary": compact_text(item.get("summary", ""), 420),
            "changed_files": _compact_manifest_values(item.get("changed_files", []), 8, 140),
            "verification": compact_text(item.get("verification", ""), 240),
            "integration_manifest": compact_manifest(item.get("integration_manifest")),
            "evidence": compact_text(item.get("evidence", ""), 520),
        })
    return projected


def _integration_context_for_task(parent_task, child_info, preflight):
    return {
        "parent_goal": compact_text(parent_task.get("goal", ""), 1000),
        "project_invariants": bounded_list(
            (preflight or {}).get("project_invariants", []) or RUN.get("project_invariants", []),
            12, MAX_INTEGRATION_FACT_CHARS,
        ),
        "verified_child_manifests": _compact_integration_child_info(child_info),
    }


def build_integration_node_packet(task, root_contract, repo_snapshot, parent_summary="",
                                  dependency_summaries=None, failure_evidence=None,
                                  brain_projection=None, worker_mission=None):
    """Build the bounded packet used only by an integration task leaf."""
    context = task.get("integration_context") if isinstance(task.get("integration_context"), dict) else {}
    try:
        invariants = collect_project_invariants() if WORKSPACE is not None else []
    except Exception:
        invariants = []
    if not invariants:
        invariants = context.get("project_invariants") or RUN.get("project_invariants", [])
    if isinstance(brain_projection, dict):
        projected_state = brain_projection.get("verified_state")
        if isinstance(projected_state, dict) and "project_invariants" in projected_state:
            invariants = projected_state.get("project_invariants", [])
    dependencies = []
    for item in list(dependency_summaries or [])[-MAX_INTEGRATION_MANIFEST_ITEMS:]:
        if not isinstance(item, dict) or str(item.get("status", "")).casefold() not in {"done", "verified", "passed"}:
            continue
        dependencies.append({
            "task_id": str(item.get("task_id", ""))[:80],
            "goal": compact_text(item.get("goal", ""), 280),
            "status": str(item.get("status", ""))[:40],
            "summary": compact_text(item.get("summary", ""), 420),
            "changed_files": _compact_manifest_values(item.get("changed_files", []), 8, 140),
            "evidence": compact_text(item.get("evidence", ""), 520),
            "integration_manifest": compact_manifest(item.get("integration_manifest")),
        })
    failure_projection = _compact_failure_evidence(failure_evidence or task.get("failure_evidence", []), max_items=4)
    packet = {
        "ROOT CONTRACT": compact_contract(root_contract, max_chars=MAX_ROOT_PACKET_CHARS),
        "PROJECT BRAIN PROJECTION": _compact_brain_projection(brain_projection)
        if isinstance(brain_projection, dict) and brain_projection else {},
        "PARENT GOAL": compact_text(context.get("parent_goal") or parent_summary or "(none)", 1000),
        "CURRENT INTEGRATION TASK": {
            "id": str(task.get("id", "")),
            "kind": "integration",
            "goal": compact_text(task.get("goal", ""), 900),
            "done_when": bounded_list(task.get("done_when", []), 6, 260),
            "scope_hint": bounded_list(task.get("scope_hint", []), 6, 180),
        },
        "PROJECT INVARIANTS": bounded_list(invariants, 12, MAX_INTEGRATION_FACT_CHARS),
        "RELEVANT CHILD INTEGRATION MANIFESTS": context.get("verified_child_manifests", [])[:MAX_INTEGRATION_MANIFEST_ITEMS],
        "RELEVANT PREFLIGHT CONFLICT(S)": bounded_list(
            task.get("integration_conflicts", []), MAX_INTEGRATION_MANIFEST_ITEMS, 700,
        ),
        "VERIFIED DEPENDENCY SUMMARIES": dependencies,
        "CURRENT FAILURE EVIDENCE": failure_projection,
        "BOUNDED REPOSITORY HINTS": repository_hints(
            repo_snapshot, task.get("scope_hint"), max_chars=1900,
        ),
    }
    if isinstance(worker_mission, dict) and worker_mission:
        packet["WORKER MISSION"] = worker_mission
    encoded = json.dumps(packet, ensure_ascii=False, default=str)
    return "INTEGRATION NODE PACKET:\n" + encoded[:MAX_NODE_PACKET_CHARS - 24]


def _materialize_integration_tasks(parent_task, specs, context):
    children = []
    for index, spec in enumerate(list(specs or [])[:MAX_CHILDREN], 1):
        parent_id = str(parent_task.get("id", ""))
        if parent_id == "ROOT":
            child_id = f"I.{index}"
        elif parent_id.startswith("I.") or ".I." in parent_id:
            child_id = f"{parent_id}.{index}"
        else:
            child_id = f"{parent_id}.I.{index}"
        child_context = dict(context or {})
        child_context["parent_goal"] = compact_text(parent_task.get("goal", ""), 1000)
        child = make_task(
            child_id, spec["goal"], int(parent_task.get("depth", 0)) + 1, parent_task.get("id"),
            spec.get("done_when", []), spec.get("scope_hint", []),
            kind="integration", integration_conflicts=spec.get("conflicts", []),
            integration_context=child_context,
        )
        TASKS[child_id] = child
        parent_task.setdefault("children", []).append(child_id)
        RUN["tasks_created"] += 1
        RUN["max_depth"] = max(RUN.get("max_depth", 0), child["depth"])
        update_task_ledger(child)
        children.append(child)
    return children


def create_integration_tasks(parent_task, contract, child_info, preflight, root=False):
    """Turn current blocking preflight facts into bounded integration nodes."""
    conflicts = [
        item for item in (preflight or {}).get("conflicts", [])
        if (not isinstance(item, dict))
        or str(item.get("severity", "error")).casefold() not in {"warning", "info"}
    ]
    if not conflicts:
        return []
    remaining = MAX_TOTAL_TASKS - RUN.get("tasks_created", 0)
    if remaining < 1:
        return []
    groups = _group_integration_conflicts(conflicts, max_groups=min(MAX_CHILDREN, remaining))
    context = _integration_context_for_task(parent_task, child_info, preflight)
    specs = [_integration_task_spec(group, parent_task.get("scope_hint")) for group in groups]
    children = _materialize_integration_tasks(parent_task, specs, context)
    if children:
        parent_task["integration_split_boundary"] = True
        parent_task.setdefault("integration_preflight", {})["integration_tasks"] = [
            {
                "task_id": child.get("id"), "kind": child.get("kind"),
                "goal": child.get("goal"), "done_when": child.get("done_when"),
                "scope_hint": child.get("scope_hint"),
                "conflicts": child.get("integration_conflicts", []),
            }
            for child in children
        ]
        RUN["integration_splits"] = RUN.get("integration_splits", 0) + 1
        record_run_event(
            "integration_tasks_created", parent_task_id=parent_task.get("id"),
            task_ids=[child.get("id") for child in children],
            conflicts=[_normalize_integration_conflict(item) for item in conflicts],
        )
    return children


def _integration_stage_specs(task):
    group = [_normalize_integration_conflict(item) for item in task.get("integration_conflicts", [])]
    label = _integration_conflict_subject(group[0]) if group else "the current integration concern"
    scope = list(task.get("scope_hint", []))
    return [
        {
            "goal": f"Make the canonical owner for {label} explicit and remove only the conflicting definition.",
            "done_when": ["the canonical owner is preserved", "affected source syntax passes"],
            "scope_hint": scope, "conflicts": group,
        },
        {
            "goal": f"Reconnect the affected consumers of {label} to the canonical owner and verify the focused behavior.",
            "done_when": ["fresh preflight has no owned blocking conflict", "focused executable verification passes"],
            "scope_hint": scope, "conflicts": group,
        },
    ]


def decompose_integration_task(task, contract, repo_snapshot, parent_summary="", dependency_summaries=None,
                               force_smaller=False):
    """Deterministically split one integration concern for solve_task()."""
    remaining = MAX_TOTAL_TASKS - RUN.get("tasks_created", 0)
    if remaining < 2:
        return []
    groups = _group_integration_conflicts(
        task.get("integration_conflicts", []), max_groups=min(MAX_CHILDREN, remaining),
    )
    specs = [_integration_task_spec(group, task.get("scope_hint")) for group in groups]
    if force_smaller and len(specs) < 2:
        specs = _integration_stage_specs(task)
    if len(specs) < 2:
        return []
    base_context = task.get("integration_context") if isinstance(task.get("integration_context"), dict) else {}
    children = _materialize_integration_tasks(task, specs, base_context)
    if not children:
        return []
    task["integration_split_boundary"] = True
    _record_decomposition_branch(
        task, specs, children, kind="integration_resplit" if force_smaller else "integration",
    )
    return children


def build_integration_contract(task, contract, child_info, preflight, root=False, fit=None,
                               brain_projection=None):
    """Create the parent-facing Hierarchical Integration Contract."""
    integration_contract = {
        "parent_goal": compact_text(task.get("goal", ""), 1000),
        "root": bool(root),
        "current_syntax": preflight.get("current_syntax", "PASS"),
        "integration_conflicts": preflight.get("conflicts", []),
        "integration_warnings": preflight.get("warnings", []),
        "project_invariants": preflight.get("project_invariants", []),
        "verified_children": [
            {
                "task_id": item.get("task_id"),
                "goal": item.get("goal"),
                "manifest": compact_manifest(item.get("integration_manifest")),
                "verification": item.get("verification"),
            }
            for item in child_info or []
        ],
        "integration_fit": fit or {"decision": "execute", "reason": "single focused integration pass"},
        "milestones": [
            "normalize shared state",
            "resolve symbol/interface conflicts",
            "connect child behaviors",
            "run syntax/build verification",
            "run behavioral verification",
        ],
        "root_contract": compact_contract(contract, max_chars=MAX_ROOT_PACKET_CHARS),
    }
    if isinstance(brain_projection, dict) and brain_projection:
        integration_contract["project_brain_alignment"] = _compact_brain_projection(
            brain_projection, max_chars=MAX_BRAIN_PROJECTION_CHARS,
        )
    return integration_contract


def decide_integration_fit(task, child_info, preflight):
    errors = list(preflight.get("conflicts", []))
    manifest_size = sum(sum(len(item.get(field, [])) for field in _MANIFEST_FIELDS)
                        for item in (item.get("integration_manifest") or {} for item in child_info or [])
                        if isinstance(item, dict))
    if errors and (len(child_info or []) >= 3 or len(errors) >= 2 or manifest_size > 12):
        return {"decision": "split", "reason": "integration conflicts exceed one focused repair boundary",
                "milestones": ["normalize_shared_state", "resolve_conflicts", "connect_behaviors",
                               "syntax_build", "behavioral_verification"]}
    return {"decision": "execute", "reason": "integration fits one focused parent pass",
            "milestones": ["focused_integration"]}


def _integration_failure_evidence(preflight):
    preflight = _effective_preflight(preflight)
    if not preflight or preflight.get("passed"):
        return []
    return [{"kind": "integration_preflight", "status": preflight.get("status", "FAIL"),
             "result": compact_text(json.dumps({
                 "current_syntax": preflight.get("current_syntax"),
                 "conflicts": preflight.get("conflicts", []),
                 "warnings": preflight.get("warnings", []),
             }, ensure_ascii=False), 1500)}]


def run_integration_milestones(task, contract, child_info, memory, repo_snapshot, integration_contract):
    """Run only the bounded integration-specific repair path."""
    RUN["integration_milestone_runs"] = RUN.get("integration_milestone_runs", 0) + 1
    label = "ROOT" if task.get("id") == "ROOT" else str(task.get("id"))
    specs = (
        ("normalize_shared_state", "Normalize shared state and persistence ownership using the canonical project invariants."),
        ("resolve_conflicts", "Resolve the concrete symbol and interface conflicts from the integration preflight; preserve one canonical definition."),
        ("connect_behaviors", "Connect the already verified child behaviors through their declared interfaces without duplicating owners."),
        ("syntax_build", "Run syntax/build verification for the complete integrated parent and repair only concrete errors."),
        ("behavioral_verification", "Run fresh behavioral verification for the complete parent integration."),
    )
    current = integration_contract
    records = []
    evidence = []
    for milestone_id, goal in specs:
        RUN["integration_milestone_steps"] = RUN.get("integration_milestone_steps", 0) + 1
        event(f"[INTEGRATION MILESTONE {label}] {milestone_id}", role="Builder", task=label,
              action="integration-specific repair")
        context = (
            f"HIERARCHICAL INTEGRATION CONTRACT:\n{json.dumps(current, ensure_ascii=False)[:8500]}\n\n"
            f"INTEGRATION MILESTONE: {milestone_id}\n{goal}\n"
            "Make only the smallest concrete changes needed for this milestone. Preserve project invariants. "
            "Inspect the shared workspace and run an executable verification before stopping."
        )
        result = execute_agent_task(goal, memory, role="Builder", task_id=f"{label}:integration:{milestone_id}",
                                    extra_context=context)
        memory = result.get("memory", memory)
        milestone_evidence = _worker_failure_evidence(result)
        evidence.extend(milestone_evidence)
        records.append({"id": milestone_id, "status": result.get("status", "failed"),
                        "summary": compact_text(result.get("summary", ""), MAX_NODE_SUMMARY_CHARS),
                        "evidence": _compact_failure_evidence(milestone_evidence, max_items=4)})
        if result.get("status") != "done":
            failure_type = "ENVIRONMENT_ERROR" if result.get("status") == "provider_failure" else (
                "INTEGRATION_TOO_BROAD" if result.get("status") == "too_broad" else "INTEGRATION_FAILURE"
            )
            return {"status": "failed", "failure_type": failure_type,
                    "summary": f"integration milestone {milestone_id} failed: {result.get('summary', '')}",
                    "memory": memory, "tool_evidence": evidence, "integration_milestones": records,
                    "mutation_failures": _merge_mutation_failure_records(
                        _mutation_failure_records(result),
                    ),
                    "failure_evidence": _integration_failure_evidence(current) or _compact_failure_evidence(evidence)}
        refreshed = run_integration_preflight(task, child_info, contract)
        current = dict(current)
        current["passed"] = refreshed.get("passed")
        current["status"] = refreshed.get("status")
        current["current_syntax"] = refreshed.get("current_syntax")
        current["integration_conflicts"] = refreshed.get("conflicts", [])
        current["integration_warnings"] = refreshed.get("warnings", [])
        current["project_invariants"] = refreshed.get("project_invariants", [])
    return {"status": "done", "summary": "integration-specific milestones completed", "memory": memory,
            "tool_evidence": evidence, "integration_milestones": records,
            "integration_preflight": current}


def _integration_fit_decider(task, depth, contract, repo_snapshot, parent_summary,
                             dependency_summaries, force_smaller=False):
    if task.get("kind") == "integration":
        return {
            "decision": "split" if force_smaller else "execute",
            "reason": "integration conflict groups are already bounded" if not force_smaller
            else "the integration concern exceeded one focused execution",
        }
    return decide_task_fit(
        task, depth, contract, repo_snapshot, parent_summary,
        dependency_summaries, force_smaller=force_smaller,
    )


def _integration_result_info(child_task, child_result):
    child_task = child_task if isinstance(child_task, dict) else {}
    child_result = child_result if isinstance(child_result, dict) else {}
    if child_result.get("status") == "done":
        attach_verified_manifest(child_task, child_result)
    return {
        "task_id": str(child_task.get("id", "")),
        "goal": compact_text(child_task.get("goal", ""), 360),
        "status": str(child_result.get("status", "failed")),
        "summary": compact_text(child_result.get("summary", ""), MAX_NODE_SUMMARY_CHARS),
        "changed_files": _compact_manifest_values(child_result.get("changed_files", []), 12, 140),
        "verification": child_task.get("verification_status", "unknown"),
        "integration_manifest": compact_manifest(
            child_result.get("integration_manifest") or child_task.get("integration_manifest")
        ),
        "evidence": compact_evidence_summary(child_result),
    }


def _aggregate_integration_children(task, contract, child_results, memory, repo_snapshot=None, root=False):
    """Aggregate a split integration concern without invoking a second planner."""
    child_info = [
        _integration_result_info(
            item.get("task", {}) if isinstance(item, dict) else {},
            item.get("result", {}) if isinstance(item, dict) else {},
        )
        for item in child_results or []
    ]
    if any(item.get("status") != "done" for item in child_info):
        return {
            "status": "failed", "failure_type": "CHILD_FAILURE",
            "summary": "not all integration children were verified", "memory": memory,
            "children": child_info,
        }
    base_info = _integration_child_info_from_context(task)
    preflight = run_integration_preflight(task, base_info + child_info, contract)
    task["integration_preflight"] = {"after": preflight}
    owned_remaining = _integration_owned_conflicts(task, preflight)
    if preflight.get("current_syntax", "PASS") == "PASS" and not owned_remaining:
        changed = []
        for item in child_info:
            for path in item.get("changed_files", []):
                if path not in changed:
                    changed.append(path)
        return {
            "status": "done", "summary": "integration concern subtree verified", "memory": memory,
            "changed_files": changed, "children": child_info,
            "integration_preflight": {"after": preflight},
        }
    return {
        "status": "failed", "failure_type": "INTEGRATION_FAILURE",
        "summary": "integration concern subtree still has an owned blocking conflict",
        "memory": memory, "children": child_info,
        "integration_preflight": {"after": preflight},
        "failure_evidence": _integration_failure_evidence(preflight),
    }


def run_integration_tasks_sequentially(parent_task, contract, child_info, integration_tasks,
                                       memory, repo_snapshot):
    """Run integration nodes one at a time through solve_task()."""
    results = []
    integration_info = []
    dependencies = list(child_info or [])
    current_preflight = (parent_task.get("integration_preflight") or {}).get("before") or {}
    for child in integration_tasks or []:
        result = solve_task(
            child, int(parent_task.get("depth", 0)), contract, memory, repo_snapshot,
            parent_summary=f"Integration parent: {parent_task.get('goal', '')}",
            dependency_summaries=dependencies,
            fit_decider=_integration_fit_decider,
            leaf_executor=None,
            aggregator=_aggregate_integration_children,
        )
        memory = result.get("memory", memory)
        results.append({"task": child, "result": result})
        info = _integration_result_info(child, result)
        integration_info.append(info)
        dependencies.append(info)
        current_preflight = run_integration_preflight(
            parent_task, list(child_info or []) + integration_info, contract,
        )
        parent_task.setdefault("integration_preflight", {})["after"] = current_preflight
        if result.get("status") != "done":
            return {
                "status": "failed", "failure_type": result.get("failure_type", "INTEGRATION_FAILURE"),
                "summary": f"integration task {child.get('id')} failed: {result.get('summary', '')}",
                "memory": memory, "children": results, "integration_children": integration_info,
                "integration_preflight": current_preflight,
            }
    return {
        "status": "done", "summary": "all integration tasks verified sequentially", "memory": memory,
        "children": results, "integration_children": integration_info,
        "integration_preflight": current_preflight,
    }


def _start_parent_integration(task, preflight):
    """Count one real parent integration boundary exactly once."""
    if not isinstance(task, dict) or task.get("_parent_integration_started"):
        return
    preflight = preflight if isinstance(preflight, dict) else {}
    initial_conflicts = int(preflight.get("error_count", 0) or 0)
    if not initial_conflicts:
        initial_conflicts = sum(
            1 for item in preflight.get("conflicts", [])
            if isinstance(item, dict) and item.get("severity", "error") == "error"
        )
    invariant_violations = int(preflight.get("invariant_violation_count", 0) or 0)
    if not invariant_violations:
        invariant_violations = _preflight_invariant_violation_count(preflight)
    task["_parent_integration_started"] = True
    task["_parent_integration_initial_conflicts"] = initial_conflicts
    RUN["parent_integrations_attempted"] = RUN.get("parent_integrations_attempted", 0) + 1
    RUN["integration_preflight_conflicts"] = RUN.get("integration_preflight_conflicts", 0) + initial_conflicts
    _record_preflight_conflict_snapshot(preflight)
    RUN["invariant_violations_detected"] = RUN.get("invariant_violations_detected", 0) + invariant_violations
    recompute_integration_metrics()
    record_run_event(
        "parent_integration_started", task_id=task.get("id"),
        initial_conflicts=initial_conflicts, invariant_violations=invariant_violations,
    )


def _finish_parent_integration(task, *, passed, recovered=False, preflight=None):
    """Record the terminal outcome of one parent integration attempt."""
    if not isinstance(task, dict) or not task.get("_parent_integration_started"):
        return None
    if task.get("_parent_integration_recorded"):
        return task.get("integration_outcome")
    preflight = preflight if isinstance(preflight, dict) else {}
    _record_preflight_conflict_snapshot(preflight)
    final_conflicts = int(preflight.get("error_count", 0) or 0)
    if not final_conflicts:
        final_conflicts = sum(
            1 for item in preflight.get("conflicts", [])
            if isinstance(item, dict) and item.get("severity", "error") == "error"
        )
    initial_conflicts = int(task.get("_parent_integration_initial_conflicts", 0) or 0)
    resolved = max(0, initial_conflicts - final_conflicts)
    if passed:
        RUN["parent_integrations_passed"] = RUN.get("parent_integrations_passed", 0) + 1
        if recovered:
            RUN["parent_integrations_recovered"] = RUN.get("parent_integrations_recovered", 0) + 1
    else:
        RUN["parent_integrations_failed"] = RUN.get("parent_integrations_failed", 0) + 1
    RUN["integration_conflicts_resolved"] = RUN.get("integration_conflicts_resolved", 0) + resolved
    outcome = {
        "attempted": True, "passed": bool(passed), "recovered": bool(recovered and passed),
        "initial_conflicts": initial_conflicts, "final_conflicts": final_conflicts,
        "conflicts_resolved": resolved,
    }
    task["_parent_integration_recorded"] = True
    task["integration_outcome"] = outcome
    recompute_integration_metrics()
    record_run_event("parent_integration_finished", task_id=task.get("id"), **outcome)
    return outcome


# ---------------------------------------------------------------------------
# HIERARCHICAL INTEGRATION AND TRUE RECURSION
# ---------------------------------------------------------------------------

def compact_evidence_summary(result):
    """Project a child result into evidence facts safe for its parent packet."""
    if not isinstance(result, dict):
        return "(no result)"
    gate = result.get("gate")
    if isinstance(gate, dict):
        projection = {
            "passed": bool(gate.get("passed")),
            "deterministic_failures": gate.get("deterministic_failures", []),
        }
        return compact_text(json.dumps(projection, ensure_ascii=False), 700)
    evidence = result.get("tool_evidence")
    if not evidence and isinstance(result.get("builder"), dict):
        evidence = result["builder"].get("tool_evidence", [])
    if evidence:
        return compact_text(json.dumps(evidence_for_review(evidence)[-3:], ensure_ascii=False), 700)
    return "(no deterministic evidence projection supplied)"


def aggregate_task(task, contract, child_results, memory, repo_snapshot=None, root=False):
    label = "ROOT" if root else task["id"]
    event(f"[AGGREGATE {label}]", role="Builder", task=label, action="hierarchical integration")
    child_info = []
    for item in child_results:
        child_task = item.get("task", {}) if isinstance(item, dict) else {}
        child_result = item.get("result", {}) if isinstance(item, dict) else {}
        if not isinstance(child_task, dict):
            child_task = {"id": str(child_task), "goal": str(child_task)}
        if not isinstance(child_result, dict):
            child_result = {"status": "failed", "summary": str(child_result)}
        if child_result.get("status") == "done":
            attach_verified_manifest(child_task, child_result)
        child_info.append({
            "task_id": str(child_task.get("id", "")),
            "goal": compact_text(child_task.get("goal", ""), 360),
            "status": str(child_result.get("status", "failed")),
            "summary": compact_text(child_result.get("summary", ""), MAX_NODE_SUMMARY_CHARS),
            "changed_files": _compact_manifest_values(child_result.get("changed_files", []), 12, 140),
            "verification": child_task.get("verification_status", "unknown"),
            "integration_manifest": compact_manifest(
                child_result.get("integration_manifest") or child_task.get("integration_manifest")
            ),
            "evidence": compact_evidence_summary(child_result),
        })
    if any(item["status"] != "done" for item in child_info):
        RUN["integration_failures"] += 1
        return {"status": "failed", "failure_type": "CHILD_FAILURE", "summary": "not all children verified",
                "memory": memory, "children": child_info}

    preflight_before = run_integration_preflight(task, child_info, contract)
    fit = decide_integration_fit(task, child_info, preflight_before)
    integration_brain_projection = None
    if isinstance(RUN.get("project_brain"), dict):
        refresh_project_brain_verified_state()
        integration_brain_projection = build_brain_projection(
            RUN["project_brain"], task, child_info, repo_snapshot, record=False,
        )
    integration_contract = build_integration_contract(
        task, contract, child_info, preflight_before, root=root, fit=fit,
        brain_projection=integration_brain_projection,
    )
    task["integration_preflight"] = {
        "before": preflight_before, "fit": fit, "after": None, "milestones": [],
    }
    _start_parent_integration(task, preflight_before)
    integration_recovery_needed = bool(
        not preflight_before.get("passed") or fit.get("decision") == "split"
    )
    event(
        f"[INTEGRATION PREFLIGHT {label}] {preflight_before.get('status', 'FAIL')} "
        f"({len(preflight_before.get('conflicts', []))} conflict(s))",
        role="Coordinator", task=label, action="integration preflight",
    )

    # Blocking preflight facts become real sequential integration nodes. Each
    # node owns one deterministic concern and runs through solve_task(), so a
    # too-broad integration repair can use the same adaptive decomposition
    # machinery as any other task.
    integration_children = []
    if not preflight_before.get("passed"):
        integration_children = create_integration_tasks(
            task, contract, child_info, preflight_before, root=root,
        )
        if not integration_children:
            _finish_parent_integration(task, passed=False, preflight=preflight_before)
            RUN["integration_failures"] += 1
            return {
                "status": "failed", "failure_type": "INTEGRATION_FAILURE",
                "summary": "blocking integration conflicts remain but no integration task budget is available",
                "memory": memory, "children": child_info,
                "integration_preflight": task["integration_preflight"],
            }
        integration_result = run_integration_tasks_sequentially(
            task, contract, child_info, integration_children, memory, repo_snapshot,
        )
        memory = integration_result.get("memory", memory)
        integration_info = list(integration_result.get("integration_children", []) or [])
        combined_child_info = child_info + integration_info
        preflight_after_children = integration_result.get("integration_preflight")
        if not isinstance(preflight_after_children, dict):
            preflight_after_children = run_integration_preflight(
                task, combined_child_info, contract,
            )
        task["integration_preflight"]["integration_children"] = integration_info
        task["integration_preflight"]["after"] = preflight_after_children
        if integration_result.get("status") != "done" or not preflight_after_children.get("passed"):
            _finish_parent_integration(task, passed=False, preflight=preflight_after_children)
            RUN["integration_failures"] += 1
            failure_type = integration_result.get("failure_type", "INTEGRATION_FAILURE")
            if failure_type == "CHILD_FAILURE":
                failure_type = "INTEGRATION_FAILURE"
            return {
                "status": "failed", "failure_type": failure_type,
                "summary": integration_result.get("summary", "integration tasks did not resolve all conflicts"),
                "memory": memory, "children": combined_child_info,
                "integration_preflight": task["integration_preflight"],
                "integration_tasks": integration_info,
                "failure_evidence": _integration_failure_evidence(preflight_after_children),
            }
        child_info = combined_child_info
        preflight_before = preflight_after_children
        fit = {"decision": "execute", "reason": "bounded integration tasks completed before parent verification"}
        if isinstance(RUN.get("project_brain"), dict):
            refresh_project_brain_verified_state()
            integration_brain_projection = build_brain_projection(
                RUN["project_brain"], task, child_info, repo_snapshot, record=False,
            )
        integration_contract = build_integration_contract(
            task, contract, child_info, preflight_before, root=root, fit=fit,
            brain_projection=integration_brain_projection,
        )
        integration_contract["integration_tasks"] = integration_info

    begin_transaction(f"aggregate-{label}")
    global ACTIVE_TOOL_CONTRACT
    ACTIVE_TOOL_CONTRACT = {
        "goal": task["goal"], "requirements": task.get("done_when", []),
        "constraints": contract.get("constraints", []), "success_criteria": task.get("done_when", []),
        "task_id": label, "project_invariants": RUN.get("project_invariants", []),
    }
    ACTIVE_TOOL_CONTRACT.update(_active_plan_tool_contract_fields(task))
    context = (
        f"PROJECT BRAIN ALIGNMENT:\n{json.dumps(integration_contract.get('project_brain_alignment', {}), ensure_ascii=False)[:MAX_BRAIN_PROJECTION_CHARS]}\n"
        f"HIERARCHICAL INTEGRATION CONTRACT:\n{json.dumps(integration_contract, ensure_ascii=False)[:9000]}\n"
        f"REPOSITORY HINTS: {repository_hints(repo_snapshot, task.get('scope_hint'), max_chars=1800)}\n"
        "Inspect the real shared workspace. Use the verified child manifests and canonical project invariants. "
        "Resolve only the concrete integration conflicts listed by the preflight, then run executable verification. "
        "Do not request child chat histories. "
        + ("At ROOT explicitly verify fidelity against the authoritative Goal Contract." if root else "")
    )

    # There is no second integration orchestrator: after bounded integration
    # children, the existing parent Builder/evidence path verifies the result.
    builder = execute_agent_task(task["goal"], memory, role="Builder", task_id=label, extra_context=context)
    memory = builder.get("memory", memory)
    builder["integration_contract"] = integration_contract
    if builder["status"] != "done":
        preflight_after = run_integration_preflight(task, child_info, contract)
        task["integration_preflight"]["after"] = preflight_after
        _finish_parent_integration(task, passed=False, preflight=preflight_after)
        rollback_transaction(); RUN["integration_failures"] += 1
        failure_type = "ENVIRONMENT_ERROR" if builder["status"] == "provider_failure" else (
            "INTEGRATION_TOO_BROAD" if builder["status"] == "too_broad" else "INTEGRATION_FAILURE"
        )
        parent_failure_evidence = _integration_failure_evidence(preflight_after) + _worker_failure_evidence(builder)
        return {"status": "failed",
                "failure_type": failure_type, "summary": builder["summary"], "memory": memory,
                "builder": builder,
                "mutation_failures": _mutation_failure_records(builder),
                "failure_evidence": _compact_failure_evidence(_unique_failure_evidence(parent_failure_evidence)),
                "integration_preflight": task["integration_preflight"],
                "integration_milestones": builder.get("integration_milestones", []), "children": child_info}

    preflight_after = run_integration_preflight(task, child_info, contract)
    task["integration_preflight"]["after"] = preflight_after

    if preflight_after.get("passed"):
        falsifier = falsify_task(task, ACTIVE_TOOL_CONTRACT, memory, builder, repo_snapshot, context)
    else:
        falsifier = {"status": "skipped", "summary": "blocked by integration preflight", "tool_evidence": [],
                     "memory": memory}
    memory = falsifier.get("memory", memory)
    if falsifier.get("status") == "provider_failure":
        _finish_parent_integration(task, passed=False, preflight=preflight_after)
        rollback_transaction(); RUN["integration_failures"] += 1
        return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": falsifier.get("summary", ""),
                "memory": memory, "children": child_info, "integration_preflight": task["integration_preflight"]}
    browser = (
        optional_browser_check(
            task, ACTIVE_TOOL_CONTRACT,
            syntax_failures=_combined_syntax_validation_failures(builder, falsifier),
        )
        if preflight_after.get("passed") else None
    )
    gate = evidence_gate(builder, falsifier, browser, integration_preflight=preflight_after)
    verify_label = "ROOT VERIFIED" if root and gate["passed"] else ("ROOT VERIFY" if root else "VERIFY " + label)
    event(f"[{verify_label}] {'PASS' if gate['passed'] else 'FAIL'}",
          role="Quality Review", task=label, action="parent evidence gate")
    if not gate["passed"]:
        failure_type = "INTEGRATION_FAILURE" if not preflight_after.get("passed") else classify_failure(
            builder, gate, browser, falsifier,
        )
        integration_failure = not preflight_after.get("passed")
        if failure_type != "IMPLEMENTATION_ERROR" and not integration_failure:
            _finish_parent_integration(task, passed=False, preflight=preflight_after)
            rollback_transaction(); RUN["integration_failures"] += 1
            return {"status": "failed", "failure_type": failure_type,
                    "summary": "parent integration failed evidence gate", "memory": memory, "gate": gate,
                    "children": child_info, "integration_preflight": task["integration_preflight"],
                    "failure_evidence": _integration_failure_evidence(preflight_after)}

        # Parent integration follows the same obvious implementation-error route as a leaf:
        # focused Repairer -> fresh deterministic verification. The Falsifier is not rerun.
        integration_recovery_needed = True
        integration_context = (
            f"PROJECT BRAIN ALIGNMENT:\n{json.dumps(integration_contract.get('project_brain_alignment', {}), ensure_ascii=False)[:MAX_BRAIN_PROJECTION_CHARS]}\n"
            f"HIERARCHICAL INTEGRATION CONTRACT:\n{json.dumps(integration_contract, ensure_ascii=False)[:9000]}\n"
            f"CURRENT PREFLIGHT:\n{json.dumps(preflight_after, ensure_ascii=False)[:4500]}\n"
            f"VERIFIED CHILD MANIFESTS:\n{json.dumps(child_info, ensure_ascii=False)[:6000]}\n"
            "Repair only the concrete integration defect demonstrated by the preflight/evidence. "
            "Inspect the current shared workspace and run fresh executable verification."
        )
        current_gate = gate
        current_browser = browser
        current_preflight = preflight_after
        repaired = None
        integration_repair_mutation_failures = []
        for _ in range(MAX_REPAIRS_PER_LEAF):
            repaired = repair_task(task, ACTIVE_TOOL_CONTRACT, current_gate["deterministic_failures"],
                                   memory, integration_context)
            memory = repaired["memory"]
            integration_repair_mutation_failures = _merge_mutation_failure_records(
                integration_repair_mutation_failures, _mutation_failure_records(repaired),
            )
            if repaired["status"] == "provider_failure":
                _finish_parent_integration(task, passed=False, preflight=current_preflight)
                rollback_transaction(); RUN["integration_failures"] += 1
                return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR",
                        "summary": repaired["summary"], "memory": memory, "children": child_info,
                        "repairer": repaired, "mutation_failures": integration_repair_mutation_failures,
                        "failure_evidence": _compact_failure_evidence(integration_repair_mutation_failures)}
            if repaired["status"] == "too_broad":
                _finish_parent_integration(task, passed=False, preflight=current_preflight)
                rollback_transaction(); RUN["integration_failures"] += 1
                return {"status": "failed", "failure_type": "INTEGRATION_TOO_BROAD",
                        "summary": repaired["summary"], "memory": memory, "children": child_info,
                        "integration_preflight": task["integration_preflight"],
                        "repairer": repaired,
                        "mutation_failures": integration_repair_mutation_failures,
                        "failure_evidence": _compact_failure_evidence(integration_repair_mutation_failures)}
            current_preflight = run_integration_preflight(task, child_info, contract)
            task["integration_preflight"]["after"] = current_preflight
            current_browser = (
                optional_browser_check(
                    task, ACTIVE_TOOL_CONTRACT,
                    syntax_failures=_combined_syntax_validation_failures(repaired),
                )
                if current_preflight.get("passed") else None
            )
            current_gate = evidence_gate(repaired, None, current_browser,
                                         integration_preflight=current_preflight)
            verify_label = "ROOT VERIFIED" if root and current_gate["passed"] else ("ROOT VERIFY" if root else "VERIFY " + label)
            event(f"[{verify_label}] "
                  f"{'PASS' if current_gate['passed'] else 'FAIL'} (fresh)",
                  role="Quality Review", task=label, action="fresh parent verification")
            if current_gate["passed"]:
                _finish_parent_integration(
                    task, passed=True, recovered=integration_recovery_needed, preflight=current_preflight,
                )
                changed = commit_transaction()
                remember_verified_outcome(task, contract, repaired["summary"], changed)
                return {"status": "done", "summary": repaired["summary"], "memory": memory,
                        "changed_files": changed, "gate": current_gate, "children": child_info,
                        "integration_preflight": task["integration_preflight"],
                        "integration_milestones": task["integration_preflight"].get("milestones", []),
                        "integration_outcome": task.get("integration_outcome")}
            failure_type = "INTEGRATION_FAILURE" if not current_preflight.get("passed") else classify_failure(
                repaired, current_gate, current_browser, None,
            )
            if failure_type != "IMPLEMENTATION_ERROR" and current_preflight.get("passed"):
                _finish_parent_integration(task, passed=False, preflight=current_preflight)
                rollback_transaction(); RUN["integration_failures"] += 1
                return {"status": "failed", "failure_type": failure_type,
                        "summary": "fresh parent verification failed", "memory": memory, "gate": current_gate,
                        "children": child_info, "integration_preflight": task["integration_preflight"],
                        "repairer": repaired, "mutation_failures": integration_repair_mutation_failures,
                        "failure_evidence": _compact_failure_evidence(integration_repair_mutation_failures)}
        _finish_parent_integration(task, passed=False, preflight=current_preflight)
        rollback_transaction(); RUN["integration_failures"] += 1
        terminal_failure_type = "INTEGRATION_FAILURE" if not current_preflight.get("passed") else "IMPLEMENTATION_ERROR"
        return {"status": "failed", "failure_type": terminal_failure_type,
                "summary": "parent integration failed after repair limit", "memory": memory, "gate": current_gate,
                "children": child_info, "integration_preflight": task["integration_preflight"],
                "repairer": repaired, "mutation_failures": integration_repair_mutation_failures,
                "failure_evidence": _compact_failure_evidence(_unique_failure_evidence(
                    _integration_failure_evidence(task["integration_preflight"].get("after"))
                    + current_gate.get("deterministic_failures", [])
                    + integration_repair_mutation_failures,
                ))}
    changed = commit_transaction()
    remember_verified_outcome(task, contract, builder["summary"], changed)
    _finish_parent_integration(
        task, passed=True, recovered=integration_recovery_needed, preflight=preflight_after,
    )
    return {"status": "done", "summary": builder["summary"], "memory": memory, "changed_files": changed,
            "gate": gate, "falsifier": falsifier, "browser": browser, "children": child_info,
            "integration_preflight": task["integration_preflight"],
            "integration_milestones": builder.get("integration_milestones", []),
            "integration_outcome": task.get("integration_outcome")}


def _can_expand(depth):
    return depth < MAX_DEPTH and RUN.get("tasks_created", 0) + 2 <= MAX_TOTAL_TASKS


def _record_terminal_too_broad(task, result):
    """Persist a depth-limit overflow so its parent can backtrack once."""
    if not isinstance(task, dict) or not isinstance(result, dict):
        return False
    if int(task.get("depth", 0) or 0) < MAX_DEPTH:
        return False
    if result.get("failure_type") != "TASK_TOO_BROAD" and str(result.get("status", "")).casefold() != "too_broad":
        return False
    if not _has_positive_scope_evidence(task, result):
        return False
    if task.get("terminal_too_broad") is None:
        task["terminal_too_broad"] = {
            "status": str(result.get("status", "too_broad")),
            "failure_type": str(result.get("failure_type", "TASK_TOO_BROAD")),
            "summary": compact_text(result.get("summary", ""), MAX_NODE_SUMMARY_CHARS),
            "failure_evidence": _failure_evidence_from_result(result),
            "depth": int(task.get("depth", 0) or 0),
        }
        record_run_event(
            "terminal_too_broad", task_id=task.get("id"), depth=task.get("depth", 0),
            failure_evidence=task["terminal_too_broad"]["failure_evidence"],
        )
    result["terminal_too_broad"] = True
    return True


def _mark_task_result(task, result, *, count=True):
    status = str(result.get("status", "failed"))
    task["status"] = status
    task["verification_status"] = "passed" if status == "done" else "failed"
    task["summary"] = compact_text(result.get("summary", ""), MAX_NODE_SUMMARY_CHARS)
    if result.get("changed_files"):
        task["changed_files"] = list(result["changed_files"])
    if count:
        if status == "done":
            attach_verified_manifest(task, result)
            RUN["verified_nodes"] += 1
            if str(task.get("id")) == "ROOT":
                RUN["root_verified"] = True
        else:
            diagnosis = _record_task_failure(task, result, phase="node_result")
            if diagnosis is not None:
                result.setdefault("failure_diagnosis", diagnosis)
            RUN["failed_nodes"] += 1
    update_task_ledger(task)


def _is_terminal_too_broad_child(child, result):
    if not isinstance(child, dict) or not isinstance(result, dict):
        return False
    diagnosis = result.get("failure_diagnosis")
    if not isinstance(diagnosis, dict):
        diagnosis = child.get("failure_diagnosis")
    if int(child.get("depth", 0) or 0) < MAX_DEPTH:
        return False
    too_broad_marker = (
        result.get("failure_type") == "TASK_TOO_BROAD"
        or str(result.get("status", "")).casefold() == "too_broad"
    )
    budget_scope = (
        _is_execution_budget_exhausted(result)
        and isinstance(diagnosis, dict)
        and diagnosis.get("category") == "scope_too_broad"
    )
    return (too_broad_marker or budget_scope) and _has_positive_scope_evidence(child, result)


def _materialize_alternative_children(task, specs, attempt):
    branch_id = f"alternative-{attempt}"
    children = []
    for index, spec in enumerate(list(specs or [])[:MAX_CHILDREN], 1):
        child_id = (
            f"alt{attempt}.{index}" if task.get("id") == "ROOT"
            else f"{task['id']}.alt{attempt}.{index}"
        )
        child = make_task(
            child_id, spec["goal"], int(task.get("depth", 0)) + 1, task.get("id"),
            spec.get("done_when", []), spec.get("scope_hint", []),
        )
        plan = current_approved_change_plan()
        if isinstance(plan, dict):
            attach_approved_plan_to_task(child, plan, spec.get("plan_node_ids"))
            child["plan_requirement_ids"] = list(spec.get("requirement_ids", []))
            child["plan_impact_ids"] = list(spec.get("impact_ids", []))
            child["plan_evidence_ids"] = list(spec.get("evidence_ids", []))
            child["verification_only"] = bool(spec.get("verification_only"))
        TASKS[child_id] = child
        task.setdefault("children", []).append(child_id)
        RUN["tasks_created"] += 1
        RUN["max_depth"] = max(RUN.get("max_depth", 0), child["depth"])
        update_task_ledger(child)
        children.append(child)
    _record_decomposition_branch(task, specs, children, kind="alternative", branch_id=branch_id)
    return children, branch_id


def _backtrack_decomposition(task, depth, contract, memory, repo_snapshot, parent_summary,
                             dependency_summaries, failed_child, failed_result, fit_decider,
                             leaf_executor, aggregator):
    """Try at most two genuinely different child boundaries for one failed parent."""
    if task.get("kind") == "integration":
        # Integration concerns have their own deterministic conflict grouping;
        # do not send them through the implementation-only v3 alternative
        # decomposition search.
        return None
    if not _is_terminal_too_broad_child(failed_child, failed_result):
        return None
    attempts = task.setdefault("decomposition_alternatives", [])
    if len(attempts) >= MAX_DECOMPOSITION_ALTERNATIVES:
        task["decomposition_search_exhausted"] = True
        return None
    if not _can_expand(depth):
        task["decomposition_backtrack_blocked_reason"] = "hard recursion/task budget reached"
        return None

    attempt_number = len(attempts) + 1
    task["decomposition_backtracks"] = int(task.get("decomposition_backtracks", 0) or 0) + 1
    terminal_label = (
        EXECUTION_BUDGET_EXHAUSTED
        if _is_execution_budget_exhausted(failed_result) else "TASK_TOO_BROAD"
    )
    event(
        f"[BACKTRACK {task['id']}] terminal {terminal_label} -> alternative decomposition #{attempt_number}",
        role="Coordinator", task=task["id"], action="decomposition backtracking",
    )
    record_run_event(
        "decomposition_backtrack", task_id=task.get("id"), depth=task.get("depth", depth),
        attempt=attempt_number, failed_child_id=failed_child.get("id"),
        terminal_failure=_failure_evidence_from_result(failed_result),
        failed_decompositions=compact_failed_decompositions(task),
    )
    try:
        specs = decompose_alternative_task(
            task, contract, repo_snapshot, parent_summary, dependency_summaries, failed_result,
        )
    except ProviderError as exc:
        attempts.append({
            "attempt": attempt_number, "status": "provider_failure", "children": [],
            "error": compact_text(str(exc), 300), "failed_child_id": str(failed_child.get("id", "")),
        })
        task["decomposition_backtrack_blocked_reason"] = "alternative decomposition provider failure"
        record_run_event(
            "alternative_decomposition_failed", task_id=task.get("id"), attempt=attempt_number,
            failure_type="ENVIRONMENT_ERROR", summary=str(exc),
        )
        recompute_search_metrics()
        return None
    if len(specs) < 2:
        attempts.append({
            "attempt": attempt_number, "status": "rejected", "children": [],
            "reason": "no materially different child boundaries were produced",
            "failed_child_id": str(failed_child.get("id", "")),
        })
        if len(attempts) >= MAX_DECOMPOSITION_ALTERNATIVES:
            task["decomposition_search_exhausted"] = True
        recompute_search_metrics()
        return None

    children, branch_id = _materialize_alternative_children(task, specs, attempt_number)
    attempts.append({
        "attempt": attempt_number, "branch_id": branch_id, "status": "running",
        "children": [_compact_decomposition_spec(spec) for spec in specs],
        "child_ids": [child["id"] for child in children],
        "failed_child_id": str(failed_child.get("id", "")),
        "terminal_failure": {
            "summary": compact_text(failed_result.get("summary", ""), MAX_NODE_SUMMARY_CHARS),
            "failure_evidence": _failure_evidence_from_result(failed_result),
        },
    })
    RUN["splits"] += 1
    recompute_search_metrics()
    return _execute_children(
        task, children, depth, contract, memory, repo_snapshot, parent_summary, dependency_summaries,
        fit_decider, leaf_executor, aggregator,
    )


def _execute_children(task, children, depth, contract, memory, repo_snapshot, parent_summary,
                      dependency_summaries, fit_decider, leaf_executor, aggregator):
    """Run sibling milestones sequentially, then integrate only verified results."""
    completed = []
    dependencies = list(dependency_summaries or [])
    child_parent = f"{task.get('goal', '')} | {compact_text(task.get('summary') or '(parent is being decomposed)', 500)}"
    for child in children:
        result = solve_task(
            child, depth + 1, contract, memory, repo_snapshot,
            parent_summary=child_parent, dependency_summaries=dependencies,
            fit_decider=fit_decider, leaf_executor=leaf_executor, aggregator=aggregator,
        )
        memory = result.get("memory", memory)
        completed.append({"task": child, "result": result})
        if result.get("status") == "done":
            attach_verified_manifest(child, result)
        dependencies.append({
            "task_id": child["id"], "goal": child["goal"], "status": result.get("status", "failed"),
            "summary": compact_text(result.get("summary", ""), MAX_NODE_SUMMARY_CHARS),
            "changed_files": _compact_manifest_values(result.get("changed_files", []), 12, 140),
            "integration_manifest": compact_manifest(
                result.get("integration_manifest") or child.get("integration_manifest")
            ),
            "evidence": compact_evidence_summary(result),
        })
        if result.get("status") != "done":
            parent_result = {
                "status": "failed", "summary": compact_text(
                f"child {child['id']} failed: {result.get('summary', '')}", MAX_NODE_SUMMARY_CHARS,
                ), "memory": memory,
                "failure_type": result.get("failure_type", "CHILD_FAILURE"), "children": completed,
            }
            _update_resplit_outcome(task, children, completed, parent_result)
            _record_task_failure(task, parent_result, phase="child_result")
            alternative = _backtrack_decomposition(
                task, depth, contract, memory, repo_snapshot, parent_summary, dependency_summaries,
                child, result, fit_decider, leaf_executor, aggregator,
            )
            if alternative is not None:
                return alternative
            if task.get("decomposition_search_exhausted"):
                parent_result["decomposition_search_exhausted"] = True
                _record_task_failure(task, parent_result, phase="decomposition_search")
            _mark_task_result(task, parent_result)
            return parent_result

    aggregate_fn = aggregator or (
        _aggregate_integration_children if task.get("kind") == "integration" else aggregate_task
    )
    try:
        aggregate = aggregate_fn(task, contract, completed, memory, repo_snapshot, root=(task["id"] == "ROOT"))
    except ProviderError as exc:
        aggregate = {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": str(exc), "memory": memory}
    aggregate["memory"] = aggregate.get("memory", memory)
    _mark_task_result(task, aggregate)
    _update_resplit_outcome(task, children, completed, aggregate)
    if task["status"] == "done":
        event(f"[DONE {task['id']}]", task=task["id"], action="aggregated verified node")
    else:
        event(f"[FAILED {task['id']}]", task=task["id"], action="aggregation failed")
    return aggregate


def _resplit_too_broad(task, depth, contract, memory, repo_snapshot, parent_summary, dependency_summaries,
                       leaf_result, fit_decider, leaf_executor, aggregator):
    if not _can_expand(depth):
        return None
    is_integration = task.get("kind") == "integration"
    if not is_integration and not _has_positive_scope_evidence(task, leaf_result):
        return None
    RUN["re_splits"] += 1
    evidence = list(leaf_result.get("failure_evidence", []))
    if not evidence:
        evidence = [{"kind": "task_status", "result": leaf_result.get(
            "summary", EXECUTION_BUDGET_EXHAUSTED if _is_execution_budget_exhausted(leaf_result) else "TASK_TOO_BROAD",
        )}]
    task["failure_evidence"] = evidence[-6:]
    trigger = (
        "INTEGRATION_TOO_BROAD" if is_integration else
        (EXECUTION_BUDGET_EXHAUSTED if _is_execution_budget_exhausted(leaf_result) else "TASK_TOO_BROAD")
    )
    event(f"[RE-SPLIT {task['id']}] {trigger} -> smaller granularity", role="Coordinator",
          task=task["id"], action="re-decompose")
    try:
        decision = (
            fit_decider(task, depth, contract, repo_snapshot, parent_summary, dependency_summaries, True)
            if fit_decider else decide_task_fit(
                task, depth, contract, repo_snapshot, parent_summary, dependency_summaries, force_smaller=True,
            )
        )
    except ProviderError as exc:
        return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": str(exc), "memory": memory}
    # A proven capacity failure is stronger than a second optimistic EXECUTE
    # response. Ask for fit evidence, then force the smaller decomposition while
    # recursion and task budgets remain available.
    if str((decision or {}).get("decision", "")).lower() != "split":
        event(f"[FIT {task['id']}] SPLIT (forced after {trigger})", role="Coordinator",
              task=task["id"], action="smaller granularity")
    try:
        children = decompose_task(
            task, contract, repo_snapshot, parent_summary, dependency_summaries, force_smaller=True,
        )
    except ProviderError as exc:
        return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": str(exc), "memory": memory}
    if len(children) < 2:
        return None
    if is_integration:
        task["integration_too_broad"] = True
        task["integration_resplit_attempts"] = int(task.get("integration_resplit_attempts", 0) or 0) + 1
        task["integration_split_boundary"] = True
    _register_resplit(task, leaf_result, trigger, decision)
    RUN["splits"] += 1
    return _execute_children(
        task, children, depth, contract, memory, repo_snapshot, parent_summary, dependency_summaries,
        fit_decider, leaf_executor, aggregator,
    )


def _resplit_after_leaf_failure(task, depth, contract, memory, repo_snapshot, parent_summary,
                                dependency_summaries, leaf_result, fit_decider, leaf_executor, aggregator):
    """Give a repeated deterministic leaf failure one bounded capacity probe.

    A normal implementation failure is not automatically a reason to split.  We
    ask the same fit decision with the concrete failure evidence and only
    decompose when that decision says the focused node is too large.  The
    ``force_smaller`` hint makes the previous failed execution part of the
    model-visible fit evidence without turning every failure into recursion.
    """
    if not _can_expand(depth) or leaf_result.get("failure_type") != "IMPLEMENTATION_ERROR":
        return None
    evidence = list(leaf_result.get("failure_evidence", []))
    if not evidence:
        return None
    task["failure_evidence"] = evidence[-6:]
    event(f"[CAPACITY PROBE {task['id']}] deterministic failure -> evaluate smaller granularity",
          role="Coordinator", task=task["id"], action="capacity probe")
    try:
        decision = (
            fit_decider(task, depth, contract, repo_snapshot, parent_summary, dependency_summaries, True)
            if fit_decider else decide_task_fit(
                task, depth, contract, repo_snapshot, parent_summary, dependency_summaries, force_smaller=True,
            )
        )
    except ProviderError as exc:
        return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": str(exc), "memory": memory}
    if str((decision or {}).get("decision", "")).lower() != "split":
        event(f"[NO RE-SPLIT {task['id']}] fit decision kept the failure at current granularity",
              role="Coordinator", task=task["id"], action="route failure diagnosis")
        return None
    try:
        children = decompose_task(
            task, contract, repo_snapshot, parent_summary, dependency_summaries, force_smaller=True,
        )
    except ProviderError as exc:
        return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": str(exc), "memory": memory}
    if len(children) < 2:
        return None
    _register_resplit(task, leaf_result, "IMPLEMENTATION_ERROR", decision)
    RUN["re_splits"] += 1
    RUN["splits"] += 1
    return _execute_children(
        task, children, depth, contract, memory, repo_snapshot, parent_summary, dependency_summaries,
        fit_decider, leaf_executor, aggregator,
    )


def solve_task(task, depth, contract, memory, repo_snapshot=None, parent_summary="", dependency_summaries=None,
               fit_decider=None, leaf_executor=None, aggregator=None):
    """Fit one node, execute one leaf if it fits, and recurse only on evidence."""
    dependency_summaries = list(dependency_summaries or [])
    repo_snapshot = repo_snapshot or inspect_repository()
    task["status"] = "running"
    RUN["max_depth"] = max(RUN.get("max_depth", 0), depth)
    if str(task.get("id", "")) == "ROOT" and "TASK_FIT" not in RUN.setdefault("control_flow", []):
        RUN["control_flow"].append("TASK_FIT")
    update_task_ledger(task)
    label = task["id"]
    if label == "ROOT":
        event(f"[ROOT] {compact_text(task['goal'], 180)}", role="Coordinator", task="ROOT", action="task fit")
    else:
        event(f"[TASK {label}] {compact_text(task['goal'], 160)}", role="Coordinator", task=label, action="task fit")

    can_split = _can_expand(depth)
    if can_split:
        try:
            decision = (
                fit_decider(task, depth, contract, repo_snapshot, parent_summary, dependency_summaries, False)
                if fit_decider else decide_task_fit(
                    task, depth, contract, repo_snapshot, parent_summary, dependency_summaries,
                )
            )
        except ProviderError as exc:
            result = {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": str(exc), "memory": memory}
            _mark_task_result(task, result)
            event(f"[FAILED {label}] provider/environment error; no decomposition", task=label)
            return result
    else:
        decision = {"decision": "execute", "reason": "hard recursion/task budget reached"}
    decision_name = str((decision or {}).get("decision", "execute")).lower()
    if task.get("fit_before_execution") is None:
        task["fit_before_execution"] = {
            "decision": decision_name.upper(),
            "reason": compact_text((decision or {}).get("reason", ""), 500),
        }
        update_task_ledger(task)
    event(f"[FIT {label}] {decision_name.upper()}", role="Coordinator", task=label, action="granularity decision")

    if decision_name == "split" and can_split:
        try:
            children = decompose_task(task, contract, repo_snapshot, parent_summary, dependency_summaries)
        except ProviderError as exc:
            result = {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": str(exc), "memory": memory}
            _mark_task_result(task, result)
            event(f"[FAILED {label}] provider/environment error; no decomposition", task=label)
            return result
        if len(children) >= 2:
            RUN["splits"] += 1
            return _execute_children(
                task, children, depth, contract, memory, repo_snapshot, parent_summary, dependency_summaries,
                fit_decider, leaf_executor, aggregator,
            )

    executor = leaf_executor or execute_leaf
    try:
        leaf = executor(task, contract, memory, repo_snapshot, parent_summary, dependency_summaries)
    except ProviderError as exc:
        leaf = {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": str(exc), "memory": memory}
    memory = leaf.get("memory", memory)
    is_too_broad = (
        (
            leaf.get("status") == "too_broad"
            or leaf.get("failure_type") == "TASK_TOO_BROAD"
        )
        and _has_positive_scope_evidence(task, leaf)
    ) or (
        task.get("kind") == "integration"
        and leaf.get("failure_type") == "INTEGRATION_TOO_BROAD"
    )
    if is_too_broad:
        _record_terminal_too_broad(task, leaf)
        _record_task_failure(task, leaf, phase="leaf")
        resplit = _resplit_too_broad(
            task, depth, contract, memory, repo_snapshot, parent_summary, dependency_summaries,
            leaf, fit_decider, leaf_executor, aggregator,
        )
        if resplit is not None:
            return resplit
    elif (
        _is_execution_budget_exhausted(leaf)
        or leaf.get("status") == "too_broad"
        or leaf.get("failure_type") in {"IMPLEMENTATION_ERROR", "TASK_TOO_BROAD"}
    ):
        # The focused loop reports an observation. Record the final evidence
        # and diagnosis first, then let the diagnosis select one existing
        # recovery mechanism regardless of the raw failure origin.
        diagnosis = _record_task_failure(task, leaf, phase="leaf")
        leaf["failure_diagnosis"] = diagnosis
        recovery = route_recovery_from_diagnosis(
            task, contract, leaf, diagnosis, memory, repo_snapshot,
            parent_summary, dependency_summaries,
        )
        if recovery is not None:
            # A started strategy search owns this failure route. In particular,
            # a failed or unavailable search must not fall through to another
            # automatic split or a second strategy search.
            leaf = recovery
            memory = leaf.get("memory", memory)
        elif diagnosis and diagnosis.get("category") == "scope_too_broad":
            if _is_execution_budget_exhausted(leaf):
                resplit = _resplit_too_broad(
                    task, depth, contract, memory, repo_snapshot, parent_summary, dependency_summaries,
                    leaf, fit_decider, leaf_executor, aggregator,
                )
            else:
                resplit = _resplit_after_leaf_failure(
                    task, depth, contract, memory, repo_snapshot, parent_summary, dependency_summaries,
                    leaf, fit_decider, leaf_executor, aggregator,
                )
            if resplit is not None:
                return resplit

    leaf["memory"] = memory
    _mark_task_result(task, leaf)
    if task["status"] == "done":
        event(f"[DONE {label}]", task=label, action="verified leaf")
    else:
        event(f"[FAILED {label}]", task=label, action="leaf failed")
    return leaf


# ---------------------------------------------------------------------------
# RUN MODES / FAIR CONTROL
# ---------------------------------------------------------------------------

def begin_durable_run(contract):
    global ACTIVE_CONTRACT, ACTIVE_TOOL_CONTRACT
    ACTIVE_CONTRACT = dict(contract)
    ACTIVE_TOOL_CONTRACT = dict(contract)
    store = get_memory_store()
    if store and RUN_ID:
        try:
            store.begin_run(RUN_ID, str(contract.get("goal") or "coding task"), contract)
        except Exception:
            pass


def run_baseline_request(user_text, memory, contract_override=None, repo_snapshot=None, reset=True, finish=True,
                         leaf_executor=None, interactive=True):
    if reset:
        reset_run("baseline")
    elif RUN.get("mode") != "auto":
        RUN["mode"] = "baseline"
    # Baseline remains the pre-v15 comparable path.  A caller reusing a run
    # object must not accidentally inherit recursive Project Brain state.
    RUN.pop("project_brain", None)
    try:
        contract = contract_override or get_goal_contract(user_text, interactive=interactive)
    except ProviderError as exc:
        result = {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": str(exc), "memory": memory}
        if finish:
            finish_metrics("failed")
        return result, memory
    if _contract_needs_clarification(contract):
        result_status = "clarification_required" if contract.get("terminal_state") == "CLARIFICATION_REQUIRED" else "needs_clarification"
        result = {
            "status": result_status, "terminal_state": contract.get("terminal_state"),
            "summary": contract.get("question", ""),
            "clarification_questions": contract.get("questions", []), "memory": memory,
        }
        if finish:
            finish_metrics(result_status)
        return result, memory
    repo_snapshot = repo_snapshot or inspect_repository()
    # Baseline keeps the pre-Stage-2 coding condition. Only cheap project-mode
    # bookkeeping is shared; no Task Brain reaches its Worker execution.
    classification = classify_project_mode(user_text, repo_snapshot=repo_snapshot)
    _record_project_mode(classification)
    RUN["baseline_stage2_scope"] = "PROJECT_MODE_BOOKKEEPING_ONLY"
    begin_durable_run(contract)
    root = root_task_from_contract(contract)
    approved_plan = current_approved_change_plan()
    if isinstance(approved_plan, dict):
        # Direct frozen-baseline runs never create this state.  An auto run may
        # already have obtained approval before routing to the shared leaf.
        attach_approved_plan_to_task(root, approved_plan)
    TASKS["ROOT"] = root
    RUN["tasks_created"] = 1
    update_task_ledger(root)
    print("[MODE] baseline")
    # Crucial control: the exact same execute_leaf engine as recursive leaves.
    result = (leaf_executor or execute_leaf)(root, contract, memory, repo_snapshot, "", [])
    _mark_task_result(root, result)
    if finish:
        finish_metrics("done" if root["status"] == "done" else "failed")
    return result, result.get("memory", memory)


def run_recursive_request(user_text, memory, interactive=True, contract_override=None, repo_snapshot=None,
                          fit_decider=None, leaf_executor=None, aggregator=None, reset=True, finish=True,
                          initial_decision=None, specification_override=None,
                          understanding_override=None, impact_planning_override=None,
                          impact_planner_structured_call=None,
                          impact_challenger_structured_call=None,
                          impact_reviser_structured_call=None,
                          plan_approval_selector=None, plan_approval_answer_reader=None,
                          terminal_available=None):
    if reset:
        reset_run("recursive")
    elif RUN.get("mode") != "auto":
        RUN["mode"] = "recursive"
    supplied_contract = contract_override is not None
    try:
        contract = contract_override or get_goal_contract(user_text, interactive=interactive)
    except ProviderError as exc:
        event(f"[ERROR] {exc}", role="Coordinator", task="ROOT", action="provider failure")
        result = {"status": "failed", "failure_type": "ENVIRONMENT_ERROR",
                  "summary": str(exc), "memory": memory}
        if finish:
            finish_metrics("failed")
        return result, memory
    if _contract_needs_clarification(contract):
        result_status = "clarification_required" if contract.get("terminal_state") == "CLARIFICATION_REQUIRED" else "needs_clarification"
        if finish:
            finish_metrics(result_status)
        return {
            "status": result_status, "terminal_state": contract.get("terminal_state"),
            "summary": contract.get("question", ""),
            "clarification_questions": contract.get("questions", []), "memory": memory,
        }, memory
    repo_snapshot = repo_snapshot or inspect_repository()
    # Stage 2 is a deterministic gate before root fit or decomposition.
    try:
        understanding = understanding_override or prepare_stage2_context(
            user_text, contract, repo_snapshot=repo_snapshot, interactive=interactive,
            supplied_contract=supplied_contract,
            specification_override=specification_override,
        )
    except ProviderError as exc:
        event(f"[ERROR] {exc}", role="Specifier", task="ROOT", action="specification provider failure")
        result = {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": str(exc), "memory": memory}
        if finish:
            finish_metrics("failed")
        return result, memory
    if understanding.get("status") != "ready":
        result = dict(understanding)
        result["memory"] = memory
        if finish:
            finish_metrics(result.get("status", "failed"))
        return result, memory
    contract = understanding.get("contract", contract)
    begin_durable_run(contract)
    try:
        impact_planning = impact_planning_override or prepare_stage3_context(
            understanding, contract, interactive=interactive,
            terminal_available=terminal_available,
            planner_structured_call=impact_planner_structured_call,
            challenger_structured_call=impact_challenger_structured_call,
            reviser_structured_call=impact_reviser_structured_call,
            approval_selector=plan_approval_selector,
            approval_answer_reader=plan_approval_answer_reader,
        )
    except ProviderError as exc:
        result = {
            "status": "failed", "failure_type": "ENVIRONMENT_ERROR",
            "summary": str(exc), "memory": memory,
        }
        if finish:
            finish_metrics("failed")
        return result, memory
    if impact_planning.get("status") != "ready":
        result = dict(impact_planning)
        result["memory"] = memory
        if finish:
            finish_metrics(result.get("status", "failed"))
        return result, memory
    contract = impact_planning.get("contract", contract)
    root = root_task_from_contract(contract)
    approved_plan = current_approved_change_plan()
    if isinstance(approved_plan, dict):
        attach_approved_plan_to_task(root, approved_plan)
    TASKS["ROOT"] = root
    RUN["tasks_created"] = 1
    routed_fit = fit_decider
    if initial_decision is not None:
        def routed_fit(task, depth, fit_contract, fit_repo, parent, deps, force_smaller):
            if task.get("id") == "ROOT" and not force_smaller:
                return initial_decision
            if fit_decider:
                return fit_decider(task, depth, fit_contract, fit_repo, parent, deps, force_smaller)
            return decide_task_fit(task, depth, fit_contract, fit_repo, parent, deps, force_smaller=force_smaller)
    result = solve_task(root, 0, contract, memory, repo_snapshot,
                        fit_decider=routed_fit, leaf_executor=leaf_executor, aggregator=aggregator)
    print(f"[FINAL] {'done' if result['status'] == 'done' else 'failed'}")
    if finish:
        finish_metrics("done" if result["status"] == "done" else "failed")
    return result, result.get("memory", memory)


def run_auto_request(user_text, memory, interactive=True):
    reset_run("auto")
    print("[GOAL] understanding before routing")
    try:
        contract = get_goal_contract(user_text, interactive=interactive)
    except ProviderError as exc:
        event(f"[ERROR] {exc}", role="Coordinator", task="ROOT", action="goal provider failure")
        finish_metrics("failed")
        return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": str(exc)}, memory
    if _contract_needs_clarification(contract):
        result_status = "clarification_required" if contract.get("terminal_state") == "CLARIFICATION_REQUIRED" else "needs_clarification"
        finish_metrics(result_status)
        return {
            "status": result_status, "terminal_state": contract.get("terminal_state"),
            "summary": contract.get("question", ""),
            "clarification_questions": contract.get("questions", []),
        }, memory
    repo_snapshot = inspect_repository()
    try:
        understanding = prepare_stage2_context(
            user_text, contract, repo_snapshot=repo_snapshot, interactive=interactive,
            supplied_contract=False,
        )
    except ProviderError as exc:
        event(f"[ERROR] {exc}", role="Coordinator", task="ROOT", action="Stage 2 provider failure")
        finish_metrics("failed")
        return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": str(exc)}, memory
    if understanding.get("status") != "ready":
        finish_metrics(understanding.get("status", "failed"))
        return understanding, memory
    contract = understanding.get("contract", contract)
    recon = understanding.get("reconnaissance", {})
    print(
        f"[PROJECT MODE] {understanding.get('project_mode')} | "
        f"recon={recon.get('status')} evidence={len(recon.get('evidence', []))}"
    )
    begin_durable_run(contract)
    try:
        impact_planning = prepare_stage3_context(
            understanding, contract, interactive=interactive,
        )
    except ProviderError as exc:
        event(f"[ERROR] {exc}", role="ImpactPlanner", task="ROOT", action="impact planning provider failure")
        finish_metrics("failed")
        return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": str(exc)}, memory
    if impact_planning.get("status") != "ready":
        finish_metrics(impact_planning.get("status", "failed"))
        return impact_planning, memory
    contract = impact_planning.get("contract", contract)
    root = root_task_from_contract(contract)
    approved_plan = current_approved_change_plan()
    if isinstance(approved_plan, dict):
        attach_approved_plan_to_task(root, approved_plan)
    # Auto is explicitly decided after Stage 2 Task Brain preparation.
    try:
        decision = decide_task_fit(root, 0, contract, repo_snapshot)
    except ProviderError as exc:
        event(f"[ERROR] {exc}", role="Coordinator", task="ROOT", action="routing provider failure")
        finish_metrics("failed")
        return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": str(exc)}, memory
    selected = "baseline" if decision["decision"] == "execute" else "recursive"
    RUN["auto_selected_mode"] = selected
    print(f"[AUTO MODE] {selected}")
    if selected == "baseline":
        result, memory = run_baseline_request(user_text, memory, contract_override=contract,
                                              repo_snapshot=repo_snapshot, reset=False, finish=False,
                                              interactive=False)
    else:
        result, memory = run_recursive_request(user_text, memory, interactive=False, contract_override=contract,
                                               repo_snapshot=repo_snapshot, reset=False, finish=False,
                                               initial_decision=decision,
                                               specification_override=understanding.get("specification"),
                                               understanding_override=understanding,
                                               impact_planning_override=impact_planning)
    finish_metrics("done" if result.get("status") == "done" else result.get("status", "failed"))
    return result, memory


# ---------------------------------------------------------------------------
# SELF TEST
# ---------------------------------------------------------------------------

def _mock_contract():
    return {"status": "ready", "goal": "Build hard mock", "requirements": ["a", "b", "c"],
            "constraints": ["local"], "success_criteria": ["verified"], "original_goal": "Build hard mock"}


def run_self_test(install_browser=False):
    global WORKSPACE
    print("[SELF TEST]")
    with tempfile.TemporaryDirectory(prefix="mini_hivo_selftest_", ignore_cleanup_errors=True) as tmp:
        WORKSPACE = Path(tmp)
        memory = load_memory()
        contract = _mock_contract()
        repo = inspect_repository()
        reset_run("recursive")
        expanded_specification = normalize_project_specification(
            contract["original_goal"], contract,
            {
                "root_goal": contract["goal"],
                "user_visible_behavior": ["the mock project exposes verified outcomes"],
                "major_functional_areas": ["mock loop behavior", "mock persistence behavior"],
                "major_system_components": ["mock loop owner"],
                "state_ownership": ["mock state has one authoritative owner"],
                "interaction_model": ["mock interaction triggers the loop"],
                "ui_ux_expectations": [], "persistence_requirements": [],
                "important_edge_cases": ["mock loop does not duplicate itself"],
                "architecture_invariants": ["preserve one authoritative mock loop"],
                "interface_contracts": ["mock loop exposes a verified state interface"],
                "quality_constraints": [],
                "project_specific_coding_constraints": ["keep mock update and render ownership separate"],
                "acceptance_criteria": ["mock loop is verified"],
                "explicit_assumptions": [],
                "unresolved_critical_ambiguities": [],
                "non_goals": ["unrelated enemy AI"],
            },
        )
        project_brain = prepare_project_brain(
            contract["original_goal"], contract, repo, specification=expanded_specification,
        )
        mission_task = make_task(
            "self-test-mission", "Implement the mock loop", 1, "ROOT",
            ["mock loop is verified"], ["game.js"],
        )
        mission_projection = build_brain_projection(
            project_brain, mission_task, repo_snapshot=repo,
        )
        compiler_prompts = []

        def fake_mission_structured(prompt_text, _validator, _label, _schema):
            compiler_prompts.append(prompt_text)
            return {
                "goal_anchor": "ignored model anchor",
                "task": "ignored model task",
                "expected_outcome": "the mock loop is verified",
                "targets": ["game.js"],
                "existing_facts": ["reuse the verified state owner"],
                "implementation_plan": ["extend the existing loop owner"],
                "interfaces_to_reuse": ["mock loop state interface"],
                "invariants": ["preserve one authoritative mock loop"],
                "project_specific_quality_rules": ["keep update and render ownership separate"],
                "do_not": ["create a second loop"],
                "verification_plan": ["run deterministic mock loop verification"],
                "done_when": ["model output should not replace the task contract"],
            }

        compiled_mission = compile_worker_mission(
            mission_task, mission_projection, repo_snapshot=repo,
            structured_call=fake_mission_structured,
        )
        first_packet = build_node_context(
            make_task("fresh-a", "Implement the first mock behavior", 1, "ROOT", ["first verified"], []),
            contract, None, repo, brain_projection=mission_projection,
            worker_mission=compiled_mission,
        )
        second_packet = build_node_context(
            make_task("fresh-b", "Implement the second mock behavior", 1, "ROOT", ["second verified"], []),
            contract, None, repo, brain_projection=mission_projection,
        )
        captured_worker_messages = []
        original_ask_ollama = globals()["ask_ollama"]

        def fake_worker_call(messages, **_kwargs):
            captured_worker_messages.append(copy.deepcopy(messages))
            return {"role": "assistant", "content": "mocked worker response"}

        globals()["ask_ollama"] = fake_worker_call
        try:
            execute_agent_task("first node", {}, task_id="self-test-a", extra_context="FIRST_ONLY", max_steps=1)
            execute_agent_task("second node", {}, task_id="self-test-b", extra_context="SECOND_ONLY", max_steps=1)
        finally:
            globals()["ask_ollama"] = original_ask_ollama
        root = root_task_from_contract(contract); TASKS["ROOT"] = root; RUN["tasks_created"] = 1

        def fit(task, depth, contract, repo, parent, deps, force):
            if force:
                return {"decision": "split"}
            if depth < 3 and task["id"] in {"ROOT", "1", "2", "2.2"}:
                return {"decision": "split"}
            return {"decision": "execute"}

        def leaf(task, contract, mem, repo, parent, deps):
            RUN["leaf_tasks"] += 1
            return {"status": "done", "summary": f"verified {task['id']}", "memory": mem, "changed_files": []}

        def aggregate(task, contract, children, mem, repo, root=False):
            return {"status": "done", "summary": "verified aggregate", "memory": mem, "changed_files": []}

        # deterministic decomposition fallback avoids any live model call
        original_decompose = globals()["decompose_task"]
        def fake_decompose(task, contract, repo, parent_summary="", dependency_summaries=None, force_smaller=False):
            remaining = MAX_TOTAL_TASKS - RUN["tasks_created"]
            if remaining < 2:
                return []
            specs = [{"goal": f"{task['goal']} part A", "done_when": ["A"], "scope_hint": []},
                     {"goal": f"{task['goal']} part B", "done_when": ["B"], "scope_hint": []}]
            children=[]
            for i,spec in enumerate(specs,1):
                cid=str(i) if task['id']=='ROOT' else f"{task['id']}.{i}"
                child=make_task(cid,spec['goal'],task['depth']+1,task['id'],spec['done_when'],[])
                TASKS[cid]=child; task['children'].append(cid); RUN['tasks_created']+=1; children.append(child)
            return children
        globals()["decompose_task"] = fake_decompose
        try:
            result = solve_task(root, 0, contract, memory, repo, fit_decider=fit, leaf_executor=leaf, aggregator=aggregate)
        finally:
            globals()["decompose_task"] = original_decompose
        # Host qualification is tested with injected deterministic probes so
        # the architecture self-test never contacts Ollama or requires GPU
        # hardware.  This remains outside the HIVO task metrics.
        preflight_workspace = Path(tmp) / "host_preflight"
        preflight_workspace.mkdir()
        preflight_calls = []
        mocked_resources = {
            "total_system_ram_bytes": 16 * 1024 ** 3,
            "available_system_ram_bytes": 8 * 1024 ** 3,
            "gpu": {"status": "UNKNOWN", "reason": "self-test"},
        }
        preflight_result = run_host_preflight(
            preflight_workspace, "gemma4:e4b", "http://127.0.0.1:11434",
            model_catalog_loader=lambda _base_url: [{"name": "gemma4:e4b"}],
            canary_call=lambda model, prompt, timeout, base_url: (
                preflight_calls.append((model, prompt, timeout, base_url))
                or {"status_code": 200, "body": {"message": {"content": "HIVO_PREFLIGHT_OK"}}}
            ),
            resource_sampler=lambda: dict(mocked_resources),
            sleep=lambda _seconds: None,
            preflight_id="self-test-preflight",
        )
        # v16 requirement/clarification checks use deterministic inputs and
        # injected selectors only. They never invoke Ollama or a real TTY.
        v16_raw = "Build a timer.\n- persist the best score\n- support WASD"
        v16_ledger = extract_source_requirement_ledger(v16_raw, use_model=False)
        v17_compound_raw = (
            "Add Escape-key pause/resume support to the existing game. "
            "Reuse the current input and pause-state architecture instead of creating duplicate input state "
            "or another game-state owner. "
            "Preserve the current WASD/arrow controls and persistent best-score behavior. "
            "Update or add the relevant tests."
        )
        v17_compound_ledger = extract_source_requirement_ledger(v17_compound_raw, use_model=False)
        v17_compound_records = ledger_requirements(v17_compound_ledger)
        v17_compound_text = " ".join(item.get("text", "") for item in v17_compound_records)
        v17_compound_reuse = next(
            (item.get("text", "") for item in v17_compound_records if item.get("text", "").startswith("Reuse ")),
            "",
        )
        v17_compound_coverage = (
            "Add Escape-key pause/resume support" in v17_compound_text,
            v17_compound_reuse.startswith("Reuse ") and "current input" in v17_compound_reuse,
            v17_compound_reuse.startswith("Reuse ") and "pause-state architecture" in v17_compound_reuse,
            "duplicate input state" in v17_compound_reuse and "instead of" in v17_compound_reuse,
            "another game-state owner" in v17_compound_reuse and "instead of" in v17_compound_reuse,
            "Preserve the current WASD/arrow controls" in v17_compound_text,
            "persistent best-score behavior" in v17_compound_text,
            "Update or add the relevant tests" in v17_compound_text,
        )
        v16_no_questions = clarify_request(v16_raw, v16_ledger)
        v16_specialization_raw = (
            "Build a responsive UI.\n- The UI must fit a 390px-wide viewport."
        )
        v16_specialization_ledger = extract_source_requirement_ledger(
            v16_specialization_raw, use_model=False,
        )
        v16_specialization = clarify_request(
            v16_specialization_raw, v16_specialization_ledger,
        )
        v16_inline_raw = """- Expose a deterministic bridge on window.AGENT_GAME that allows:
  getState()
  start()
  restart()
  move(direction)
  forceCollision()
  forceCollect()
  forceWin()"""
        v16_inline_ledger = extract_source_requirement_ledger(v16_inline_raw, use_model=False)
        v16_inline_records = ledger_requirements(v16_inline_ledger)
        v16_inline_expected = [
            "window.AGENT_GAME", "getState()", "start()", "restart()",
            "move(direction)", "forceCollision()", "forceCollect()", "forceWin()",
        ]
        v16_bridge_profile = infer_web_profile("Build a browser game", {})
        v16_bridge_verification = evaluate_web_snapshot({
            "title": "Arena Game", "text": "Playable arena game",
            "console_errors": [], "page_errors": [], "network_errors": [],
            "runtime_state": {
                "canvasCount": 1,
                "gameBridge": {"name": GAME_BRIDGE_NAME, "state": {"status": "playing"}},
            },
            "interaction_checks": [
                {"name": name, "passed": True}
                for name in v16_bridge_profile.required_interactions
            ],
        }, v16_bridge_profile)
        v16_conflict_raw = "Build a timer.\n- restart resets everything\n- persist the best score"
        v16_conflict_ledger = extract_source_requirement_ledger(v16_conflict_raw, use_model=False)
        v16_blocking_questions = clarify_request(v16_conflict_raw, v16_conflict_ledger)
        v16_blocking = resolve_clarification_questions(
            v16_blocking_questions, interactive=False, terminal_available=False,
        )
        v16_optional_question = normalize_question(
            {
                "question": "Which persistence behavior should be used?",
                "reason": "This changes persistence behavior.",
                "affected_requirement_ids": ["REQ-001"],
                "impact_if_unknown": "The acceptance behavior changes.",
                "recommended_option": "Keep it", "options": ["Keep it", "Reset it"],
                "allow_other": True, "blocking": False,
            }, 1, extract_source_requirement_ledger("- save settings", use_model=False),
            "LOW_FRICTION", [],
        )
        v16_optional = resolve_clarification_questions(
            {"questions": [v16_optional_question]}, interactive=True, terminal_available=False,
        )
        v16_other = resolve_clarification_questions(
            {"questions": [dict(v16_optional_question, blocking=True)]},
            interactive=True, terminal_available=True,
            selector=lambda _question, **_kwargs: 2,
            answer_reader=lambda *_args: "localStorage",
        )
        v16_brain_contract = get_goal_contract(v16_raw, interactive=False)
        v16_brain = build_project_brain(
            v16_brain_contract, specification_from_goal_contract(v16_brain_contract), {"files": []},
        )
        # v17 architecture checks remain pure/deterministic. They create tiny
        # fixture repositories, never call Ollama, and never execute Workers.
        v17_root = Path(tmp) / "v17_fixtures"
        v17_new_root = v17_root / "new"
        v17_new_root.mkdir(parents=True)
        v17_new_inventory = stage2.inventory_repository(v17_new_root)
        v17_new_mode = stage2.classify_project_mode("Build a game from scratch", v17_new_inventory)
        v17_new_recon = stage2.run_repository_reconnaissance(
            v17_new_root, "Build a game from scratch", [], inventory=v17_new_inventory,
        )
        v17_new_task_brain = stage2.build_task_brain(
            "ROOT", "Build a game from scratch", NEW_PROJECT, v16_brain_contract, {}, [], [],
        )
        v17_new_validation = stage2.validate_task_brain(
            v17_new_task_brain,
            [item.get("requirement_id") for item in ledger_requirements(
                v16_brain_contract.get("source_requirement_ledger"), include_confirmed=True,
            )],
            [],
        )

        v17_existing_root = v17_root / "existing"
        (v17_existing_root / "src").mkdir(parents=True)
        (v17_existing_root / "tests").mkdir()
        (v17_existing_root / "src" / "input.js").write_text(
            "export class InputManager {\n"
            "  constructor() { this.keys = new Set(); }\n"
            "  onKeyDown(event) { if ([\"ArrowUp\", \"w\"].includes(event.key)) this.keys.add(event.key); }\n"
            "  isPressed(key) { return this.keys.has(key); }\n"
            "}\n", encoding="utf-8",
        )
        (v17_existing_root / "src" / "game.js").write_text(
            "export class GameState {\n"
            "  constructor() { this.paused = false; }\n"
            "  togglePause() { this.paused = !this.paused; }\n"
            "}\n", encoding="utf-8",
        )
        (v17_existing_root / "src" / "storage.js").write_text(
            "const BEST_SCORE_KEY = 'score';\n"
            "export function loadBestScore(storage = localStorage) { return Number(storage.getItem(BEST_SCORE_KEY) || 0); }\n"
            "export function saveBestScore(score, storage = localStorage) { storage.setItem(BEST_SCORE_KEY, String(score)); }\n",
            encoding="utf-8",
        )
        (v17_existing_root / "tests" / "input.test.js").write_text(
            "import { InputManager } from '../src/input.js';\n"
            "describe('keyboard input', () => it('uses arrows', () => expect(new InputManager().isPressed('ArrowUp')).toBe(false)));\n",
            encoding="utf-8",
        )
        (v17_existing_root / "index.html").write_text(
            "<!doctype html><script type=\"module\" src=\"src/input.js\"></script>\n"
            "<script type=\"module\" src=\"src/game.js\"></script>\n"
            "<script type=\"module\" src=\"src/storage.js\"></script>\n",
            encoding="utf-8",
        )
        v17_pause_raw = (
            "Add Escape-key pause/resume support to the existing game. Reuse the current input and "
            "pause-state architecture instead of creating duplicate input state or another game-state owner. "
            "Preserve the current WASD/arrow controls and persistent best-score behavior. "
            "Update or add the relevant tests."
        )
        v17_pause_ledger = extract_source_requirement_ledger(v17_pause_raw, use_model=False)
        v17_pause_contract = normalize_goal_contract(
            v17_pause_raw, _deterministic_contract_from_ledger(v17_pause_raw, v17_pause_ledger),
            source_ledger=v17_pause_ledger, confirmed=[], derived=[],
        )
        v17_existing_inventory = stage2.inventory_repository(v17_existing_root)
        v17_existing_mode = stage2.classify_project_mode(v17_pause_raw, v17_existing_inventory)
        v17_existing_recon = stage2.run_repository_reconnaissance(
            v17_existing_root, v17_pause_raw, ledger_requirements(v17_pause_ledger),
            inventory=v17_existing_inventory,
        )
        v17_pause_projection = {
            "relevant_core": {
                "architecture_invariants": ["preserve one keyboard owner"],
                "product_contract": {"acceptance_criteria": ["Escape toggles pause"]},
            },
        }
        v17_existing_task_brain = stage2.build_task_brain(
            "ROOT", v17_pause_raw, EXISTING_PROJECT, v17_pause_contract,
            v17_pause_projection, v17_existing_recon.get("evidence", []), [],
        )
        v17_existing_validation = stage2.validate_task_brain(
            v17_existing_task_brain,
            [item.get("requirement_id") for item in ledger_requirements(v17_pause_ledger)],
            v17_existing_recon.get("evidence", []),
        )
        v17_existing_evidence = v17_existing_recon.get("evidence", [])
        v17_existing_categories = {item.get("category") for item in v17_existing_evidence}
        v17_existing_encoded = json.dumps(v17_existing_task_brain, ensure_ascii=False)
        v17_existing_evidence_checks = {
            "input_owner": any(
                item.get("category") == "CURRENT_OWNER"
                and item.get("path") == "src/input.js"
                and item.get("symbol") == "InputManager"
                for item in v17_existing_evidence
            ),
            "input_state": any(
                item.get("category") == "CURRENT_STATE_OWNER"
                and item.get("path") == "src/input.js"
                and item.get("symbol") == "InputManager"
                for item in v17_existing_evidence
            ),
            "game_state": any(
                item.get("category") == "CURRENT_STATE_OWNER"
                and item.get("path") == "src/game.js"
                and item.get("symbol") == "GameState"
                and "paused" in str(item.get("fact", ""))
                for item in v17_existing_evidence
            ),
            "pause_interface": any(
                item.get("category") == "CURRENT_INTERFACE"
                and "togglePause" in str(item.get("symbol", ""))
                for item in v17_existing_evidence
            ),
            "persistence": any(
                item.get("category") == "CURRENT_PERSISTENCE"
                and item.get("path") == "src/storage.js"
                and item.get("symbol") == "BEST_SCORE_KEY"
                for item in v17_existing_evidence
            ),
            "input_test": any(
                item.get("category") == "CURRENT_TEST"
                and item.get("path") == "tests/input.test.js"
                and item.get("symbol") == "InputManager"
                for item in v17_existing_evidence
            ),
            "no_test_local_interface": not any(
                item.get("category") == "CURRENT_INTERFACE"
                and item.get("symbol") in {"assert", "input"}
                for item in v17_existing_evidence
            ),
            "all_source_valid": all(
                stage2.validate_repository_evidence(item, v17_existing_root)
                for item in v17_existing_evidence
            ),
            "no_raw_files": not any(
                value in v17_existing_encoded
                for value in ("this.keys = new Set", "this.paused = !this.paused", "localStorage.getItem")
            ),
        }

        # v18 Stage 3 self-test scenarios use the accepted v17 evidence and
        # injected/deterministic outputs only. No model or Worker is invoked.
        v18_requirements = stage3.active_requirements(ledger_requirements(v17_pause_ledger))
        v18_req_by_prefix = {
            prefix: next(
                item.get("requirement_id") for item in v18_requirements
                if item.get("text", "").startswith(prefix)
            )
            for prefix in ("Add ", "Reuse ", "Preserve ", "Update ")
        }

        def v18_evidence_id(category, path, symbol_text=""):
            return next(
                item.get("evidence_id") for item in v17_existing_evidence
                if item.get("category") == category
                and item.get("path") == path
                and (not symbol_text or symbol_text in str(item.get("symbol", "")))
            )

        v18_input_owner = v18_evidence_id("CURRENT_OWNER", "src/input.js", "InputManager")
        v18_input_state = v18_evidence_id("CURRENT_STATE_OWNER", "src/input.js", "InputManager")
        v18_input_interface = v18_evidence_id("CURRENT_INTERFACE", "src/input.js", "isPressed")
        v18_game_owner = v18_evidence_id("CURRENT_OWNER", "src/game.js", "GameState")
        v18_pause_state = v18_evidence_id("CURRENT_STATE_OWNER", "src/game.js", "GameState")
        v18_pause_interface = v18_evidence_id("CURRENT_INTERFACE", "src/game.js", "togglePause")
        v18_persistence = v18_evidence_id("CURRENT_PERSISTENCE", "src/storage.js", "BEST_SCORE_KEY")
        v18_input_test = v18_evidence_id("CURRENT_TEST", "tests/input.test.js", "InputManager")
        v18_candidate = stage3.normalize_impact_map({
            "task_goal": v17_pause_raw,
            "impacts": [
                {
                    "impact_id": "IMP-001", "component": "InputManager", "path": "src/input.js",
                    "symbols": ["InputManager", "InputManager.isPressed"],
                    "impact_kind": "BEHAVIOR_CHANGE",
                    "requirement_ids": [v18_req_by_prefix["Add "], v18_req_by_prefix["Reuse "], v18_req_by_prefix["Preserve "]],
                    "repository_evidence_ids": [v18_input_owner, v18_input_state, v18_input_interface],
                    "reason": "InputManager is the current keyboard owner.",
                    "existing_owner": "InputManager",
                    "existing_interfaces_to_reuse": ["InputManager.isPressed"],
                    "preserve": ["WASD/arrow controls"],
                    "candidate_change": "Integrate Escape detection through the current InputManager.",
                    "local_verification": ["Escape is detected and WASD/arrow controls remain intact"],
                    "necessity_status": "MUST_CHANGE",
                },
                {
                    "impact_id": "IMP-002", "component": "GameState", "path": "src/game.js",
                    "symbols": ["GameState", "GameState.paused", "GameState.togglePause"],
                    "impact_kind": "INTEGRATION_CHANGE",
                    "requirement_ids": [v18_req_by_prefix["Add "], v18_req_by_prefix["Reuse "]],
                    "repository_evidence_ids": [v18_game_owner, v18_pause_state, v18_pause_interface],
                    "reason": "GameState owns the paused state and transition.",
                    "existing_owner": "GameState",
                    "existing_interfaces_to_reuse": ["GameState.togglePause"],
                    "preserve": ["GameState remains the paused-state owner"],
                    "candidate_change": "Connect Escape handling to GameState.togglePause.",
                    "local_verification": ["Escape toggles current GameState.paused"],
                    "necessity_status": "CANDIDATE",
                },
                {
                    "impact_id": "IMP-003", "component": "best-score persistence", "path": "src/storage.js",
                    "symbols": ["BEST_SCORE_KEY"], "impact_kind": "INTEGRATION_CHANGE",
                    "requirement_ids": [v18_req_by_prefix["Preserve "]],
                    "repository_evidence_ids": [v18_persistence],
                    "reason": "Best-score persistence must remain unchanged.",
                    "existing_owner": "BEST_SCORE_KEY", "existing_interfaces_to_reuse": [],
                    "preserve": ["persistent best-score behavior"],
                    "candidate_change": "Modify storage for pause support.",
                    "local_verification": ["best-score persistence remains unchanged"],
                    "necessity_status": "MUST_CHANGE",
                },
                {
                    "impact_id": "IMP-004", "component": "input tests", "path": "tests/input.test.js",
                    "symbols": ["InputManager"], "impact_kind": "TEST_CHANGE",
                    "requirement_ids": [v18_req_by_prefix["Update "]],
                    "repository_evidence_ids": [v18_input_test],
                    "reason": "The current input test is relevant.", "existing_owner": "",
                    "existing_interfaces_to_reuse": [], "preserve": ["existing input assertions"],
                    "candidate_change": "Update or add relevant pause/input tests.",
                    "local_verification": ["pause/input tests pass"],
                    "necessity_status": "CANDIDATE",
                },
            ],
            "integration_verification": [
                "Escape toggles current GameState.paused", "WASD/arrow controls still work",
                "best-score persistence is unchanged", "no duplicate owner exists", "relevant tests pass",
            ],
            "insufficient_evidence": [],
        })
        v18_challenges = stage3.deterministic_challenges(
            v18_candidate, v18_requirements, v17_existing_evidence,
        )
        v18_challenge_validation = stage3.validate_challenges(
            v18_challenges, v18_candidate, v18_requirements, v17_existing_evidence,
        )
        v18_reconciled, v18_resolved, v18_unresolved = stage3.reconcile_impact_map(
            v18_candidate, v18_challenge_validation.get("validated", []),
            v18_requirements, v17_existing_evidence,
        )
        v18_plan = stage3.build_minimal_change_plan(
            v18_reconciled, v18_requirements, v17_existing_evidence,
            v18_resolved, v18_unresolved,
        )
        v18_plan_gate = stage3.validate_change_plan(
            v18_plan, v18_requirements, v17_existing_evidence,
        )
        v18_approval = request_plan_approval(
            v18_plan, interactive=True, terminal_available=True,
            selector=lambda *_args, **_kwargs: 0,
        )
        v18_noninteractive = request_plan_approval(
            v18_plan, interactive=False, terminal_available=False,
        )
        v18_duplicate = copy.deepcopy(v18_candidate)
        v18_duplicate["impacts"][0]["candidate_change"] = "Add a paused field to InputManager."
        v18_duplicate["impacts"][0]["repository_evidence_ids"] = [
            v18_input_owner, v18_pause_state, v18_pause_interface,
        ]
        v18_duplicate_types = {
            item.get("challenge_type") for item in stage3.deterministic_challenges(
                v18_duplicate, v18_requirements, v17_existing_evidence,
            )
        }
        v18_missing_test = copy.deepcopy(v18_candidate)
        v18_missing_test["impacts"] = [
            item for item in v18_missing_test["impacts"] if item.get("impact_kind") != "TEST_CHANGE"
        ]
        v18_test_challenges = stage3.deterministic_challenges(
            v18_missing_test, v18_requirements, v17_existing_evidence,
        )
        v18_test_validation = stage3.validate_challenges(
            v18_test_challenges, v18_missing_test, v18_requirements, v17_existing_evidence,
        )
        v18_test_reconciled, _, _ = stage3.reconcile_impact_map(
            v18_missing_test, v18_test_validation.get("validated", []),
            v18_requirements, v17_existing_evidence,
        )

        # v18.1 canonical-surface checks are deterministic and use the same
        # accepted Stage 2 evidence; no model, approval, or Worker is needed.
        v18_registry = stage3.build_canonical_surface_registry(
            v17_existing_task_brain, v17_existing_evidence,
        )
        v18_registry_validation = stage3.validate_canonical_surface_registry(
            v18_registry, v17_existing_evidence,
        )
        v18_canonical = stage3.hydrate_impact_map(
            v18_candidate, v18_registry, v18_requirements, v17_existing_evidence,
            allow_legacy_exact=True,
        )
        v18_bad_surface = copy.deepcopy(v18_candidate)
        v18_bad_surface["impacts"][0]["path"] = "src/input/InputHandler.cpp"
        v18_bad_surface_hydration = stage3.hydrate_impact_map(
            v18_bad_surface, v18_registry, v18_requirements, v17_existing_evidence,
        )
        v18_same_surface = copy.deepcopy(v18_canonical)
        v18_same_surface["impacts"].append({
            **copy.deepcopy(v18_same_surface["impacts"][0]),
            "impact_id": "IMP-SAME-PRESERVE", "disposition": "PRESERVATION_ONLY",
            "impact_kind": "PRESERVATION_ONLY", "necessity_status": "PRESERVATION_ONLY",
            "preserve": ["existing input behavior remains intact"],
        })
        v18_canonical_challenges = stage3.deterministic_challenges(
            v18_canonical, v18_requirements, v17_existing_evidence,
        )
        v18_canonical_challenge_validation = stage3.validate_challenges(
            v18_canonical_challenges, v18_canonical, v18_requirements,
            v17_existing_evidence, surface_registry=v18_registry,
        )
        v18_canonical_reconciled, v18_canonical_resolved, v18_canonical_unresolved = stage3.reconcile_impact_map(
            v18_same_surface, v18_canonical_challenge_validation.get("validated", []),
            v18_requirements, v17_existing_evidence, surface_registry=v18_registry,
        )
        v18_canonical_plan = stage3.build_minimal_change_plan(
            v18_canonical_reconciled, v18_requirements, v17_existing_evidence,
            v18_canonical_resolved, v18_canonical_unresolved,
            surface_registry=v18_registry,
        )
        v18_canonical_gate = stage3.validate_change_plan(
            v18_canonical_plan, v18_requirements, v17_existing_evidence,
            surface_registry=v18_registry,
        )
        v18_canonical_noninteractive = request_plan_approval(
            v18_canonical_plan, interactive=False, terminal_available=False,
        )

        # v18.2 surface-bound planner checks use a complete deterministic
        # packet and mocked semantic decisions.  They never invoke Gemma,
        # Ollama, a Challenger model, or a Worker.
        v18_planning_packet = stage3.build_canonical_planning_packet(
            v17_existing_task_brain, v18_requirements, v17_existing_evidence,
            project_invariants=["preserve verified owners"], surface_registry=v18_registry,
        )
        v18_planning_packet_validation = stage3.validate_planning_packet(
            v18_planning_packet, registry=v18_registry, requirements=v18_requirements,
        )
        v18_input_surface = next(
            (item for item in v18_registry.get("surfaces", [])
             if item.get("path") == "src/input.js" and item.get("kind") == "OWNER"),
            {},
        )
        v18_seed_decision = {
            "impact_id": "impact_001",
            "disposition": "MUST_CHANGE",
            "requirement_ids": [v18_req_by_prefix["Add "], v18_req_by_prefix["Reuse "]],
            "interfaces_to_reuse": ["surface_input_handler"],
            "action": "Handle Escape using the current input architecture.",
            "preserve": ["WASD/arrow controls"],
            "verification": ["Escape is detected"],
        }
        v18_seed_hydration = stage3.hydrate_impact_map(
            v18_seed_decision, v18_registry, v18_requirements, v17_existing_evidence,
            impact_seeds=v18_planning_packet.get("impact_seeds", []),
        )
        v18_partial_hydration = stage3.hydrate_impact_map(
            {"impacts": [
                {
                    "impact_id": "IMPACT_001", "disposition": "MUST_CHANGE",
                    "requirement_ids": [v18_req_by_prefix["Add "]],
                    "action": "Handle Escape through the current input owner.",
                },
                {
                    "impact_id": "IMPACT-002", "disposition": "NOT_A_DISPOSITION",
                    "requirement_ids": [v18_req_by_prefix["Reuse "]],
                    "action": "Malformed decision should be rejected independently.",
                },
            ]}, v18_registry, v18_requirements, v17_existing_evidence,
            impact_seeds=v18_planning_packet.get("impact_seeds", []),
        )
        v18_challenger_packet = stage3.build_challenger_packet(
            v18_canonical, v18_requirements, v17_existing_evidence,
            task_brain=v17_existing_task_brain, surface_registry=v18_registry,
        )

        v17_auth_root = v17_root / "repo_conflict"
        (v17_auth_root / "src").mkdir(parents=True)
        (v17_auth_root / "src" / "legacy-auth.js").write_text(
            "export function legacyAuthCallback(request) {\n"
            "  // Legacy auth owns SSO callback handling.\n"
            "  return completeSsoCallback(request);\n}\n", encoding="utf-8",
        )
        v17_auth_raw = "Remove legacy auth while preserving SSO."
        v17_auth_ledger = extract_source_requirement_ledger(v17_auth_raw, use_model=False)
        v17_auth_inventory = stage2.inventory_repository(v17_auth_root)
        v17_auth_recon = stage2.run_repository_reconnaissance(
            v17_auth_root, v17_auth_raw, ledger_requirements(v17_auth_ledger),
            inventory=v17_auth_inventory,
        )
        v17_auth_questions = stage2.repository_grounded_questions(
            v17_auth_raw, ledger_requirements(v17_auth_ledger), v17_auth_recon.get("evidence", []),
        )
        checks = {
            "deep recursion": result["status"] == "done" and RUN["max_depth"] >= 3,
            "more than old eight": RUN["tasks_created"] > 8,
            "hard depth budget": RUN["max_depth"] <= MAX_DEPTH,
            "hard task budget": RUN["tasks_created"] <= MAX_TOTAL_TASKS,
            "recon bounded": len(json.dumps(inspect_repository(max_files=5, max_chars=900))) <= 900,
            "node packet bounded": len(build_node_context(root, contract, None, repo)) <= MAX_NODE_PACKET_CHARS,
            "project brain core": (
                project_brain.get("core", {}).get("root_goal") == contract["goal"]
                and "verified_state" not in project_brain.get("core", {})
            ),
            "verified state separate": (
                isinstance(project_brain.get("verified_state"), dict)
                and project_brain.get("verified_state") is not project_brain.get("core")
            ),
            "brain projection bounded and relevant": (
                len(json.dumps(mission_projection, ensure_ascii=False)) <= MAX_BRAIN_PROJECTION_CHARS
                and "unrelated enemy AI" not in json.dumps(mission_projection, ensure_ascii=False)
                and "mock loop" in json.dumps(mission_projection, ensure_ascii=False)
            ),
            "mission compilation mocked": (
                len(compiler_prompts) == 1
                and compiled_mission.get("task") == mission_task.get("goal")
                and compiled_mission.get("goal_anchor") == project_brain["core"]["root_goal"]
                and "MISSION COMPILER" in compiler_prompts[0]
            ),
            "fresh worker context": (
                len(captured_worker_messages) == 2
                and "FIRST_ONLY" in json.dumps(captured_worker_messages[0], ensure_ascii=False)
                and "FIRST_ONLY" not in json.dumps(captured_worker_messages[1], ensure_ascii=False)
                and "SECOND_ONLY" in json.dumps(captured_worker_messages[1], ensure_ascii=False)
            ),
            "goal anchor preserved": compiled_mission.get("goal_anchor") == contract["goal"],
            "summaries bounded": all(
                len(str(item.get("summary", ""))) <= MAX_NODE_SUMMARY_CHARS for item in compact_task_tree()
            ),
            "falsifier read only": "write_file" not in {t["function"]["name"] for t in tools_for_role("Falsifier")},
            "host preflight mocked": preflight_result["passed"] and len(preflight_calls) == 3,
            "host preflight marker": (
                json.loads((preflight_workspace / ".agent_host_preflight.json").read_text(encoding="utf-8"))["status"] == "PASS"
            ),
            "host preflight no app files": not any(
                (preflight_workspace / name).exists() for name in ("index.html", "style.css", "game.js")
            ),
            "source ledger stable and immutable": (
                [item.get("requirement_id") for item in ledger_requirements(v16_ledger)] == ["REQ-001", "REQ-002"]
                and v16_ledger.get("immutable") is True
                and isinstance(v16_ledger.get("requirements"), list)
            ),
            "compound source extraction": (
                sum(v17_compound_coverage) == 8
                and all(item.get("provenance") == USER_STATED for item in v17_compound_records)
                and all(item.get("source_segments") == [1] for item in v17_compound_records)
                and v17_compound_ledger.get("immutable") is True
            ),
            "source provenance separated": (
                all(item.get("provenance") == USER_STATED for item in ledger_requirements(v16_ledger))
                and v16_other["answers"][0].get("provenance") == USER_CONFIRMED
            ),
            "clarifier compatible pair": (
                not v16_no_questions["conflicts"] and not v16_no_questions["questions"]
            ),
            "clarifier specialization pair": (
                not v16_specialization["conflicts"] and not v16_specialization["questions"]
            ),
            "inline enumeration retention": (
                len(v16_inline_records) == 1
                and all(item in v16_inline_records[0].get("text", "") for item in v16_inline_expected)
                and v16_inline_records[0].get("explicit_items") == v16_inline_expected
                and v16_inline_records[0].get("provenance") == USER_STATED
            ),
            "exact identifier preservation": (
                "window.AGENT_GAME" in v16_inline_records[0].get("explicit_items", [])
                and "forceCollision()" in v16_inline_records[0].get("explicit_items", [])
            ),
            "source contract bridge": (
                GAME_BRIDGE_NAME == "AGENT_GAME"
                and GAME_BRIDGE_EXPRESSION == "window.AGENT_GAME"
                and v16_inline_records[0].get("explicit_items", [])[0] == GAME_BRIDGE_EXPRESSION
            ),
            "verification bridge": (
                v16_bridge_verification["passed"]
                and not any(
                    item.get("code") == "missing_game_bridge"
                    for item in v16_bridge_verification.get("failures", [])
                )
            ),
            "clarifier true contradiction": (
                len(v16_blocking_questions["conflicts"]) == 1
                and v16_blocking_questions["conflicts"][0].get("relationship") == "CONFLICT"
                and v16_blocking_questions["conflicts"][0].get("can_satisfy_both") is False
            ),
            "clarifier blocking path": (
                v16_blocking["status"] == "clarification_required"
                and v16_blocking["unanswered"][0].get("blocking") is True
            ),
            "recommended terminal option": (
                clarification_option_labels(v16_optional_question)[0].endswith("Recommended")
            ),
            "other free-text path": v16_other["answers"][0].get("answer") == "localStorage",
            "noninteractive optional behavior": (
                v16_optional["status"] == "ready"
                and v16_optional["derived"][0].get("provenance") == DERIVED
            ),
            "lossless brain handoff": (
                len(ledger_requirements(v16_brain["source_requirement_ledger"])) == 2
                and len(v16_brain["source_requirement_coverage"]) == 2
            ),
            "v17 new project": (
                v17_new_mode.get("project_mode") == NEW_PROJECT
                and v17_new_recon.get("status") == REPOSITORY_EMPTY
                and v17_new_validation.get("valid")
            ),
            "v17 existing project": (
                v17_existing_mode.get("project_mode") == EXISTING_PROJECT
                and v17_existing_recon.get("status") == REPOSITORY_RECONNAISSANCE_COMPLETE
                and v17_existing_recon.get("read_only") is True
                and v17_existing_validation.get("valid")
                and bool(v17_existing_task_brain.get("current_owners"))
                and bool(v17_existing_task_brain.get("relevant_tests"))
            ),
            "v17 semantic repository evidence": (
                {"CURRENT_OWNER", "CURRENT_STATE_OWNER", "CURRENT_INTERFACE", "CURRENT_PERSISTENCE", "CURRENT_TEST"}
                .issubset(v17_existing_categories)
                and all(v17_existing_evidence_checks.values())
                and len(v17_existing_evidence) <= stage2.MAX_TASK_BRAIN_EVIDENCE
                and v17_existing_recon.get("read_only") is True
            ),
            "v17 repo conflict": (
                len(v17_auth_questions) == 1
                and bool(v17_auth_questions[0].get("affected_requirement_ids"))
                and bool(v17_auth_questions[0].get("repository_evidence_ids"))
            ),
            "v17 context hygiene": (
                "unrelated storage implementation" not in v17_existing_encoded
                and "src/storage.js" in v17_existing_encoded
                and "this.keys = new Set" not in v17_existing_encoded
                and "this.paused = !this.paused" not in v17_existing_encoded
                and "support" not in json.dumps(
                    v17_existing_task_brain.get("evidence_index", []), ensure_ascii=False,
                )
            ),
            "v18 valid existing plan": (
                v18_plan_gate.get("valid")
                and v18_approval.get("status") == "approved"
                and stage3.approval_is_current(v18_plan, v18_approval.get("approval"))
            ),
            "v18 unnecessary mutation": (
                "src/storage.js" in v18_plan.get("do_not_touch", [])
                and not any(
                    "src/storage.js" in node.get("candidate_targets", [])
                    for node in v18_plan.get("approved_change_nodes", [])
                )
            ),
            "v18 duplicate ownership": (
                {"DUPLICATE_OWNERSHIP_RISK", "WRONG_OWNER"}.issubset(v18_duplicate_types)
                and "InputManager.paused" not in json.dumps(v18_plan, ensure_ascii=False)
            ),
            "v18 test gap": (
                any(item.get("challenge_type") == "TEST_GAP" for item in v18_test_challenges)
                and any(item.get("impact_kind") == "TEST_CHANGE" for item in v18_test_reconciled.get("impacts", []))
            ),
            "v18 noninteractive approval": (
                v18_noninteractive.get("terminal_state") == PLAN_APPROVAL_REQUIRED
                and v18_noninteractive.get("status") == "plan_approval_required"
            ),
            "v18.1 canonical surface registry": (
                v18_registry_validation.get("valid")
                and len(v18_registry.get("surfaces", [])) >= 6
                and all(item.get("surface_id", "").startswith("SURF-") for item in v18_registry.get("surfaces", []))
            ),
            "v18.1 canonical hydration": (
                v18_canonical.get("hydration_valid")
                and all(item.get("surface_id") in v18_registry.get("surface_ids", [])
                        for item in v18_canonical.get("impacts", []))
                and all(item.get("path") in {surface.get("path") for surface in v18_registry.get("surfaces", [])}
                        for item in v18_canonical.get("impacts", []))
            ),
            "v18.1 hallucination rejected": (
                not v18_bad_surface_hydration.get("hydration_valid")
                and v18_bad_surface_hydration.get("impact_invented_existing_paths_rejected", 0) >= 1
                and "InputHandler.cpp" not in json.dumps(v18_bad_surface_hydration.get("impacts", []))
            ),
            "v18.1 self-conflict normalization": (
                v18_canonical_gate.get("valid")
                and "SURF-001" in v18_canonical_plan.get("mutation_surface_ids", [])
                and "SURF-001" not in v18_canonical_plan.get("do_not_touch_surface_ids", [])
            ),
            "v18.1 canonical noninteractive approval": (
                v18_canonical_noninteractive.get("terminal_state") == PLAN_APPROVAL_REQUIRED
                and v18_canonical_noninteractive.get("status") == "plan_approval_required"
            ),
            "v18.2 complete planning packet": (
                v18_planning_packet.get("packet_complete")
                and v18_planning_packet_validation.get("valid")
                and len(v18_planning_packet.get("observability", {}).get("selected_surface_ids", [])) == 7
                and v18_planning_packet.get("observability", {}).get("selected_surface_ids")
                == v18_planning_packet.get("observability", {}).get("serialized_surface_ids")
                and not v18_planning_packet.get("observability", {}).get("dropped_surface_ids")
                and len(v18_planning_packet.get("impact_seeds", [])) == 7
            ),
            "v18.2 seed-bound decision": (
                v18_seed_hydration.get("hydration_valid")
                and len(v18_seed_hydration.get("impacts", [])) == 1
                and v18_seed_hydration["impacts"][0].get("impact_id") == "IMPACT-001"
                and v18_seed_hydration["impacts"][0].get("surface_id") == v18_input_surface.get("surface_id")
                and v18_seed_hydration["impacts"][0].get("path") == "src/input.js"
            ),
            "v18.2 optional bad interface": (
                v18_seed_hydration.get("impact_invented_interfaces_rejected", 0) >= 1
                and v18_seed_hydration.get("impact_invalid_optional_fields_rejected", 0) >= 1
                and "surface_input_handler" not in json.dumps(v18_seed_hydration.get("impacts", []))
            ),
            "v18.2 partial validation": (
                v18_partial_hydration.get("hydration_valid")
                and len(v18_partial_hydration.get("impacts", [])) == 1
                and v18_partial_hydration.get("impact_seed_decisions_validated") == 1
                and v18_partial_hydration.get("impact_seed_decisions_rejected") >= 1
            ),
            "v18.2 challenger complete": (
                v18_challenger_packet.get("packet_complete")
                and v18_challenger_packet.get("reviewed_impact_ids")
                == v18_challenger_packet.get("serialized_impact_ids")
                and not v18_challenger_packet.get("dropped_impact_ids")
            ),
        }
        for name, ok in checks.items():
            print(f"{name:<24} {'PASS' if ok else 'FAIL'}")
        if install_browser:
            ok, detail = ensure_browser(True)
            print(f"{'browser':<24} {'PASS' if ok else 'FAIL'} {detail}")
            checks["browser"] = ok
        return all(checks.values())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def get_workspace(explicit=None, projects_root=None):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            raise RuntimeError(f"workspace is not a folder: {path}")
        print(f"workspace set to: {path}\n")
        return path
    store = ProjectStore(projects_root or DEFAULT_PROJECTS_ROOT)
    migration = store.migrate_legacy_contents()
    if migration.moved:
        print(f"[PROJECT MIGRATION] moved {len(migration.moved)} legacy item(s) into {migration.project}")
    while True:
        default_path = store.root / store.peek_next_name()
        raw = input(f"Workspace [Enter = {default_path}]: ").strip()
        if raw.lower() in {"exit", "quit"}:
            raise SystemExit()
        if not raw:
            path = store.create_project(); print(f"workspace created: {path}\n"); return path
        path = Path(raw).expanduser().resolve()
        if path.exists() and path.is_dir():
            print(f"workspace set to: {path}\n"); return path
        print(f"error: folder does not exist: {path}")


def read_user_prompt(prompt_label="You> "):
    if PROMPT_TOOLKIT_AVAILABLE and sys.stdin.isatty():
        bindings = KeyBindings()
        @bindings.add("enter")
        def _submit(event_obj):
            event_obj.current_buffer.validate_and_handle()
        @bindings.add("escape", "enter")
        def _newline(event_obj):
            event_obj.current_buffer.insert_text("\n")
        return prompt(prompt_label, multiline=True, key_bindings=bindings).strip()
    return input(prompt_label).strip()


def parse_args():
    parser = argparse.ArgumentParser(description="Mini Hivo adaptive task-granularity research prototype")
    parser.add_argument("--mode", choices=("auto", "baseline", "recursive"), default="auto")
    parser.add_argument("--model", help=f"Compatibility option; only {GEMMA_MODEL} is accepted")
    parser.add_argument("--prompt-file")
    parser.add_argument("--workspace")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--install-browser", action="store_true")
    parser.add_argument("--no-bootstrap", action="store_true")
    return parser.parse_args()


def ollama_reachable():
    try:
        response = http_get_json(OLLAMA_BASE_URL + "/api/tags", timeout=2)
        return response.status_code == 200
    except Exception:
        return False


def main():
    global WORKSPACE, HOST_PREFLIGHT_RESULT
    configure_console_streams()
    args = parse_args()
    # The architecture self-test is deterministic and must remain runnable on
    # a clean machine without installing optional Rich/Playwright packages.
    _load_optional_imports()
    if args.self_test:
        ok = run_self_test(install_browser=args.install_browser)
        raise SystemExit(0 if ok else 1)
    if not ensure_dependencies(auto_install=not args.no_bootstrap):
        raise SystemExit(2)
    try:
        selected_model = MODEL_POLICY.validate(args.model)
    except ValueError as exc:
        print(f"[SETUP_ERROR] {exc}")
        raise SystemExit(2)
    try:
        WORKSPACE = get_workspace(args.workspace)
    except RuntimeError as exc:
        if args.workspace:
            HOST_PREFLIGHT_RESULT = failed_host_preflight_result(
                args.workspace, selected_model, reason="WORKSPACE_UNUSABLE", stage="workspace", summary=exc,
            )
            print(format_host_preflight_report(HOST_PREFLIGHT_RESULT))
            print("terminal: HOST_PREFLIGHT_FAILED")
        else:
            print(f"[SETUP_ERROR] {exc}")
        raise SystemExit(2)
    HOST_PREFLIGHT_RESULT = run_host_preflight(WORKSPACE, selected_model, OLLAMA_BASE_URL)
    print(format_host_preflight_report(HOST_PREFLIGHT_RESULT))
    if not HOST_PREFLIGHT_RESULT["passed"]:
        print("terminal: HOST_PREFLIGHT_FAILED")
        raise SystemExit(2)
    # Preserve the established model configuration path after qualification;
    # the preflight itself never mutates HIVO task state or metrics.
    try:
        select_local_ollama_model(selected_model)
    except (RuntimeError, ValueError) as exc:
        print(f"[SETUP_ERROR] {exc}")
        raise SystemExit(2)
    memory = load_memory()

    def handle(user_text, interactive=True):
        nonlocal memory
        if args.mode == "baseline":
            result, memory = run_baseline_request(user_text, memory)
        elif args.mode == "recursive":
            result, memory = run_recursive_request(user_text, memory, interactive=interactive)
        else:
            result, memory = run_auto_request(user_text, memory, interactive=interactive)
        print("Agent>", result.get("summary", ""))

    if args.prompt_file:
        path = Path(args.prompt_file).expanduser().resolve()
        handle(path.read_text(encoding="utf-8"), interactive=False)
        return
    while True:
        try:
            user_text = read_user_prompt()
        except (EOFError, KeyboardInterrupt):
            print(); break
        if user_text.lower() in {"exit", "quit"}:
            break
        if user_text:
            handle(user_text, interactive=True)


if __name__ == "__main__":
    main()
