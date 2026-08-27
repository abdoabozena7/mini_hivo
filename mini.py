import argparse
import base64
import importlib
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# CONFIG - keep model/provider configuration simple for the experiment
# ---------------------------------------------------------------------------

MODEL = ""
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_URL = OLLAMA_BASE_URL + "/api/chat"

WORKSPACE = None
MEMORY_FILE = ".agent_memory.json"
EXPERIMENT_FILE = ".agent_experiment.jsonl"
EVIDENCE_DIR = ".agent_evidence"

MAX_TOOL_STEPS = 20
MAX_DEPTH = 3
MAX_CHILDREN = 4
MAX_TOTAL_TASKS = 12
MAX_CLARIFICATION_QUESTIONS = 5
MAX_REPAIRS_PER_LEAF = 2
MAX_STRUCTURED_RETRIES = 5
CONTEXT_LIMIT_TOKENS = 32768
MODEL_TASK_CAPACITY = 2  # auto-derived from the selected local model; 1=very weak ... 4=stronger
ENABLE_VISION = False

DANGEROUS = ["rm -rf", "sudo", "mkfs", "shutdown", "reboot", "format ", "del /f", ":(){"]
KNOWN_DEPENDENCIES = {
    "requests": "requests>=2.31,<3",
    "rich": "rich>=13.7,<15",
    "prompt_toolkit": "prompt_toolkit>=3.0.43,<4",
    "playwright": "playwright>=1.45,<2",
}

requests = None
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


# ---------------------------------------------------------------------------
# DEPENDENCY BOOTSTRAP
# ---------------------------------------------------------------------------

def _load_optional_imports():
    global requests, RICH_AVAILABLE, PROMPT_TOOLKIT_AVAILABLE, PLAYWRIGHT_AVAILABLE
    global Console, Live, Panel, Table, Tree, Group, Text, prompt, KeyBindings, PathCompleter, radiolist_dialog, sync_playwright

    try:
        requests = importlib.import_module("requests")
    except ImportError:
        requests = None

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
    if requests is None:
        raise RuntimeError("requests dependency is unavailable")
    if not is_local_ollama_url(OLLAMA_BASE_URL):
        raise RuntimeError(
            f"OLLAMA_BASE_URL must point to local Ollama only; got: {OLLAMA_BASE_URL}"
        )
    try:
        response = requests.get(OLLAMA_BASE_URL + "/api/tags", timeout=5)
    except requests.exceptions.RequestException as exc:
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


def select_local_ollama_model(explicit=None):
    global MODEL, MODEL_TASK_CAPACITY
    models = fetch_local_ollama_models()
    if not models:
        raise RuntimeError(
            "no LOCAL Ollama models were found. Pull at least one local model first, "
            "for example: `ollama pull qwen2.5-coder:7b`. Cloud-tagged models are intentionally hidden."
        )

    by_name = {(item.get("name") or item.get("model")): item for item in models}
    if explicit:
        if explicit not in by_name:
            available = ", ".join(by_name)
            raise RuntimeError(f"requested local model '{explicit}' was not found. Available local models: {available}")
        chosen = by_name[explicit]
    elif PROMPT_TOOLKIT_AVAILABLE and sys.stdin.isatty():
        values = [(name, _model_choice_label(info)) for name, info in by_name.items()]
        selected = radiolist_dialog(
            title="Local Ollama Model",
            text="Use Up/Down arrows to choose a LOCAL model, then press Enter.",
            values=values,
        ).run()
        if not selected:
            raise SystemExit()
        chosen = by_name[selected]
    elif len(models) == 1:
        chosen = models[0]
        print(f"[MODEL AUTO-SELECT] {_model_choice_label(chosen)}")
    else:
        raise RuntimeError(
            "multiple local models are installed but no interactive terminal is available. "
            "Use --model <name> for non-interactive runs."
        )

    MODEL = chosen.get("name") or chosen.get("model")
    MODEL_TASK_CAPACITY = infer_model_capacity(chosen)
    print(f"[MODEL] {MODEL}")
    print("[PROVIDER] local Ollama only")
    print("[CLOUD MODELS] hidden/disabled by this agent selection")
    print(f"[CAPACITY] {MODEL_TASK_CAPACITY}/4 (AUTO-ESTIMATED FROM MODEL SIZE; EXPERIMENTAL)")
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
        "description": "Create a file, or overwrite an existing one (a backup is made automatically first).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
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
]


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
# MEMORY - preserved small JSON workspace memory
# ---------------------------------------------------------------------------

def load_memory():
    path = WORKSPACE / MEMORY_FILE
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"workspace": str(WORKSPACE), "recent_files": [], "operations": [],
            "last_error": None, "last_fix_attempt": None}


