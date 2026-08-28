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

from hivo.evidence import result_failed as evidence_result_failed
from hivo.evidence import evidence_for_review
from hivo.evidence import unresolved_tool_failures
from hivo.browser_checks import run_profile_interactions
from hivo.context import compact_messages
from hivo.http_client import HttpTransportError, get_json as http_get_json, post_json as http_post_json
from hivo.memory import MemoryStore
from hivo.model_policy import GEMMA_MODEL, SingleModelPolicy
from hivo.playbooks import build_execution_stages, classify_project, compact_stage_plan, playbook_context
from hivo.projects import ProjectStore
from hivo.verification import evaluate_web_snapshot, infer_web_profile, interaction_expectations

# ---------------------------------------------------------------------------
# CONFIG - keep model/provider configuration simple for the experiment
# ---------------------------------------------------------------------------

MODEL_POLICY = SingleModelPolicy()
MODEL = GEMMA_MODEL
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_URL = OLLAMA_BASE_URL + "/api/chat"

WORKSPACE = None
DEFAULT_PROJECTS_ROOT = Path(__file__).resolve().parent / "list"
MEMORY_FILE = ".agent_memory.json"
EXPERIMENT_FILE = ".agent_experiment.jsonl"
EVIDENCE_DIR = ".agent_evidence"
RUNS_DIR = ".agent_runs"

MAX_TOOL_STEPS = 28
MAX_STAGE_CONTINUATIONS = 1
MAX_DEPTH = 2
MAX_CHILDREN = 4
MAX_TOTAL_TASKS = 8
MAX_CLARIFICATION_QUESTIONS = 5
MAX_REPAIRS_PER_LEAF = 2
MAX_STRUCTURED_RETRIES = 2
MAX_PROVIDER_RETRIES = 2
OLLAMA_TIMEOUT_SECONDS = 120
CONTEXT_LIMIT_TOKENS = MODEL_POLICY.context_window("builder")
MODEL_TASK_CAPACITY = 2  # auto-derived from the selected local model; 1=very weak ... 4=stronger
ENABLE_VISION = True
MODEL_CAPABILITIES = set()
ROUTER_MODEL = ""
FALLBACK_MODEL = ""
VISION_MODEL = ""
MODEL_CAPABILITY_MAP = {}
VISION_ERROR = None

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
prompt = KeyBindings = PathCompleter = radiolist_dialog = None
sync_playwright = None

RUN = {}
TASKS = {}
ROLE_STATUS = {}
DASHBOARD = {"mode": "baseline", "context": 0, "active_role": "-", "active_task": "-", "action": "-", "tool": "-", "event": "-"}
LIVE_VIEW = None
RUN_STARTED = 0.0
VISION_ENABLED_FOR_RUN = False
RUN_ID = ""
ACTIVE_TRANSACTION = None
ACTIVE_CONTRACT = None
ACTIVE_TOOL_CONTRACT = None
MEMORY_STORE = None
FORCE_CPU_FOR_RUN = False


class ProviderError(RuntimeError):
    """The model provider could not complete a request."""


class StructuredOutputError(RuntimeError):
    """The provider replied, but the structured contract was not satisfied."""


def configure_console_streams(streams=None):
    """Prevent generated Unicode from crashing legacy Windows code pages."""
    for stream in streams or (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="backslashreplace")
            except (OSError, ValueError):
                pass


# ---------------------------------------------------------------------------
# DEPENDENCY BOOTSTRAP
# ---------------------------------------------------------------------------

def _load_optional_imports():
    global RICH_AVAILABLE, PROMPT_TOOLKIT_AVAILABLE, PLAYWRIGHT_AVAILABLE
    global Console, Live, Panel, Table, Tree, Group, Text, prompt, KeyBindings, PathCompleter, radiolist_dialog, sync_playwright

    try:
        rich_console = importlib.import_module("rich.console")
        rich_live = importlib.import_module("rich.live")
        rich_panel = importlib.import_module("rich.panel")
        rich_table = importlib.import_module("rich.table")
        rich_tree = importlib.import_module("rich.tree")
        rich_text = importlib.import_module("rich.text")
        Console, Group = rich_console.Console, rich_console.Group
        Live, Panel, Table, Tree, Text = rich_live.Live, rich_panel.Panel, rich_table.Table, rich_tree.Tree, rich_text.Text
        RICH_AVAILABLE = True
    except ImportError:
        RICH_AVAILABLE = False

    try:
        pt = importlib.import_module("prompt_toolkit")
        kb = importlib.import_module("prompt_toolkit.key_binding")
        completion = importlib.import_module("prompt_toolkit.completion")
        shortcuts = importlib.import_module("prompt_toolkit.shortcuts")
        prompt, KeyBindings = pt.prompt, kb.KeyBindings
        PathCompleter, radiolist_dialog = completion.PathCompleter, shortcuts.radiolist_dialog
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
    missing = [module for module in KNOWN_DEPENDENCIES if importlib.util.find_spec(module) is None]
    if missing and auto_install:
        for module in missing:
            spec = KNOWN_DEPENDENCIES[module]
            print(f"[SETUP] installing missing dependency: {module}")
            result = subprocess.run([sys.executable, "-m", "pip", "install", spec], text=True)
            if result.returncode != 0:
                print(f"[SETUP_ERROR] failed to install {module}")
                print(f"Manual command: {sys.executable} -m pip install '{spec}'")
                return False
        _load_optional_imports()

    still_missing = [module for module in KNOWN_DEPENDENCIES if importlib.util.find_spec(module) is None]
    if still_missing:
        for module in still_missing:
            print(f"[SETUP_ERROR] missing dependency: {module}")
            print(f"Manual command: {sys.executable} -m pip install '{KNOWN_DEPENDENCIES[module]}'")
        return False
    return True



# ---------------------------------------------------------------------------
# LOCAL OLLAMA MODEL SELECTION
# ---------------------------------------------------------------------------

def is_local_ollama_url(url):
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname
        return host in {"127.0.0.1", "localhost", "::1"}
    except Exception:
        return False


def is_cloud_model_name(name):
    lower = str(name).lower()
    return lower.endswith("-cloud") or ":cloud" in lower or "-cloud:" in lower


def fetch_local_ollama_models():
    if not is_local_ollama_url(OLLAMA_BASE_URL):
        raise RuntimeError(
            f"OLLAMA_BASE_URL must point to local Ollama only; got: {OLLAMA_BASE_URL}"
        )
    try:
        response = http_get_json(OLLAMA_BASE_URL + "/api/tags", timeout=5)
    except HttpTransportError as exc:
        raise RuntimeError(
            f"could not reach local Ollama at {OLLAMA_BASE_URL}. "
            f"Start Ollama first (for example: `ollama serve`). Details: {exc}"
        )
    if response.status_code != 200:
        raise RuntimeError(f"local Ollama /api/tags returned status {response.status_code}: {response.text[:300]}")
    try:
        models = response.json().get("models", [])
    except ValueError as exc:
        raise RuntimeError(f"invalid response from local Ollama /api/tags: {exc}")

    local_models = []
    for item in models:
        name = item.get("name") or item.get("model")
        if not name or is_cloud_model_name(name):
            continue
        local_models.append(item)
    local_models.sort(key=lambda item: (item.get("name") or item.get("model") or "").lower())
    return local_models


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
    """Small experimental heuristic; not a scientific model benchmark."""
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


def _model_choice_label(model_info):
    name = model_info.get("name") or model_info.get("model") or "unknown"
    details = model_info.get("details") or {}
    params = details.get("parameter_size") or "? params"
    quant = details.get("quantization_level") or ""
    capacity = infer_model_capacity(model_info)
    suffix = f" | {params}"
    if quant:
        suffix += f" | {quant}"
    suffix += f" | capacity {capacity}/4"
    return name + suffix


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
    global ROUTER_MODEL, FALLBACK_MODEL, VISION_MODEL, MODEL_CAPABILITY_MAP
    MODEL_POLICY.validate(primary_name)
    installed_names = {item.get("name") or item.get("model") for item in models}
    if primary_name not in installed_names:
        raise RuntimeError(f"required local model is not installed: {primary_name}")
    capabilities = fetch_model_capabilities(primary_name)
    MODEL_CAPABILITY_MAP = {primary_name: capabilities}
    ROUTER_MODEL = primary_name
    FALLBACK_MODEL = ""
    VISION_MODEL = primary_name


def select_local_ollama_model(explicit=None):
    global MODEL, MODEL_TASK_CAPACITY, MODEL_CAPABILITIES
    try:
        required_name = MODEL_POLICY.validate(explicit)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    models = fetch_local_ollama_models()
    if not models:
        raise RuntimeError(
            f"no LOCAL Ollama models were found. Install the required model with `ollama pull {required_name}`."
        )

    by_name = {(item.get("name") or item.get("model")): item for item in models}
    if required_name not in by_name:
        raise RuntimeError(
            f"required local model '{required_name}' was not found. "
            f"Install it with `ollama pull {required_name}`."
        )
    chosen = by_name[required_name]

    MODEL = required_name
    MODEL_TASK_CAPACITY = infer_model_capacity(chosen)
    configure_role_models(models, MODEL)
    MODEL_CAPABILITIES = MODEL_CAPABILITY_MAP.get(MODEL, set())
    print(f"[MODEL] {MODEL}")
    print("[PROVIDER] local Ollama only")
    print("[CLOUD MODELS] hidden/disabled by this agent selection")
    print(f"[CAPACITY] {MODEL_TASK_CAPACITY}/4 (AUTO-ESTIMATED FROM MODEL SIZE; EXPERIMENTAL)")
    print(f"[CAPABILITIES] {', '.join(sorted(MODEL_CAPABILITIES)) or 'unknown'}")
    print(f"[ROLE MODELS] every model-backed role={MODEL} | fallback=disabled")
    return chosen


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
        print("[SETUP] installing Playwright Chromium")
        result = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], text=True)
        if result.returncode != 0:
            return False, f"Chromium install failed. Manual command: {sys.executable} -m playwright install chromium"
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(**browser_launch_kwargs())
                browser.close()
            return True, "Chromium installed"
        except Exception as second_exc:
            return False, str(second_exc)


# ---------------------------------------------------------------------------
# TOOLS - preserved from the original harness
# ---------------------------------------------------------------------------

TOOLS = [
    {"type": "function", "function": {
        "name": "write_file",
        "description": (
            "Create a NEW file. Always provide path before content. Existing files are protected; "
            "use edit_file for focused changes. Keep one call compact enough to finish completely."
        ),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": (
            "Safely replace one SMALL exact text fragment in an existing file. Always provide path, old, then new. "
            "Use multiple compact edits instead of one large rewrite so the tool call cannot be truncated."
        ),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"},
            "expected_replacements": {"type": "integer", "minimum": 1, "maximum": 20}},
            "required": ["path", "old", "new"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "read_file_range",
        "description": (
            "Read a bounded 1-based line range with line numbers. Use this before edit_file_range "
            "or when a full file is too large."
        ),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1}},
            "required": ["path"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "edit_file_range",
        "description": (
            "Replace a bounded 1-based line range after reading it. This is more reliable than a large exact old/new "
            "replacement. Always provide path, start_line, end_line, then compact new content."
        ),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
            "new": {"type": "string"}},
            "required": ["path", "start_line", "end_line", "new"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file's content.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "backup_file",
        "description": "Make a timestamped backup copy of a file without changing it.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "list_files",
        "description": "List the files in the workspace.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "run_file",
        "description": "Run a code file (.py, .js, or .cpp) and return its output, so errors can be found and fixed.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "run_command",
        "description": "Run a simple terminal command inside the workspace. Dangerous commands are refused.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"}}, "required": ["command"]},
    }},
    {"type": "function", "function": {
        "name": "verify_web_app",
        "description": "Serve an HTML file from the workspace, open it in Chromium, capture runtime errors/state and a screenshot.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"], "additionalProperties": False},
    }},
]

TOOL_DEFINITIONS = {item["function"]["name"]: item["function"] for item in TOOLS}


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
        f"error: incomplete or truncated {name} tool call; missing required arguments: {', '.join(missing)}. "
        "Retry with every required field, put path first when present, and use smaller content/edit fragments. "
        "No file was changed."
    )


# ---------------------------------------------------------------------------
# WORKSPACE SECURITY - preserved behavior
# ---------------------------------------------------------------------------

def safe_path(path_str):
    try:
        candidate = Path(path_str)
        if not candidate.is_absolute():
            candidate = WORKSPACE / candidate
        resolved = candidate.resolve()
        return resolved if resolved.is_relative_to(WORKSPACE) else None
    except Exception:
        return None


FILE_WORDS = ("explain", "read", "modify", "update", "edit", "fix", "change", "run", "open")


def precheck_file_reference(user_text):
    lower = user_text.lower()
    if any(word in lower for word in ("create", "make", "generate", "write")):
        return None
    if not any(w in lower for w in FILE_WORDS):
        return None

    for token in user_text.replace("\\", "/").split():
        token = token.strip(".,;:'\"")
        if "." in token or "/" in token:
            target = safe_path(token)
            if target is None:
                return "[ERROR] Access denied. Files outside the selected workspace are not allowed."
            if not target.exists():
                return "[ERROR] File not found inside workspace."
            return None
    return None


# ---------------------------------------------------------------------------
# MEMORY - durable SQLite ledger with bounded verified retrieval
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
    recent_files = store.recent_files() if store else []
    resumable = store.latest_resumable_run(exclude_run_id=RUN_ID or None) if store else None
    if resumable:
        print(
            f"[MEMORY] durable unfinished run available: {resumable['run_id']} "
            f"({len(resumable.get('tasks', []))} ledger task(s))"
        )
    return {
        "workspace": str(WORKSPACE),
        "memory_db": str(store.db_path) if store else "",
        "recent_files": recent_files,
        # Kept as a bounded compatibility field; full history lives in SQLite.
        "operations": [],
        "last_error": None,
        "last_fix_attempt": None,
        "resume_snapshot": resumable,
    }


def relevant_memory_context(query, role="Builder", memory=None):
    store = get_memory_store()
    if not store:
        return ""
    max_chars = 2200 if role in {"Builder", "Repairer"} else 1000
    try:
        verified_budget = int(max_chars * 0.7)
        verified = store.context_for(query, max_items=6, max_chars=verified_budget)
        resumable = store.resumable_context(
            query,
            max_chars=max_chars - verified_budget,
            snapshot=(memory or {}).get("resume_snapshot"),
        )
        return "\n\n".join(item for item in (verified, resumable) if item)[:max_chars]
    except Exception as exc:
        print(f"[WARN] could not retrieve durable memory: {exc}")
        return ""


def tool_result_failed(result):
    return evidence_result_failed(result)


_INTERACTION_DIAGNOSES = {
    "timer_start_changes_visible_time": (
        "The Start button was activated and the deterministic browser clock advanced 1200 ms, but the visible "
        "countdown did not decrease. Inspect the real click handler, interval/tick creation, and any duplicate or "
        "immediate reset logic; this is executable code evidence, not a screenshot opinion."
    ),
    "timer_pause_freezes_visible_time": (
        "Pause is evaluated after Start. If Start did not change the clock, fix Start first; otherwise ensure Pause "
        "clears the one active interval without resetting the displayed value."
    ),
    "timer_reset_restores_visible_time": (
        "Reset did not restore the configured phase duration after real Start/Pause interaction."
    ),
    "timer_duration_configuration": (
        "The verifier requires two visible numeric duration inputs. A valid Focus value must update the visible "
        "clock after input/change and optional Save Settings, and each duration needs a positive min bound that "
        "makes a below-minimum value invalid."
    ),
    "timer_phase_switches_and_counts_session": (
        "A full deterministic phase duration elapsed. Both the visible phase label and completed-session count must "
        "change through the real timer logic."
    ),
    "settings_persistence": (
        "A visible numeric setting was changed, change/blur was dispatched, Save/Apply was clicked when present, "
        "and the page was reloaded; the requested value did not survive."
    ),
    "keyboard_activation": "Focusing the primary Start button and pressing Enter did not activate it.",
    "responsive_no_overflow": "The 390px viewport produced horizontal overflow or no usable visible controls.",
    "reduced_motion": "With prefers-reduced-motion enabled, non-trivial CSS motion remained active.",
}


def verification_failure_signature(result):
    """Return a port- and prose-independent signature for repeated web failures."""
    try:
        payload = json.loads(str(result))
    except (TypeError, ValueError):
        return ()
    if not isinstance(payload, dict) or payload.get("passed"):
        return ()
    signals = []
    for item in payload.get("interaction_checks") or []:
        if not isinstance(item, dict) or item.get("passed") or not item.get("name"):
            continue
        name = str(item["name"])
        if name == "timer_phase_switches_and_counts_session":
            problems = []
            before_phase = item.get("before_phase")
            after_phase = item.get("after_phase")
            if not before_phase or not after_phase or before_phase == after_phase:
                problems.append("phase_not_changed")
            before_count = item.get("before_count")
            after_count = item.get("after_count")
            if before_count is None or after_count is None:
                problems.append("completed_count_missing")
            elif after_count <= before_count:
                problems.append("completed_count_not_incremented")
            signals.extend(f"interaction:{name}:{problem}" for problem in (problems or ["failed"]))
        else:
            signals.append(f"interaction:{name}")
    signals.extend(
        f"failure:{item.get('code')}"
        for item in payload.get("failures") or []
        if isinstance(item, dict) and item.get("code") not in {"failed_interaction"}
    )
    signals.extend(f"page:{str(item)[:120]}" for item in payload.get("page_errors") or [])
    signals.extend(f"console:{str(item)[:120]}" for item in payload.get("console_errors") or [])
    if payload.get("environment_error"):
        signals.append("environment_error")
    return tuple(sorted(set(signals or ["web_verification_failed"])))


