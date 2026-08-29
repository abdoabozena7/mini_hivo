import argparse
import base64
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
from hivo.evidence import result_failed as evidence_result_failed
from hivo.evidence import result_not_applicable
from hivo.evidence import result_is_tool_rejection
from hivo.evidence import unresolved_tool_failures
from hivo.http_client import HttpTransportError, get_json as http_get_json, post_json as http_post_json
from hivo.memory import MemoryStore
from hivo.model_policy import GEMMA_MODEL, SingleModelPolicy
from hivo.playbooks import classify_project, playbook_context
from hivo.projects import ProjectStore
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
MAX_ALTERNATE_STRATEGIES = 2
MAX_CLARIFICATION_QUESTIONS = 5
MAX_REPAIRS_PER_LEAF = 2
MAX_STRUCTURED_RETRIES = 5
MAX_PROVIDER_RETRIES = 2
MAX_RECON_FILES = 120
MAX_RECON_DEPTH = 3
MAX_RECON_CHARS = 6000
MAX_NODE_SUMMARY_CHARS = 700
MAX_NODE_PACKET_CHARS = 12000
MAX_ROOT_PACKET_CHARS = 2400
MAX_MEMORY_CONTEXT_CHARS = 1800
MAX_FALSIFIER_STEPS = 8
MAX_INTEGRATION_MANIFEST_ITEMS = 8
MAX_INTEGRATION_FACT_CHARS = 280
MAX_INTEGRATION_CONFLICTS = 24
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


class ProviderError(RuntimeError):
    """The local model provider could not complete a request."""


class StructuredOutputError(RuntimeError):
    """The provider replied, but a tiny structured orchestration contract was invalid."""


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
        return f"error: {name} arguments must be one JSON object"
    required = definition.get("parameters", {}).get("required", [])
    missing = [key for key in required if key not in args or args.get(key) is None]
    if not missing:
        return None
    return (
        f"error: incomplete or truncated {name} tool call; missing: {', '.join(missing)}. "
        "Retry with every required field and smaller content/edit fragments. No file was changed."
    )


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
            return json.dumps(browser_workspace_snapshot(path, "run_file"), ensure_ascii=False)
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


def run_tool(name, args, role="System"):
    if role == "Falsifier" and name in {"write_file", "edit_file", "edit_file_range", "backup_file"}:
        return "error: Falsifier is read-only and may not modify files"
    if role == "Repairer" and name in {"write_file", "backup_file"}:
        return "error: Repairer may only make focused edits"
    issue = tool_argument_error(name, args)
    if issue:
        return issue
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
        return json.dumps(browser_workspace_snapshot(args["path"], "tool", profile=profile), ensure_ascii=False)
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
    return {
        "run_id": RUN_ID, "source_sha256": _source_hash(), "mode": mode, "model": MODEL,
        "model_capabilities": sorted(MODEL_CAPABILITIES),
        "role_models": {role: MODEL for role in MODEL_POLICY.role_models()},
        "clarification_questions": 0,
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
        "alternate_strategies_attempted": 0,
        "strategy_rescues": 0,
        "strategy_rescue_rate": None,
        "capability_floor_nodes": 0,
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
        "browser_checks": 0, "verification_failures": 0, "task_too_broad_count": 0,
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
    global VISION_ENABLED_FOR_RUN, VISION_ERROR
    RUN_ID = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    ACTIVE_TRANSACTION = None
    LAST_COMMITTED_TRANSACTION = None
    ACTIVE_CONTRACT = None
    ACTIVE_TOOL_CONTRACT = None
    FORCE_CPU_FOR_RUN = False
    RUN = new_metrics(mode)
    TASKS = {}
    ROLE_STATUS = {"Coordinator": "active", "Builder": "waiting", "Falsifier": "waiting",
                   "Repairer": "unused", "Browser": "waiting", "Quality Review": "waiting"}
    DASHBOARD = {"mode": mode, "context": 0, "active_role": "Coordinator", "active_task": "ROOT",
                 "action": "starting", "tool": "-", "event": f"[MODE] {mode}"}
    RUN_STARTED = time.time()
    VISION_ENABLED_FOR_RUN = ENABLE_VISION and bool(VISION_MODEL)
    VISION_ERROR = None
    record_run_event("run_started", mode=mode, model=MODEL, source_sha256=RUN["source_sha256"])


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
    "window.__AGENT_GAME__ with getState(), start(), restart(), move(direction), plus forceCollision/forceCollect/forceWin "
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
                            "Coordinator": 1536, "Quality": 1536}.get(role, 2048),
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


def structured_model_call(prompt_text, validator, label, schema, retries=MAX_STRUCTURED_RETRIES):
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
                                 think=False, provider_retries=0, role="Coordinator" if label != "quality-review" else "Quality")
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
    requirements = []
    for raw_line in str(raw_goal).splitlines():
        line = raw_line.strip()
        match = re.match(r"^(?:[-*•]|\d+[.)])\s+(.+)$", line)
        if match and len(match.group(1).strip()) >= 3:
            requirements.append(match.group(1).strip())
    return requirements


def normalize_goal_contract(raw_goal, contract):
    """Preserve explicit user bullets when a weak model summarizes lossy."""
    normalized = dict(contract or {})
    explicit = extract_explicit_requirements(raw_goal)
    if len(explicit) >= 2:
        normalized["requirements"] = explicit
    normalized.setdefault("status", "ready")
    normalized.setdefault("constraints", [])
    normalized.setdefault("success_criteria", ["every explicit requirement is implemented and verified"])
    normalized["original_goal"] = str(raw_goal)
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


def get_goal_contract(raw_goal, interactive=True):
    explicit = extract_explicit_requirements(raw_goal)
    if len(explicit) >= 2:
        contract = {
            "status": "ready", "question": "", "goal": compact_text(raw_goal.splitlines()[0], 1200),
            "requirements": explicit, "constraints": [],
            "success_criteria": ["every explicit requirement is implemented and verified"],
            "original_goal": raw_goal, "clarifications": [],
        }
        return contract
    answers = []
    for attempt in range(MAX_CLARIFICATION_QUESTIONS + 1):
        result = understand_goal(raw_goal, "\n".join(answers))
        if result["status"] == "ready":
            result = normalize_goal_contract(raw_goal, result)
            result["clarifications"] = list(answers)
            return result
        if attempt >= MAX_CLARIFICATION_QUESTIONS or not interactive:
            return {"status": "question", "question": result.get("question", "clarification required"),
                    "original_goal": raw_goal, "clarifications": list(answers)}
        RUN["clarification_questions"] = RUN.get("clarification_questions", 0) + 1
        print(f"[CLARIFY] {result['question']}")
        answer = read_user_prompt()
        answers.append(f"Q: {result['question']}\nA: {answer}")
    return {"status": "question", "question": "clarification limit reached", "original_goal": raw_goal}


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