def update_memory(memory, tool_name, tool_args, result):
    path_arg = tool_args.get("path")
    if path_arg:
        if path_arg in memory["recent_files"]:
            memory["recent_files"].remove(path_arg)
        memory["recent_files"] = [path_arg] + memory["recent_files"][:9]

    memory["operations"] = memory["operations"][-19:] + [{
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tool": tool_name, "args": tool_args, "result": str(result)[:200],
    }]

    if tool_name in ("run_file", "run_command"):
        lower = str(result).lower()
        is_error = "error" in lower or "traceback" in lower or "exception" in lower
        memory["last_error"] = str(result)[:500] if is_error else None

    if tool_name == "write_file" and memory.get("last_error"):
        memory["last_fix_attempt"] = f"Edited {path_arg} after an error"

    try:
        (WORKSPACE / MEMORY_FILE).write_text(json.dumps(memory, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"[WARN] could not save memory file: {exc}")
    return memory


# ---------------------------------------------------------------------------
# TOOL IMPLEMENTATIONS - intentionally kept simple
# ---------------------------------------------------------------------------

def backup(target):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = target.with_name(target.name + f".backup_{stamp}")
    try:
        shutil.copy2(target, backup_path)
        return f" (backup created: {backup_path.name})"
    except OSError as exc:
        return f"error: backup failed, file NOT changed: {exc}"


def write_file(path, content):
    target = safe_path(path)
    if target is None:
        return f"error: '{path}' is outside the workspace."
    note = ""
    if target.exists():
        note = backup(target)
        if note.startswith("error"):
            return note
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"wrote file: {target}{note}"
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
        names = [p.name for p in sorted(WORKSPACE.iterdir())
                 if MEMORY_FILE not in p.name and ".backup_" not in p.name]
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
            cmd = ["node", str(target)]
        elif ext in (".cpp", ".cc"):
            exe = target.with_suffix(".out")
            build = subprocess.run(["g++", str(target), "-o", str(exe)], cwd=WORKSPACE,
                                   capture_output=True, text=True, timeout=30)
            if build.returncode != 0:
                return f"compile error:\n{build.stderr}"
            cmd = [str(exe)]
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


def run_command(command):
    if any(bad in command.lower() for bad in DANGEROUS):
        return f"error: this command was refused for safety reasons: {command}"
    try:
        result = subprocess.run(command, shell=True, cwd=WORKSPACE,
                                capture_output=True, text=True, timeout=60)
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return "error: command timed out (60s limit)"
    except Exception as exc:
        return f"tool error: {exc}"


def run_tool(name, args):
    if name == "write_file":
        return write_file(args["path"], args["content"])
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
    return f"unknown tool: {name}"


# ---------------------------------------------------------------------------
# SYSTEM PROMPT - unchanged core coding behavior
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a terminal coding agent working ONLY inside one workspace folder. "
    "Never access, describe, or reference any path outside it.\n"
    "Use read_file before explaining or editing a file - never answer from "
    "general knowledge. Use write_file to create or update a file (it backs "
    "up automatically). Use list_files if unsure what exists. Use run_file "
    "to execute a file and check its real output.\n"
    "If a request is unclear or a tool returns an error, say so plainly "
    "instead of guessing.\n"
    "To fix broken code: read_file, run_file, find the cause of the error, "
    "write_file with the corrected version, run_file again to confirm it "
    "works, then report what was wrong and what you changed. If it still "
    "fails, repeat rather than giving up after one try.\n"
    "Never attempt destructive or system-altering commands. "
    "When done, give a short final answer with the result."
)


# ---------------------------------------------------------------------------
# METRICS / TERMINAL VISIBILITY
# ---------------------------------------------------------------------------

def new_metrics(mode):
    return {
        "mode": mode, "model": MODEL, "clarification_questions": 0,
        "tasks_created": 0, "leaf_tasks": 0, "splits": 0, "re_splits": 0,
        "max_depth": 0, "builder_calls": 0, "predictor_calls": 0,
        "challenger_calls": 0, "falsifier_calls": 0, "repairer_calls": 0,
        "quality_reviews": 0, "browser_checks": 0, "verification_failures": 0,
        "task_too_broad_count": 0, "model_calls": 0, "tool_calls": 0,
        "peak_estimated_context_tokens": 0, "elapsed_seconds": 0.0,
        "status": "unknown",
    }


def reset_run(mode):
    global RUN, TASKS, ROLE_STATUS, DASHBOARD, RUN_STARTED, VISION_ENABLED_FOR_RUN
    RUN = new_metrics(mode)
    TASKS = {}
    ROLE_STATUS = {
        "Coordinator": "active", "Predictor": "unused", "Builder": "waiting",
        "Challenger": "unused", "Falsifier": "waiting", "Quality Review": "waiting",
        "Repairer": "unused", "Browser": "waiting",
    }
    DASHBOARD = {"mode": mode, "context": 0, "active_role": "Coordinator", "active_task": "ROOT",
                 "action": "starting", "tool": "-", "event": f"[MODE] {mode}"}
    RUN_STARTED = time.time()
    VISION_ENABLED_FOR_RUN = ENABLE_VISION


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
    refresh_dashboard()