def verification_failure_digest(result, limit=1800):
    """Project verbose browser JSON into the exact actionable evidence Gemma needs."""
    try:
        payload = json.loads(str(result))
    except (TypeError, ValueError):
        return compact_text(str(result), limit)
    if not isinstance(payload, dict):
        return compact_text(str(result), limit)
    failed = []
    for item in payload.get("interaction_checks") or []:
        if not isinstance(item, dict) or item.get("passed"):
            continue
        name = str(item.get("name") or "unknown_interaction")
        projection = {key: item[key] for key in (
            "name", "before", "after", "before_phase", "after_phase",
            "before_count", "after_count", "missing", "evidence",
        ) if key in item}
        missing = set(projection.get("missing") or [])
        if "clock" in missing:
            projection["diagnosis"] = (
                "No visible countdown could be recognized. Render the live value as combined MM:SS or HH:MM:SS "
                "text in one visible clock container; nested spans are allowed. Inspect the markup/display update "
                "before changing button or interval logic."
            )
        elif name == "timer_phase_switches_and_counts_session" and (
            projection.get("before_count") is None or projection.get("after_count") is None
        ):
            projection["diagnosis"] = (
                "The phase may already switch, but no dedicated completed-session counter was recognized. Add a "
                "visible label such as 'Completed Sessions: 0' and increment it to 1 only when a focus phase "
                "finishes. 'Session 1' inside phase/status prose is a current-session ordinal and does not satisfy "
                "the completed-session count. Preserve the working phase transition."
            )
        else:
            projection["diagnosis"] = _INTERACTION_DIAGNOSES.get(
                name, "The required real-browser interaction did not produce its observable outcome."
            )
        failed.append(projection)
    digest = {
        "passed": bool(payload.get("passed")),
        "environment_error": bool(payload.get("environment_error")),
        "page_errors": payload.get("page_errors") or [],
        "console_errors": payload.get("console_errors") or [],
        "failed_interactions": failed,
        "failures": payload.get("failures") or [],
    }
    return json.dumps(digest, ensure_ascii=False, default=str)[:max(100, int(limit))]


def update_memory(memory, tool_name, tool_args, result, role=None, task_id=None):
    path_arg = tool_args.get("path")
    if path_arg:
        if path_arg in memory["recent_files"]:
            memory["recent_files"].remove(path_arg)
        memory["recent_files"] = [path_arg] + memory["recent_files"][:9]

    memory["operations"] = memory.get("operations", [])[-7:] + [{
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tool": tool_name, "args": _sanitize_event_value(tool_args), "result": str(result)[:500],
    }]

    if tool_name in ("run_file", "run_command", "verify_web_app"):
        if not tool_result_failed(result):
            memory["last_error"] = None
        elif tool_name == "verify_web_app":
            memory["last_error"] = verification_failure_digest(result)
        else:
            memory["last_error"] = str(result)[:800]

    if (tool_name in ("write_file", "edit_file", "edit_file_range") and path_arg and memory.get("last_error")
            and not tool_result_failed(result)):
        memory["last_fix_attempt"] = f"Edited {path_arg} after an error"

    record_run_event("tool_result", tool=tool_name, args=tool_args, result=str(result))

    try:
        store = get_memory_store()
        if store:
            store.record_event(
                run_id=RUN_ID or None,
                task_id=task_id,
                role=role,
                tool=tool_name,
                target=str(path_arg or tool_args.get("command") or ""),
                status="failed" if tool_result_failed(result) else "succeeded",
                content=str(result),
                details={
                    "args": _sanitize_event_value(tool_args),
                    "model": MODEL,
                    "mutation_author": "model_tool_call" if tool_name in {
                        "write_file", "edit_file", "edit_file_range",
                    } else None,
                },
            )
            if (
                role == "Builder" and tool_name == "write_file" and path_arg
                and not tool_result_failed(result)
            ):
                store.mark_model_artifact(path_arg, RUN_ID or None)
            elif (
                role == "Builder" and tool_name in {"edit_file", "edit_file_range"} and path_arg
                and not tool_result_failed(result)
            ):
                store.refresh_unverified_model_artifact(path_arg, RUN_ID or None)
            memory["recent_files"] = store.recent_files()
    except (OSError, ValueError) as exc:
        print(f"[WARN] could not save durable memory event: {exc}")
    return memory


# ---------------------------------------------------------------------------
# TOOL IMPLEMENTATIONS - intentionally kept simple
# ---------------------------------------------------------------------------

def begin_transaction(task_id):
    global ACTIVE_TRANSACTION
    if ACTIVE_TRANSACTION is not None:
        raise RuntimeError(f"transaction already active for {ACTIVE_TRANSACTION['task_id']}")
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
    global ACTIVE_TRANSACTION
    task_id = (ACTIVE_TRANSACTION or {}).get("task_id")
    changed = sorted((ACTIVE_TRANSACTION or {}).get("files", {}))
    ACTIVE_TRANSACTION = None
    record_run_event("transaction_commit", task_id=task_id, changed=changed)
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
    run_name = RUN_ID or stamp
    relative = target.relative_to(WORKSPACE)
    backup_path = WORKSPACE / ".agent_backups" / run_name / relative
    try:
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        if backup_path.exists():
            backup_path = backup_path.with_name(backup_path.name + f".{stamp}")
        shutil.copy2(target, backup_path)
        return f" (managed backup: {backup_path.relative_to(WORKSPACE)})"
    except OSError as exc:
        return f"error: backup failed, file NOT changed: {exc}"


def source_validation_error(target, content):
    """Return a deterministic syntax error without mutating the workspace."""
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
        blocks = re.findall(
            r"<script(?![^>]*\bsrc=)(?![^>]*type=[\"'](?:application|application/ld)\/json[\"'])[^>]*>([\s\S]*?)</script>",
            text,
            flags=re.IGNORECASE,
        )
        javascript = "\n;\n".join(blocks)
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
        detail = compact_text(checked.stderr or checked.stdout, 500)
        return f"JavaScript syntax validation failed: {detail}"
    return None


