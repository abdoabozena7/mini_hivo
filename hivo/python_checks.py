"""Bounded Python-call assertions without accepting executable probe code."""

import contextlib
import ast
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


_RESULT_PREFIX = "HIVO_PYTHON_CALL:"

_CLI_EXAMPLE = re.compile(
    r"\b(?:running\s+)?(?:python3?|py)\s+([A-Za-z0-9_./\\-]+\.py)"
    r"(.*?)\s+prints?\s+exactly\s+(.+?)\s+followed\s+by\s+(?:a\s+)?newline\b",
    re.IGNORECASE,
)
_SAME_RETURN = re.compile(
    r"\b([A-Za-z]\w*\([^()]*\))\s+function\b.*?\breturns?\s+the\s+same\b"
    r".*?\bwithout\s+(?:a\s+)?(?:trailing\s+)?newline\b", re.IGNORECASE,
)


def runtime_documentation(request):
    match = re.fullmatch(r"([A-Za-z]\w*)\.([A-Za-z]\w*)", str(request.get("target", "")))
    if not match or match.group(1) not in sys.builtin_module_names:
        return None
    module = sys.modules.get(match.group(1))
    if module is None or match.group(2) not in vars(module):
        return None
    attribute = match.group(2)
    lines = str(module.__doc__ or "").splitlines()
    matching = [
        line.strip() for line in lines
        if re.search(r"\b" + re.escape(attribute) + r"\b", line)
    ]
    member = vars(module)[attribute]
    text = "\n".join(matching)
    if callable(member) and isinstance(member.__doc__, str):
        text = member.__doc__
    if not text:
        return None
    return {
        "request_kind": request["kind"], "target": request["target"],
        "resolution_status": "resolved" if len(text) <= 650 else "partial",
        "facts_established": [text[:650]],
        "evidence": [{
            "kind": request["kind"], "target": request["target"],
            "source_identity": "python-runtime:" + request["target"],
            "source_kind": "PYTHON_RUNTIME_DOCUMENTATION", "authoritative": True,
            "excerpt": text[:650], "interpreter_version": sys.version.split()[0],
        }],
        "resolver": "PYTHON_RUNTIME_DOCUMENTATION", "source_scan_performed": False,
    }


def source_exit_expectation(requirements, command_parts):
    """Recognize source-required rejection of malformed fixed-arity integer CLI input."""
    if (len(command_parts) < 2 or Path(command_parts[0]).stem.casefold() not in {"python", "python3", "py"}
            or Path(command_parts[1]).suffix.casefold() != ".py"):
        return None
    records = [
        item for item in requirements
        if item.get("provenance") in {"USER_STATED", "USER_CONFIRMED"}
    ]
    words = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
             "five": 5, "six": 6, "seven": 7, "eight": 8}
    counts = {}
    rejections = []
    paths = set()
    for record in records:
        text = str(record.get("text", ""))
        match = re.search(
            r"\bexactly\s+(\d+|zero|one|two|three|four|five|six|seven|eight)"
            r"\s+integer\s+command[- ]line\s+arguments?\b", text, re.IGNORECASE,
        )
        if match:
            count_text = match.group(1).casefold()
            count = int(count_text) if count_text.isdecimal() else words[count_text]
            counts.setdefault(count, []).append(record["requirement_id"])
        if (re.search(r"\b(?:invalid|missing)\b.*\bnon[- ]?zero\b", text, re.IGNORECASE)
                and not re.search(r"\b(?:not|never)\b.{0,40}\bnon[- ]?zero\b", text, re.IGNORECASE)):
            rejections.append(record["requirement_id"])
        paths.update(
            match.group(0).replace("\\", "/").removeprefix("./").casefold()
            for match in re.finditer(r"\b[A-Za-z0-9_./\\-]+\.py\b", text)
        )
    script = command_parts[1].replace("\\", "/").removeprefix("./").casefold()
    if len(counts) != 1 or paths != {script} or not rejections:
        return None
    count = next(iter(counts))
    invalid = len(command_parts[2:]) != count
    if not invalid:
        try:
            for argument in command_parts[2:]:
                int(argument)
        except ValueError:
            invalid = True
    if not invalid:
        return None
    return {
        "expected_exit_code": "nonzero", "script": script,
        "required_argument_count": count,
        "requirement_ids": [*counts[count], *rejections],
    }