def print_context(messages):
    estimate = estimate_context_tokens(messages)
    RUN["peak_estimated_context_tokens"] = max(RUN["peak_estimated_context_tokens"], estimate)
    DASHBOARD["context"] = estimate
    remaining = max(0.0, 100.0 * (1 - estimate / CONTEXT_LIMIT_TOKENS))
    print(f"[MODEL] {MODEL}")
    print(f"[CALL] {RUN['model_calls']}")
    print(f"[CONTEXT] ESTIMATED {estimate:,} / {CONTEXT_LIMIT_TOKENS:,} tokens | ~{remaining:.0f}% remaining")
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
    append_metrics()


# ---------------------------------------------------------------------------
# OLLAMA CALLS + TINY STRUCTURED JSON HELPER
# ---------------------------------------------------------------------------

def ask_ollama(messages, tools=TOOLS, response_format=None, temperature=None):
    if requests is None:
        raise RuntimeError("requests dependency is unavailable")
    RUN["model_calls"] += 1
    print_context(messages)
    headers = {}
    api_key = os.environ.get("OLLAMA_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {"model": MODEL, "messages": messages, "stream": False}
    if tools is not None:
        payload["tools"] = tools
    if response_format is not None:
        payload["format"] = response_format
    if temperature is not None:
        payload["options"] = {"temperature": temperature}
    try:
        response = requests.post(OLLAMA_URL, headers=headers, timeout=300, json=payload)
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"could not reach Ollama at {OLLAMA_URL}: {exc}")

    if response.status_code in (401, 403):
        raise RuntimeError("authentication failed - sign in (`ollama signin`) or check OLLAMA_API_KEY.")
    if response.status_code != 200:
        raise RuntimeError(f"Ollama returned an error (status {response.status_code}): {response.text}")
    try:
        message = response.json()["message"]
    except (ValueError, KeyError):
        raise RuntimeError("invalid response from the model.")
    if not message.get("content") and not message.get("tool_calls"):
        raise RuntimeError("empty response from the model.")
    return message


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
            message = ask_ollama(messages, tools=None, response_format=schema, temperature=0)
            last_content = message.get("content", "")
            data = _normalize_structured_data(_parse_json_content(last_content), label)
            if validator(data):
                return data
            last_error = f"JSON parsed but failed {label} validation"
        except RuntimeError:
            # Provider/network/auth failures are not structured-output mistakes.
            raise
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            last_error = str(exc)

        attempt_no = attempt + 1
        print(f"[STRUCTURED RETRY] {label} {attempt_no}/{MAX_STRUCTURED_RETRIES} | {last_error}")
        if attempt_no < MAX_STRUCTURED_RETRIES:
            messages = [
                {"role": "system", "content": (
                    "STRICT JSON REPAIR. Return ONLY one JSON object matching the schema exactly. "
                    "No markdown, no explanation, no additional keys."
                )},
                {"role": "user", "content": (
                    f"The previous {label} output was invalid. Error: {last_error}\n"
                    f"Previous output: {last_content[:1500]}\n"
                    f"Required schema: {schema_text}\n"
                    "Generate a fresh valid object now."
                )},
            ]
    raise RuntimeError(
        f"invalid {label} structured response after {MAX_STRUCTURED_RETRIES} strict attempts: {last_error}"
    )


# ---------------------------------------------------------------------------
# REUSABLE EXISTING TOOL LOOP (baseline and recursive leaves share this)
# ---------------------------------------------------------------------------