def write_file(path, content, role="System"):
    target = safe_path(path)
    if target is None:
        return f"error: '{path}' is outside the workspace."
    transaction_snapshot = (ACTIVE_TRANSACTION or {}).get("files", {}).get(str(target))
    created_in_transaction = bool(transaction_snapshot and not transaction_snapshot.get("existed"))
    resumable_model_artifact = False
    if role == "Repairer":
        return "error: Repairer cannot replace files with write_file; use a focused edit_file change"
    if target.exists() and role == "Builder" and not created_in_transaction:
        store = get_memory_store()
        resumable_model_artifact = bool(
            ACTIVE_TRANSACTION is not None and store
            and store.is_unverified_model_artifact(target)
        )
        if not resumable_model_artifact:
            return (
                "error: write_file cannot replace an existing user-owned or verified file; "
                "read it and use edit_file for a focused verified change"
            )
    note = backup(target) if target.exists() and not created_in_transaction else ""
    if note.startswith("error"):
        return note
    validation_error = source_validation_error(target, content)
    if validation_error:
        return f"error: {validation_error}; file was not changed"
    try:
        _transaction_capture(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        ownership = ""
        if role == "Builder":
            ownership = (
                " (resumed unverified model artifact; Builder may revise it in this transaction)"
                if resumable_model_artifact
                else " (transaction-owned; Builder may revise it with write_file)"
            )
        return f"wrote file: {target}{ownership}{note}"
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
    actual = original.count(old)
    expected = expected_replacements or 1
    if actual != expected:
        return f"error: expected {expected} exact replacement(s), found {actual}; file was not changed"
    candidate = original.replace(old, new, expected)
    validation_error = source_validation_error(target, candidate)
    if validation_error:
        return f"error: {validation_error}; edit was automatically rejected and file was not changed"
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
    selected = lines[start - 1:end]
    return f"[lines {start}-{end} of {len(lines)}]\n" + "\n".join(
        f"{number}: {line}" for number, line in enumerate(selected, start=start)
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
    note = "" if transaction_owned else backup(target)
    if note.startswith("error"):
        return note
    replacement = str(new)
    if end < len(lines) and replacement and not replacement.endswith(("\n", "\r")):
        replacement += "\n"
    candidate = "".join(lines[:start - 1]) + replacement + "".join(lines[end:])
    validation_error = source_validation_error(target, candidate)
    if validation_error:
        return f"error: {validation_error}; edit was automatically rejected and file was not changed"
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
    if target is None:
        return f"error: '{path}' is outside the workspace."
    if not target.exists():
        return f"error: file does not exist, nothing to backup: {target}"
    return f"backup created for {target}{backup(target)}"


def list_files():
    try:
        hidden_agent_names = {
            MEMORY_FILE, EXPERIMENT_FILE, EVIDENCE_DIR, RUNS_DIR, ".hivo",
            ".agent_backups", ".git", ".venv", "__pycache__",
        }
        names = [p.name for p in sorted(WORKSPACE.iterdir())
                 if p.name not in hidden_agent_names and ".backup_" not in p.name]
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
            if re.search(
                r"\b(?:document|localStorage|sessionStorage|navigator|requestAnimationFrame)\b|\bwindow\s*[.[]",
                source,
            ):
                return (
                    "[not_applicable] browser-target JavaScript is not executed under Node because DOM/browser "
                    "globals are intentionally unavailable there. Mutation-time JavaScript syntax validation "
                    "already ran; use verify_web_app on the local HTML entry point for runtime behavior. Do not "
                    "remove valid browser APIs merely to make this Node command run."
                )
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
        return output if output else "(ran successfully, no output)"
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
        return None, "inline Python is not allowed; run a workspace script or approved module"
    if executable == "node" and any(flag in parts for flag in ("-e", "--eval")):
        return None, "inline Node.js is not allowed; run a workspace script"
    if executable == "git":
        subcommand = next((part for part in parts[1:] if not part.startswith("-")), "")
        if subcommand not in {"status", "diff", "log", "show", "ls-files", "rev-parse"}:
            return None, f"git subcommand '{subcommand}' is not read-only and is not allowed"
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
    parts, validation_error = _validated_command_parts(command)
    if validation_error:
        return f"error: command refused: {validation_error}"
    try:
        result = subprocess.run(parts, shell=False, cwd=WORKSPACE,
                                capture_output=True, text=True, timeout=60)
        output = (result.stdout + result.stderr).strip()
        return f"[exit_code={result.returncode}]\n{output or '(no output)'}"
    except subprocess.TimeoutExpired:
        return "error: command timed out (60s limit)"
    except Exception as exc:
        return f"tool error: {exc}"


def run_tool(name, args, role="System"):
    if role == "Falsifier" and name in {"write_file", "edit_file", "edit_file_range", "backup_file"}:
        return "error: Falsifier is read-only and may not modify files"
    if role == "Repairer" and name in {"write_file", "backup_file"}:
        return "error: Repairer may only make focused edit_file changes to existing files"
    argument_error = tool_argument_error(name, args)
    if argument_error:
        return argument_error
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
        return json.dumps(
            browser_workspace_snapshot(args["path"], "tool", profile=profile), ensure_ascii=False
        )
    return f"unknown tool: {name}"


# ---------------------------------------------------------------------------
# SYSTEM PROMPT - unchanged core coding behavior
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a terminal coding agent working ONLY inside one workspace folder. "
    "Never access, describe, or reference any path outside it.\n"
    "Use read_file before explaining or editing a file - never answer from "
    "general knowledge. Use write_file to create a new file, or to continue an unverified model-owned artifact "
    "when the tool explicitly permits it. Other existing files are protected: "
    "use edit_file for the smallest exact change after reading the current content. A file created by Builder in the "
    "active transaction is transaction-owned and may be revised with write_file. After one repeated exact-match failure, "
    "use read_file_range and edit_file_range instead of guessing the old text. Use list_files if unsure what exists. "
    "Use run_file to execute code. For HTML/web work use verify_web_app or run_file on the HTML file, "
    "then inspect the returned browser evidence and screenshot.\n"
    "For every browser game, expose a non-visual test bridge at window.__AGENT_GAME__. It must provide "
    "getState(), start(), restart(), and move(direction). Add forceCollision(), forceCollect(), and forceWin() "
    "when those mechanics are requested. State must include status, score, and best when relevant. "
    "This bridge is required for independent browser verification and must call the real game logic.\n"
    "If a request is unclear or a tool returns an error, say so plainly "
    "instead of guessing.\n"
    "To fix broken code: read_file, run_file, find the demonstrated cause of the error, "
    "edit only that defect, then run fresh verification to confirm it "
    "works, then report what was wrong and what you changed. If it still "
    "fails, repeat rather than giving up after one try.\n"
    "Never attempt destructive or system-altering commands. "
    "When done, give a short final answer with the result."
)

ROLE_SYSTEM_PROMPTS = {
    "Builder": SYSTEM_PROMPT,
    "Repairer": SYSTEM_PROMPT + (
        "\nYou are the Repairer. Change only what deterministic failure evidence demonstrates. "
        "You cannot replace existing files or use write_file. If evidence is missing or an environment/model/visual "
        "check failed, report that condition without editing application code."
    ),
    "Falsifier": (
        "You are a read-only verification agent inside one workspace. Use read_file, list_files, run_file, "
        "run_command, and verify_web_app to seek concrete failures. Never request write_file, edit_file, "
        "or backup_file. Report evidence concisely and do not claim success without verification."
    ),
}


def tools_for_role(role, tool_policy=None):
    if role == "Builder" and tool_policy == "coherent_rewrite":
        allowed = {
            "write_file", "read_file", "read_file_range", "list_files",
            "run_file", "run_command", "verify_web_app",
        }
        return [tool for tool in TOOLS if tool["function"]["name"] in allowed]
    if role == "Builder" and tool_policy == "coherent_rewrite_followup":
        allowed = {
            "edit_file", "edit_file_range", "read_file", "read_file_range", "list_files",
            "run_file", "run_command", "verify_web_app",
        }
        return [tool for tool in TOOLS if tool["function"]["name"] in allowed]
    if role == "Falsifier":
        allowed = {"read_file", "read_file_range", "list_files", "run_file", "run_command", "verify_web_app"}
        return [tool for tool in TOOLS if tool["function"]["name"] in allowed]
    if role == "Repairer":
        allowed = {
            "edit_file", "edit_file_range", "read_file", "read_file_range",
            "list_files", "run_file", "run_command", "verify_web_app",
        }
        return [tool for tool in TOOLS if tool["function"]["name"] in allowed]
    return TOOLS


# ---------------------------------------------------------------------------
# METRICS / TERMINAL VISIBILITY
# ---------------------------------------------------------------------------

def _source_hash():
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return "unavailable"


def _sanitize_event_value(value, key=""):
    if key == "images" and isinstance(value, list):
        return [{"redacted_base64_chars": len(str(item))} for item in value]
    if key == "content" and isinstance(value, str) and len(value) > 10000:
        return {"chars": len(value), "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                "preview": value[:2000]}
    if isinstance(value, dict):
        return {str(k): _sanitize_event_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_event_value(item, key) for item in value]
    return value


def record_run_event(kind, **payload):
    if WORKSPACE is None or not RUN_ID:
        return
    try:
        run_dir = WORKSPACE / RUNS_DIR
        run_dir.mkdir(parents=True, exist_ok=True)
        item = _sanitize_event_value({
            "time": datetime.now().isoformat(timespec="milliseconds"),
            "run_id": RUN_ID,
            "kind": kind,
            **payload,
        })
        with (run_dir / f"{RUN_ID}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        print(f"[WARN] could not write run event: {exc}")


def persist_run_summary():
    if WORKSPACE is None or not RUN_ID:
        return
    try:
        run_dir = WORKSPACE / RUNS_DIR
        run_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "run": RUN,
            "tasks": TASKS,
            "roles": ROLE_STATUS,
            "source": {"path": str(Path(__file__).resolve()), "sha256": _source_hash()},
        }
        (run_dir / f"{RUN_ID}.summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    except OSError as exc:
        print(f"[WARN] could not persist run summary: {exc}")


def new_metrics(mode):
    return {
        "run_id": RUN_ID, "source_sha256": _source_hash(),
        "mode": mode, "model": MODEL, "model_capabilities": sorted(MODEL_CAPABILITIES),
        "role_models": {"router": MODEL, "builder": MODEL,
                        "visual": MODEL, "fallback": None},
        "clarification_questions": 0,
        "tasks_created": 0, "leaf_tasks": 0, "splits": 0, "re_splits": 0,
        "max_depth": 0, "builder_calls": 0, "predictor_calls": 0,
        "challenger_calls": 0, "falsifier_calls": 0, "repairer_calls": 0,
        "quality_reviews": 0, "browser_checks": 0, "verification_failures": 0,
        "task_too_broad_count": 0, "model_calls": 0, "tool_calls": 0,
        "invalid_tool_calls": 0,
        "stage_continuations": 0,
        "coherent_rewrite_recoveries": 0,
        "provider_cpu_fallbacks": 0,
        "provider_execution": "gpu_or_auto",
        "peak_estimated_context_tokens": 0, "elapsed_seconds": 0.0,
        "status": "unknown",
    }


def reset_run(mode):
    global RUN, TASKS, ROLE_STATUS, DASHBOARD, RUN_STARTED, VISION_ENABLED_FOR_RUN, VISION_ERROR
    global RUN_ID, ACTIVE_TRANSACTION, ACTIVE_CONTRACT, ACTIVE_TOOL_CONTRACT, FORCE_CPU_FOR_RUN
    RUN_ID = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    ACTIVE_TRANSACTION = None
    ACTIVE_CONTRACT = None
    ACTIVE_TOOL_CONTRACT = None
    FORCE_CPU_FOR_RUN = False
    RUN = new_metrics(mode)
    TASKS = {}
    ROLE_STATUS = {
        "Coordinator": "active", "Predictor": "unused", "Builder": "waiting",
        "Challenger": "unused", "Falsifier": "waiting", "Quality Review": "waiting",
        "Repairer": "unused", "Browser": "waiting", "Visual QA": "waiting",
    }
    DASHBOARD = {"mode": mode, "context": 0, "active_role": "Coordinator", "active_task": "ROOT",
                 "action": "starting", "tool": "-", "event": f"[MODE] {mode}"}
    RUN_STARTED = time.time()
    VISION_ENABLED_FOR_RUN = ENABLE_VISION and bool(VISION_MODEL)
    VISION_ERROR = None
    record_run_event("run_started", mode=mode, model=MODEL, source_sha256=RUN["source_sha256"])
    try:
        store = get_memory_store()
        if store:
            store.begin_run(RUN_ID, "(goal understanding pending)", {"status": "pending"})
    except Exception as exc:
        print(f"[WARN] could not initialize durable run ledger: {exc}")


def begin_durable_run(contract):
    global ACTIVE_CONTRACT, ACTIVE_TOOL_CONTRACT
    ACTIVE_CONTRACT = dict(contract)
    ACTIVE_TOOL_CONTRACT = dict(contract)
    store = get_memory_store()
    if not store or not RUN_ID:
        return
    try:
        store.begin_run(
            RUN_ID,
            str(contract.get("goal") or contract.get("original_goal") or "coding task"),
            contract,
        )
    except Exception as exc:
        print(f"[WARN] could not start durable run ledger: {exc}")


def set_active_tool_contract(contract):
    """Scope model-invoked verification to the requirements of the active stage."""
    global ACTIVE_TOOL_CONTRACT
    ACTIVE_TOOL_CONTRACT = dict(contract or {})


def update_task_ledger(task_id, goal, status, summary="", parent_id=None, stage_index=None):
    store = get_memory_store()
    if not store or not RUN_ID:
        return
    try:
        store.upsert_task(
            RUN_ID, str(task_id), str(goal), str(status), summary=str(summary),
            parent_id=parent_id, stage_index=stage_index,
        )
    except Exception as exc:
        print(f"[WARN] could not update durable task ledger: {exc}")


def remember_verified_outcome(task, contract, summary, changed_files):
    """Persist only outcomes that already passed deterministic evidence gates."""
    store = get_memory_store()
    if not store:
        return
    profile = classify_project(contract)
    content = (
        f"Verified task completed. Goal: {compact_text(task.get('goal', ''), 500)}. "
        f"Result: {compact_text(summary, 500)}. "
        f"Changed files: {', '.join(changed_files[:20]) or '(none captured)'}"
    )
    try:
        store.add_note(
            content,
            kind="verified_outcome",
            scope=profile,
            verified=True,
            importance=0.8,
            run_id=RUN_ID or None,
            task_id=task.get("id"),
        )
        store.mark_artifacts_verified(changed_files, RUN_ID or None)
    except Exception as exc:
        print(f"[WARN] could not save verified outcome: {exc}")


def estimate_context_tokens(messages):
    chars = 0
    for message in messages:
        chars += len(str(message.get("role", ""))) + len(str(message.get("content", "")))
        chars += len(json.dumps(message.get("tool_calls", []), ensure_ascii=False))
    return max(1, int(chars / 4))


def compact_text(text, limit=120):
    one_line = " ".join(str(text).split())
    return one_line if len(one_line) <= limit else one_line[:limit - 3] + "..."


def prompt_display(text):
    lines = text.count("\n") + 1
    if len(text) > 500 or lines > 1:
        return f"Pasted {len(text):,} chars / {lines:,} lines"
    return compact_text(text, 180)


def _task_tree_node(task_id, tree_node=None):
    task = TASKS[task_id]
    icon = {"pending": "○", "running": "●", "done": "✓", "failed": "✗"}.get(task.get("status"), "○")
    label = f"{icon} {task_id} {compact_text(task.get('goal', ''), 54)}  [{task.get('status', 'pending')}]"
    if tree_node is None:
        node = Tree(label)
    else:
        node = tree_node.add(label)
    for child_id in task.get("children", []):
        _task_tree_node(child_id, node)
    return node


def build_dashboard_renderable():
    if not RICH_AVAILABLE:
        return None
    header = Table.grid(expand=True)
    header.add_column(); header.add_column()
    elapsed = max(0, int(time.time() - RUN_STARTED))
    header.add_row(f"MODEL: {MODEL or '(unset)'}", f"MODE: {DASHBOARD['mode']}")
    header.add_row(f"CAPACITY: {MODEL_TASK_CAPACITY}/4 (EXPERIMENTAL MANUAL)",
                   f"CONTEXT: {DASHBOARD['context']:,} / {CONTEXT_LIMIT_TOKENS:,} est.")
    header.add_row(f"CALLS: {RUN.get('model_calls', 0)}", f"ELAPSED: {elapsed // 60:02d}:{elapsed % 60:02d}")

    tree = _task_tree_node("ROOT") if "ROOT" in TASKS else Tree("○ ROOT pending")
    active = f"Role: {DASHBOARD['active_role']}\nTask: {DASHBOARD['active_task']}\nAction: {DASHBOARD['action']}\nTool: {DASHBOARD['tool']}"
    roles = Table.grid(expand=True)
    for role, status in ROLE_STATUS.items():
        roles.add_row(role, status)
    return Group(Panel(header, title="EXPERIMENT"), Panel(tree, title="TASK TREE"),
                 Panel(active, title="ACTIVE AGENT"), Panel(roles, title="AGENTS / ROLES"),
                 Panel(DASHBOARD["event"], title="RECENT EVENT"))


def refresh_dashboard():
    if LIVE_VIEW is not None and RICH_AVAILABLE:
        try:
            LIVE_VIEW.update(build_dashboard_renderable(), refresh=True)
        except Exception:
            pass


def event(text, role=None, task=None, action=None, tool=None, plain=True):
    if role:
        DASHBOARD["active_role"] = role
    if task:
        DASHBOARD["active_task"] = task
    if action:
        DASHBOARD["action"] = action
    if tool:
        DASHBOARD["tool"] = tool
    DASHBOARD["event"] = text
    if plain and LIVE_VIEW is None:
        print(text)
    record_run_event("status", text=text, role=role, task=task, action=action, tool=tool)
    refresh_dashboard()


def print_context(messages, context_limit=CONTEXT_LIMIT_TOKENS):
    estimate = estimate_context_tokens(messages)
    RUN["peak_estimated_context_tokens"] = max(RUN["peak_estimated_context_tokens"], estimate)
    DASHBOARD["context"] = estimate
    remaining = max(0.0, 100.0 * (1 - estimate / context_limit))
    print(f"[MODEL] {MODEL}")
    print(f"[CALL] {RUN['model_calls']}")
    print(f"[CONTEXT] ESTIMATED {estimate:,} / {context_limit:,} tokens | ~{remaining:.0f}% remaining")
    refresh_dashboard()


def append_metrics():
    if WORKSPACE is None:
        return
    path = WORKSPACE / EXPERIMENT_FILE
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(RUN, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[WARN] could not append experiment metrics: {exc}")


def finish_metrics(status):
    RUN["elapsed_seconds"] = round(time.time() - RUN_STARTED, 2)
    RUN["status"] = status
    print("\n[RUN METRICS]")
    for key, value in RUN.items():
        print(f"{key}: {value}")
    record_run_event("run_finished", status=status, metrics=RUN, tasks=TASKS)
    persist_run_summary()
    append_metrics()
    try:
        store = get_memory_store()
        if store and RUN_ID:
            store.finish_run(RUN_ID, status)
    except Exception as exc:
        print(f"[WARN] could not close durable run ledger: {exc}")


# ---------------------------------------------------------------------------
# OLLAMA CALLS + TINY STRUCTURED JSON HELPER
# ---------------------------------------------------------------------------

def ask_ollama(messages, tools=TOOLS, response_format=None, temperature=None, think=None,
               provider_retries=None, model_override=None, fallback_model=None, role="Builder"):
    global FORCE_CPU_FOR_RUN
    headers = {}
    api_key = os.environ.get("OLLAMA_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    requested_model = model_override or MODEL
    try:
        MODEL_POLICY.validate(requested_model)
    except ValueError as exc:
        raise ProviderError(str(exc)) from exc
    if fallback_model and fallback_model != requested_model:
        raise ProviderError("cross-model fallback is disabled by the single-model policy")

    policy_context_window = MODEL_POLICY.context_window(role)
    context_window = min(policy_context_window, 8192) if FORCE_CPU_FOR_RUN else policy_context_window
    # Reserve substantial context for Gemma's generated tool arguments. CPU
    # fallback uses a tighter projection to keep the combined 8K window safe.
    message_ratio = 1.25 if FORCE_CPU_FOR_RUN else 1.5
    provider_messages = compact_messages(
        messages, max_chars=int(context_window * message_ratio), keep_recent=4
    )
    print_context(provider_messages, context_window)
    payload = {
        "model": requested_model,
        "messages": provider_messages,
        "stream": False,
        "keep_alive": "10m",
        "options": {
            "num_ctx": context_window,
            "num_predict": {
                "Builder": 4096,
                "Repairer": 3072,
                "Falsifier": 1536,
                "Visual": 1024,
                "Quality": 1536,
                "Coordinator": 1536,
            }.get(role, 2048),
        },
    }
    if FORCE_CPU_FOR_RUN:
        payload["options"]["num_gpu"] = 0
        payload["options"]["num_predict"] = min(payload["options"]["num_predict"], 3072)
    if tools is not None:
        payload["tools"] = tools
    if response_format is not None:
        payload["format"] = response_format
    effective_temperature = MODEL_POLICY.temperature(role) if temperature is None else temperature
    payload["options"].update({"temperature": effective_temperature, "seed": 0})
    if think is not None:
        payload["think"] = think

    retry_limit = MAX_PROVIDER_RETRIES if provider_retries is None else max(0, int(provider_retries))
    last_error = "unknown provider error"
    for attempt in range(retry_limit + 1):
        RUN["model_calls"] += 1
        started = time.time()
        record_run_event("model_request", model=requested_model, role=role, attempt=attempt + 1,
                         context_window=context_window, messages=provider_messages,
                         tools=[tool["function"]["name"] for tool in (tools or [])],
                         structured=bool(response_format), think=think)
        try:
            response = http_post_json(
                OLLAMA_URL, headers=headers, timeout=OLLAMA_TIMEOUT_SECONDS, payload=payload
            )
        except HttpTransportError as exc:
            last_error = f"could not reach Ollama at {OLLAMA_URL}: {exc}"
            response = None

        if response is not None and response.status_code in (401, 403):
            raise ProviderError("authentication failed - sign in (`ollama signin`) or check OLLAMA_API_KEY.")
        if response is not None and response.status_code == 200:
            try:
                body = response.json()
                message = body["message"]
            except (ValueError, KeyError) as exc:
                last_error = f"invalid response from the model: {exc}"
            else:
                if message.get("content") or message.get("tool_calls"):
                    record_run_event("model_response", model=requested_model, role=role,
                                     elapsed_seconds=round(time.time() - started, 3), message=message,
                                     done_reason=body.get("done_reason"),
                                     prompt_eval_count=body.get("prompt_eval_count"),
                                     eval_count=body.get("eval_count"))
                    return message
                last_error = "empty response from the model"
        elif response is not None:
            last_error = f"Ollama returned an error (status {response.status_code}): {response.text[:2000]}"

        record_run_event("provider_retry", model=requested_model, role=role,
                         attempt=attempt + 1, error=last_error)
        if attempt < retry_limit:
            transient_worker_crash = any(marker in last_error.casefold() for marker in (
                "llama-server process has terminated", "cuda error", "shared object initialization",
                "connection reset", "eof",
            ))
            if transient_worker_crash and not FORCE_CPU_FOR_RUN:
                FORCE_CPU_FOR_RUN = True
                RUN["provider_cpu_fallbacks"] += 1
                RUN["provider_execution"] = "cpu_only_after_cuda_crash"
                cpu_context = min(policy_context_window, 8192)
                provider_messages = compact_messages(
                    messages, max_chars=int(cpu_context * 1.25), keep_recent=4
                )
                payload["messages"] = provider_messages
                payload["options"]["num_ctx"] = cpu_context
                payload["options"]["num_gpu"] = 0
                payload["options"]["num_predict"] = min(payload["options"]["num_predict"], 3072)
                print(f"[PROVIDER DEGRADE] {requested_model} CPU-only after CUDA worker crash")
                record_run_event(
                    "provider_cpu_fallback", model=requested_model, role=role,
                    context_window=cpu_context,
                )
            delay = (3.0 * (attempt + 1)) if transient_worker_crash else (0.5 * (2 ** attempt))
            record_run_event(
                "provider_backoff", model=requested_model, role=role,
                seconds=delay, transient_worker_crash=transient_worker_crash,
            )
            time.sleep(delay)
    raise ProviderError(last_error)


def _parse_json_content(content):
    text = str(content).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Strict structured output should already be JSON, but tolerate harmless wrapper text.
        left, right = text.find("{"), text.rfind("}")
        if left >= 0 and right > left:
            return json.loads(text[left:right + 1])
        raise


def _normalize_structured_data(data, label):
    """Normalize harmless shape variations without changing the model's semantic decision."""
    if not isinstance(data, dict):
        return data
    if label == "task-fit":
        decision = str(data.get("decision", "")).strip().lower()
        if decision:
            data["decision"] = decision
        data.setdefault("reason", "")
        data.setdefault("subtasks", [])
        if isinstance(data.get("subtasks"), list):
            data["subtasks"] = [str(x).strip() for x in data["subtasks"] if str(x).strip()][:MAX_CHILDREN]
    elif label == "execution-mode":
        mode = str(data.get("mode", data.get("decision", ""))).strip().lower()
        if mode:
            data["mode"] = mode
        data.setdefault("reason", "")
    elif label == "goal-understanding":
        status = str(data.get("status", "")).strip().lower()
        if status:
            data["status"] = status
        data.setdefault("question", "")
        data.setdefault("goal", "")
        for key in ("requirements", "constraints", "success_criteria"):
            data.setdefault(key, [])
    elif label == "quality-review":
        data.setdefault("checks", [])
        for check in data.get("checks", []):
            if isinstance(check, dict) and "status" in check:
                check["status"] = str(check["status"]).strip().upper()
    return data


def structured_model_call(prompt_text, validator, label, schema):
    schema_text = json.dumps(schema, ensure_ascii=False)
    messages = [
        {"role": "system", "content": (
            "Return ONLY one JSON object that exactly matches the supplied JSON Schema. "
            "No markdown, no commentary, no extra keys, no text before or after JSON."
        )},
        {"role": "user", "content": f"{prompt_text}\n\nMANDATORY JSON SCHEMA:\n{schema_text}"},
    ]
    last_error = None
    last_content = ""
    for attempt in range(MAX_STRUCTURED_RETRIES):
        try:
            structured_role = "Quality" if label == "quality-review" else "Coordinator"
            message = ask_ollama(messages, tools=None, response_format=schema, temperature=0, think=False,
                                 provider_retries=0, model_override=MODEL, role=structured_role)
            last_content = message.get("content", "")
            data = _normalize_structured_data(_parse_json_content(last_content), label)
            if validator(data):
                record_run_event("structured_valid", label=label, attempt=attempt + 1, data=data)
                return data
            last_error = f"JSON parsed but failed {label} semantic validation: {json.dumps(data, ensure_ascii=False)}"
        except ProviderError:
            # Provider/network/auth failures are not structured-output mistakes.
            raise
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            last_error = str(exc)

        attempt_no = attempt + 1
        print(f"[STRUCTURED RETRY] {label} {attempt_no}/{MAX_STRUCTURED_RETRIES} | {last_error}")
        record_run_event("structured_invalid", label=label, attempt=attempt_no,
                         error=last_error, raw_content=last_content)
        if attempt_no < MAX_STRUCTURED_RETRIES:
            messages = [
                {"role": "system", "content": (
                    "STRICT JSON REPAIR. Return ONLY one JSON object matching the schema exactly. "
                    "No markdown, no explanation, no additional keys."
                )},
                {"role": "user", "content": (
                    f"Original task context:\n{prompt_text}\n\n"
                    f"The previous {label} output was invalid. Error: {last_error}\n"
                    f"Previous output: {last_content[:1500]}\n"
                    f"Required schema: {schema_text}\n"
                    "Generate a fresh valid object now."
                )},
            ]
    raise StructuredOutputError(
        f"invalid {label} structured response after {MAX_STRUCTURED_RETRIES} strict attempts: {last_error}"
    )


# ---------------------------------------------------------------------------
# REUSABLE EXISTING TOOL LOOP (baseline and recursive leaves share this)
# ---------------------------------------------------------------------------

def tool_recovery_hint(tool_name, result, repeated_failures):
    lower = str(result).casefold()
    if tool_name == "edit_file" and repeated_failures >= 2 and (
        "exact replacement" in lower or "found 0" in lower
    ):
        return (
            "Stop repeating the same exact-string edit. Use read_file_range to inspect numbered lines, then "
            "edit_file_range with a small bounded range. If the Builder created this file in the current "
            "transaction, it may instead issue one complete write_file revision. Re-verify afterward."
        )
    if "incomplete or truncated" in lower and repeated_failures >= 2:
        return (
            "The tool JSON is being truncated. Put path first and make the next write/edit substantially smaller; "
            "prefer read_file_range plus edit_file_range."
        )
    if tool_name == "edit_file_range" and repeated_failures >= 2 and "invalid line range" in lower:
        return (
            "The line numbers are stale or invalid. Read a small current range with read_file_range, then ensure "
            "1 <= start_line <= end_line <= the reported total before one focused edit_file_range. Do not guess "
            "line numbers or replace a protected existing file."
        )
    if repeated_failures >= 2 and "syntax validation failed" in lower:
        return (
            "The proposed edit is repeatedly syntactically incomplete. Re-read the enclosing function or block, "
            "then submit one smaller balanced replacement that includes every required closing delimiter. Run "
            "fresh verification after the accepted edit."
        )
    return ""


def coherent_rewrite_preflight(args):
    """Reject an obvious function fragment before it replaces a full model draft."""
    target = safe_path(args.get("path"))
    content = args.get("content")
    if target is None or not target.is_file() or not isinstance(content, str):
        return ""
    try:
        existing = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    old_size = len(existing.strip())
    new_size = len(content.strip())
    if old_size >= 1200 and new_size < max(300, int(old_size * 0.30)):
        ratio = round((100 * new_size / old_size), 1) if old_size else 0
        return (
            f"error: coherent rewrite rejected before mutation: proposed {new_size}-character content is only "
            f"{ratio}% of the existing {old_size}-character model draft and appears to be a fragment. Re-read "
            "the file and submit one complete replacement that preserves all previously verified behavior, "
            "interfaces, event handlers, and current-stage requirements. No file was changed."
        )
    return ""


def execute_agent_task(
    task_text, memory, messages=None, role="Builder", task_id="ROOT", extra_context="", tool_policy=None,
):
    if messages is None:
        messages = [{"role": "system", "content": ROLE_SYSTEM_PROMPTS.get(role, SYSTEM_PROMPT)}]
    durable_context = relevant_memory_context(
        f"{role} {task_text} {extra_context[:1200]}", role=role, memory=memory,
    )
    if durable_context:
        extra_context = f"{durable_context}\n\n{extra_context}" if extra_context else durable_context
    if extra_context:
        task_text = f"{extra_context}\n\nCURRENT TASK:\n{task_text}"
    messages.append({"role": "user", "content": task_text})
    tool_evidence = []
    status = "unknown"
    summary = ""
    provider_error = None
    repeated_failures = {}
    mutation_failures = {}
    last_mutation_target = None
    last_verification_signature = ()
    stagnant_verifications = 0
    recovery_strategy = None
    recovery_targets = []
    stop_early = False
    coherent_rewrite_written = False
    coherent_followup_unlocked = False

    ROLE_STATUS[role] = "working"
    event(f"[{role.upper()}] {task_id} executing", role=role, task=task_id, action="model/tool loop")

    for _step in range(MAX_TOOL_STEPS):
        active_tool_policy = (
            "coherent_rewrite_followup"
            if tool_policy == "coherent_rewrite" and coherent_followup_unlocked
            else tool_policy
        )
        offered_tools = tools_for_role(role, tool_policy=active_tool_policy)
        offered_tool_names = {
            tool["function"]["name"] for tool in offered_tools
        }
        try:
            assistant_message = ask_ollama(
                messages, tools=offered_tools, role=role,
            )
        except ProviderError as exc:
            provider_error = str(exc)
            status = "provider_failure"
            summary = provider_error
            event(f"[ERROR] {provider_error}", role=role, task=task_id, action="provider failure")
            break

        messages.append(assistant_message)
        tool_calls = assistant_message.get("tool_calls", [])
        if not tool_calls:
            summary = assistant_message.get("content", "") or "done"
            if role in {"Builder", "Repairer"} and not tool_evidence:
                status = "failed"
                summary = "No tool evidence was produced; implementation cannot be marked done. " + summary
            else:
                status = "done"
            break

        for call in tool_calls:
            try:
                name = call["function"]["name"]
                args = call["function"].get("arguments", {})
            except (KeyError, TypeError) as exc:
                result = f"error: malformed tool call: {exc}"
                tool_evidence.append({"tool": "malformed", "target": "-", "result": result})
                messages.append({"role": "tool", "tool_name": "malformed", "content": result})
                continue
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            target = args.get("path") or args.get("command") or "-"
            RUN["tool_calls"] += 1
            event(f"[TOOL] {name} {compact_text(target, 80)}", role=role, task=task_id,
                  action=f"using {name}", tool=name)
            if name not in offered_tool_names:
                RUN["invalid_tool_calls"] += 1
                if active_tool_policy == "coherent_rewrite":
                    result = (
                        f"error: tool {name!r} is unavailable under the active coherent rewrite policy; "
                        "use read tools, then write_file for an eligible unverified model-owned artifact, "
                        "and run fresh verification"
                    )
                elif active_tool_policy == "coherent_rewrite_followup":
                    result = (
                        f"error: tool {name!r} is unavailable during focused post-rewrite repair; "
                        "use one small edit_file or edit_file_range change justified by the fresh evidence, "
                        "then verify"
                    )
                else:
                    result = f"error: tool {name!r} is unavailable for role {role}"
            else:
                argument_issue = tool_argument_error(name, args)
                if argument_issue:
                    RUN["invalid_tool_calls"] += 1
                    result = argument_issue
                else:
                    rewrite_issue = (
                        coherent_rewrite_preflight(args)
                        if active_tool_policy == "coherent_rewrite" and name == "write_file"
                        else ""
                    )
                    if rewrite_issue:
                        result = rewrite_issue
                    else:
                        try:
                            result = run_tool(name, args, role=role)
                        except (KeyError, TypeError, ValueError) as exc:
                            result = f"error: invalid arguments for {name}: {exc}"
            print(f"[RESULT] {str(result)[:300]}")
            projected_result = (
                verification_failure_digest(result, 1400)
                if name == "verify_web_app" and tool_result_failed(result)
                else str(result)[:1000]
            )
            tool_evidence.append({"tool": name, "target": target, "result": projected_result})
            memory = update_memory(memory, name, args, str(result), role=role, task_id=task_id)
            messages.append({"role": "tool", "tool_name": name, "content": str(result)})

            if tool_policy == "coherent_rewrite" and name == "write_file" \
                    and not tool_result_failed(result):
                coherent_rewrite_written = True

            if tool_policy == "coherent_rewrite" and coherent_rewrite_written \
                    and name == "verify_web_app" and tool_result_failed(result):
                coherent_followup_unlocked = True
                messages.append({
                    "role": "user",
                    "content": (
                        "The mandatory coherent rewrite is complete and fresh browser evidence now isolates the "
                        "remaining defect. Focused edit_file/edit_file_range tools are unlocked for a small "
                        "evidence-backed correction. Do not rewrite again; verify immediately after the fix."
                    ),
                })

            # A contract-aware browser verifier is executable proof for the
            # active stage. Weak models commonly keep "polishing" after this
            # point and regress already-correct behavior, so the orchestrator
            # owns the stopping decision instead of asking for another sample.
            if role in {"Builder", "Repairer"} and name == "verify_web_app" \
                    and not tool_result_failed(result):
                status = "done"
                summary = "Deterministic browser verification passed; stop-on-proof completed this stage."
                print("[STAGE VERIFIED] stopping before unnecessary model edits")
                stop_early = True
                break

            failure_key = (name, str(target))
            if tool_result_failed(result):
                repeated_failures[failure_key] = repeated_failures.get(failure_key, 0) + 1
            else:
                repeated_failures[failure_key] = 0
            recovery_hint = tool_recovery_hint(name, result, repeated_failures[failure_key])
            if recovery_hint:
                print(f"[TOOL RECOVERY] {recovery_hint}")
                messages.append({"role": "user", "content": recovery_hint})

            if memory.get("last_error") and name in ("run_file", "run_command", "verify_web_app"):
                print(f"[ERROR DETECTED] {memory['last_error'][:200]}")
                messages.append({
                    "role": "user",
                    "content": (
                        "Verification failed. Decide first whether this is a code defect, a tool capability issue, "
                        "or an environment failure. Only edit code for a demonstrated code defect, then rerun fresh verification."
                    ),
                })
            if name == "write_file" and memory.get("last_fix_attempt"):
                print(f"[FIX ATTEMPT] {memory['last_fix_attempt']}")
            if role == "Builder" and name in {"write_file", "edit_file", "edit_file_range"}:
                if str(target) != "-":
                    last_mutation_target = str(target)
                effective_target = str(target) if str(target) != "-" else last_mutation_target
                if effective_target and tool_result_failed(result):
                    mutation_failures[effective_target] = mutation_failures.get(effective_target, 0) + 1
                    candidate = safe_path(effective_target)
                    store = get_memory_store()
                    rewrite_safe = bool(candidate and (
                        not candidate.exists()
                        or (store and store.is_unverified_model_artifact(candidate))
                    ))
                    if mutation_failures[effective_target] >= 4 and rewrite_safe:
                        status = "too_broad"
                        recovery_strategy = "rewrite_unverified"
                        recovery_targets = [effective_target]
                        summary = (
                            "STAGNANT_MUTATION: repeated invalid or contradictory edits targeted the same "
                            "model-owned artifact; stop patching and use a fresh coherent model-authored rewrite pass"
                        )
                        print("[STAGNATION] repeated mutation failures; routing to coherent rewrite continuation")
                        stop_early = True
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
                    recovery_strategy = "fresh_focused"
                    recovery_targets = list(dict.fromkeys(memory.get("recent_files", [])[:5]))
                    summary = (
                        "STAGNANT_VERIFICATION: the same executable browser failures survived three verification "
                        "cycles; continue in a fresh focused evidence context without replacing the working artifact"
                    )
                    print("[STAGNATION] repeated browser failure; routing to fresh focused continuation")
                    stop_early = True
                    break
        if stop_early:
            break
    else:
        status = "too_broad"
        summary = "TASK_TOO_BROAD: existing maximum tool-step limit reached"
        if role == "Builder" and any(
            key[0] == "verify_web_app" and count >= 3
            for key, count in repeated_failures.items()
        ):
            recovery_strategy = "fresh_focused"
            recovery_targets = [last_mutation_target] if last_mutation_target else []

    ROLE_STATUS[role] = "done" if status == "done" else "failed"
    record_run_event("agent_finished", role=role, task_id=task_id, status=status,
                     summary=summary, tool_evidence=tool_evidence)
    return {
        "status": status, "summary": compact_text(summary, 700), "messages": messages,
        "memory": memory, "tool_evidence": tool_evidence, "provider_error": provider_error,
        "recovery_strategy": recovery_strategy, "recovery_targets": recovery_targets,
    }


# ---------------------------------------------------------------------------
# GOAL UNDERSTANDING / CONTRACT
# ---------------------------------------------------------------------------

def _goal_validator(data):
    if not isinstance(data, dict) or data.get("status") not in {"question", "ready"}:
        return False
    if data["status"] == "question":
        return isinstance(data.get("question"), str) and bool(data["question"].strip())
    return all(isinstance(data.get(key), expected) for key, expected in (
        ("goal", str), ("requirements", list), ("constraints", list), ("success_criteria", list)))


def understand_goal(raw_goal, prior_answers=""):
    prompt_text = f"""Understand this coding request before execution.
Return exactly one JSON object containing ALL schema fields.
If clarification is required:
{{"status":"question","question":"one necessary clarification","goal":"","requirements":[],"constraints":[],"success_criteria":[]}}
If ready:
{{"status":"ready","question":"","goal":"compact goal","requirements":[...],"constraints":[...],"success_criteria":[...]}}
Ask only if a missing fact genuinely blocks safe/correct execution. Prefer inspecting the project or a safe reasonable assumption later.
Preserve the requested outcome and constraints. Do not implement anything.

RAW REQUEST:
{raw_goal}

PRIOR CLARIFICATIONS:
{prior_answers or '(none)'}"""
    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["question", "ready"]},
            "question": {"type": "string"},
            "goal": {"type": "string"},
            "requirements": {"type": "array", "items": {"type": "string"}},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "success_criteria": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["status", "question", "goal", "requirements", "constraints", "success_criteria"],
        "additionalProperties": False,
    }
    try:
        return structured_model_call(prompt_text, _goal_validator, "goal-understanding", schema)
    except (StructuredOutputError, ProviderError) as exc:
        fallback = {
            "status": "ready", "question": "", "goal": compact_text(raw_goal, 1200),
            # Preserve the complete request even when the weak model cannot satisfy
            # the JSON envelope; provider-side context projection remains bounded.
            "requirements": [raw_goal],
            "constraints": [prior_answers] if prior_answers else [],
            "success_criteria": ["The requested outcome is implemented and verified with executable evidence"],
        }
        record_run_event("structured_fallback", label="goal-understanding", error=str(exc), fallback=fallback)
        return fallback


def compact_contract(contract):
    return json.dumps({
        "goal": contract.get("goal", ""),
        "requirements": contract.get("requirements", []),
        "constraints": contract.get("constraints", []),
        "success_criteria": contract.get("success_criteria", []),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# RECURSIVE TASK FIT / DECOMPOSITION
# ---------------------------------------------------------------------------

def _fit_validator(data):
    if not isinstance(data, dict) or data.get("decision") not in {"execute", "split"}:
        return False
    if data["decision"] == "execute":
        return data.get("subtasks") == [] and isinstance(data.get("reason", ""), str)
    subtasks = data.get("subtasks")
    return (isinstance(data.get("reason", ""), str) and isinstance(subtasks, list)
            and 2 <= len(subtasks) <= MAX_CHILDREN
            and all(isinstance(x, str) and x.strip() for x in subtasks))


def task_fit_schema():
    common = {
        "reason": {"type": "string"},
    }
    return {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "decision": {"const": "execute"},
                    **common,
                    "subtasks": {"type": "array", "maxItems": 0},
                },
                "required": ["decision", "reason", "subtasks"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "decision": {"const": "split"},
                    **common,
                    "subtasks": {"type": "array", "items": {"type": "string"},
                                 "minItems": 2, "maxItems": MAX_CHILDREN},
                },
                "required": ["decision", "reason", "subtasks"],
                "additionalProperties": False,
            },
        ]
    }


def deterministic_task_fit(task, depth, contract):
    if depth >= MAX_DEPTH or RUN["tasks_created"] >= MAX_TOTAL_TASKS:
        return {"decision": "execute", "reason": "deterministic recursion limit fallback", "subtasks": []}
    requirements = [str(item).strip() for item in contract.get("requirements", []) if str(item).strip()]
    if depth == 0 and len(requirements) >= 2:
        subtasks = requirements[:min(MAX_CHILDREN, MAX_TOTAL_TASKS - RUN["tasks_created"])]
        if len(subtasks) >= 2:
            return {"decision": "split", "reason": "structured router failed; split by locked requirements",
                    "subtasks": subtasks}
    return {"decision": "execute", "reason": "structured router failed; safe focused execution fallback", "subtasks": []}


def decide_task_fit(task, depth, contract, dependency_summaries=None):
    if depth >= MAX_DEPTH or RUN["tasks_created"] >= MAX_TOTAL_TASKS:
        return {"decision": "execute", "reason": "recursion limit reached"}
    deps = dependency_summaries or []
    prompt_text = f"""Decide whether this task is small/cohesive enough for one focused coding-agent execution.
Return exactly one JSON object containing ALL schema fields.
EXECUTE: {{"decision":"execute","reason":"short reason","subtasks":[]}}
SPLIT: {{"decision":"split","reason":"short reason","subtasks":["...","..."]}}
Split only when there are multiple independently solvable/verifiable pieces with a clear integration boundary, too much context at once, or the task is too broad for one focused execution.
Do not split trivial work or fragment many children that all rewrite the same monolithic file. Children must collectively preserve the parent goal. Prefer 2-3 vertical slices that each leave the workspace coherent and verifiable.
MODEL_TASK_CAPACITY={MODEL_TASK_CAPACITY}/4 (SIZE-DERIVED ADVISORY HINT ONLY). Low capacity alone is not a reason to split; recursion can amplify correlated model errors.
Depth={depth}; max_depth={MAX_DEPTH}; remaining_task_budget={MAX_TOTAL_TASKS - RUN['tasks_created']}.
ROOT CONTRACT: {compact_contract(contract)}
TASK: {task['goal']}
COMPLETED DEPENDENCY SUMMARIES: {json.dumps(deps[-3:], ensure_ascii=False)}
{('ORIGINAL ROOT REQUEST (root planning only): ' + contract.get('original_goal', '')) if depth == 0 else ''}"""
    try:
        return structured_model_call(prompt_text, _fit_validator, "task-fit", task_fit_schema())
    except (StructuredOutputError, ProviderError) as exc:
        fallback = deterministic_task_fit(task, depth, contract)
        record_run_event("structured_fallback", label="task-fit", error=str(exc), fallback=fallback)
        event(f"[TASK-FIT FALLBACK] {task['id']} -> {fallback['decision']}", role="Coordinator",
              task=task["id"], action="deterministic task-fit fallback")
        return fallback


def decompose_task(task, decision):
    available = MAX_TOTAL_TASKS - RUN["tasks_created"]
    if available < 2:
        return []
    goals = decision.get("subtasks", [])[:min(MAX_CHILDREN, available)]
    children = []
    base = task["id"]
    for index, goal in enumerate(goals, 1):
        child_id = str(index) if base == "ROOT" else f"{base}.{index}"
        child = {"id": child_id, "goal": goal, "depth": task["depth"] + 1,
                 "parent": base, "status": "pending", "children": [], "summary": ""}
        TASKS[child_id] = child
        task["children"].append(child_id)
        RUN["tasks_created"] += 1
        RUN["max_depth"] = max(RUN["max_depth"], child["depth"])
        children.append(child)
    return children


# ---------------------------------------------------------------------------
# OPTIONAL ADAPTIVE REASONING ROLES
# ---------------------------------------------------------------------------

def task_risk(task_text):
    lower = task_text.lower()
    high_words = (
        "auth", "security", "migration", "database", "architecture", "refactor", "payment", "permission",
        "concurrent", "game", "physics", "collision", "3d", "webgl", "three.js", "ui", "ux", "animation",
        "responsive", "accessibility", "design",
    )
    if any(word in lower for word in high_words) or len(task_text) > 900:
        return "high"
    low_words = ("css", "rename", "comment", "typo", "readme", "documentation", "format")
    if any(word in lower for word in low_words) and len(task_text) < 400:
        return "low"
    return "normal"


def short_role_call(role, task, contract, instruction):
    metric = role.lower() + "_calls"
    if metric in RUN:
        RUN[metric] += 1
    ROLE_STATUS[role] = "working"
    event(f"[{role.upper()}] {task['id']}", role=role, task=task["id"], action="focused review", tool="-")
    messages = [
        {"role": "system", "content": "Be concise. Do not reveal chain-of-thought. Return only a short checklist or findings."},
        {"role": "user", "content": f"ROOT CONTRACT: {compact_contract(contract)}\nTASK: {task['goal']}\n{instruction}"},
    ]
    try:
        message = ask_ollama(messages, tools=None, role=role)
        text = compact_text(message.get("content", ""), 600)
        ROLE_STATUS[role] = "done"
        return text
    except RuntimeError as exc:
        ROLE_STATUS[role] = "failed"
        return f"{role} unavailable: {exc}"


def run_adaptive_checks(task, contract, memory, builder_result, allow_falsifier=True):
    risk = task_risk(task["goal"])
    predictor = challenger = falsifier = ""
    falsifier_result = None
    if allow_falsifier and risk in {"normal", "high"} and builder_result.get("status") == "done":
        RUN["falsifier_calls"] += 1
        ROLE_STATUS["Falsifier"] = "working"
        instruction = (
            f"ROOT CONTRACT: {compact_contract(contract)}\nTASK: {task['goal']}\n"
            f"BUILDER SUMMARY: {builder_result.get('summary', '')}\n"
            "Act as a Falsifier. Do NOT modify files. Inspect relevant current files and run appropriate existing tests/commands. "
            "Try to prove the implementation wrong. Return concrete failures/evidence or a short verified summary."
        )
        falsifier_result = execute_agent_task(instruction, memory, role="Falsifier", task_id=task["id"])
        memory = falsifier_result["memory"]
        ROLE_STATUS["Falsifier"] = "done" if falsifier_result["status"] == "done" else "failed"
        falsifier = falsifier_result.get("summary", "")

    return {"risk": risk, "predictor": predictor, "challenger": challenger,
            "falsifier": falsifier, "falsifier_result": falsifier_result, "memory": memory}


# ---------------------------------------------------------------------------
# PLAYWRIGHT OPTIONAL BROWSER EVIDENCE
# ---------------------------------------------------------------------------

def browser_snapshot(url, task_id="ROOT", profile=None):
    RUN["browser_checks"] += 1
    ROLE_STATUS["Browser"] = "working"
    event(f"[BROWSER] opening {url}", role="Browser", task=task_id, action="browser verification")
    ok, detail = ensure_browser(install_if_missing=False)
    if not ok:
        ROLE_STATUS["Browser"] = "failed"
        return {"passed": False, "environment_error": True, "evidence": detail}

    evidence_dir = WORKSPACE / EVIDENCE_DIR
    evidence_dir.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id)
    screenshot = evidence_dir / f"task_{safe_id}.png"
    console_errors = []
    page_errors = []
    network_errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**browser_launch_kwargs())
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            if profile and profile.kind == "timer":
                page.clock.install()
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on("response", lambda response: network_errors.append(
                f"{response.status} {response.url}"
            ) if response.status >= 400 and not response.url.endswith("/favicon.ico") else None)
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(800)
            title = page.title()
            final_url = page.url
            text = page.locator("body").inner_text(timeout=5000)[:4000]
            runtime_state = page.evaluate("""() => {
                const bridge = window.__AGENT_GAME__ || window.__HOPLINE__ || null;
                const state = bridge && typeof bridge.getState === 'function' ? bridge.getState() : null;
                return {
                    canvasCount: document.querySelectorAll('canvas').length,
                    viewport: [innerWidth, innerHeight],
                    gameBridge: bridge ? {name: window.__AGENT_GAME__ ? '__AGENT_GAME__' : '__HOPLINE__', state} : null,
                    debugState: state
                };
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

                has_collect_probe = page.evaluate(
                    f"() => typeof ({bridge_expr}).forceCollect === 'function'"
                )
                if has_collect_probe:
                    before_collect = page.evaluate(f"() => ({bridge_expr}).getState()")
                    page.evaluate(f"() => ({bridge_expr}).forceCollect()")
                    page.wait_for_timeout(100)
                    collected_state = page.evaluate(f"() => ({bridge_expr}).getState()")
                    collected = (
                        collected_state.get("score", 0) > (before_collect or {}).get("score", -1)
                        or collected_state.get("collected") != (before_collect or {}).get("collected")
                        or collected_state.get("energy") != (before_collect or {}).get("energy")
                    )
                    interaction_checks.append({"name": "collection_updates_state", "passed": bool(collected),
                                               "before": before_collect, "after": collected_state})

                has_collision_probe = page.evaluate(
                    f"() => typeof ({bridge_expr}).forceCollision === 'function'"
                )
                if has_collision_probe:
                    page.evaluate(f"() => ({bridge_expr}).forceCollision()")
                    page.wait_for_timeout(150)
                    collision_state = page.evaluate(f"() => ({bridge_expr}).getState()")
                    interaction_checks.append({"name": "collision_game_over",
                                               "passed": str(collision_state.get("status", "")).lower()
                                                         in {"gameover", "game-over", "lost", "dead"},
                                               "after": collision_state})
                has_restart_probe = page.evaluate(f"() => typeof ({bridge_expr}).restart === 'function'")
                if has_restart_probe:
                    page.evaluate(f"() => ({bridge_expr}).restart()")
                    page.wait_for_timeout(150)
                    restart_state = page.evaluate(f"() => ({bridge_expr}).getState()")
                    interaction_checks.append({"name": "restart_resets_state",
                                               "passed": str(restart_state.get("status", "")).lower()
                                                         not in {"gameover", "game-over", "lost", "dead"}
                                                         and restart_state.get("score") == 0,
                                               "after": restart_state})
                has_win_probe = page.evaluate(f"() => typeof ({bridge_expr}).forceWin === 'function'")
                if has_win_probe:
                    page.evaluate(f"() => ({bridge_expr}).forceWin()")
                    page.wait_for_timeout(150)
                    win_state = page.evaluate(f"() => ({bridge_expr}).getState()")
                    interaction_checks.append({"name": "goal_win_state",
                                               "passed": str(win_state.get("status", "")).lower()
                                                         in {"won", "win", "complete", "completed"},
                                               "after": win_state})
                    best_before_reload = win_state.get("best")
                    if best_before_reload is not None:
                        page.reload(wait_until="domcontentloaded", timeout=15000)
                        page.wait_for_timeout(350)
                        persistence_state = page.evaluate("""() => {
                            const game = window.__AGENT_GAME__ || window.__HOPLINE__;
                            return game && typeof game.getState === 'function' ? game.getState() : null;
                        }""")
                        best_after_reload = (persistence_state or {}).get("best")
                        interaction_checks.append({
                            "name": "score_persistence",
                            "passed": best_after_reload is not None and best_after_reload >= best_before_reload,
                            "before": best_before_reload, "after": best_after_reload,
                        })

                touch_required = bool(profile and "touch_control" in profile.required_interactions)
                if touch_required:
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_timeout(200)
                touch_selector = (
                    "[data-direction], [data-move], [data-action='up'], "
                    "button[aria-label*='forward' i], button[aria-label*='up' i], .touch-controls button"
                )
                touch_button = page.locator(touch_selector).first
                touch_available = touch_button.count() > 0 and touch_button.is_visible()
                if touch_required and touch_available:
                    page.evaluate("""() => {
                        const game = window.__AGENT_GAME__ || window.__HOPLINE__;
                        if (game && typeof game.restart === 'function') game.restart();
                        if (game && typeof game.start === 'function') game.start();
                    }""")
                    touch_before = page.evaluate("""() => {
                        const game = window.__AGENT_GAME__ || window.__HOPLINE__;
                        return game && game.getState ? game.getState() : null;
                    }""")
                    touch_button.click()
                    page.wait_for_timeout(650)
                    touch_after = page.evaluate("""() => {
                        const game = window.__AGENT_GAME__ || window.__HOPLINE__;
                        return game && game.getState ? game.getState() : null;
                    }""")
                    interaction_checks.append({"name": "touch_control", "passed": touch_after != touch_before,
                                               "before": touch_before, "after": touch_after})
            if profile:
                interaction_checks.extend(run_profile_interactions(page, profile))
            page.set_viewport_size({"width": 1440, "height": 900})
            page.screenshot(path=str(screenshot), full_page=True)
            browser.close()
        print(f"[BROWSER] title={json.dumps(title)}")
        print(f"[BROWSER] console_errors={len(console_errors)}")
        print(f"[SCREENSHOT] {screenshot.relative_to(WORKSPACE)}")
        ROLE_STATUS["Browser"] = "done"
        snapshot = {"passed": False, "environment_error": False,
                    "title": title, "url": final_url, "text": text,
                    "console_errors": console_errors, "page_errors": page_errors,
                    "network_errors": network_errors, "runtime_state": runtime_state,
                    "interaction_checks": interaction_checks,
                    "screenshot": str(screenshot.relative_to(WORKSPACE))}
        effective_profile = profile or infer_web_profile(
            "game" if runtime_state.get("gameBridge") or runtime_state.get("canvasCount") else "web", {}
        )
        return evaluate_web_snapshot(snapshot, effective_profile)
    except Exception as exc:
        ROLE_STATUS["Browser"] = "failed"
        return {"passed": False, "environment_error": True, "evidence": str(exc)}


def browser_inline_snapshot(html, task_id="browser_self_test"):
    """Self-test fallback when the environment blocks file:// and localhost navigation."""
    RUN["browser_checks"] += 1
    evidence_dir = WORKSPACE / EVIDENCE_DIR
    evidence_dir.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id)
    screenshot = evidence_dir / f"task_{safe_id}.png"
    console_errors, page_errors = [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**browser_launch_kwargs())
            page = browser.new_page()
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.set_content(html, wait_until="domcontentloaded")
            title = page.title()
            text = page.locator("body").inner_text()[:4000]
            page.screenshot(path=str(screenshot), full_page=True)
            browser.close()
        return {"passed": not console_errors and not page_errors, "environment_error": False, "title": title,
                "url": "about:blank", "text": text, "console_errors": console_errors,
                "page_errors": page_errors, "screenshot": str(screenshot.relative_to(WORKSPACE))}
    except Exception as exc:
        return {"passed": False, "environment_error": True, "evidence": str(exc)}