def compact_contract(contract, max_chars=8000):
    projection = {
        "goal": compact_text(contract.get("goal", ""), 900),
        "requirements": bounded_list(contract.get("requirements", []), 20, 320),
        "constraints": bounded_list(contract.get("constraints", []), 12, 260),
        "success_criteria": bounded_list(contract.get("success_criteria", []), 12, 260),
    }
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
    responsibilities = task.get("done_when") or list(contract.get("requirements", [])) + list(contract.get("success_criteria", []))
    # An explicit TASK_TOO_BROAD result may force a smaller decomposition.  A
    # generic implementation failure only gets a split when the remaining
    # contract/evidence still indicates a broad scope.
    if (force_smaller and task.get("initial_failure_type") in {"TASK_TOO_BROAD", "INTEGRATION_TOO_BROAD"}) or len(responsibilities) >= 3:
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
    remaining = MAX_TOTAL_TASKS - RUN.get("tasks_created", 0)
    if depth >= MAX_DEPTH or remaining < 2:
        return {"decision": "execute", "reason": "hard budget reached"}
    failure = task.get("failure_evidence", [])[-3:]
    prompt_text = f"""Decide TASK GRANULARITY FIT, not generic complexity.
Question: Is CURRENT NODE small and explicit enough that THIS pinned local model is likely to implement AND verify it reliably in ONE focused Builder execution?
Return only EXECUTE or SPLIT in the schema. Find the coarsest reliable granularity; more splitting is not automatically better.
Consider responsibilities, likely files/interfaces, context needed, independent verification boundaries, dependency complexity, ambiguity, previous failure evidence, model-capacity heuristic, depth, and remaining task budget.
Sequential milestones MAY edit the same file; cohesive/single-file work is NOT a reason to force EXECUTE.
{('The previous focused execution exceeded capacity. SPLIT into materially smaller scope if budget permits.' if force_smaller else '')}
MODEL={MODEL}; CAPACITY_HINT={MODEL_TASK_CAPACITY}/4 heuristic only; DEPTH={depth}/{MAX_DEPTH}; REMAINING={remaining}
ROOT CONTRACT: {compact_contract(contract)}
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


def decompose_task(task, contract, repo_snapshot, parent_summary="", dependency_summaries=None, force_smaller=False):
    if task.get("kind") == "integration":
        return decompose_integration_task(
            task, contract, repo_snapshot, parent_summary, dependency_summaries, force_smaller,
        )
    remaining = MAX_TOTAL_TASKS - RUN.get("tasks_created", 0)
    if remaining < 2:
        return []
    prompt_text = f"""Split CURRENT NODE into 2-4 SMALL STRUCTURED SEQUENTIAL child contracts for the pinned weak local model.
Each child supplies only goal, done_when, scope_hint. Children together must preserve the parent goal.
Prefer independently verifiable milestones. Sequential children MAY touch the same file; never create parallel ownership assumptions.
Do not create arbitrary microtasks like 'write import' or 'create variable' unless previous failure proves larger scope is still too broad.
{('The failed parent still exceeded capacity: make each child materially smaller in simultaneous reasoning/context.' if force_smaller else '')}
ROOT CONTRACT: {compact_contract(contract)}
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
    if len(specs) < 2:
        return []
    children = []
    for index, spec in enumerate(specs, 1):
        child_id = str(index) if task["id"] == "ROOT" else f"{task['id']}.{index}"
        child = make_task(child_id, spec["goal"], task["depth"] + 1, task["id"],
                          spec.get("done_when", []), spec.get("scope_hint", []))
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
This is decomposition BACKTRACKING after a terminal child still returned TASK_TOO_BROAD.
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
    return list(specs)[:MAX_CHILDREN]


def alternate_strategy_schema():
    strategy = {
        "type": "object", "properties": {
            "label": {"type": "string"},
            "approach": {"type": "string"},
            "verification_plan": {"type": "string"},
        },
        "required": ["label", "approach", "verification_plan"],
        "additionalProperties": False,
    }
    return {
        "type": "object", "properties": {
            "strategies": {"type": "array", "items": strategy,
                           "minItems": MAX_ALTERNATE_STRATEGIES, "maxItems": MAX_ALTERNATE_STRATEGIES},
        },
        "required": ["strategies"], "additionalProperties": False,
    }


def _alternate_strategy_validator(data):
    if not isinstance(data, dict) or not isinstance(data.get("strategies"), list):
        return False
    strategies = data["strategies"]
    if len(strategies) != MAX_ALTERNATE_STRATEGIES:
        return False
    for strategy in strategies:
        if not isinstance(strategy, dict) or not all(
            isinstance(strategy.get(key), str) and strategy[key].strip()
            for key in ("label", "approach", "verification_plan")
        ):
            return False
    first = _decomposition_tokens(strategies[0]["approach"])
    second = _decomposition_tokens(strategies[1]["approach"])
    overlap = len(first & second) / max(1, len(first | second))
    return overlap < 0.78 and strategies[0]["label"].casefold() != strategies[1]["label"].casefold()


def _alternate_strategy_fallback(task):
    goal = compact_text(task.get("goal", "the focused node"), 620)
    return [
        {
            "label": "extend_existing_boundary",
            "approach": (
                f"Inspect the existing function or state boundary that already owns this behavior, then make one "
                f"minimal local extension for: {goal}. Preserve existing control flow and interfaces."
            ),
            "verification_plan": "Run the narrowest deterministic check for the existing boundary and the requested outcome.",
        },
        {
            "label": "explicit_state_transition",
            "approach": (
                f"Model the requested behavior as one explicit input/state transition for: {goal}; implement the "
                "smallest observable transition and connect it through the existing entry point."
            ),
            "verification_plan": "Exercise the input/state transition directly and verify the observable before/after state.",
        },
    ]