def execute_agent_task(task_text, memory, messages=None, role="Builder", task_id="ROOT", extra_context=""):
    if messages is None:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if extra_context:
        task_text = f"{extra_context}\n\nCURRENT TASK:\n{task_text}"
    messages.append({"role": "user", "content": task_text})
    tool_evidence = []
    status = "unknown"
    summary = ""
    provider_error = None

    ROLE_STATUS[role] = "working"
    event(f"[{role.upper()}] {task_id} executing", role=role, task=task_id, action="model/tool loop")

    for _step in range(MAX_TOOL_STEPS):
        try:
            assistant_message = ask_ollama(messages)
        except RuntimeError as exc:
            provider_error = str(exc)
            status = "provider_failure"
            summary = provider_error
            event(f"[ERROR] {provider_error}", role=role, task=task_id, action="provider failure")
            break

        messages.append(assistant_message)
        tool_calls = assistant_message.get("tool_calls", [])
        if not tool_calls:
            summary = assistant_message.get("content", "") or "done"
            status = "done"
            break

        for call in tool_calls:
            name = call["function"]["name"]
            args = call["function"]["arguments"]
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            target = args.get("path") or args.get("command") or "-"
            RUN["tool_calls"] += 1
            event(f"[TOOL] {name} {compact_text(target, 80)}", role=role, task=task_id,
                  action=f"using {name}", tool=name)
            if role == "Falsifier" and name in {"write_file", "backup_file"}:
                result = "error: Falsifier is read-only and may not modify files"
            else:
                result = run_tool(name, args)
            print(f"[RESULT] {str(result)[:300]}")
            tool_evidence.append({"tool": name, "target": target, "result": str(result)[:1000]})
            memory = update_memory(memory, name, args, str(result))
            messages.append({"role": "tool", "content": str(result)})

            if memory.get("last_error") and name in ("run_file", "run_command"):
                print(f"[ERROR DETECTED] {memory['last_error'][:200]}")
                messages.append({
                    "role": "user",
                    "content": (
                        "Execution failed. Automatically read the file, diagnose the error, "
                        "create a backup, fix the code, run it again, and verify the result."
                    ),
                })
            if name == "write_file" and memory.get("last_fix_attempt"):
                print(f"[FIX ATTEMPT] {memory['last_fix_attempt']}")
    else:
        status = "too_broad"
        summary = "TASK_TOO_BROAD: existing maximum tool-step limit reached"

    ROLE_STATUS[role] = "done" if status == "done" else "failed"
    return {
        "status": status, "summary": compact_text(summary, 700), "messages": messages,
        "memory": memory, "tool_evidence": tool_evidence, "provider_error": provider_error,
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
    return structured_model_call(prompt_text, _goal_validator, "goal-understanding", schema)


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
        return True
    subtasks = data.get("subtasks")
    return isinstance(subtasks, list) and 2 <= len(subtasks) <= MAX_CHILDREN and all(isinstance(x, str) and x.strip() for x in subtasks)


def decide_task_fit(task, depth, contract, dependency_summaries=None):
    if depth >= MAX_DEPTH or RUN["tasks_created"] >= MAX_TOTAL_TASKS:
        return {"decision": "execute", "reason": "recursion limit reached"}
    deps = dependency_summaries or []
    prompt_text = f"""Decide whether this task is small/cohesive enough for one focused coding-agent execution.
Return exactly one JSON object containing ALL schema fields.
EXECUTE: {{"decision":"execute","reason":"short reason","subtasks":[]}}
SPLIT: {{"decision":"split","reason":"short reason","subtasks":["...","..."]}}
Split only when there are multiple independently solvable/verifiable pieces, too much context at once, or the task is too broad for one focused execution.
Do not split trivial work. Children must collectively preserve the parent goal. Prefer 2-4 meaningful children. Do not invent unrelated work.
MODEL_TASK_CAPACITY={MODEL_TASK_CAPACITY}/4 (EXPERIMENTAL MANUAL CAPACITY). Low capacity means split more conservatively into narrower tasks.
Depth={depth}; max_depth={MAX_DEPTH}; remaining_task_budget={MAX_TOTAL_TASKS - RUN['tasks_created']}.
ROOT CONTRACT: {compact_contract(contract)}
TASK: {task['goal']}
COMPLETED DEPENDENCY SUMMARIES: {json.dumps(deps[-3:], ensure_ascii=False)}
{('ORIGINAL ROOT REQUEST (root planning only): ' + contract.get('original_goal', '')) if depth == 0 else ''}"""
    schema = {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["execute", "split"]},
            "reason": {"type": "string"},
            "subtasks": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_CHILDREN},
        },
        "required": ["decision", "reason", "subtasks"],
        "additionalProperties": False,
    }
    return structured_model_call(prompt_text, _fit_validator, "task-fit", schema)


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
    high_words = ("auth", "security", "migration", "database", "architecture", "refactor", "payment", "permission", "concurrent")
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
        message = ask_ollama(messages, tools=None)
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

def browser_snapshot(url, task_id="ROOT"):
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
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**browser_launch_kwargs())
            page = browser.new_page()
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            title = page.title()
            final_url = page.url
            text = page.locator("body").inner_text(timeout=5000)[:4000]
            page.screenshot(path=str(screenshot), full_page=True)
            browser.close()
        print(f"[BROWSER] title={json.dumps(title)}")
        print(f"[BROWSER] console_errors={len(console_errors)}")
        print(f"[SCREENSHOT] {screenshot.relative_to(WORKSPACE)}")
        ROLE_STATUS["Browser"] = "done"
        return {"passed": not console_errors and not page_errors, "environment_error": False,
                "title": title, "url": final_url, "text": text,
                "console_errors": console_errors, "page_errors": page_errors,
                "screenshot": str(screenshot.relative_to(WORKSPACE))}
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