def _extract_local_url(text):
    match = re.search(r"https?://(?:127\.0\.0\.1|localhost)(?::\d+)?(?:/\S*)?", text)
    return match.group(0).rstrip(".,);]") if match else None


def browser_workspace_snapshot(path="index.html", task_id="ROOT", profile=None):
    target = safe_path(path)
    if target is None:
        return {"passed": False, "environment_error": False, "evidence": f"path escapes workspace: {path}"}
    if not target.exists() or target.suffix.lower() not in {".html", ".htm"}:
        return {"passed": False, "environment_error": False, "evidence": f"HTML entry not found: {path}"}

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    relative = target.relative_to(WORKSPACE).as_posix()
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=WORKSPACE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )
    try:
        time.sleep(0.35)
        result = browser_snapshot(f"http://127.0.0.1:{port}/{relative}", task_id, profile=profile)
        result["entry_path"] = relative
        return result
    finally:
        server.terminate()
        try:
            server.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=3)


def discover_web_entrypoint(task, contract=None):
    combined = task.get("goal", "") + " " + compact_contract(contract or {})
    lower = combined.lower()
    webish = any(word in lower for word in (
        "web", "frontend", "browser", "html", "css", "react", "page", "ui", "game", "3d", "webgl", "three.js"
    ))
    url = _extract_local_url(combined)
    if url:
        return {"url": url}
    if not webish or WORKSPACE is None:
        return None
    preferred = WORKSPACE / "index.html"
    if preferred.exists():
        return {"path": "index.html"}
    candidates = sorted(WORKSPACE.glob("*.htm*"))
    return {"path": str(candidates[0].relative_to(WORKSPACE))} if candidates else None