def search_alternate_strategies(task, contract, failure_result, memory, repo_snapshot,
                                parent_summary="", dependency_summaries=None):
    """Plan two non-mutating strategies for a small implementation failure."""
    RUN["strategy_searches"] = RUN.get("strategy_searches", 0) + 1
    evidence = _failure_evidence_from_result(failure_result)
    node_packet = build_node_context(
        task, contract, get_memory_store(), repo_snapshot, parent_summary, dependency_summaries, evidence,
    )
    prompt_text = f"""Generate exactly TWO materially different implementation strategies for this SMALL failed node.
Do not edit files. Do not propose another decomposition. Strategy A and Strategy B must use different
implementation boundaries or mechanisms, and each must include a cheap executable verification plan.
The current deterministic failure is evidence, not a request to repeat the same approach.

CURRENT NODE: {json.dumps({k: task.get(k) for k in ('goal','done_when','scope_hint')}, ensure_ascii=False)}
FAILURE EVIDENCE: {json.dumps(evidence, ensure_ascii=False)[:3600]}
NODE PACKET: {node_packet[:5200]}
Return only the two candidate strategies in the schema."""
    try:
        data = structured_model_call(
            prompt_text, _alternate_strategy_validator, "alternate-strategy-search", alternate_strategy_schema(),
        )
        strategies = data["strategies"]
    except (StructuredOutputError, KeyError, TypeError, ValueError) as exc:
        strategies = _alternate_strategy_fallback(task)
        record_run_event("structured_fallback", label="alternate-strategy-search", error=str(exc))
    strategies = strategies[:MAX_ALTERNATE_STRATEGIES]
    task["strategy_search"] = {
        "status": "planned",
        "strategies": [
            {"label": compact_text(item.get("label", ""), 80),
             "approach": compact_text(item.get("approach", ""), 700),
             "verification_plan": compact_text(item.get("verification_plan", ""), 400)}
            for item in strategies
        ],
        "failure_evidence": evidence[-4:],
    }
    record_run_event(
        "strategy_search", task_id=task.get("id"),
        strategies=[compact_text(item.get("label", ""), 80) for item in strategies],
    )
    return strategies


def select_alternate_strategy(task, strategies, failure_result):
    """Use one cheap challenger decision; only the selected strategy may mutate."""
    strategies = list(strategies or [])
    if len(strategies) != MAX_ALTERNATE_STRATEGIES:
        return 0
    RUN["challenger_calls"] = RUN.get("challenger_calls", 0) + 1
    schema = {
        "type": "object", "properties": {
            "selected_index": {"type": "integer", "enum": list(range(MAX_ALTERNATE_STRATEGIES))},
            "rationale": {"type": "string"},
        },
        "required": ["selected_index", "rationale"], "additionalProperties": False,
    }

    def validator(data):
        return (
            isinstance(data, dict)
            and data.get("selected_index") in range(MAX_ALTERNATE_STRATEGIES)
            and isinstance(data.get("rationale"), str)
            and bool(data["rationale"].strip())
        )

    prompt_text = f"""Act as a cheap read-only Challenger for one small failed coding node.
Compare the TWO proposed strategies against the deterministic failure. Choose exactly one index for execution.
Prefer the approach that changes the implementation boundary materially, preserves existing interfaces, and has
an executable verification path. Do not edit files and do not invent a third strategy.
NODE: {json.dumps({k: task.get(k) for k in ('goal','done_when','scope_hint')}, ensure_ascii=False)}
FAILURE: {json.dumps(_failure_evidence_from_result(failure_result), ensure_ascii=False)[:2600]}
STRATEGIES: {json.dumps(strategies, ensure_ascii=False)[:4200]}"""
    try:
        choice = structured_model_call(prompt_text, validator, "strategy-challenger", schema)
    except (StructuredOutputError, KeyError, TypeError, ValueError) as exc:
        choice = {"selected_index": 0, "rationale": "deterministic first-candidate fallback"}
        record_run_event("structured_fallback", label="strategy-challenger", error=str(exc))
    index = int(choice.get("selected_index", 0))
    task.setdefault("strategy_search", {})["selected_index"] = index
    task["strategy_search"]["challenger_rationale"] = compact_text(choice.get("rationale", ""), 420)
    record_run_event(
        "strategy_selected", task_id=task.get("id"), selected_index=index,
        rationale=task["strategy_search"]["challenger_rationale"],
    )
    return index