def optional_browser_check(task):
    lower = task["goal"].lower()
    webish = any(word in lower for word in ("web", "frontend", "browser", "html", "css", "react", "page", "ui"))
    url = _extract_local_url(task["goal"])
    if webish and url:
        return browser_snapshot(url, task["id"])
    ROLE_STATUS["Browser"] = "unused"
    return None


def maybe_vision_review(browser_result, task, contract):
    global VISION_ENABLED_FOR_RUN
    if not VISION_ENABLED_FOR_RUN or not browser_result or not browser_result.get("screenshot"):
        return None
    screenshot = safe_path(browser_result["screenshot"])
    if screenshot is None or not screenshot.exists():
        return None
    try:
        image_b64 = base64.b64encode(screenshot.read_bytes()).decode("ascii")
        messages = [{"role": "user", "content": f"Verify screenshot against task: {task['goal']}\nContract: {compact_contract(contract)}",
                     "images": [image_b64]}]
        message = ask_ollama(messages, tools=None)
        return compact_text(message.get("content", ""), 500)
    except Exception as exc:
        print(f"[WARN] vision verification disabled for this run: {exc}")
        VISION_ENABLED_FOR_RUN = False
        return None


# ---------------------------------------------------------------------------
# QUALITY REVIEW / EVIDENCE GATE / REPAIR
# ---------------------------------------------------------------------------

def _quality_validator(data):
    if not isinstance(data, dict) or not isinstance(data.get("checks"), list):
        return False
    allowed = {"PASS", "FAIL", "NOT_APPLICABLE"}
    for check in data["checks"]:
        if not isinstance(check, dict) or check.get("status") not in allowed:
            return False
        if not isinstance(check.get("name"), str) or not isinstance(check.get("evidence"), str):
            return False
    return True