def optional_browser_check(task, contract=None):
    target = discover_web_entrypoint(task, contract)
    profile = infer_web_profile(task.get("goal", ""), contract or {})
    if target and target.get("url"):
        return browser_snapshot(target["url"], task["id"], profile=profile)
    if target and target.get("path"):
        return browser_workspace_snapshot(target["path"], task["id"], profile=profile)
    ROLE_STATUS["Browser"] = "unused"
    return None


def maybe_vision_review(browser_result, task, contract):
    global VISION_ENABLED_FOR_RUN, VISION_ERROR
    if VISION_ERROR is not None:
        return VISION_ERROR
    if not VISION_ENABLED_FOR_RUN or not browser_result or not browser_result.get("screenshot"):
        return None
    screenshot = safe_path(browser_result["screenshot"])
    if screenshot is None or not screenshot.exists():
        return None
    try:
        ROLE_STATUS["Visual QA"] = "working"
        image_b64 = base64.b64encode(screenshot.read_bytes()).decode("ascii")
        messages = [{"role": "user", "content": (
            f"Act as Visual QA. Verify this rendered screenshot against the task and contract. "
            "Check hierarchy, composition, legibility, recognizable product/game state, visual defects, empty space, "
            "responsive framing, and visible goal fidelity. Start with exactly PASS:, FAIL:, or UNKNOWN:, followed by "
            "concise concrete evidence. FAIL only for a concrete defect visible in the pixels (blank, clipped, illegible, "
            "broken, placeholder-looking, or visibly off-contract). Use UNKNOWN when behavior such as timers, persistence, "
            "or interactions cannot be proven by one screenshot. Do not praise the design or infer hidden behavior.\n"
            f"Task: {task['goal']}\nContract: {compact_contract(contract)}"
        ),
                     "images": [image_b64]}]
        message = ask_ollama(messages, tools=None, temperature=0, think=False,
                             model_override=MODEL, fallback_model="", role="Visual")
        text = compact_text(message.get("content", ""), 900)
        upper = text.lstrip().upper()
        if not upper.startswith(("PASS:", "FAIL:", "UNKNOWN:")):
            VISION_ERROR = {
                "passed": False,
                "environment_error": True,
                "status": "ERROR",
                "evidence": f"visual model returned an invalid verdict: {text or '(empty)'}",
            }
            ROLE_STATUS["Visual QA"] = "failed"
            VISION_ENABLED_FOR_RUN = False
            return VISION_ERROR
        result = {
            "passed": upper.startswith("PASS:"),
            "environment_error": False,
            "status": "PASS" if upper.startswith("PASS:") else ("FAIL" if upper.startswith("FAIL:") else "UNKNOWN"),
            "evidence": text or "visual model returned no verdict",
        }
        ROLE_STATUS["Visual QA"] = "done"
        record_run_event("vision_review", task_id=task["id"], result=result,
                         screenshot=browser_result.get("screenshot"))
        return result
    except Exception as exc:
        print(f"[WARN] visual verification environment failure: {exc}")
        ROLE_STATUS["Visual QA"] = "failed"
        VISION_ENABLED_FOR_RUN = False
        VISION_ERROR = {
            "passed": False,
            "environment_error": True,
            "status": "ERROR",
            "evidence": f"visual review unavailable: {exc}",
        }
        return VISION_ERROR


# ---------------------------------------------------------------------------
# QUALITY REVIEW / EVIDENCE GATE / REPAIR
# ---------------------------------------------------------------------------

def _quality_validator(data):
    if not isinstance(data, dict) or not isinstance(data.get("checks"), list):
        return False
    allowed = {"PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"}
    for check in data["checks"]:
        if not isinstance(check, dict) or check.get("status") not in allowed:
            return False
        if not isinstance(check.get("name"), str) or not isinstance(check.get("evidence"), str):
            return False
    return True


def deterministic_quality_checks(builder_result, browser_result=None, vision_review=None):
    evidence = builder_result.get("tool_evidence", [])
    checks = []
    if builder_result.get("status") != "done":
        checks.append({"name": "builder_completion", "status": "FAIL",
                       "evidence": f"builder status is {builder_result.get('status')}",
                       "source": "deterministic"})
    if not evidence:
        checks.append({"name": "tool_evidence", "status": "FAIL",
                       "evidence": "no tool evidence was produced", "source": "deterministic"})
    failing_tools = unresolved_tool_failures(evidence)
    if browser_result and browser_result.get("passed"):
        entry = str(browser_result.get("entry_path") or "index.html")
        failing_tools = [item for item in failing_tools if not (
            item.get("tool") in {"verify_web_app", "run_file"}
            and str(item.get("target")) == entry
        )]
    if failing_tools:
        checks.append({"name": "tool_execution", "status": "FAIL",
                       "evidence": compact_text(json.dumps(failing_tools, ensure_ascii=False), 700),
                       "source": "deterministic"})
    verification_tools = {"run_file", "run_command", "verify_web_app"}
    verification_ran = any(item.get("tool") in verification_tools for item in evidence) or browser_result is not None
    if not verification_ran:
        checks.append({"name": "executable_verification", "status": "FAIL",
                       "evidence": "no executable command, file run, or browser check was performed",
                       "source": "deterministic"})
    if browser_result is not None and not browser_result.get("passed"):
        checks.append({"name": "browser_contract", "status": "FAIL",
                       "evidence": compact_text(json.dumps(browser_result, ensure_ascii=False), 700),
                       "source": "deterministic"})
    # A screenshot model is useful critique, but its opinion is not independent
    # deterministic evidence and cannot itself authorize application-code repair.
    return checks