def execute_selected_strategy(task, contract, strategy, failure_result, memory, repo_snapshot,
                              parent_summary="", dependency_summaries=None):
    """Execute and verify only the challenger-selected strategy."""
    strategy = strategy if isinstance(strategy, dict) else {}
    RUN["alternate_strategies_attempted"] = RUN.get("alternate_strategies_attempted", 0) + 1
    label = compact_text(strategy.get("label", "alternative"), 80).replace(" ", "-") or "alternative"
    task_id = f"{task.get('id', 'NODE')}:strategy:{label}"
    node_context = build_node_context(
        task, contract, get_memory_store(), repo_snapshot, parent_summary, dependency_summaries,
        _failure_evidence_from_result(failure_result),
    )
    context = (
        f"{node_context}\n\nSELECTED ALTERNATE STRATEGY (the only candidate to execute):\n"
        f"{json.dumps(strategy, ensure_ascii=False)[:2400]}\n"
        "Implement only this strategy for the current small node. Do not broaden scope or try another strategy. "
        "Run the stated executable verification before stopping."
    )
    global ACTIVE_TOOL_CONTRACT
    ACTIVE_TOOL_CONTRACT = {
        "goal": task["goal"], "requirements": task.get("done_when", []),
        "constraints": contract.get("constraints", []), "success_criteria": task.get("done_when", []),
    }
    begin_transaction(task_id)
    builder = execute_agent_task(
        task["goal"], memory, role="Builder", task_id=task_id, extra_context=context,
    )
    memory = builder.get("memory", memory)
    if builder.get("status") in {"provider_failure", "too_broad"}:
        rollback_transaction()
        result = {
            "status": "failed" if builder.get("status") == "provider_failure" else "too_broad",
            "failure_type": "ENVIRONMENT_ERROR" if builder.get("status") == "provider_failure" else "TASK_TOO_BROAD",
            "summary": builder.get("summary", "alternate strategy execution failed"),
            "memory": memory, "builder": builder,
        }
        task.setdefault("strategy_search", {})["outcome"] = "failed"
        task["strategy_search"]["result"] = compact_text(result["summary"], MAX_NODE_SUMMARY_CHARS)
        return result
    falsifier = falsify_task(task, ACTIVE_TOOL_CONTRACT, memory, builder, repo_snapshot, node_context)
    memory = falsifier.get("memory", memory)
    if falsifier.get("status") == "provider_failure":
        rollback_transaction()
        result = {
            "status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": falsifier.get("summary", ""),
            "memory": memory, "builder": builder, "falsifier": falsifier,
        }
        task.setdefault("strategy_search", {})["outcome"] = "failed"
        task["strategy_search"]["result"] = compact_text(result["summary"], MAX_NODE_SUMMARY_CHARS)
        return result
    browser = optional_browser_check(task, ACTIVE_TOOL_CONTRACT)
    gate = evidence_gate(builder, falsifier, browser)
    event(
        f"[STRATEGY VERIFY {task.get('id')}] {'PASS' if gate.get('passed') else 'FAIL'}",
        role="Quality Review", task=task.get("id"), action="alternate strategy verification",
    )
    if not gate.get("passed"):
        rollback_transaction()
        result = {
            "status": "failed", "failure_type": classify_failure(builder, gate, browser, falsifier),
            "summary": "alternate strategy failed deterministic evidence gate", "memory": memory,
            "builder": builder, "falsifier": falsifier, "browser": browser, "gate": gate,
            "failure_evidence": gate.get("deterministic_failures", []),
        }
        task.setdefault("strategy_search", {})["outcome"] = "failed"
        task["strategy_search"]["result"] = compact_text(result["summary"], MAX_NODE_SUMMARY_CHARS)
        return result
    changed = commit_transaction()
    remember_verified_outcome(task, contract, builder.get("summary", "alternate strategy verified"), changed)
    result = {
        "status": "done", "summary": builder.get("summary", "alternate strategy verified"),
        "memory": memory, "builder": builder, "falsifier": falsifier, "browser": browser,
        "gate": gate, "changed_files": changed, "strategy": strategy,
    }
    task.setdefault("strategy_search", {})["outcome"] = "rescued"
    task["strategy_search"]["result"] = compact_text(result["summary"], MAX_NODE_SUMMARY_CHARS)
    RUN["strategy_rescues"] = RUN.get("strategy_rescues", 0) + 1
    record_run_event("strategy_rescue", task_id=task.get("id"), strategy=label, changed_files=changed)
    return result


def _maybe_search_alternate_strategy(task, contract, leaf_result, memory, repo_snapshot,
                                     parent_summary="", dependency_summaries=None):
    if not isinstance(task, dict) or not isinstance(leaf_result, dict):
        return None
    if leaf_result.get("failure_type") != "IMPLEMENTATION_ERROR" or not _looks_like_tiny_scope(task):
        return None
    strategies = search_alternate_strategies(
        task, contract, leaf_result, memory, repo_snapshot, parent_summary, dependency_summaries,
    )
    if len(strategies) != MAX_ALTERNATE_STRATEGIES:
        return None
    selected = select_alternate_strategy(task, strategies, leaf_result)
    return execute_selected_strategy(
        task, contract, strategies[selected], leaf_result, memory, repo_snapshot,
        parent_summary, dependency_summaries,
    )