def review_quality(task, contract, builder_result, adaptive, browser_result=None, fresh=False):
    RUN["quality_reviews"] += 1
    ROLE_STATUS["Quality Review"] = "working"
    event(f"[VERIFY] {'fresh verification' if fresh else task['id']}", role="Quality Review",
          task=task["id"], action="evidence review", tool="-")
    evidence = {
        "builder_status": builder_result.get("status"),
        "builder_summary": builder_result.get("summary"),
        "builder_tool_evidence": builder_result.get("tool_evidence", [])[-8:],
        "falsifier_summary": adaptive.get("falsifier", ""),
        "falsifier_tool_evidence": (adaptive.get("falsifier_result") or {}).get("tool_evidence", [])[-8:],
        "browser": browser_result,
    }
    prompt_text = f"""Review this coding task against relevant fixed quality concerns:
correctness, testing, security, clean code/maintainability, architecture consistency, regression, goal fidelity.
Select only concerns relevant to this task. For each return PASS, FAIL, or NOT_APPLICABLE with short concrete evidence.
Do not say 'looks correct'. Prefer actual command/test/file/browser evidence. A missing executable check should not become PASS.
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
                            "status": {"type": "string", "enum": ["PASS", "FAIL", "NOT_APPLICABLE"]},
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
        result = {"checks": [{"name": "verification", "status": "FAIL", "evidence": f"quality review unavailable: {exc}"}]}
    ROLE_STATUS["Quality Review"] = "done"
    return result


def evidence_gate(builder_result, quality):
    checks = quality.get("checks", [])
    failures = [check for check in checks if check.get("status") == "FAIL"]
    deterministic_failure = any(
        any(term in item.get("result", "").lower() for term in ("traceback", "compile error", "syntaxerror"))
        for item in builder_result.get("tool_evidence", [])
    )
    passed = builder_result.get("status") == "done" and bool(checks) and not failures and not deterministic_failure
    if not passed:
        RUN["verification_failures"] += 1
    return {"passed": passed, "checks": checks, "deterministic_failure": deterministic_failure}


def classify_failure(builder_result, quality, browser_result=None):
    if builder_result.get("status") == "too_broad":
        return "TASK_TOO_BROAD"
    if builder_result.get("status") == "provider_failure":
        return "ENVIRONMENT_ERROR"
    evidence_text = json.dumps({"quality": quality, "browser": browser_result}, ensure_ascii=False).lower()
    if any(term in evidence_text for term in ("connection refused", "not found", "unavailable", "missing dependency", "browser executable")):
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


# ---------------------------------------------------------------------------
# FOCUSED LEAF EXECUTION
# ---------------------------------------------------------------------------

def leaf_context(contract, task, parent_summary, dependency_summaries, predictor="", challenger=""):
    return (
        f"ROOT GOAL CONTRACT (compact; authoritative):\n{compact_contract(contract)}\n\n"
        f"PARENT CONTEXT: {compact_text(parent_summary or '(none)', 900)}\n"
        f"COMPLETED DEPENDENCIES: {json.dumps(dependency_summaries[-4:], ensure_ascii=False)[:3000]}\n"
        f"PREDICTOR CHECKLIST: {predictor or '(not used)'}\n"
        f"CHALLENGER NOTE: {challenger or '(not used)'}\n"
        "Use the shared workspace as source of truth. Do not assume sibling hidden history. "
        "Implement only this leaf and verify with real evidence where possible."
    )


def execute_builder(task, contract, memory, parent_summary="", dependency_summaries=None):
    dependency_summaries = dependency_summaries or []
    RUN["leaf_tasks"] += 1
    RUN["builder_calls"] += 1
    risk = task_risk(task["goal"])
    predictor = challenger = ""
    if risk == "high":
        predictor = short_role_call("Predictor", task, contract,
                                    "Predict likely failure points/interfaces/regressions. Short checklist only.")
        if any(word in task["goal"].lower() for word in ("design", "architecture", "approach")):
            challenger = short_role_call("Challenger", task, contract,
                                         "Challenge the approach for simplicity/safety before implementation. Do not modify files.")

    context = leaf_context(contract, task, parent_summary, dependency_summaries, predictor, challenger)
    result = execute_agent_task(task["goal"], memory, role="Builder", task_id=task["id"], extra_context=context)
    memory = result["memory"]
    if result["status"] == "too_broad":
        RUN["task_too_broad_count"] += 1
        return {"status": "too_broad", "summary": result["summary"], "memory": memory, "builder": result}
    if result["status"] == "provider_failure":
        return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": result["summary"], "memory": memory, "builder": result}

    adaptive = run_adaptive_checks(task, contract, memory, result, allow_falsifier=True)
    memory = adaptive["memory"]
    browser_result = optional_browser_check(task)
    maybe_vision_review(browser_result, task, contract)
    quality = review_quality(task, contract, result, adaptive, browser_result, fresh=False)
    gate = evidence_gate(result, quality)
    if gate["passed"]:
        return {"status": "done", "summary": result["summary"], "memory": memory,
                "builder": result, "quality": quality, "gate": gate, "browser": browser_result}

    failure_type = classify_failure(result, quality, browser_result)
    if failure_type != "IMPLEMENTATION_ERROR":
        if failure_type == "TASK_TOO_BROAD":
            RUN["task_too_broad_count"] += 1
        return {"status": "too_broad" if failure_type == "TASK_TOO_BROAD" else "failed",
                "failure_type": failure_type, "summary": f"verification failed: {failure_type}",
                "memory": memory, "builder": result, "quality": quality, "gate": gate, "browser": browser_result}

    current = result
    for _repair in range(MAX_REPAIRS_PER_LEAF):
        repaired = repair_task(task, contract, {"quality": quality, "gate": gate, "browser": browser_result}, memory)
        memory = repaired["memory"]
        if repaired["status"] == "provider_failure":
            return {"status": "failed", "failure_type": "ENVIRONMENT_ERROR", "summary": repaired["summary"], "memory": memory}
        if repaired["status"] == "too_broad":
            RUN["task_too_broad_count"] += 1
            return {"status": "too_broad", "failure_type": "TASK_TOO_BROAD", "summary": repaired["summary"], "memory": memory}
        current = repaired
        fresh_adaptive = {"falsifier": "not rerun; one Falsifier call max per leaf", "falsifier_result": None}
        fresh_browser = optional_browser_check(task)
        quality = review_quality(task, contract, current, fresh_adaptive, fresh_browser, fresh=True)
        gate = evidence_gate(current, quality)
        if gate["passed"]:
            return {"status": "done", "summary": current["summary"], "memory": memory,
                    "builder": current, "quality": quality, "gate": gate, "browser": fresh_browser}
        failure_type = classify_failure(current, quality, fresh_browser)
        if failure_type != "IMPLEMENTATION_ERROR":
            return {"status": "too_broad" if failure_type == "TASK_TOO_BROAD" else "failed",
                    "failure_type": failure_type, "summary": f"fresh verification failed: {failure_type}", "memory": memory}

    return {"status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "failed evidence gate after repair limit", "memory": memory}


# ---------------------------------------------------------------------------
# AGGREGATION / INTEGRATION
# ---------------------------------------------------------------------------

def aggregate_task(task, contract, child_results, memory, root=False):
    label = "ROOT" if root else task["id"]
    event(f"[AGGREGATE {label}]", role="Builder", task=label, action="integration verification")
    child_info = [{"task": child["task"], "status": child["result"]["status"],
                   "summary": child["result"].get("summary", "")} for child in child_results]
    if any(item["status"] != "done" for item in child_info):
        return {"status": "failed", "summary": "one or more child tasks failed", "memory": memory,
                "children": child_info}

    RUN["builder_calls"] += 1
    instruction = (
        f"ROOT CONTRACT: {compact_contract(contract)}\n"
        f"PARENT GOAL: {task['goal']}\n"
        f"CHILD RESULTS: {json.dumps(child_info, ensure_ascii=False)[:8000]}\n"
        f"{('ORIGINAL ROOT REQUEST: ' + contract.get('original_goal', '')) if root else ''}\n"
        "Inspect the combined REAL workspace. Integrate only necessary gaps, resolve conflicts, and verify the parent goal. "
        "At root explicitly check original outcome, root constraints, and missing requirements. Return a short result summary."
    )
    result = execute_agent_task(instruction, memory, role="Builder", task_id=label)
    memory = result["memory"]
    if result["status"] != "done":
        return {"status": "failed", "summary": result["summary"], "memory": memory}
    adaptive = {"falsifier": "parent integration verification", "falsifier_result": None}
    quality = review_quality(task, contract, result, adaptive, optional_browser_check(task), fresh=True)
    gate = evidence_gate(result, quality)
    return {"status": "done" if gate["passed"] else "failed", "summary": result["summary"],
            "memory": memory, "quality": quality, "gate": gate}


# ---------------------------------------------------------------------------
# TRUE RECURSION
# ---------------------------------------------------------------------------

def solve_task(task, depth, contract, memory, parent_summary="", dependency_summaries=None, fit_decider=None, leaf_executor=None):
    dependency_summaries = dependency_summaries or []
    task["status"] = "running"
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
                return aggregate

    task["status"] = leaf.get("status", "failed")
    task["summary"] = leaf.get("summary", "")
    event(f"[{'DONE' if task['status'] == 'done' else 'FAILED'} {task['id']}]", task=task["id"], action="leaf complete")
    return leaf


# ---------------------------------------------------------------------------
# INPUT / WORKSPACE SETUP
# ---------------------------------------------------------------------------

def get_workspace(explicit=None):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            raise RuntimeError(f"workspace is not a folder: {path}")
        print(f"workspace set to: {path}\n")
        return path
    while True:
        if PROMPT_TOOLKIT_AVAILABLE and sys.stdin.isatty():
            print("Choose workspace folder. Type a path; Tab autocompletes folders.")
            raw = prompt("Workspace> ", completer=PathCompleter(only_directories=True, expanduser=True)).strip()
        else:
            raw = input("Enter the workspace folder path: ").strip()
        if raw.lower() in ("exit", "quit"):
            raise SystemExit()
        if not raw:
            print("error: workspace is required. Choose/type a folder path; blank Enter is not accepted.")
            continue
        path = Path(raw).expanduser().resolve()
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


def get_goal_contract(raw_goal, interactive=True):
    answers = []
    for attempt in range(MAX_CLARIFICATION_QUESTIONS + 1):
        result = understand_goal(raw_goal, "\n".join(answers))
        if result["status"] == "ready":
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


def decide_execution_mode(raw_goal, contract):
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
Choose RECURSIVE when the goal contains multiple independently implementable/verifiable parts, many components/files/features, a large project specification, substantial integration work, or is too broad for this model in one focused context.
When capacity is low, prefer recursive mode earlier. Do not choose recursive just because a task is non-trivial.

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
    return structured_model_call(prompt_text, _mode_validator, "execution-mode", schema)


def baseline_prompt_with_clarifications(raw_goal, contract):
    clarifications = contract.get("clarifications") or []
    if not clarifications:
        return raw_goal
    return raw_goal + "\n\nPRE-EXECUTION CLARIFICATIONS (authoritative):\n" + "\n\n".join(clarifications)


# ---------------------------------------------------------------------------
# RUN MODES
# ---------------------------------------------------------------------------

def run_baseline_request(user_text, memory, history=None, reset=True, finish=True):
    if reset:
        reset_run("baseline")
    else:
        RUN["mode"] = "baseline"
        DASHBOARD["mode"] = "baseline"
    RUN["tasks_created"] = 1
    RUN["leaf_tasks"] = 1
    RUN["builder_calls"] = 1
    RUN["max_depth"] = 0
    TASKS["ROOT"] = {"id": "ROOT", "goal": user_text, "depth": 0, "parent": None,
                     "status": "running", "children": [], "summary": ""}
    print("[MODE] baseline")
    print(f"[MODEL] {MODEL}")
    print(f"[ROOT] {compact_text(user_text, 160)}")
    messages = history if history is not None else [{"role": "system", "content": SYSTEM_PROMPT}]
    result = execute_agent_task(user_text, memory, messages=messages, role="Builder", task_id="ROOT")
    TASKS["ROOT"]["status"] = "done" if result["status"] == "done" else "failed"
    TASKS["ROOT"]["summary"] = result["summary"]
    final_status = "done" if result["status"] == "done" else result["status"]
    if finish:
        finish_metrics(final_status)
    return result, result["memory"], result["messages"]


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
            effective_prompt, memory, history=history, reset=False, finish=False
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
    global WORKSPACE, ask_ollama, execute_agent_task, run_adaptive_checks, review_quality, repair_task, optional_browser_check
    WORKSPACE = Path(tmp)
    memory = load_memory()

    # 1. Baseline really enters the shared existing-style loop once and never splits.
    real_ask = ask_ollama
    def mock_ask(messages, tools=TOOLS):
        RUN["model_calls"] += 1
        return {"role": "assistant", "content": "mock baseline done"}
    ask_ollama = mock_ask
    baseline_result, memory, _history = run_baseline_request("single baseline task", memory)
    baseline_ok = baseline_result["status"] == "done" and RUN["tasks_created"] == 1 and RUN["leaf_tasks"] == 1 and RUN["splits"] == 0
    ask_ollama = real_ask

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
                "tool_evidence": [{"tool": "run_command", "result": "tests ran"}]}
    def fake_adaptive(task, contract, mem, builder, allow_falsifier=True):
        return {"risk": "normal", "falsifier": "checked", "falsifier_result": None, "memory": mem}
    def fake_review(task, contract, builder, adaptive, browser_result=None, fresh=False):
        state["reviews"] += 1
        if state["reviews"] == 1:
            return {"checks": [{"name": "tests", "status": "FAIL", "evidence": "1 failed"}]}
        return {"checks": [{"name": "tests", "status": "PASS", "evidence": "1 passed fresh"}]}
    def fake_repair(task, contract, evidence, mem):
        state["repairs"] += 1
        return {"status": "done", "summary": "repaired", "memory": mem,
                "tool_evidence": [{"tool": "run_command", "result": "1 passed fresh"}]}
    execute_agent_task, run_adaptive_checks = fake_execute, fake_adaptive
    review_quality, repair_task, optional_browser_check = fake_review, fake_repair, lambda task: None
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

    return {"architecture": baseline_ok, "true recursion": recursion_ok, "max depth": depth_ok,
            "max total tasks": total_ok, "focused context": focused_ok, "re-split": resplit_ok,
            "repair routing": repair_ok, "fresh verification": fresh_ok,
            "evidence gate": failed_not_done_ok, "large paste": large_ok,
            "dashboard isolation": dashboard_ok}

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
        except subprocess.TimeoutExpired: server.kill()

    if result.get("environment_error"):
        result = browser_inline_snapshot(html, "browser_self_test")
        result["navigation_limitation"] = navigation_limitation
    screenshot = WORKSPACE / EVIDENCE_DIR / "task_browser_self_test.png"
    passed = (not result.get("environment_error") and result.get("title") == "Agent Browser Test"
              and "Browser wrapper works" in result.get("text", "")
              and len(result.get("console_errors", [])) == 1 and screenshot.exists())
    return passed, result, screenshot

def ollama_reachable():
    if not OLLAMA_URL or requests is None:
        return False
    try:
        response = requests.get(OLLAMA_URL.rsplit("/api/chat", 1)[0] + "/api/tags", timeout=2)
        return response.status_code == 200
    except Exception:
        return False


def run_self_test(install_browser=False):
    global WORKSPACE
    print("[SELF TEST]")
    with tempfile.TemporaryDirectory(prefix="agent21_selftest_") as tmp:
        results = _self_test_architecture(tmp)
        browser_ok, browser_result, screenshot = _self_test_browser(tmp, install_browser=install_browser)
        results["browser wrapper"] = browser_ok
        live = ollama_reachable()

        labels = ["architecture", "true recursion", "max depth", "max total tasks", "focused context",
                  "re-split", "repair routing", "fresh verification", "evidence gate", "large paste",
                  "dashboard isolation", "browser wrapper"]
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
    parser.add_argument("--model", help="Use one installed LOCAL Ollama model without showing the arrow-key selector")
    parser.add_argument("--prompt-file", help="Read one large benchmark prompt from a file")
    parser.add_argument("--workspace", help="Workspace path (otherwise prompted interactively)")
    parser.add_argument("--self-test", action="store_true", help="Run deterministic architecture tests")
    parser.add_argument("--install-browser", action="store_true", help="Allow self-test/startup to install Playwright Chromium if missing")
    parser.add_argument("--no-bootstrap", action="store_true", help="Do not auto-install missing Python dependencies")
    return parser.parse_args()


def main():
    global WORKSPACE, LIVE_VIEW
    args = parse_args()
    if not ensure_dependencies(auto_install=not args.no_bootstrap):
        raise SystemExit(2)

    if args.self_test:
        ok = run_self_test(install_browser=args.install_browser)
        raise SystemExit(0 if ok else 1)

    try:
        print("[STARTUP 1/3] Choose LOCAL Ollama model")
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