def review_quality(task, contract, builder_result, adaptive, browser_result=None, vision_review=None, fresh=False):
    RUN["quality_reviews"] += 1
    ROLE_STATUS["Quality Review"] = "working"
    event(f"[VERIFY] {'fresh verification' if fresh else task['id']}", role="Quality Review",
          task=task["id"], action="evidence review", tool="-")
    evidence = {
        "builder_status": builder_result.get("status"),
        "builder_summary": builder_result.get("summary"),
        "builder_tool_evidence": evidence_for_review(builder_result.get("tool_evidence", [])),
        "falsifier_summary": adaptive.get("falsifier", ""),
        "falsifier_tool_evidence": evidence_for_review(
            (adaptive.get("falsifier_result") or {}).get("tool_evidence", [])
        ),
        "browser": browser_result,
        "vision_review": vision_review,
    }
    prompt_text = f"""Review this coding task against relevant fixed quality concerns:
correctness, testing, security, clean code/maintainability, architecture consistency, regression, goal fidelity.
Select only concerns relevant to this task. For each return PASS, FAIL, UNKNOWN, or NOT_APPLICABLE with short concrete evidence.
FAIL requires direct evidence that behavior is wrong. Missing or unexecuted evidence is UNKNOWN, never FAIL and never PASS.
Treat narrative Builder/Falsifier claims without matching current tool or browser evidence as advisory, not proof.
Do not say 'looks correct'. Prefer actual command/test/file/browser evidence.
Return JSON: {{"checks":[{{"name":"correctness","status":"PASS","evidence":"..."}}]}}
ROOT CONTRACT: {compact_contract(contract)}
TASK: {task['goal']}
EVIDENCE: {json.dumps(evidence, ensure_ascii=False)[:14000]}"""
    try:
        schema = {
            "type": "object",
            "properties": {
                "checks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "status": {"type": "string", "enum": ["PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"]},
                            "evidence": {"type": "string"},
                        },
                        "required": ["name", "status", "evidence"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["checks"],
            "additionalProperties": False,
        }
        result = structured_model_call(prompt_text, _quality_validator, "quality-review", schema)
    except RuntimeError as exc:
        result = {"checks": [{"name": "verification", "status": "FAIL",
                              "evidence": f"quality review unavailable: {exc}", "source": "model"}]}
    for check in result["checks"]:
        check.setdefault("source", "model")
    result["checks"].extend(deterministic_quality_checks(builder_result, browser_result, vision_review))
    ROLE_STATUS["Quality Review"] = "done"
    record_run_event("quality_review", task_id=task["id"], fresh=fresh, result=result)
    return result


def evidence_gate(builder_result, quality):
    checks = quality.get("checks", [])
    failures = [check for check in checks if (
        check.get("status") == "FAIL" and check.get("source") != "model"
    )]
    advisory_failures = [check for check in checks if (
        check.get("status") == "FAIL" and check.get("source") == "model"
    )]
    deterministic_failure = any(
        check.get("status") == "FAIL" and check.get("source") == "deterministic"
        for check in checks
    )
    passed = builder_result.get("status") == "done" and bool(checks) and not failures and not deterministic_failure
    if not passed:
        RUN["verification_failures"] += 1
    return {"passed": passed, "checks": checks, "deterministic_failure": deterministic_failure,
            "advisory_failures": advisory_failures}


def classify_failure(builder_result, quality, browser_result=None, vision_review=None):
    if builder_result.get("status") == "too_broad":
        return "TASK_TOO_BROAD"
    if builder_result.get("status") == "provider_failure":
        return "ENVIRONMENT_ERROR"
    if browser_result and browser_result.get("environment_error"):
        return "ENVIRONMENT_ERROR"
    if vision_review and vision_review.get("environment_error"):
        return "ENVIRONMENT_ERROR"
    blocking_quality = {
        "checks": [check for check in quality.get("checks", []) if check.get("source") != "model"]
    }
    evidence_text = json.dumps({"quality": blocking_quality, "browser": browser_result}, ensure_ascii=False).lower()
    if any(term in evidence_text for term in ("missing dependency", "browser executable", "cuda error", "provider error")):
        return "ENVIRONMENT_ERROR"
    if "blocked" in evidence_text:
        return "BLOCKED"
    return "IMPLEMENTATION_ERROR"


def repair_task(task, contract, failure_evidence, memory):
    RUN["repairer_calls"] += 1
    ROLE_STATUS["Repairer"] = "working"
    event(f"[REPAIR] task {task['id']}", role="Repairer", task=task["id"], action="focused repair")
    extra = (
        f"ROOT CONTRACT: {compact_contract(contract)}\n"
        f"VERIFIED FAILURE EVIDENCE: {json.dumps(failure_evidence, ensure_ascii=False)[:9000]}\n"
        "Repair only the current task. Inspect current files, make the smallest fix, and run fresh verification."
    )
    result = execute_agent_task(task["goal"], memory, role="Repairer", task_id=task["id"], extra_context=extra)
    ROLE_STATUS["Repairer"] = "done" if result["status"] == "done" else "failed"
    return result


def repair_evidence(quality, gate, browser_result):
    return {
        "deterministic_checks": [
            check for check in quality.get("checks", [])
            if check.get("source") == "deterministic" and check.get("status") == "FAIL"
        ],
        "browser": browser_result,
        "deterministic_failure": gate.get("deterministic_failure", False),
    }


# ---------------------------------------------------------------------------
# FOCUSED LEAF EXECUTION
# ---------------------------------------------------------------------------

def contract_for_task(task, root_contract):
    if task.get("id") == "ROOT":
        return root_contract
    return {
        "status": "ready",
        "goal": task.get("goal", ""),
        "requirements": [task.get("goal", "")],
        "constraints": list(root_contract.get("constraints", [])),
        "success_criteria": ["this leaf's observable behavior is implemented and verified"],
        "original_goal": root_contract.get("original_goal", root_contract.get("goal", "")),
    }


def should_run_visual_review(task):
    if task.get("id") == "ROOT":
        return True
    lower = str(task.get("goal", "")).casefold()
    return any(word in lower for word in (
        "ui", "ux", "visual", "design", "layout", "responsive", "css", "animation",
        "واجهة", "تصميم", "متجاوب",
    ))


def leaf_context(contract, task, parent_summary, dependency_summaries, predictor="", challenger=""):
    return (
        f"ROOT GOAL CONTRACT (compact; authoritative):\n{compact_contract(contract)}\n\n"
        f"{playbook_context(contract)}\n\n"
        f"PARENT CONTEXT: {compact_text(parent_summary or '(none)', 900)}\n"
        f"COMPLETED DEPENDENCIES: {json.dumps(dependency_summaries[-4:], ensure_ascii=False)[:3000]}\n"
        f"PREDICTOR CHECKLIST: {predictor or '(not used)'}\n"
        f"CHALLENGER NOTE: {challenger or '(not used)'}\n"
        "Use the shared workspace as source of truth. Do not assume sibling hidden history. "
        "Implement only this leaf and verify with real evidence where possible."
    )


def execute_builder_stages(task, contract, memory, base_context=""):
    """Give Gemma bounded passes while keeping all generated code model-authored."""
    local_contract = contract if task.get("id") == "ROOT" else {
        "goal": task.get("goal", ""),
        "requirements": [task.get("goal", "")],
        "constraints": contract.get("constraints", []),
        "success_criteria": contract.get("success_criteria", []),
    }
    stages = build_execution_stages(local_contract)
    plan = compact_stage_plan(stages)
    previous_summaries = []
    combined_evidence = []
    stage_records = []
    last_result = None

    for stage in stages:
        stage_id = f"{task['id']}.S{stage['index']}"
        RUN["builder_calls"] += 1
        update_task_ledger(
            stage_id, stage["goal"], "running", parent_id=task.get("id"),
            stage_index=stage["index"],
        )
        event(
            f"[STAGE {stage['index']}/{len(stages)}] {stage['name']}",
            role="Builder", task=stage_id, action="bounded implementation stage",
        )
        stage_contract = {
            "status": "ready",
            "goal": stage["goal"],
            "requirements": list(stage.get("requirements", [])),
            "constraints": list(local_contract.get("constraints", [])),
            "success_criteria": [stage.get("acceptance", "verify this stage's observable behavior")],
            # Preserve project identity for profile selection without importing
            # requirements that belong to later stages.
            "original_goal": local_contract.get("goal", task.get("goal", "")),
        }
        set_active_tool_contract(stage_contract)
        stage_profile = infer_web_profile(stage["goal"], stage_contract)
        observable_checks = interaction_expectations(stage_profile)
        observable_context = "\n".join(f"- {item}" for item in observable_checks)
        stage_context = (
            f"{base_context}\n\n"
            f"FULL BOUNDED STAGE PLAN: {plan}\n"
            f"THIS PASS: stage {stage['index']} of {len(stages)} - {stage['name']}\n"
            f"STAGE ACCEPTANCE FOCUS: {stage.get('acceptance', 'verify observable behavior')}\n"
            f"DETERMINISTIC STAGE OBSERVABLES:\n{observable_context or '- Run the relevant executable checks.'}\n"
            f"PRIOR STAGE SUMMARIES: {json.dumps(previous_summaries[-3:], ensure_ascii=False)[:2400]}\n"
            "You are the sole author of all implementation code. Inspect the real workspace first. "
            "Implement only this stage, preserve completed behavior, and run focused executable verification. "
            "Do not claim requirements from later stages are complete."
        )
        result = execute_agent_task(
            stage["goal"], memory, role="Builder", task_id=stage_id,
            extra_context=stage_context,
        )
        stage_evidence = list(result.get("tool_evidence", []))
        continuation_count = 0

        while result["status"] == "too_broad" and continuation_count < MAX_STAGE_CONTINUATIONS:
            continuation_count += 1
            RUN["stage_continuations"] += 1
            RUN["builder_calls"] += 1
            memory = result["memory"]
            latest_error = compact_text(memory.get("last_error") or "(no unresolved verification error recorded)", 1800)
            recent_evidence = evidence_for_review(stage_evidence, limit=6)
            rewrite_recovery = result.get("recovery_strategy") == "rewrite_unverified"
            recovery_targets = list(result.get("recovery_targets") or [])
            store = get_memory_store()
            rewrite_candidates = store.unverified_model_artifacts() if store else []
            if rewrite_recovery:
                RUN["coherent_rewrite_recoveries"] += 1
            update_task_ledger(
                stage_id, stage["goal"], "continuing",
                "bounded pass exhausted; continuing from the same transactional workspace",
                parent_id=task.get("id"), stage_index=stage["index"],
            )
            event(
                f"[STAGE CONTINUATION {continuation_count}/{MAX_STAGE_CONTINUATIONS}] {stage['name']}",
                role="Builder", task=stage_id, action="fresh-context continuation",
            )
            if rewrite_recovery:
                recovery_instruction = (
                    "COHERENT REWRITE RECOVERY: repeated patching preserved the same executable failure. Stop the "
                    "micro-patch loop. Inspect the relevant files once, then use write_file to replace the defective "
                    "unverified model-owned artifact(s) with a simple, complete, internally coherent implementation "
                    "authored entirely by you. Do not call edit_file or edit_file_range before that first coherent "
                    "rewrite. Preserve selectors/interfaces used by the other files, avoid duplicated functions/state, "
                    "then run syntax and fresh browser verification. The tool will refuse any user-owned or verified "
                    f"file. FAILURE TARGET HINTS: {json.dumps(recovery_targets, ensure_ascii=False)}. "
                    f"ALLOWED FULL-REWRITE CANDIDATES: {json.dumps(rewrite_candidates, ensure_ascii=False)}"
                )
            else:
                recovery_instruction = (
                    "The CURRENT WORKSPACE is authoritative and contains your own valid progress. Inspect only the "
                    "exact area implicated by the latest evidence, make the smallest syntax-valid correction, and run "
                    "fresh executable verification. Do not rebuild or duplicate the implementation."
                )
            continuation_context = (
                f"{stage_context}\n\n"
                f"CONTINUATION PASS {continuation_count}/{MAX_STAGE_CONTINUATIONS}: This is the same stage and the "
                "same active transaction, not a new project.\n"
                f"{recovery_instruction}\n"
                f"ACTIONABLE VERIFICATION DIGEST: {latest_error}\n"
                f"RECENT NON-STALE EVIDENCE: {json.dumps(recent_evidence, ensure_ascii=False)[:3200]}"
            )
            continuation_kwargs = {"tool_policy": "coherent_rewrite"} if rewrite_recovery else {}
            result = execute_agent_task(
                stage["goal"], memory, role="Builder", task_id=stage_id,
                extra_context=continuation_context, **continuation_kwargs,
            )
            stage_evidence.extend(result.get("tool_evidence", []))

        last_result = result
        memory = result["memory"]
        combined_evidence.extend(stage_evidence)
        record = {
            "task_id": stage_id,
            "goal": stage["goal"],
            "status": result["status"],
            "summary": result.get("summary", ""),
            "stage_index": stage["index"],
            "continuations": continuation_count,
        }
        stage_records.append(record)
        if result["status"] != "done":
            update_task_ledger(
                stage_id, stage["goal"], result["status"], result.get("summary", ""),
                parent_id=task.get("id"), stage_index=stage["index"],
            )
            return {
                **result,
                "memory": memory,
                "tool_evidence": combined_evidence,
                "stage_records": stage_records,
                "stage_plan": stages,
            }
        update_task_ledger(
            stage_id, stage["goal"], "implemented_unverified", result.get("summary", ""),
            parent_id=task.get("id"), stage_index=stage["index"],
        )
        previous_summaries.append({"stage": stage["index"], "summary": result.get("summary", "")})

    summaries = [record["summary"] for record in stage_records if record.get("summary")]
    return {
        "status": "done",
        "summary": compact_text(" | ".join(summaries) or "all bounded stages implemented", 700),
        "messages": (last_result or {}).get("messages", []),
        "memory": memory,
        "tool_evidence": combined_evidence,
        "provider_error": (last_result or {}).get("provider_error"),
        "stage_records": stage_records,
        "stage_plan": stages,
    }


def finalize_stage_ledger(builder_result, status):
    for stage in builder_result.get("stage_records", []):
        update_task_ledger(
            stage["task_id"], stage["goal"], status, stage.get("summary", ""),
            parent_id=stage["task_id"].rsplit(".S", 1)[0],
            stage_index=stage.get("stage_index"),
        )


def _execute_builder_impl(task, contract, memory, parent_summary="", dependency_summaries=None):
    dependency_summaries = dependency_summaries or []
    verification_contract = contract_for_task(task, contract)
    RUN["leaf_tasks"] += 1
    begin_transaction(task["id"])
    risk = task_risk(task["goal"])
    predictor = challenger = ""
    if risk == "high":
        predictor = "Use the deterministic project playbook and verify after each bounded stage."
        ROLE_STATUS["Predictor"] = "deterministic"
        ROLE_STATUS["Challenger"] = "unused"

    context = leaf_context(contract, task, parent_summary, dependency_summaries, predictor, challenger)
    result = execute_builder_stages(task, contract, memory, base_context=context)
    set_active_tool_contract(verification_contract)
    memory = result["memory"]
    if result["status"] == "too_broad":
        RUN["task_too_broad_count"] += 1
        rollback_transaction()
        finalize_stage_ledger(result, "rolled_back")
        return {"status": "too_broad", "summary": result["summary"], "memory": memory, "builder": result}
    if result["status"] == "provider_failure":
        rollback_transaction()
        finalize_stage_ledger(result, "rolled_back")
        return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": result["summary"], "memory": memory, "builder": result}

    adaptive = run_adaptive_checks(task, verification_contract, memory, result, allow_falsifier=True)
    memory = adaptive["memory"]
    browser_result = optional_browser_check(task, verification_contract)
    vision_review = maybe_vision_review(browser_result, task, verification_contract) if should_run_visual_review(task) else None
    quality = review_quality(task, verification_contract, result, adaptive, browser_result, vision_review, fresh=False)
    gate = evidence_gate(result, quality)
    if gate["passed"]:
        changed_files = commit_transaction()
        finalize_stage_ledger(result, "done")
        remember_verified_outcome(task, contract, result["summary"], changed_files)
        return {"status": "done", "summary": result["summary"], "memory": memory,
                "builder": result, "quality": quality, "gate": gate, "browser": browser_result,
                "vision": vision_review, "changed_files": changed_files}

    failure_type = classify_failure(result, quality, browser_result, vision_review)
    if failure_type != "IMPLEMENTATION_ERROR":
        if failure_type == "TASK_TOO_BROAD":
            RUN["task_too_broad_count"] += 1
        rollback_transaction()
        finalize_stage_ledger(result, "rolled_back")
        return {"status": "too_broad" if failure_type == "TASK_TOO_BROAD" else "failed",
                "failure_type": failure_type, "summary": f"verification failed: {failure_type}",
                "memory": memory, "builder": result, "quality": quality, "gate": gate, "browser": browser_result}

    current = result
    for _repair in range(MAX_REPAIRS_PER_LEAF):
        repaired = repair_task(task, verification_contract, repair_evidence(quality, gate, browser_result), memory)
        memory = repaired["memory"]
        if repaired["status"] == "provider_failure":
            rollback_transaction()
            finalize_stage_ledger(result, "rolled_back")
            return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": repaired["summary"], "memory": memory}
        if repaired["status"] == "too_broad":
            RUN["task_too_broad_count"] += 1
            rollback_transaction()
            finalize_stage_ledger(result, "rolled_back")
            return {"status": "too_broad", "failure_type": "TASK_TOO_BROAD", "summary": repaired["summary"], "memory": memory}
        current = repaired
        fresh_adaptive = {"falsifier": "not rerun; one Falsifier call max per leaf", "falsifier_result": None}
        fresh_browser = optional_browser_check(task, verification_contract)
        fresh_vision = maybe_vision_review(fresh_browser, task, verification_contract) if should_run_visual_review(task) else None
        quality = review_quality(task, verification_contract, current, fresh_adaptive, fresh_browser, fresh_vision, fresh=True)
        gate = evidence_gate(current, quality)
        if gate["passed"]:
            changed_files = commit_transaction()
            finalize_stage_ledger(result, "done")
            remember_verified_outcome(task, contract, current["summary"], changed_files)
            return {"status": "done", "summary": current["summary"], "memory": memory,
                    "builder": current, "quality": quality, "gate": gate, "browser": fresh_browser,
                    "vision": fresh_vision, "changed_files": changed_files}
        failure_type = classify_failure(current, quality, fresh_browser, fresh_vision)
        if failure_type != "IMPLEMENTATION_ERROR":
            rollback_transaction()
            finalize_stage_ledger(result, "rolled_back")
            return {"status": "too_broad" if failure_type == "TASK_TOO_BROAD" else "failed",
                    "failure_type": failure_type, "summary": f"fresh verification failed: {failure_type}", "memory": memory}

    rollback_transaction()
    finalize_stage_ledger(result, "rolled_back")
    return {"status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "failed evidence gate after repair limit", "memory": memory}


def execute_builder(task, contract, memory, parent_summary="", dependency_summaries=None):
    try:
        return _execute_builder_impl(task, contract, memory, parent_summary, dependency_summaries)
    except Exception:
        restored = rollback_transaction()
        record_run_event("transaction_rollback", task_id=task.get("id"), restored=restored,
                         reason="unexpected exception")
        raise


# ---------------------------------------------------------------------------
# AGGREGATION / INTEGRATION
# ---------------------------------------------------------------------------

def _aggregate_task_impl(task, contract, child_results, memory, root=False):
    label = "ROOT" if root else task["id"]
    event(f"[AGGREGATE {label}]", role="Builder", task=label, action="integration verification")
    child_info = [{"task": child["task"], "status": child["result"]["status"],
                   "summary": child["result"].get("summary", "")} for child in child_results]
    RUN["builder_calls"] += 1
    begin_transaction(f"aggregate-{label}")
    failed_children = [item for item in child_info if item["status"] != "done"]
    instruction = (
        f"ROOT CONTRACT: {compact_contract(contract)}\n"
        f"{playbook_context(contract)}\n"
        f"PARENT GOAL: {task['goal']}\n"
        f"CHILD RESULTS: {json.dumps(child_info, ensure_ascii=False)[:8000]}\n"
        f"{('ORIGINAL ROOT REQUEST: ' + contract.get('original_goal', '')) if root else ''}\n"
        "Inspect the combined REAL workspace. Integrate successful child work, recover any failed child requirements, "
        "resolve conflicts, and run executable verification for the complete parent goal. "
        "For a visual/web project, use the real browser screenshot for one focused visual and responsive polish pass. "
        "At root explicitly check every original requirement and constraint. Return a short evidence-based result summary."
    )
    result = execute_agent_task(instruction, memory, role="Builder", task_id=label)
    memory = result["memory"]
    if result["status"] != "done":
        rollback_transaction()
        return {"status": "failed", "summary": result["summary"], "memory": memory,
                "children": child_info, "failed_children": failed_children}
    adaptive = {"falsifier": "parent integration verification", "falsifier_result": None}
    browser_result = optional_browser_check(task, contract)
    vision_review = maybe_vision_review(browser_result, task, contract)
    quality = review_quality(task, contract, result, adaptive, browser_result, vision_review, fresh=True)
    gate = evidence_gate(result, quality)
    if gate["passed"]:
        changed_files = commit_transaction()
        remember_verified_outcome(task, contract, result["summary"], changed_files)
        return {"status": "done", "summary": result["summary"], "memory": memory,
                "quality": quality, "gate": gate, "browser": browser_result,
                "vision": vision_review, "children": child_info, "changed_files": changed_files}
    rollback_transaction()
    return {"status": "failed", "summary": "parent integration failed evidence gate", "memory": memory,
            "quality": quality, "gate": gate, "browser": browser_result,
            "vision": vision_review, "children": child_info, "failed_children": failed_children}


def aggregate_task(task, contract, child_results, memory, root=False):
    try:
        return _aggregate_task_impl(task, contract, child_results, memory, root=root)
    except Exception:
        restored = rollback_transaction()
        record_run_event("transaction_rollback", task_id=task.get("id"), restored=restored,
                         reason="unexpected aggregation exception")
        raise


# ---------------------------------------------------------------------------
# TRUE RECURSION
# ---------------------------------------------------------------------------

def solve_task(task, depth, contract, memory, parent_summary="", dependency_summaries=None, fit_decider=None, leaf_executor=None):
    dependency_summaries = dependency_summaries or []
    task["status"] = "running"
    update_task_ledger(
        task["id"], task["goal"], "running", task.get("summary", ""),
        parent_id=task.get("parent"),
    )
    RUN["max_depth"] = max(RUN["max_depth"], depth)
    event(f"[TASK {task['id']}] depth={depth} evaluating", role="Coordinator", task=task["id"], action="task fit")

    can_split = depth < MAX_DEPTH and RUN["tasks_created"] < MAX_TOTAL_TASKS
    decision = {"decision": "execute"}
    if can_split:
        decision = fit_decider(task, depth, contract, dependency_summaries) if fit_decider else decide_task_fit(task, depth, contract, dependency_summaries)

    if decision.get("decision") == "split" and can_split:
        children = decompose_task(task, decision)
        if len(children) >= 2:
            RUN["splits"] += 1
            event(f"[SPLIT] {task['id']} -> {len(children)} children", role="Coordinator", task=task["id"], action="recursive split")
            completed = []
            deps = list(dependency_summaries)
            for child in children:
                child_result = solve_task(child, depth + 1, contract, memory,
                                          parent_summary=task.get("summary", ""), dependency_summaries=deps,
                                          fit_decider=fit_decider, leaf_executor=leaf_executor)
                memory = child_result["memory"]
                completed.append({"task": child["goal"], "result": child_result})
                deps.append({"task": child["goal"], "status": child_result["status"], "summary": child_result.get("summary", "")})
            if leaf_executor is not None:
                failed = any(x["result"]["status"] != "done" for x in completed)
                aggregate = {"status": "failed" if failed else "done",
                             "summary": "mock aggregate", "memory": memory}
            else:
                aggregate = aggregate_task(task, contract, completed, memory, root=(task["id"] == "ROOT"))
            task["status"] = aggregate["status"]
            task["summary"] = aggregate.get("summary", "")
            update_task_ledger(
                task["id"], task["goal"], task["status"], task["summary"],
                parent_id=task.get("parent"),
            )
            event(f"[{'DONE' if task['status'] == 'done' else 'FAILED'} {task['id']}]", task=task["id"], action="aggregated")
            return aggregate

    task["children"] = task.get("children", [])
    leaf = leaf_executor(task, contract, memory, parent_summary, dependency_summaries) if leaf_executor else execute_builder(
        task, contract, memory, parent_summary, dependency_summaries)
    memory = leaf["memory"]

    if leaf.get("status") == "too_broad" and depth < MAX_DEPTH and RUN["tasks_created"] < MAX_TOTAL_TASKS:
        RUN["re_splits"] += 1
        event(f"[RE-SPLIT] {task['id']} after TASK_TOO_BROAD", role="Coordinator", task=task["id"], action="re-decompose")
        decision = fit_decider(task, depth, contract, dependency_summaries) if fit_decider else decide_task_fit(task, depth, contract, dependency_summaries)
        if decision.get("decision") == "split":
            children = decompose_task(task, decision)
            if len(children) >= 2:
                RUN["splits"] += 1
                completed = []
                deps = list(dependency_summaries)
                for child in children:  # literal recursive call: child may split again
                    child_result = solve_task(child, depth + 1, contract, memory,
                                              parent_summary=task.get("summary", ""), dependency_summaries=deps,
                                              fit_decider=fit_decider, leaf_executor=leaf_executor)
                    memory = child_result["memory"]
                    completed.append({"task": child["goal"], "result": child_result})
                    deps.append({"task": child["goal"], "status": child_result["status"], "summary": child_result.get("summary", "")})
                if leaf_executor is not None:
                    failed = any(x["result"]["status"] != "done" for x in completed)
                    aggregate = {"status": "failed" if failed else "done", "summary": "mock aggregate", "memory": memory}
                else:
                    aggregate = aggregate_task(task, contract, completed, memory, root=(task["id"] == "ROOT"))
                task["status"] = aggregate["status"]
                task["summary"] = aggregate.get("summary", "")
                update_task_ledger(
                    task["id"], task["goal"], task["status"], task["summary"],
                    parent_id=task.get("parent"),
                )
                return aggregate

    task["status"] = leaf.get("status", "failed")
    task["summary"] = leaf.get("summary", "")
    update_task_ledger(
        task["id"], task["goal"], task["status"], task["summary"],
        parent_id=task.get("parent"),
    )
    event(f"[{'DONE' if task['status'] == 'done' else 'FAILED'} {task['id']}]", task=task["id"], action="leaf complete")
    return leaf


# ---------------------------------------------------------------------------
# INPUT / WORKSPACE SETUP
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
        if PROMPT_TOOLKIT_AVAILABLE and sys.stdin.isatty():
            print(f"Workspace: press Enter to create {default_path}, or type an existing path.")
            raw = prompt("Workspace> ", completer=PathCompleter(only_directories=True, expanduser=True)).strip()
        else:
            raw = input(f"Workspace [Enter = {default_path}]: ").strip()
        if raw.lower() in ("exit", "quit"):
            raise SystemExit()
        if not raw:
            path = store.create_project()
            print(f"workspace created: {path}\n")
            return path
        path = Path(raw).expanduser().resolve()
        if path == store.root:
            path = store.create_project()
            print(f"workspace created: {path}\n")
            return path
        if not path.exists():
            print(f"error: that folder does not exist: {path}")
        elif not path.is_dir():
            print(f"error: that path is not a folder: {path}")
        else:
            print(f"workspace set to: {path}\n")
            return path


def read_user_prompt():
    if PROMPT_TOOLKIT_AVAILABLE and sys.stdin.isatty():
        bindings = KeyBindings()

        @bindings.add("enter")
        def _submit(event_obj):
            event_obj.current_buffer.validate_and_handle()

        @bindings.add("escape", "enter")
        def _newline(event_obj):
            event_obj.current_buffer.insert_text("\n")

        print("Paste/write task. Enter submits; Esc+Enter adds a manual newline. Multiline paste is preserved.")
        return prompt("You> ", multiline=True, key_bindings=bindings).strip()
    return input("You> ").strip()


def extract_explicit_requirements(raw_goal):
    requirements = []
    for raw_line in str(raw_goal).splitlines():
        line = raw_line.strip()
        match = re.match(r"^(?:[-*•]|\d+[.)])\s+(.+)$", line)
        if match:
            item = match.group(1).strip()
            if len(item) >= 3:
                requirements.append(item)
    return requirements


def normalize_goal_contract(raw_goal, contract):
    normalized = dict(contract)
    explicit = extract_explicit_requirements(raw_goal)
    if len(explicit) >= 2:
        normalized["requirements"] = explicit
        record_run_event(
            "contract_requirement_normalization",
            source="explicit_prompt_bullets", count=len(explicit),
        )
    return normalized


def get_goal_contract(raw_goal, interactive=True):
    explicit = extract_explicit_requirements(raw_goal)
    if len(explicit) >= 2:
        first_line = next(
            (
                line.strip() for line in str(raw_goal).splitlines()
                if line.strip() and not re.match(
                    r"^(?:requirements?|المتطلبات)\s*:?$", line.strip(), re.IGNORECASE
                )
            ),
            compact_text(raw_goal, 1200),
        )
        result = {
            "status": "ready",
            "question": "",
            "goal": compact_text(first_line, 1200),
            "requirements": explicit,
            "constraints": [],
            "success_criteria": ["every explicit requirement is implemented and verified"],
            "original_goal": raw_goal,
            "clarifications": [],
        }
        record_run_event("deterministic_goal_contract", requirement_count=len(explicit))
        return result
    answers = []
    for attempt in range(MAX_CLARIFICATION_QUESTIONS + 1):
        result = understand_goal(raw_goal, "\n".join(answers))
        if result["status"] == "ready":
            result = normalize_goal_contract(raw_goal, result)
            result["original_goal"] = raw_goal
            result["clarifications"] = list(answers)
            return result
        if attempt >= MAX_CLARIFICATION_QUESTIONS:
            return {"status": "question", "question": "clarification limit reached", "original_goal": raw_goal,
                    "clarifications": list(answers)}
        RUN["clarification_questions"] += 1
        question = result["question"]
        print(f"[CLARIFY] {question}")
        if not interactive:
            return {"status": "question", "question": question, "original_goal": raw_goal,
                    "clarifications": list(answers)}
        answer = read_user_prompt()
        answers.append(f"Q: {question}\nA: {answer}")
    return {"status": "question", "question": "clarification limit reached", "original_goal": raw_goal,
            "clarifications": list(answers)}


# ---------------------------------------------------------------------------
# AUTOMATIC MODE ROUTING
# ---------------------------------------------------------------------------

def _mode_validator(data):
    return (
        isinstance(data, dict)
        and data.get("mode") in {"baseline", "recursive"}
        and isinstance(data.get("reason", ""), str)
    )


def normalize_execution_choice(choice, contract):
    """Prevent feature-splitting when all children would fight over one artifact."""
    normalized = dict(choice)
    profile = classify_project(contract)
    text = " ".join(
        [str(contract.get("goal", "")), str(contract.get("original_goal", ""))]
        + [str(item) for item in contract.get("constraints", [])]
    ).casefold()
    cohesive_markers = (
        "self-contained", "single file", "one file", "one local", "no build step",
        "standalone", "ملف واحد", "بدون build",
    )
    distributed_markers = (
        "frontend and backend", "client and server", "microservice", "multiple services",
        "database migration", "mobile app and", "سطح المكتب والموبايل",
    )
    cohesive_web = (
        profile in {"web_game", "web_app"}
        and len(contract.get("requirements", [])) <= 8
        and (any(marker in text for marker in cohesive_markers) or not any(
            marker in text for marker in distributed_markers
        ))
    )
    if normalized.get("mode") == "recursive" and cohesive_web:
        normalized["mode"] = "baseline"
        normalized["reason"] = (
            "deterministic cohesive-artifact guard: use bounded vertical stages "
            "instead of conflicting recursive children"
        )
        record_run_event("mode_guardrail", profile=profile, original=choice, normalized=normalized)
    return normalized


def decide_execution_mode(raw_goal, contract):
    deterministic_guard = normalize_execution_choice(
        {"mode": "recursive", "reason": "cohesion probe"}, contract
    )
    if deterministic_guard["mode"] == "baseline":
        return deterministic_guard

    prompt_chars = len(raw_goal)
    prompt_lines = raw_goal.count("\n") + 1
    prompt_text = f"""Choose the smallest orchestration mode that is likely to complete this coding goal reliably with the SELECTED model.
Return JSON only:
{{"mode":"baseline","reason":"short reason"}}
or
{{"mode":"recursive","reason":"short reason"}}

BASELINE means: one existing coding-agent/tool loop handles the whole request.
RECURSIVE means: recursively split broad work into focused children, execute them sequentially, verify, repair, and aggregate.

Choose BASELINE for a small/cohesive request that this model can reasonably execute and verify in one focused pass.
Choose RECURSIVE when the goal contains multiple independently implementable/verifiable parts, many components/files/features, a large project specification, or substantial integration work.
Treat model capacity as an advisory hint only. Do not choose recursive merely because capacity is low or a task is non-trivial; recursive overhead can amplify errors when every child rewrites the same monolithic artifact.

SELECTED MODEL: {MODEL}
MODEL CAPACITY: {MODEL_TASK_CAPACITY}/4 (auto-estimated from model parameter size; experimental, not a benchmark)
PROMPT SIZE: {prompt_chars} chars / {prompt_lines} lines
GOAL CONTRACT: {compact_contract(contract)}"""
    schema = {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["baseline", "recursive"]},
            "reason": {"type": "string"},
        },
        "required": ["mode", "reason"],
        "additionalProperties": False,
    }
    try:
        choice = structured_model_call(prompt_text, _mode_validator, "execution-mode", schema)
        return normalize_execution_choice(choice, contract)
    except (StructuredOutputError, ProviderError) as exc:
        requirement_count = len(contract.get("requirements", []))
        complex_request = (requirement_count >= 3 or prompt_chars > 900
                           or (MODEL_TASK_CAPACITY <= 1 and requirement_count >= 2))
        fallback = {
            "mode": "recursive" if complex_request else "baseline",
            "reason": "deterministic fallback after invalid structured router output",
        }
        record_run_event("structured_fallback", label="execution-mode", error=str(exc), fallback=fallback)
        return normalize_execution_choice(fallback, contract)