def build_node_context(task, root_contract, memory_store, repo_snapshot, parent_summary="",
                       dependency_summaries=None, failure_evidence=None):
    dependency_summaries = dependency_summaries or []
    failure_evidence = failure_evidence or task.get("failure_evidence", [])
    if task.get("kind") == "integration":
        return build_integration_node_packet(
            task, root_contract, repo_snapshot, parent_summary,
            dependency_summaries, failure_evidence,
        )
    try:
        project_invariants = collect_project_invariants() if WORKSPACE is not None else RUN.get("project_invariants", [])
    except Exception:
        project_invariants = RUN.get("project_invariants", [])
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
        "goal": compact_text(task.get("goal", ""), 1100),
        "done_when": bounded_list(task.get("done_when", []), 6, 260),
        "scope_hint": bounded_list(task.get("scope_hint", []), 5, 180),
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
    packet = (
        f"ROOT CONTRACT:\n{compact_contract(root_contract, max_chars=MAX_ROOT_PACKET_CHARS)}\n\n"
        f"CURRENT NODE:\n{json.dumps(current_node, ensure_ascii=False)}\n\n"
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
    repeated_failures = {}
    mutation_failures = {}
    last_verification_signature = ()
    stagnant_verifications = 0
    provider_error = None
    summary = ""
    status = "unknown"
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
                result = issue if issue else run_tool(name, args, role=role)
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
                mutation_failures[str(target)] = mutation_failures.get(str(target), 0) + 1
                if mutation_failures[str(target)] >= 4:
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
        status = "too_broad"
        summary = "TASK_TOO_BROAD: maximum focused tool-step budget reached"

    record_run_event("agent_finished", role=role, task_id=task_id, status=status,
                     summary=compact_text(summary, MAX_NODE_SUMMARY_CHARS), evidence_count=len(evidence))
    return {
        "status": status, "summary": compact_text(summary, MAX_NODE_SUMMARY_CHARS), "messages": messages,
        "memory": memory, "tool_evidence": evidence, "provider_error": provider_error,
        "failure_type": "TASK_TOO_BROAD" if status == "too_broad" else (
            "ENVIRONMENT_ERROR" if status == "provider_failure" else None
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
            runtime_state = page.evaluate("""() => {
                const bridge = window.__AGENT_GAME__ || window.__HOPLINE__ || null;
                const state = bridge && typeof bridge.getState === 'function' ? bridge.getState() : null;
                return {canvasCount: document.querySelectorAll('canvas').length,
                        gameBridge: bridge ? {name: window.__AGENT_GAME__ ? '__AGENT_GAME__' : '__HOPLINE__', state} : null,
                        debugState: state};
            }""")
            interaction_checks = []
            has_game_probe = bool(runtime_state.get("gameBridge"))
            if has_game_probe:
                bridge_expr = "window.__AGENT_GAME__ || window.__HOPLINE__"
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
                        persisted = page.evaluate("""() => {
                            const game = window.__AGENT_GAME__ || window.__HOPLINE__;
                            return game && typeof game.getState === 'function' ? game.getState() : null;
                        }""")
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
                        page.evaluate("""() => {
                            const game = window.__AGENT_GAME__ || window.__HOPLINE__;
                            if (game && typeof game.restart === 'function') game.restart();
                            if (game && typeof game.start === 'function') game.start();
                        }""")
                        before_touch = page.evaluate("""() => {
                            const game = window.__AGENT_GAME__ || window.__HOPLINE__;
                            return game && game.getState ? game.getState() : null;
                        }""")
                        button.click(); page.wait_for_timeout(650)
                        after_touch = page.evaluate("""() => {
                            const game = window.__AGENT_GAME__ || window.__HOPLINE__;
                            return game && game.getState ? game.getState() : null;
                        }""")
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


def discover_web_entrypoint(task, contract=None):
    combined = task.get("goal", "") + " " + compact_contract(contract or {})
    if not any(word in combined.lower() for word in ("web", "browser", "html", "ui", "game", "timer", "frontend")):
        return None
    preferred = WORKSPACE / "index.html"
    if preferred.exists():
        return {"path": "index.html"}
    candidates = sorted(WORKSPACE.glob("*.htm*"))
    return {"path": str(candidates[0].relative_to(WORKSPACE))} if candidates else None


def optional_browser_check(task, contract=None):
    target = discover_web_entrypoint(task, contract)
    if not target:
        return None
    profile = infer_web_profile(task.get("goal", ""), contract or {})
    return browser_workspace_snapshot(target["path"], task["id"], profile=profile)


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
        entry = str(browser_result.get("entry_path") or "index.html")
        failures = [item for item in failures if not (
            item in builder_evidence
            and item.get("tool") == "verify_web_app"
            and str(item.get("target")) == entry
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
    preflight = _effective_preflight(builder_result.get("integration_preflight"))
    gate_has_preflight_failure = any(
        isinstance(item, dict) and item.get("name") == "integration_preflight"
        for item in (gate or {}).get("deterministic_failures", [])
    )
    if (preflight and not preflight.get("passed")) or gate_has_preflight_failure:
        return "INTEGRATION_TOO_BROAD" if builder_result.get("status") == "too_broad" else "INTEGRATION_FAILURE"
    if builder_result.get("status") == "too_broad":
        return "TASK_TOO_BROAD"
    text = json.dumps(gate.get("deterministic_failures", []), ensure_ascii=False).casefold()
    if any(term in text for term in ("cuda", "browser executable", "missing dependency", "provider")):
        return "ENVIRONMENT_ERROR"
    return "IMPLEMENTATION_ERROR"


def _compact_failure_evidence(evidence, max_items=6, item_chars=900):
    """Keep deterministic failure facts without copying model conversations."""
    compacted = []
    for item in list(evidence or [])[-max_items:]:
        if not isinstance(item, dict):
            compacted.append(compact_text(item, item_chars))
            continue
        projected = {}
        for key in ("tool", "target", "kind", "name", "code", "status", "source", "evidence", "result"):
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
        return _integration_failure_evidence(preflight) + _compact_failure_evidence(
            result.get("failure_evidence", []), max_items=4,
        )
    direct = result.get("failure_evidence")
    if isinstance(direct, list) and direct:
        return _compact_failure_evidence(direct)
    gate = result.get("gate")
    if isinstance(gate, dict) and gate.get("deterministic_failures"):
        return _compact_failure_evidence(gate.get("deterministic_failures"))
    builder = result.get("builder")
    if isinstance(builder, dict):
        builder_evidence = evidence_for_review(builder.get("tool_evidence", []))
        if builder_evidence:
            return _compact_failure_evidence(builder_evidence)
    evidence = result.get("tool_evidence")
    if isinstance(evidence, list) and evidence:
        return _compact_failure_evidence(evidence_for_review(evidence) or evidence)
    return []


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
    searchable = json.dumps({"summary": summary, "evidence": evidence}, ensure_ascii=False).casefold()
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

    effective_preflight = _effective_preflight(result.get("integration_preflight"))
    has_integration_preflight = (
        bool(effective_preflight) and not effective_preflight.get("passed")
    ) or any(item.get("kind") == "integration_preflight" for item in evidence if isinstance(item, dict))

    if has_integration_preflight or failure_type in {"INTEGRATION_FAILURE", "INTEGRATION_TOO_BROAD"}:
        category = "local_integration_state_corruption"
        confidence = "high" if has_integration_preflight else "medium"
        rationale = "Verified child work reached a parent integration boundary with concrete shared-state or interface conflicts."
    elif result.get("decomposition_search_exhausted"):
        category = "model_capability_floor"
        confidence = "low"
        rationale = (
            "The original decomposition and the bounded alternative decomposition attempts all remained too broad; "
            "this is evidence for a capability floor or a non-decomposition mechanism, not proof of either."
        )
    elif status == "too_broad" or failure_type == "TASK_TOO_BROAD":
        category = "scope_too_broad"
        confidence = "high"
        if at_max_depth and (task.get("terminal_too_broad") or result.get("terminal_too_broad")):
            rationale = (
                "The Builder reported a capacity/scope overflow at the depth limit; backtrack to the parent and try "
                "a materially different decomposition before considering a capability floor."
            )
        else:
            rationale = "The Builder explicitly reported a capacity/scope overflow."
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
        if at_max_depth and _looks_like_tiny_scope(task) and repeated:
            category = "model_capability_floor"
            confidence = "medium"
            rationale = "A tiny leaf still failed after focused repair attempts at the depth limit; this is a capability-floor hypothesis, not proof."
        elif at_max_depth:
            category = "unknown"
            confidence = "low"
            rationale = "The leaf is at the depth limit, but the evidence is insufficient to separate strategy, dependency, verifier, and capability causes."
        else:
            category = "implementation_strategy_wrong"
            confidence = "medium"
            rationale = "The node had executable implementation evidence but did not satisfy verification; try a different implementation strategy."

    actions = {
        "scope_too_broad": (
            "backtrack_decomposition"
            if at_max_depth and (task.get("terminal_too_broad") or result.get("terminal_too_broad"))
            else ("split" if not at_max_depth else "manual_decomposition_or_budget_review")
        ),
        "implementation_strategy_wrong": "search_or_mutate",
        "local_integration_state_corruption": "parent_repair",
        "model_capability_floor": "declare_limit",
        "verifier_builder_mismatch": "inspect_verifier_contract",
        "dependency_error": "inspect_dependencies_and_interfaces",
        "decomposition_error": "revisit_decomposition_and_order",
        "environment_failure": "environment_retry",
        "unknown": "collect_more_failure_evidence",
    }
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
    }
    return diagnosis


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
    diagnosis = diagnose_failure(task, result, evidence)
    task["failure_diagnosis"] = diagnosis
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
        "alternate_strategies_attempted": int(RUN.get("alternate_strategies_attempted", 0) or 0),
        "strategy_rescues": rescues,
        "strategy_rescue_rate": RUN["strategy_rescue_rate"],
        "capability_floor_nodes": capability_floor,
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
    detected = int(RUN.get("preflight_blocking_conflicts_detected", 0) or 0)
    resolved = int(RUN.get("preflight_blocking_conflicts_resolved", 0) or 0)
    RUN["integration_conflict_resolution"] = (
        round((resolved / detected) * 100, 2) if detected else None
    )
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
        and (item["result"].get("failure_type") == "TASK_TOO_BROAD" or
             str(item["result"].get("status", "")).casefold() == "too_broad")
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
            "terminal child remained TASK_TOO_BROAD"
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
            "terminal_too_broad": task.get("terminal_too_broad"),
            "decomposition_backtracks": int(task.get("decomposition_backtracks", 0) or 0),
            "alternative_decompositions": list(task.get("decomposition_alternatives", []) or [])[-MAX_DECOMPOSITION_ALTERNATIVES:],
            "failed_decompositions": compact_failed_decompositions(task),
            "decomposition_search_exhausted": bool(task.get("decomposition_search_exhausted")),
            "strategy_search": task.get("strategy_search"),
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
        "alternative_decomposition_rescues", "strategy_searches", "alternate_strategies_attempted",
        "strategy_rescues", "capability_floor_nodes",
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


def execute_leaf(task, contract, memory, repo_snapshot, parent_summary="", dependency_summaries=None):
    if task.get("kind") == "integration":
        return execute_integration_leaf(
            task, contract, memory, repo_snapshot, parent_summary, dependency_summaries,
        )
    dependency_summaries = dependency_summaries or []
    RUN["leaf_tasks"] += 1
    node_context = build_node_context(task, contract, get_memory_store(), repo_snapshot,
                                      parent_summary, dependency_summaries, task.get("failure_evidence"))
    context_tokens = max(1, int(len(node_context) / 4))
    RUN["peak_leaf_context_tokens"] = max(RUN["peak_leaf_context_tokens"], context_tokens)
    RUN["_leaf_context_samples"].append(context_tokens)
    begin_transaction(task["id"])
    global ACTIVE_TOOL_CONTRACT
    ACTIVE_TOOL_CONTRACT = {"goal": task["goal"], "requirements": task.get("done_when", []),
                            "constraints": contract.get("constraints", []), "success_criteria": task.get("done_when", [])}
    builder = execute_agent_task(task["goal"], memory, role="Builder", task_id=task["id"], extra_context=node_context)
    memory = builder["memory"]
    if builder["status"] == "too_broad":
        RUN["task_too_broad_count"] += 1
        rollback_transaction()
        failure_evidence = list(evidence_for_review(builder.get("tool_evidence", [])))
        failure_evidence.append({"kind": "task_status", "result": builder.get("summary", "TASK_TOO_BROAD")})
        return {"status": "too_broad", "failure_type": "TASK_TOO_BROAD", "summary": builder["summary"],
                "memory": memory, "builder": builder,
                "failure_evidence": failure_evidence[-6:]}
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
    browser = optional_browser_check(task, ACTIVE_TOOL_CONTRACT)
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
    for _ in range(MAX_REPAIRS_PER_LEAF):
        repaired = repair_task(task, ACTIVE_TOOL_CONTRACT, current_gate["deterministic_failures"], memory, node_context)
        memory = repaired["memory"]
        if repaired["status"] == "provider_failure":
            rollback_transaction()
            return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": repaired["summary"], "memory": memory}
        if repaired["status"] == "too_broad":
            RUN["task_too_broad_count"] += 1
            rollback_transaction()
            return {"status": "too_broad", "failure_type": "TASK_TOO_BROAD", "summary": repaired["summary"],
                    "memory": memory, "failure_evidence": current_gate["deterministic_failures"]}
        # Fresh verification only: do not carry stale Builder/Falsifier failures into the post-repair gate.
        current_browser = optional_browser_check(task, ACTIVE_TOOL_CONTRACT)
        current_gate = evidence_gate(repaired, None, current_browser)
        verify_label = "ROOT VERIFIED" if task.get("id") == "ROOT" and current_gate["passed"] else "VERIFY " + task["id"]
        event(f"[{verify_label}] {'PASS' if current_gate['passed'] else 'FAIL'} (fresh)",
              role="Quality Review", task=task["id"], action="fresh post-repair verification")
        if current_gate["passed"]:
            changed = commit_transaction()
            remember_verified_outcome(task, contract, repaired["summary"], changed)
            result = {"status": "done", "summary": repaired["summary"], "memory": memory, "builder": repaired,
                      "falsifier": falsifier, "browser": current_browser, "gate": current_gate, "changed_files": changed}
            attach_verified_manifest(task, result)
            return result
        failure_type = classify_failure(repaired, current_gate, current_browser, None)
        if failure_type != "IMPLEMENTATION_ERROR":
            rollback_transaction()
            return {"status": "failed", "failure_type": failure_type, "summary": f"fresh verification failed: {failure_type}",
                    "memory": memory}
    rollback_transaction()
    return {"status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "failed deterministic evidence gate after repair limit", "memory": memory,
            "failure_evidence": current_gate["deterministic_failures"]}


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
    node_context = build_node_context(
        task, contract, get_memory_store(), repo_snapshot,
        parent_summary, dependency_summaries, task.get("failure_evidence"),
    )
    context_tokens = max(1, int(len(node_context) / 4))
    RUN["peak_leaf_context_tokens"] = max(RUN["peak_leaf_context_tokens"], context_tokens)
    RUN["_leaf_context_samples"].append(context_tokens)
    begin_transaction(task["id"])
    global ACTIVE_TOOL_CONTRACT
    ACTIVE_TOOL_CONTRACT = {
        "goal": task["goal"], "requirements": task.get("done_when", []),
        "constraints": contract.get("constraints", []), "success_criteria": task.get("done_when", []),
    }
    builder = execute_agent_task(
        task["goal"], memory, role="Builder", task_id=task["id"], extra_context=node_context,
    )
    memory = builder.get("memory", memory)
    if builder.get("status") == "too_broad":
        RUN["task_too_broad_count"] += 1
        task["integration_too_broad"] = True
        rollback_transaction()
        return {
            "status": "too_broad", "failure_type": "INTEGRATION_TOO_BROAD",
            "summary": builder.get("summary", "integration task exceeds capacity"),
            "memory": memory, "builder": builder,
            "failure_evidence": _compact_failure_evidence(builder.get("tool_evidence", [])),
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
    browser = optional_browser_check(task, contract) if preflight_check["passed"] else None
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
    for _ in range(MAX_REPAIRS_PER_LEAF):
        repaired = repair_task(task, contract, current_gate["deterministic_failures"], memory, node_context)
        memory = repaired.get("memory", memory)
        if repaired.get("status") == "provider_failure":
            rollback_transaction()
            return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR",
                    "summary": repaired.get("summary", "integration repair provider failure"), "memory": memory}
        if repaired.get("status") == "too_broad":
            RUN["task_too_broad_count"] += 1
            task["integration_too_broad"] = True
            rollback_transaction()
            return {"status": "too_broad", "failure_type": "INTEGRATION_TOO_BROAD",
                    "summary": repaired.get("summary", "integration repair exceeds capacity"),
                    "memory": memory, "failure_evidence": current_gate["deterministic_failures"]}
        current_preflight = run_integration_preflight(
            task, _integration_child_info_from_context(task), contract,
        )
        task["integration_preflight"]["after"] = current_preflight
        current_check = _integration_child_preflight_check(task, current_preflight)
        current_browser = optional_browser_check(task, contract) if current_check["passed"] else None
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
            "failure_evidence": current_gate.get("deterministic_failures", [])}


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
                                  dependency_summaries=None, failure_evidence=None):
    """Build the bounded packet used only by an integration task leaf."""
    context = task.get("integration_context") if isinstance(task.get("integration_context"), dict) else {}
    try:
        invariants = collect_project_invariants() if WORKSPACE is not None else []
    except Exception:
        invariants = []
    if not invariants:
        invariants = context.get("project_invariants") or RUN.get("project_invariants", [])
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


def build_integration_contract(task, contract, child_info, preflight, root=False, fit=None):
    """Create the parent-facing Hierarchical Integration Contract."""
    return {
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
        evidence.extend(result.get("tool_evidence", []))
        records.append({"id": milestone_id, "status": result.get("status", "failed"),
                        "summary": compact_text(result.get("summary", ""), MAX_NODE_SUMMARY_CHARS),
                        "evidence": _compact_failure_evidence(result.get("tool_evidence", []), max_items=4)})
        if result.get("status") != "done":
            failure_type = "ENVIRONMENT_ERROR" if result.get("status") == "provider_failure" else (
                "INTEGRATION_TOO_BROAD" if result.get("status") == "too_broad" else "INTEGRATION_FAILURE"
            )
            return {"status": "failed", "failure_type": failure_type,
                    "summary": f"integration milestone {milestone_id} failed: {result.get('summary', '')}",
                    "memory": memory, "tool_evidence": evidence, "integration_milestones": records,
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
    RUN["preflight_blocking_conflicts_detected"] = (
        RUN.get("preflight_blocking_conflicts_detected", 0) + initial_conflicts
    )
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
    RUN["preflight_blocking_conflicts_resolved"] = (
        RUN.get("preflight_blocking_conflicts_resolved", 0) + resolved
    )
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
    integration_contract = build_integration_contract(
        task, contract, child_info, preflight_before, root=root, fit=fit,
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
        integration_contract = build_integration_contract(
            task, contract, child_info, preflight_before, root=root, fit=fit,
        )
        integration_contract["integration_tasks"] = integration_info

    begin_transaction(f"aggregate-{label}")
    global ACTIVE_TOOL_CONTRACT
    ACTIVE_TOOL_CONTRACT = {"goal": task["goal"], "requirements": task.get("done_when", []),
                            "constraints": contract.get("constraints", []), "success_criteria": task.get("done_when", [])}
    context = (
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
        return {"status": "failed",
                "failure_type": failure_type, "summary": builder["summary"], "memory": memory,
                "failure_evidence": _integration_failure_evidence(preflight_after) or builder.get("tool_evidence", []),
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
    browser = optional_browser_check(task, ACTIVE_TOOL_CONTRACT) if preflight_after.get("passed") else None
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
        for _ in range(MAX_REPAIRS_PER_LEAF):
            repaired = repair_task(task, ACTIVE_TOOL_CONTRACT, current_gate["deterministic_failures"],
                                   memory, integration_context)
            memory = repaired["memory"]
            if repaired["status"] == "provider_failure":
                _finish_parent_integration(task, passed=False, preflight=current_preflight)
                rollback_transaction(); RUN["integration_failures"] += 1
                return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR",
                        "summary": repaired["summary"], "memory": memory, "children": child_info}
            if repaired["status"] == "too_broad":
                _finish_parent_integration(task, passed=False, preflight=current_preflight)
                rollback_transaction(); RUN["integration_failures"] += 1
                return {"status": "failed", "failure_type": "INTEGRATION_TOO_BROAD",
                        "summary": repaired["summary"], "memory": memory, "children": child_info,
                        "integration_preflight": task["integration_preflight"]}
            current_preflight = run_integration_preflight(task, child_info, contract)
            task["integration_preflight"]["after"] = current_preflight
            current_browser = optional_browser_check(task, ACTIVE_TOOL_CONTRACT) if current_preflight.get("passed") else None
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
                        "children": child_info, "integration_preflight": task["integration_preflight"]}
        _finish_parent_integration(task, passed=False, preflight=current_preflight)
        rollback_transaction(); RUN["integration_failures"] += 1
        terminal_failure_type = "INTEGRATION_FAILURE" if not current_preflight.get("passed") else "IMPLEMENTATION_ERROR"
        return {"status": "failed", "failure_type": terminal_failure_type,
                "summary": "parent integration failed after repair limit", "memory": memory, "gate": current_gate,
                "children": child_info, "integration_preflight": task["integration_preflight"],
                "failure_evidence": _integration_failure_evidence(task["integration_preflight"].get("after"))
                or current_gate.get("deterministic_failures", [])}
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
    return (
        int(child.get("depth", 0) or 0) >= MAX_DEPTH
        and (result.get("failure_type") == "TASK_TOO_BROAD"
             or str(result.get("status", "")).casefold() == "too_broad")
    )


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
    event(
        f"[BACKTRACK {task['id']}] terminal TASK_TOO_BROAD -> alternative decomposition #{attempt_number}",
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
    RUN["re_splits"] += 1
    evidence = list(leaf_result.get("failure_evidence", []))
    if not evidence:
        evidence = [{"kind": "task_status", "result": leaf_result.get("summary", "TASK_TOO_BROAD")}]
    task["failure_evidence"] = evidence[-6:]
    trigger = "INTEGRATION_TOO_BROAD" if is_integration else "TASK_TOO_BROAD"
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
        event(f"[FIT {task['id']}] SPLIT (forced after TASK_TOO_BROAD)", role="Coordinator",
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
        leaf.get("status") == "too_broad"
        or leaf.get("failure_type") == "TASK_TOO_BROAD"
        or (
            task.get("kind") == "integration"
            and leaf.get("failure_type") == "INTEGRATION_TOO_BROAD"
        )
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
    elif leaf.get("failure_type") == "IMPLEMENTATION_ERROR":
        _record_task_failure(task, leaf, phase="leaf")
        resplit = _resplit_after_leaf_failure(
            task, depth, contract, memory, repo_snapshot, parent_summary, dependency_summaries,
            leaf, fit_decider, leaf_executor, aggregator,
        )
        if resplit is not None:
            return resplit
        if task.get("kind") != "integration":
            strategy_result = _maybe_search_alternate_strategy(
                task, contract, leaf, memory, repo_snapshot, parent_summary, dependency_summaries,
            )
            if strategy_result is not None:
                leaf = strategy_result
                memory = leaf.get("memory", memory)

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
    try:
        contract = contract_override or get_goal_contract(user_text, interactive=interactive)
    except ProviderError as exc:
        result = {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": str(exc), "memory": memory}
        if finish:
            finish_metrics("failed")
        return result, memory
    if contract.get("status") == "question":
        result = {"status": "needs_clarification", "summary": contract.get("question", ""), "memory": memory}
        if finish:
            finish_metrics("needs_clarification")
        return result, memory
    repo_snapshot = repo_snapshot or inspect_repository()
    begin_durable_run(contract)
    root = root_task_from_contract(contract)
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
                          initial_decision=None):
    if reset:
        reset_run("recursive")
    elif RUN.get("mode") != "auto":
        RUN["mode"] = "recursive"
    try:
        contract = contract_override or get_goal_contract(user_text, interactive=interactive)
    except ProviderError as exc:
        event(f"[ERROR] {exc}", role="Coordinator", task="ROOT", action="provider failure")
        result = {"status": "failed", "failure_type": "ENVIRONMENT_ERROR",
                  "summary": str(exc), "memory": memory}
        if finish:
            finish_metrics("failed")
        return result, memory
    if contract.get("status") == "question":
        if finish:
            finish_metrics("needs_clarification")
        return {"status": "needs_clarification", "summary": contract.get("question", ""), "memory": memory}, memory
    repo_snapshot = repo_snapshot or inspect_repository()
    begin_durable_run(contract)
    root = root_task_from_contract(contract)
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
    if contract.get("status") == "question":
        finish_metrics("needs_clarification")
        return {"status": "needs_clarification", "summary": contract.get("question", "")}, memory
    repo_snapshot = inspect_repository()
    print(f"[RECON] files={len(repo_snapshot['files'])} languages={','.join(repo_snapshot['languages']) or 'unknown'} truncated={repo_snapshot['truncated']}")
    root = root_task_from_contract(contract)
    # Auto is explicitly decided AFTER Goal Contract + bounded reconnaissance.
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
                                               initial_decision=decision)
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
        checks = {
            "deep recursion": result["status"] == "done" and RUN["max_depth"] >= 3,
            "more than old eight": RUN["tasks_created"] > 8,
            "hard depth budget": RUN["max_depth"] <= MAX_DEPTH,
            "hard task budget": RUN["tasks_created"] <= MAX_TOTAL_TASKS,
            "recon bounded": len(json.dumps(inspect_repository(max_files=5, max_chars=900))) <= 900,
            "node packet bounded": len(build_node_context(root, contract, None, repo)) <= MAX_NODE_PACKET_CHARS,
            "summaries bounded": all(
                len(str(item.get("summary", ""))) <= MAX_NODE_SUMMARY_CHARS for item in compact_task_tree()
            ),
            "falsifier read only": "write_file" not in {t["function"]["name"] for t in tools_for_role("Falsifier")},
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


def read_user_prompt():
    if PROMPT_TOOLKIT_AVAILABLE and sys.stdin.isatty():
        bindings = KeyBindings()
        @bindings.add("enter")
        def _submit(event_obj):
            event_obj.current_buffer.validate_and_handle()
        @bindings.add("escape", "enter")
        def _newline(event_obj):
            event_obj.current_buffer.insert_text("\n")
        return prompt("You> ", multiline=True, key_bindings=bindings).strip()
    return input("You> ").strip()


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
    global WORKSPACE
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
        select_local_ollama_model(args.model)
        WORKSPACE = get_workspace(args.workspace)
    except RuntimeError as exc:
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