def source_assertions(requirements):
    """Compile literal CLI examples and explicit CLI/return equality only."""
    examples = []
    functions = []
    for requirement in requirements:
        if requirement.get("provenance") not in {"USER_STATED", "USER_CONFIRMED"}:
            continue
        text = str(requirement.get("text", ""))
        match = _CLI_EXAMPLE.search(text)
        if match:
            path, raw_arguments, output = match.groups()
            raw_arguments = raw_arguments.strip()
            arguments = [] if raw_arguments.casefold() in {
                "", "without arguments", "with no arguments",
            } else shlex.split(raw_arguments)
            if len(output) >= 2 and output[0] == output[-1] and output[0] in "\"'`":
                output = output[1:-1]
            examples.append({
                "kind": "command", "path": path, "arguments": arguments,
                "expected": output + "\n", "requirement_ids": [requirement["requirement_id"]],
            })
        same = _SAME_RETURN.search(text)
        if same:
            declaration = ast.parse(same.group(1), mode="eval").body
            if (not isinstance(declaration, ast.Call) or not isinstance(declaration.func, ast.Name)
                    or declaration.args or len(declaration.keywords) != 1
                    or not isinstance(ast.literal_eval(declaration.keywords[0].value), str)):
                raise ValueError("CLI/return equality currently requires one declared string parameter")
            functions.append((declaration.func.id, requirement["requirement_id"]))
    paths = {example["path"] for example in examples}
    cases = list(examples)
    if functions and len(paths) != 1:
        raise ValueError("CLI/return equality requires one unambiguous source-declared Python script")
    for function, requirement_id in functions:
        for example in examples:
            if len(example["arguments"]) > 1:
                raise ValueError("CLI/return equality requires zero or one string CLI argument")
            cases.append({
                **example, "kind": "function", "function": function,
                "expected": example["expected"].removesuffix("\n"),
                "requirement_ids": [*example["requirement_ids"], requirement_id],
            })
    if len(cases) > 8:
        raise ValueError("source assertions exceed the eight-case verification bound")
    return cases


def check_source_assertion(workspace, case):
    if case["kind"] == "function":
        return check_call(
            workspace, case["path"], case["function"], case["arguments"], case["expected"],
        )
    root = Path(workspace).resolve()
    target = (root / case["path"]).resolve()
    if not target.is_relative_to(root) or target.suffix != ".py" or not target.is_file():
        return {"passed": False, "error": "Source assertion needs an existing workspace Python script"}
    try:
        result = subprocess.run(
            [sys.executable, str(target), *case["arguments"]], cwd=root,
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"passed": False, "error": f"Could not execute source assertion: {exc}"}
    return {
        "passed": result.returncode == 0 and result.stdout == case["expected"],
        "expected": case["expected"], "actual": result.stdout,
        "exit_code": result.returncode, "stderr": result.stderr,
        "source_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }


def check_call(workspace, path, function, arguments, expected):
    root = Path(workspace).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or target.suffix != ".py" or not target.is_file():
        return {"passed": False, "invalid_assertion": True,
                "error": "Python-call target must be an existing workspace .py file"}
    if not isinstance(function, str) or not re.fullmatch(r"[A-Za-z]\w*", function):
        return {"passed": False, "invalid_assertion": True,
                "error": "function must be one public Python identifier, not source code"}
    if not isinstance(arguments, list) or len(arguments) > 16:
        return {"passed": False, "invalid_assertion": True,
                "error": "arguments must be a JSON array with at most 16 items"}
    try:
        request = json.dumps(arguments, allow_nan=False)
        expected_json = json.dumps(expected, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        return {"passed": False, "invalid_assertion": True,
                "error": f"Python-call inputs must be JSON values: {exc}"}
    if len(request) + len(expected_json) > 4096:
        return {"passed": False, "invalid_assertion": True,
                "error": "Python-call arguments and expected value exceed 4096 characters"}
    try:
        source_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(target), function],
            input=request, cwd=root, capture_output=True, text=True, encoding="utf-8",
            timeout=10, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired:
        return {"passed": False, "error": "Python-call assertion exceeded its 10-second limit"}
    except OSError as exc:
        return {"passed": False, "error": f"Could not launch Python-call assertion: {exc}"}
    if completed.returncode != 0:
        return {
            "passed": False, "error": "Python-call assertion raised an exception",
            "path": target.relative_to(root).as_posix(), "function": function,
            "arguments": arguments, "expected": expected,
            "exit_code": completed.returncode, "stderr": completed.stderr[-2000:],
        }
    if not completed.stdout.startswith(_RESULT_PREFIX):
        return {"passed": False, "error": "Python-call assertion returned no structured result"}
    try:
        observed = json.loads(completed.stdout[len(_RESULT_PREFIX):])
        actual_json = json.dumps(observed["actual"], allow_nan=False, sort_keys=True)
    except (ValueError, KeyError, TypeError) as exc:
        return {"passed": False, "error": f"Invalid Python-call assertion result: {exc}"}
    try:
        unchanged = hashlib.sha256(target.read_bytes()).hexdigest() == source_hash
    except OSError as exc:
        return {"passed": False, "error": f"Python-call source became unreadable: {exc}"}
    return {
        "passed": actual_json == expected_json and unchanged,
        "path": target.relative_to(root).as_posix(), "function": function,
        "arguments": arguments, "expected": expected, "actual": observed["actual"],
        "stdout": observed["stdout"], "source_sha256": source_hash,
        "source_unchanged": unchanged,
    }


def _probe():
    path = Path(sys.argv[1])
    arguments = json.load(sys.stdin)
    spec = importlib.util.spec_from_file_location("_hivo_asserted_module", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Python assertion target: {path}")
    module = importlib.util.module_from_spec(spec)
    stdout = io.StringIO()
    sys.path.insert(0, str(path.parent))
    with contextlib.redirect_stdout(stdout):
        spec.loader.exec_module(module)
        actual = getattr(module, sys.argv[2])(*arguments)
    print(_RESULT_PREFIX + json.dumps(
        {"actual": actual, "stdout": stdout.getvalue()}, allow_nan=False,
    ))


if __name__ == "__main__":
    _probe()