def baseline_prompt_with_clarifications(raw_goal, contract):
    clarifications = contract.get("clarifications") or []
    if not clarifications:
        return raw_goal
    return raw_goal + "\n\nPRE-EXECUTION CLARIFICATIONS (authoritative):\n" + "\n\n".join(clarifications)


# ---------------------------------------------------------------------------
# RUN MODES
# ---------------------------------------------------------------------------

def run_baseline_request(user_text, memory, history=None, contract_override=None, reset=True, finish=True):
    if reset:
        reset_run("baseline")
    else:
        RUN["mode"] = "baseline"
        DASHBOARD["mode"] = "baseline"
    RUN["tasks_created"] = 1
    RUN["max_depth"] = 0
    contract = contract_override or {
        "status": "ready", "goal": user_text, "requirements": [user_text], "constraints": [],
        "success_criteria": ["the requested change is implemented and verified"], "original_goal": user_text,
    }
    contract = normalize_goal_contract(contract.get("original_goal", user_text), contract)
    begin_durable_run(contract)
    TASKS["ROOT"] = {"id": "ROOT", "goal": contract.get("goal", user_text), "depth": 0, "parent": None,
                      "status": "running", "children": [], "summary": ""}
    update_task_ledger("ROOT", TASKS["ROOT"]["goal"], "running")
    print("[MODE] baseline")
    print(f"[MODEL] {MODEL}")
    print(f"[ROOT] {compact_text(user_text, 160)}")
    result = execute_builder(TASKS["ROOT"], contract, memory)
    TASKS["ROOT"]["status"] = "done" if result["status"] == "done" else "failed"
    TASKS["ROOT"]["summary"] = result["summary"]
    update_task_ledger("ROOT", TASKS["ROOT"]["goal"], TASKS["ROOT"]["status"], result["summary"])
    final_status = "done" if result["status"] == "done" else result["status"]
    if finish:
        finish_metrics(final_status)
    result_messages = (result.get("builder") or {}).get("messages") or history or [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
    return result, result["memory"], result_messages


def run_recursive_request(user_text, memory, interactive=True, contract_override=None, fit_decider=None, leaf_executor=None,
                          reset=True, finish=True):
    if reset:
        reset_run("recursive")
    else:
        RUN["mode"] = "recursive"
        DASHBOARD["mode"] = "recursive"
    print("[MODE] recursive")
    print(f"[MODEL] {MODEL}")
    print(f"[CAPACITY] {MODEL_TASK_CAPACITY}/4 (EXPERIMENTAL MANUAL CAPACITY)")
    print(f"[ROOT] {compact_text(user_text, 160)}")

    try:
        contract = contract_override or get_goal_contract(user_text, interactive=interactive)
    except RuntimeError as exc:
        event(f"[ERROR] {exc}", role="Coordinator", task="ROOT", action="provider failure")
        if finish:
            finish_metrics("failed")
        return {"status": "failed", "summary": str(exc), "failure_type": "ENVIRONMENT_ERROR"}, memory
    if contract.get("status") == "question":
        if finish:
            finish_metrics("needs_clarification")
        return {"status": "needs_clarification", "summary": contract.get("question", "")}, memory

    begin_durable_run(contract)

    root = {"id": "ROOT", "goal": contract["goal"], "depth": 0, "parent": None,
            "status": "pending", "children": [], "summary": ""}
    TASKS["ROOT"] = root
    RUN["tasks_created"] = 1
    global LIVE_VIEW
    try:
        if RICH_AVAILABLE and sys.stdout.isatty() and leaf_executor is None:
            try:
                with Live(build_dashboard_renderable(), refresh_per_second=6, transient=False) as live:
                    LIVE_VIEW = live
                    result = solve_task(root, 0, contract, memory, fit_decider=fit_decider, leaf_executor=leaf_executor)
            finally:
                LIVE_VIEW = None
        else:
            result = solve_task(root, 0, contract, memory, fit_decider=fit_decider, leaf_executor=leaf_executor)
    except RuntimeError as exc:
        event(f"[ERROR] {exc}", role="Coordinator", task="ROOT", action="provider/structured-call failure")
        result = {"status": "failed", "summary": str(exc), "memory": memory, "failure_type": "ENVIRONMENT_ERROR"}
    final_status = "done" if result["status"] == "done" else "failed"
    print(f"[FINAL] {final_status}")
    if finish:
        finish_metrics(final_status)
    return result, result["memory"]


def run_auto_request(user_text, memory, history=None, interactive=True):
    """Normal UX: understand first, then let the selected local model choose baseline vs recursive."""
    reset_run("auto")
    print("[ROUTER] evaluating prompt; execution mode is not chosen yet")
    print(f"[MODEL] {MODEL}")
    print(f"[CAPACITY] {MODEL_TASK_CAPACITY}/4 (AUTO-ESTIMATED; EXPERIMENTAL)")
    print(f"[ROOT] {compact_text(user_text, 160)}")
    print("[GOAL] understanding before execution")

    try:
        contract = get_goal_contract(user_text, interactive=interactive)
    except RuntimeError as exc:
        event(f"[ERROR] {exc}", role="Coordinator", task="ROOT", action="goal understanding failure")
        finish_metrics("failed")
        return {"status": "failed", "summary": str(exc), "failure_type": "ENVIRONMENT_ERROR"}, memory, history

    if contract.get("status") == "question":
        finish_metrics("needs_clarification")
        return {"status": "needs_clarification", "summary": contract.get("question", "")}, memory, history

    print("[GOAL LOCKED] execution will continue autonomously")
    begin_durable_run(contract)
    try:
        choice = decide_execution_mode(user_text, contract)
    except RuntimeError as exc:
        event(f"[ERROR] {exc}", role="Coordinator", task="ROOT", action="mode selection failure")
        finish_metrics("failed")
        return {"status": "failed", "summary": str(exc), "failure_type": "ENVIRONMENT_ERROR"}, memory, history

    selected = choice["mode"]
    RUN["auto_selected_mode"] = selected
    RUN["auto_mode_reason"] = compact_text(choice.get("reason", ""), 240)
    print(f"[AUTO MODE] {selected}")
    if choice.get("reason"):
        print(f"[WHY] {compact_text(choice['reason'], 240)}")

    if selected == "baseline":
        effective_prompt = baseline_prompt_with_clarifications(user_text, contract)
        result, memory, history = run_baseline_request(
            effective_prompt, memory, history=history, contract_override=contract, reset=False, finish=False
        )
    else:
        result, memory = run_recursive_request(
            user_text, memory, interactive=False, contract_override=contract, reset=False, finish=False
        )

    final_status = "done" if result.get("status") == "done" else result.get("status", "failed")
    finish_metrics(final_status)
    return result, memory, history


# ---------------------------------------------------------------------------
# DETERMINISTIC SELF TESTS (no live LLM required)
# ---------------------------------------------------------------------------

def _mock_contract(raw="Build mock project"):
    return {"status": "ready", "goal": raw, "requirements": ["complete requested behavior"],
            "constraints": ["small experiment"], "success_criteria": ["verified"], "original_goal": raw}


def _mock_leaf(task, contract, memory, parent_summary, dependencies):
    RUN["leaf_tasks"] += 1
    return {"status": "done", "summary": f"done {task['id']}", "memory": memory,
            "context_probe": {"task": task["goal"], "parent": parent_summary, "dependencies": dependencies}}


def _self_test_architecture(tmp):
    global WORKSPACE, ask_ollama, execute_agent_task, execute_builder, run_adaptive_checks, review_quality, repair_task, optional_browser_check
    WORKSPACE = Path(tmp)
    memory = load_memory()

    # 1. Baseline really enters the shared existing-style loop once and never splits.
    real_builder = execute_builder
    def mock_baseline_builder(task, contract, mem, parent_summary="", dependency_summaries=None):
        RUN["leaf_tasks"] += 1
        RUN["builder_calls"] += 1
        return {"status": "done", "summary": "mock baseline done", "memory": mem,
                "builder": {"messages": [{"role": "assistant", "content": "done"}]}}
    execute_builder = mock_baseline_builder
    baseline_result, memory, _history = run_baseline_request("single baseline task", memory)
    baseline_ok = baseline_result["status"] == "done" and RUN["tasks_created"] == 1 and RUN["leaf_tasks"] == 1 and RUN["splits"] == 0
    execute_builder = real_builder

    # 2. Literal recursion: ROOT -> 1, 2 -> 2.1, 2.2.
    reset_run("recursive")
    TASKS["ROOT"] = {"id": "ROOT", "goal": "root", "depth": 0, "parent": None, "status": "pending", "children": [], "summary": ""}
    RUN["tasks_created"] = 1
    def fit(task, depth, contract, deps):
        if task["id"] == "ROOT":
            return {"decision": "split", "subtasks": ["child one", "child two"]}
        if task["id"] == "2":
            return {"decision": "split", "subtasks": ["grandchild one", "grandchild two"]}
        return {"decision": "execute"}
    result = solve_task(TASKS["ROOT"], 0, _mock_contract(), memory, fit_decider=fit, leaf_executor=_mock_leaf)
    recursion_ok = result["status"] == "done" and all(k in TASKS for k in ("1", "2", "2.1", "2.2"))

    # 3-4. Limits cap unlimited split proposals.
    reset_run("recursive")
    TASKS["ROOT"] = {"id": "ROOT", "goal": "root", "depth": 0, "parent": None, "status": "pending", "children": [], "summary": ""}
    RUN["tasks_created"] = 1
    def always_split(task, depth, contract, deps):
        return {"decision": "split", "subtasks": ["a", "b"]}
    solve_task(TASKS["ROOT"], 0, _mock_contract(), memory, fit_decider=always_split, leaf_executor=_mock_leaf)
    depth_ok = RUN["max_depth"] <= MAX_DEPTH
    total_ok = RUN["tasks_created"] <= MAX_TOTAL_TASKS

    # 5. Focused context contains short dependency summaries, not sibling histories.
    ctx = leaf_context(_mock_contract(), {"goal": "leaf"}, "parent summary", [{"summary": "sibling short summary"}])
    focused_ok = "sibling hidden conversation" not in ctx and "sibling short summary" in ctx

    # 6. Oversized leaf can become TASK_TOO_BROAD and recursively split.
    reset_run("recursive")
    TASKS["ROOT"] = {"id": "ROOT", "goal": "oversized", "depth": 0, "parent": None, "status": "pending", "children": [], "summary": ""}
    RUN["tasks_created"] = 1
    calls = {"leaf": 0}
    def execute_then_children(task, contract, memory, parent, deps):
        calls["leaf"] += 1
        if task["id"] == "ROOT":
            return {"status": "too_broad", "summary": "limit", "memory": memory}
        return _mock_leaf(task, contract, memory, parent, deps)
    def execute_first_then_split(task, depth, contract, deps):
        if task["id"] == "ROOT" and calls["leaf"] == 0:
            return {"decision": "execute"}
        if task["id"] == "ROOT":
            return {"decision": "split", "subtasks": ["small a", "small b"]}
        return {"decision": "execute"}
    result = solve_task(TASKS["ROOT"], 0, _mock_contract(), memory, fit_decider=execute_first_then_split, leaf_executor=execute_then_children)
    resplit_ok = RUN["re_splits"] == 1 and result["status"] == "done"

    # 7-8. IMPLEMENTATION_ERROR routes to Repairer and gets a fresh quality pass.
    reset_run("recursive")
    real_execute, real_adaptive = execute_agent_task, run_adaptive_checks
    real_review, real_repair, real_browser = review_quality, repair_task, optional_browser_check
    state = {"repairs": 0, "reviews": 0}
    def fake_execute(*args, **kwargs):
        return {"status": "done", "summary": "built", "memory": memory,
                "tool_evidence": [{"tool": "run_command", "result": "[exit_code=0]\ntests ran"}]}
    def fake_adaptive(task, contract, mem, builder, allow_falsifier=True):
        return {"risk": "normal", "falsifier": "checked", "falsifier_result": None, "memory": mem}
    def fake_review(task, contract, builder, adaptive, browser_result=None, vision_review=None, fresh=False):
        state["reviews"] += 1
        if state["reviews"] == 1:
            return {"checks": [{"name": "tests", "status": "FAIL", "evidence": "1 failed"}]}
        return {"checks": [{"name": "tests", "status": "PASS", "evidence": "1 passed fresh"}]}
    def fake_repair(task, contract, evidence, mem):
        state["repairs"] += 1
        return {"status": "done", "summary": "repaired", "memory": mem,
                "tool_evidence": [{"tool": "run_command", "result": "[exit_code=0]\n1 passed fresh"}]}
    execute_agent_task, run_adaptive_checks = fake_execute, fake_adaptive
    review_quality, repair_task, optional_browser_check = fake_review, fake_repair, lambda task, contract=None: None
    repaired = execute_builder({"id": "T", "goal": "fix bug", "depth": 0}, _mock_contract(), memory)
    repair_ok = repaired["status"] == "done" and state["repairs"] == 1
    fresh_ok = state["reviews"] == 2
    execute_agent_task, run_adaptive_checks = real_execute, real_adaptive
    review_quality, repair_task, optional_browser_check = real_review, real_repair, real_browser

    # 9. Failed evidence never becomes DONE.
    fake_builder = {"status": "done", "tool_evidence": [{"tool": "run_command", "result": "AssertionError"}]}
    fake_quality = {"checks": [{"name": "tests", "status": "FAIL", "evidence": "1 failed"}]}
    failed_not_done_ok = not evidence_gate(fake_builder, fake_quality)["passed"]

    # 10. Large prompt display collapses without changing the full source text.
    huge = ("line of specification\n" * 3000).strip()
    shown = prompt_display(huge)
    large_ok = huge.count("\n") > 1000 and len(shown) < 100 and len(huge) > 50000

    # 11. Dashboard updates are display-only.
    reset_run("recursive")
    TASKS["ROOT"] = {"id": "ROOT", "goal": "x", "depth": 0, "parent": None, "status": "pending", "children": [], "summary": ""}
    before = json.dumps(TASKS, sort_keys=True)
    event("[TEST EVENT]", plain=False)
    dashboard_ok = before == json.dumps(TASKS, sort_keys=True)

    # 12. Task-fit validator and schema agree on execute/split invariants.
    fit_contract_ok = (
        _fit_validator({"decision": "execute", "reason": "small", "subtasks": []})
        and not _fit_validator({"decision": "execute", "reason": "contradictory", "subtasks": ["x"]})
        and _fit_validator({"decision": "split", "reason": "broad", "subtasks": ["a", "b"]})
        and not _fit_validator({"decision": "split", "reason": "invalid", "subtasks": []})
        and len(task_fit_schema().get("oneOf", [])) == 2
    )

    # 13. Failed leaves can restore only the files they touched.
    transaction_file = WORKSPACE / "transaction_probe.txt"
    transaction_file.write_text("before", encoding="utf-8")
    begin_transaction("transaction-self-test")
    write_file("transaction_probe.txt", "after")
    write_file("created_probe.txt", "temporary")
    rollback_transaction()
    transaction_ok = (transaction_file.read_text(encoding="utf-8") == "before"
                      and not (WORKSPACE / "created_probe.txt").exists())

    # 14-15. Web entrypoints are discovered without a prompt URL and unsafe shell commands are rejected.
    (WORKSPACE / "index.html").write_text("<!doctype html><title>probe</title>", encoding="utf-8")
    browser_discovery_ok = discover_web_entrypoint(
        {"id": "T", "goal": "Build a browser game"}, _mock_contract()
    ) == {"path": "index.html"}
    safe_parts, safe_error = _validated_command_parts("git status")
    _unsafe_parts, unsafe_error = _validated_command_parts("python -c \"print(1)\"")
    command_safety_ok = bool(safe_parts) and safe_error is None and bool(unsafe_error)

    return {"architecture": baseline_ok, "true recursion": recursion_ok, "max depth": depth_ok,
            "max total tasks": total_ok, "focused context": focused_ok, "re-split": resplit_ok,
            "repair routing": repair_ok, "fresh verification": fresh_ok,
            "evidence gate": failed_not_done_ok, "large paste": large_ok,
            "dashboard isolation": dashboard_ok, "task-fit contract": fit_contract_ok,
            "transaction rollback": transaction_ok, "browser discovery": browser_discovery_ok,
            "command safety": command_safety_ok}

def _self_test_browser(tmp, install_browser=False):
    global WORKSPACE
    WORKSPACE = Path(tmp)
    html = """<!doctype html><html><head><title>Agent Browser Test</title></head>
<body><h1>Browser wrapper works</h1><script>console.error('intentional self-test console error')</script></body></html>"""
    page = WORKSPACE / "browser_test.html"
    page.write_text(html, encoding="utf-8")

    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                              cwd=WORKSPACE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    navigation_limitation = None
    try:
        time.sleep(0.4)
        result = browser_snapshot(f"http://127.0.0.1:{port}/browser_test.html", "browser_self_test")
        if result.get("environment_error"):
            navigation_limitation = result.get("evidence")
            if install_browser:
                ok, _detail = ensure_browser(install_if_missing=True)
                if ok:
                    result = browser_snapshot(f"http://127.0.0.1:{port}/browser_test.html", "browser_self_test")
                    navigation_limitation = result.get("evidence") if result.get("environment_error") else None
    finally:
        server.terminate()
        try: server.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=3)

    if result.get("environment_error"):
        result = browser_inline_snapshot(html, "browser_self_test")
        result["navigation_limitation"] = navigation_limitation
    screenshot = WORKSPACE / EVIDENCE_DIR / "task_browser_self_test.png"
    passed = (not result.get("environment_error") and result.get("title") == "Agent Browser Test"
              and "Browser wrapper works" in result.get("text", "")
              and len(result.get("console_errors", [])) == 1 and screenshot.exists())
    return passed, result, screenshot

def ollama_reachable():
    if not OLLAMA_URL:
        return False
    try:
        response = http_get_json(OLLAMA_URL.rsplit("/api/chat", 1)[0] + "/api/tags", timeout=2)
        return response.status_code == 200
    except Exception:
        return False


def run_self_test(install_browser=False):
    global WORKSPACE
    print("[SELF TEST]")
    with tempfile.TemporaryDirectory(prefix="agent21_selftest_", ignore_cleanup_errors=True) as tmp:
        results = _self_test_architecture(tmp)
        browser_ok, browser_result, screenshot = _self_test_browser(tmp, install_browser=install_browser)
        results["browser wrapper"] = browser_ok
        live = ollama_reachable()

        labels = ["architecture", "true recursion", "max depth", "max total tasks", "focused context",
                  "re-split", "repair routing", "fresh verification", "evidence gate", "large paste",
                  "dashboard isolation", "task-fit contract", "transaction rollback", "browser discovery",
                  "command safety", "browser wrapper"]
        for label in labels:
            print(f"{label + ' ':<24}.{('PASS' if results[label] else 'FAIL'):>8}")
        print(f"{'live ollama ':<24}.{('REACHABLE (smoke not auto-run)' if live else 'SKIP'):>8}")
        if browser_result.get("environment_error"):
            print(f"[BROWSER SELF-TEST LIMITATION] {browser_result.get('evidence')}")
        if browser_result.get("navigation_limitation"):
            print(f"[BROWSER NAVIGATION LIMITATION] {browser_result.get('navigation_limitation')}")
        if screenshot.exists():
            print(f"[BROWSER SELF-TEST SCREENSHOT] {screenshot}")
        return all(results.values())


# ---------------------------------------------------------------------------
# CLI / MAIN LOOP
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Small baseline vs recursive coding-agent experiment")
    parser.add_argument("--mode", choices=("auto", "baseline", "recursive"), default="auto",
                        help="auto is the normal UX; baseline/recursive remain available for A/B research")
    parser.add_argument("--model", help=f"Compatibility option; only {GEMMA_MODEL} is accepted")
    parser.add_argument("--prompt-file", help="Read one large benchmark prompt from a file")
    parser.add_argument("--workspace", help="Workspace path (otherwise prompted interactively)")
    parser.add_argument("--self-test", action="store_true", help="Run deterministic architecture tests")
    parser.add_argument("--install-browser", action="store_true", help="Allow self-test/startup to install Playwright Chromium if missing")
    parser.add_argument("--no-bootstrap", action="store_true", help="Do not auto-install missing Python dependencies")
    return parser.parse_args()


def main():
    global WORKSPACE, LIVE_VIEW
    configure_console_streams()
    args = parse_args()
    if not ensure_dependencies(auto_install=not args.no_bootstrap):
        raise SystemExit(2)

    if args.self_test:
        ok = run_self_test(install_browser=args.install_browser)
        raise SystemExit(0 if ok else 1)

    try:
        print(f"[STARTUP 1/3] Verify required LOCAL model: {GEMMA_MODEL}")
        select_local_ollama_model(args.model)
        print("[STARTUP 2/3] Choose workspace")
        WORKSPACE = get_workspace(args.workspace)
    except RuntimeError as exc:
        print(f"[SETUP_ERROR] {exc}")
        raise SystemExit(2)

    print(f"Simple coding agent - model={MODEL}")
    if args.mode == "auto":
        print("[ROUTING] auto - baseline vs recursive will be decided AFTER you submit the prompt")
    else:
        print(f"[ROUTING] manual {args.mode} override (A/B research only)")
    print("[STARTUP 3/3] Submit your prompt; routing is chosen only after goal understanding")
    print("Type 'exit' to quit.\n")

    memory = load_memory()
    baseline_history = [{"role": "system", "content": SYSTEM_PROMPT}]

    def handle(user_text, interactive=True):
        nonlocal memory, baseline_history
        if not user_text:
            return
        print(f"[USER REQUEST] {prompt_display(user_text)}")
        error = precheck_file_reference(user_text)
        if error:
            print(error + "\n")
            return
        if args.mode == "baseline":
            result, memory, baseline_history = run_baseline_request(user_text, memory, baseline_history)
        elif args.mode == "recursive":
            result, memory = run_recursive_request(user_text, memory, interactive=interactive)
        else:
            result, memory, baseline_history = run_auto_request(
                user_text, memory, history=baseline_history, interactive=interactive
            )
        print("Agent>", result.get("summary", ""))

    if args.prompt_file:
        task_file = Path(args.prompt_file).expanduser().resolve()
        if not task_file.exists():
            print(f"[SETUP_ERROR] prompt file does not exist: {task_file}")
            raise SystemExit(2)
        handle(task_file.read_text(encoding="utf-8"), interactive=False)
        return

    while True:
        try:
            user_text = read_user_prompt()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user_text.lower() in {"exit", "quit"}:
            break
        handle(user_text, interactive=True)


if __name__ == "__main__":
    main()
