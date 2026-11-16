#!/usr/bin/env python3
"""Prove It: local execution receipts and a fail-closed evidence gate.

Python 3.10+, standard library only. This is an integrity/coverage gate, not a
proof of arbitrary program correctness, a sandbox, or a hostile-agent boundary.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

import planning

VERSION = "1.0.0"
SKILL = Path(__file__).resolve().parents[1]
STATE = ".runtime-proof"
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"}
KINDS = {"web", "simulation", "cli", "api", "library", "generic"}
MODES = {"live", "offline", "replay", "fixture"}
ROLES = {"acceptance", "regression", "negative_control"}
ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$")
MAX_LOG_BYTES = 32 * 1024 * 1024


class ProofError(Exception):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"),
                          parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (OSError, ValueError) as exc:
        raise ProofError(f"Cannot read valid JSON: {path}: {exc}") from exc


def save(path: Path, value, *, exclusive: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if exclusive:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    else:
        temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)


def relative_file(root: Path, name: str, *, must_exist: bool = True) -> Path:
    """Reject absolute paths, traversal, and symlinks (including parent links)."""
    p = Path(name)
    if not name or p.is_absolute() or ".." in p.parts or "\\" in name:
        raise ProofError(f"Expected a relative POSIX path without traversal: {name!r}")
    result = root / p
    cursor = result
    while cursor != root:
        if cursor.is_symlink():
            raise ProofError(f"Symlink is not accepted as scoped evidence/source: {cursor}")
        cursor = cursor.parent
    if not result.resolve().is_relative_to(root.resolve()):
        raise ProofError(f"Path escapes root: {name}")
    if must_exist and not result.exists():
        raise ProofError(f"Missing path: {result}")
    return result


def meaningful(text, label: str, minimum: int = 8):
    if not isinstance(text, str) or len(text.strip()) < minimum:
        raise ProofError(f"{label} must be a concrete nonempty description")
    if re.search(r"\bREPLACE_ME\b|\[TODO[:\]]", text, re.I) or text.strip().upper() in {"TODO", "TBD"}:
        raise ProofError(f"{label} still contains a placeholder")


def identifier(value, label="id"):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ProofError(f"Invalid {label}: {value!r}")


def engine_hash() -> str:
    return digest({p.name: file_hash(p) for p in sorted((SKILL / "scripts").glob("*.py"))})


def snapshot(project: Path, contract: dict) -> dict:
    """Hash explicit source roots, including untracked files. Never scan weights by default."""
    files = {}
    for name in contract["source_paths"]:
        root = relative_file(project, name)
        if name == "." or STATE in Path(name).parts:
            raise ProofError("Choose explicit source paths; do not include '.' or evidence output")
        items = [root] if root.is_file() else root.rglob("*")
        for path in items:
            rel = path.relative_to(project)
            if any(part in SKIP_DIRS for part in rel.parts):
                continue
            if path.is_symlink():
                raise ProofError(f"Source symlink needs explicit real-file scope: {rel}")
            if path.is_file():
                files[rel.as_posix()] = file_hash(path)
    if not files:
        raise ProofError("Source scope contains no files")
    return {"digest": digest(files), "files": files}


def validate_contract(c: dict):
    if not isinstance(c, dict) or c.get("schema") != 1:
        raise ProofError("Contract schema must be 1")
    identifier(c.get("task_id"), "task_id")
    meaningful(c.get("goal"), "goal")
    if c.get("kind") not in KINDS:
        raise ProofError(f"kind must be one of {sorted(KINDS)}")
    if not isinstance(c.get("source_paths"), list) or not c["source_paths"]:
        raise ProofError("source_paths must list the implementation, config and verification sources")
    meaningful(c.get("scope_rationale"), "scope_rationale")
    meaningful(c.get("authorization"), "authorization")
    checks = c.get("checks")
    reqs = c.get("requirements")
    if not isinstance(checks, list) or not checks or not isinstance(reqs, list) or not reqs:
        raise ProofError("At least one check and one requirement are mandatory")
    check_map = {}
    for check in checks:
        cid = check.get("id")
        identifier(cid, "check id")
        if cid in check_map:
            raise ProofError(f"Duplicate check: {cid}")
        check_map[cid] = check
        meaningful(check.get("description"), f"{cid}.description")
        if check.get("mode") not in MODES or check.get("role") not in ROLES:
            raise ProofError(f"{cid}: invalid mode or role")
        cmd = check.get("command")
        if not isinstance(cmd, list) or not cmd or any(not isinstance(v, str) or not v for v in cmd):
            raise ProofError(f"{cid}: command must be an argv array, not a shell string")
        timeout = check.get("timeout_seconds")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 604800:
            raise ProofError(f"{cid}: explicitly choose a finite per-command timeout")
        codes = check.get("expected_exit_codes", [0])
        if not isinstance(codes, list) or not codes or any(type(x) is not int for x in codes):
            raise ProofError(f"{cid}: invalid expected_exit_codes")
        if check["role"] != "negative_control" and codes != [0]:
            raise ProofError(f"{cid}: acceptance/regression cannot accept failing exit codes")
        if check["role"] == "negative_control":
            meaningful(check.get("fault"), f"{cid}.fault")
        assertions = check.get("assertions")
        if not isinstance(assertions, list) or not assertions:
            raise ProofError(f"{cid}: exit code alone is insufficient; provide outcome assertions")
        for assertion in assertions:
            if assertion.get("type") not in {"stdout_contains", "stderr_contains", "json"}:
                raise ProofError(f"{cid}: unsupported assertion type")
            if assertion["type"] == "json":
                if assertion.get("op") not in {"eq", "ne", "gt", "ge", "lt", "le", "contains"}:
                    raise ProofError(f"{cid}: unsupported JSON comparator")
                if not isinstance(assertion.get("pointer"), str) or not assertion["pointer"].startswith("/"):
                    raise ProofError(f"{cid}: JSON pointer must select a field")
            elif not isinstance(assertion.get("value"), str) or not assertion["value"]:
                raise ProofError(f"{cid}: output assertion must look for a nonempty literal")
        arts = check.get("artifacts", [])
        if not isinstance(arts, list):
            raise ProofError(f"{cid}: artifacts must be a list")
        for art in arts:
            pattern = art.get("glob", "")
            if not isinstance(pattern, str) or not pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts or "\\" in pattern:
                raise ProofError(f"{cid}: artifact glob must stay within the fresh run directory")
            if type(art.get("min_count", 1)) is not int or art.get("min_count", 1) < 1:
                raise ProofError(f"{cid}: artifact min_count must be positive")
            if type(art.get("min_bytes", 1)) is not int or art.get("min_bytes", 1) < 1:
                raise ProofError(f"{cid}: artifact min_bytes must be positive")
    seen = set()
    for req in reqs:
        rid = req.get("id")
        identifier(rid, "requirement id")
        if rid in seen:
            raise ProofError(f"Duplicate requirement: {rid}")
        seen.add(rid)
        for field in ("claim", "oracle", "failure_example"):
            meaningful(req.get(field), f"{rid}.{field}")
        if type(req.get("runtime_required")) is not bool:
            raise ProofError(f"{rid}: runtime_required must be explicit")
        links = req.get("checks", [])
        if not links or any(x not in check_map for x in links):
            raise ProofError(f"{rid}: missing or unknown checks")
        if not any(check_map[x]["role"] == "acceptance" for x in links):
            raise ProofError(f"{rid}: at least one acceptance check is required")
        if req["runtime_required"] and not any(check_map[x]["mode"] == "live" and check_map[x]["role"] == "acceptance" for x in links):
            raise ProofError(f"{rid}: offline/replay/mock checks cannot satisfy live acceptance")
        negatives = req.get("negative_checks", [])
        if negatives:
            if any(x not in check_map or check_map[x]["role"] != "negative_control" for x in negatives):
                raise ProofError(f"{rid}: invalid negative control link")
        else:
            meaningful(req.get("negative_control_exception"), f"{rid}.negative_control_exception", 30)
        if type(req.get("review_required")) is not bool:
            raise ProofError(f"{rid}: review_required must be explicit")
        if c["kind"] in {"web", "simulation"} and not req["review_required"]:
            raise ProofError(f"{rid}: web/simulation requirements need evidence inspection")
        if c["kind"] in {"web", "simulation"} and not any(check_map[x].get("artifacts") for x in links):
            raise ProofError(f"{rid}: visual/native evidence artifacts are required")

    try:
        planning.validate(c.get("plan"), seen, set(check_map))
    except (ValueError, TypeError, KeyError) as exc:
        raise ProofError("Plan invalid: " + str(exc)) from exc


def task_context(task: Path, sealed=True):
    task = task.resolve()
    c = load(task / "contract.json")
    project = Path(load(task / "context.json")["project"]).resolve()
    validate_contract(c)
    if not task.is_relative_to(project / STATE):
        raise ProofError("Task must live within its declared project's .runtime-proof directory")
    if sealed:
        s = load(task / "seal.json")
        if s["contract_hash"] != digest(c):
            raise ProofError("Sealed contract changed. Preserve it; start a new documented contract revision")
        if s["engine_hash"] != engine_hash():
            raise ProofError("Harness scripts changed since sealing; do not reuse the old gate")
    return task, project, c


def get_check(c, cid):
    for check in c["checks"]:
        if check["id"] == cid:
            return check
    raise ProofError(f"Unknown check: {cid}")


def expand(value: str, project: Path, run: Path, task: Path):
    replacements = {"{python}": sys.executable, "{skill}": str(SKILL),
                    "{project}": str(project), "{run}": str(run), "{task}": str(task)}
    for a, b in replacements.items():
        value = value.replace(a, b)
    return value


def json_pointer(value, pointer):
    for key in pointer.split("/")[1:]:
        key = key.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def evaluate_assertions(run: Path, check: dict) -> list[str]:
    errors = []
    for i, assertion in enumerate(check["assertions"]):
        try:
            typ = assertion["type"]
            if typ in {"stdout_contains", "stderr_contains"}:
                name = "stdout.log" if typ.startswith("stdout") else "stderr.log"
                ok = assertion["value"] in relative_file(run, name).read_text(encoding="utf-8", errors="replace")
            else:
                actual = json_pointer(load(relative_file(run, assertion["file"])), assertion["pointer"])
                expected, op = assertion["value"], assertion["op"]
                if op in {"gt", "ge", "lt", "le"}:
                    if type(actual) not in {int, float} or type(expected) not in {int, float}:
                        raise ProofError("Numeric assertion received a nonnumeric value")
                    if not math.isfinite(actual) or not math.isfinite(expected):
                        raise ProofError("Nonfinite measurements are not accepted")
                if op == "eq": ok = type(actual) is type(expected) and actual == expected
                elif op == "ne": ok = actual != expected
                elif op == "gt": ok = actual > expected
                elif op == "ge": ok = actual >= expected
                elif op == "lt": ok = actual < expected
                elif op == "le": ok = actual <= expected
                else: ok = expected in actual
            if not ok:
                errors.append(f"assertion {i + 1} failed: {assertion}")
        except (ProofError, KeyError, IndexError, TypeError, ValueError, OSError) as exc:
            errors.append(f"assertion {i + 1} unreadable: {exc}")
    return errors


def collect_artifacts(run: Path, check: dict) -> tuple[dict, list[str]]:
    result, errors = {}, []
    for art in check.get("artifacts", []):
        matches = [p for p in run.glob(art["glob"]) if p.is_file()]
        if len(matches) < art.get("min_count", 1):
            errors.append(f"Missing artifact(s): {art['glob']}")
        for p in matches:
            rel = p.relative_to(run).as_posix()
            p = relative_file(run, rel)
            if p.stat().st_size < art.get("min_bytes", 1):
                errors.append(f"Empty/undersized artifact: {rel}")
            result[rel] = {"sha256": file_hash(p), "bytes": p.stat().st_size}
    # JSON assertion inputs and captured outputs are also integrity-bound.
    extras = ["stdout.log", "stderr.log"] + [a["file"] for a in check["assertions"] if a["type"] == "json"]
    for rel in extras:
        try:
            p = relative_file(run, rel)
            result[rel] = {"sha256": file_hash(p), "bytes": p.stat().st_size}
        except ProofError as exc:
            errors.append(str(exc))
    return result, errors


def stop_owned_process(proc: subprocess.Popen):
    """Only target the child process tree/group created by this invocation."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            # Kill remaining group members as well, even if the leader exited.
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        except ProcessLookupError:
            pass
    try: proc.wait(timeout=10)
    except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=10)


def run_check(task: Path, cid: str) -> dict:
    task, project, c = task_context(task)
    if (task / "blocked.json").exists():
        raise ProofError("Task is BLOCKED_UNVERIFIED; resolve the blocker and run resume first")
    check = get_check(c, cid)
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:10]
    run = task / "runs" / cid / run_id
    run.mkdir(parents=True, exist_ok=False)
    source = snapshot(project, c)
    argv = [expand(x, project, run, task) for x in check["command"]]
    cwd = relative_file(project, check.get("cwd", "."))
    if not cwd.is_dir(): raise ProofError("Command cwd is not a directory")
    env = os.environ.copy()
    env.update({"PROVE_IT_RUN_ID": run_id, "PROVE_IT_OUTPUT_DIR": str(run),
                "PROVE_IT_PROJECT_ROOT": str(project), "PYTHONDONTWRITEBYTECODE": "1"})
    stdin_bytes = None
    if check.get("stdin_file"):
        stdin_bytes = relative_file(project, check["stdin_file"]).read_bytes()
    receipt = {"schema": 1, "harness": VERSION, "task_id": c["task_id"],
               "run_id": run_id, "check_id": cid, "role": check["role"], "mode": check["mode"],
               "contract_hash": digest(c), "check_hash": digest(check), "engine_hash": engine_hash(),
               "command": argv, "cwd": str(cwd), "started_at": now(),
               "source_before": source, "timeout": False, "interrupted": False,
               "overflow": False, "spawn_error": None, "exit_code": None, "pid": None}
    # A start marker ensures an interrupted collector cannot be mistaken for a missing attempt.
    save(run / "started.json", receipt, exclusive=True)
    # A newer unfinished attempt invalidates the previous latest success.
    save(task / "latest" / (cid + ".json"), {"run": run.relative_to(task).as_posix(), "receipt_hash": None})
    started = time.monotonic()
    overflow = threading.Event()
    threads = []
    proc = None
    print(f"RUN {cid}: {run}", flush=True)
    def drain(pipe, path):
        total = 0
        try:
            with path.open("wb") as output:
                while True:
                    chunk = pipe.read(65536)
                    if not chunk: break
                    room = MAX_LOG_BYTES - total
                    if room > 0:
                        output.write(chunk[:room])
                        total += min(room, len(chunk))
                    if len(chunk) > room:
                        overflow.set()
        finally:
            pipe.close()
    try:
        kwargs = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        proc = subprocess.Popen(argv, cwd=cwd, env=env, shell=False,
                                stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        receipt["pid"] = proc.pid
        for pipe, filename in [(proc.stdout, "stdout.log"), (proc.stderr, "stderr.log")]:
            thread = threading.Thread(target=drain, args=(pipe, run / filename), daemon=True)
            thread.start(); threads.append(thread)
        if stdin_bytes is not None:
            def feed():
                try: proc.stdin.write(stdin_bytes); proc.stdin.close()
                except (BrokenPipeError, OSError): pass
            thread = threading.Thread(target=feed, daemon=True)
            thread.start(); threads.append(thread)
        heartbeat = started
        while proc.poll() is None:
            elapsed = time.monotonic() - started
            if elapsed > check["timeout_seconds"] or overflow.is_set():
                receipt["timeout"] = elapsed > check["timeout_seconds"]
                receipt["overflow"] = overflow.is_set()
                stop_owned_process(proc)
                break
            if time.monotonic() - heartbeat >= 15:
                print(f"RUNNING {cid}: {int(elapsed)}s; logs in {run}", flush=True)
                heartbeat = time.monotonic()
            time.sleep(0.05)
        receipt["exit_code"] = proc.returncode
    except KeyboardInterrupt:
        receipt["interrupted"] = True
        if proc is not None: stop_owned_process(proc); receipt["exit_code"] = proc.returncode
    except OSError as exc:
        receipt["spawn_error"] = str(exc)
    finally:
        for thread in threads: thread.join(timeout=3)
        if any(thread.is_alive() for thread in threads):
            if proc is not None: stop_owned_process(proc)
            for thread in threads: thread.join(timeout=3)
            receipt["spawn_error"] = "A child retained an output pipe; command did not clean up its process tree"
        for name in ("stdout.log", "stderr.log"):
            (run / name).touch(exist_ok=True)
    receipt["ended_at"] = now()
    receipt["wall_seconds"] = round(time.monotonic() - started, 6)
    receipt["overflow"] = receipt["overflow"] or overflow.is_set()
    errors = []
    try:
        receipt["source_after"] = snapshot(project, c)
        if receipt["source_after"]["digest"] != source["digest"]:
            errors.append("Source changed during this execution")
        receipt["artifacts"], art_errors = collect_artifacts(run, check)
        errors.extend(art_errors)
    except ProofError as exc:
        receipt["source_after"] = None
        receipt["artifacts"] = {}
        errors.append(str(exc))
    errors.extend(evaluate_assertions(run, check))
    if receipt["exit_code"] not in check.get("expected_exit_codes", [0]):
        errors.append(f"Unexpected exit code: {receipt['exit_code']}")
    for flag in ("timeout", "interrupted", "overflow", "spawn_error"):
        if receipt[flag]: errors.append(f"Execution problem: {flag}: {receipt[flag]}")
    receipt["errors"] = errors
    receipt["passed"] = not errors
    save(run / "receipt.json", receipt, exclusive=True)
    save(task / "latest" / (cid + ".json"), {"run": run.relative_to(task).as_posix(),
                                               "receipt_hash": file_hash(run / "receipt.json")})
    print(json.dumps({"check": cid, "passed": not errors, "errors": errors, "run": str(run)}, indent=2))
    return receipt


def verify(task: Path, *, include_plan: bool = True) -> dict:
    errors, checks, reviews = [], {}, {}
    try:
        task, project, c = task_context(task)
        current = snapshot(project, c)
        if (task / "blocked.json").exists():
            errors.append("Task is BLOCKED_UNVERIFIED: " + load(task / "blocked.json")["reason"])
        for check in c["checks"]:
            cid = check["id"]
            ce = []
            try:
                latest = load(task / "latest" / (cid + ".json"))
                run = relative_file(task, latest["run"])
                if not run.is_relative_to(task / "runs" / cid):
                    raise ProofError("Receipt was linked from another check")
                rpath = run / "receipt.json"
                if file_hash(rpath) != latest["receipt_hash"]:
                    raise ProofError("Receipt changed since collection")
                r = load(rpath)
                if (r["task_id"] != c["task_id"] or r["check_id"] != cid or
                    r["contract_hash"] != digest(c) or r["check_hash"] != digest(check) or
                    r["engine_hash"] != engine_hash()):
                    raise ProofError("Receipt does not match the sealed task/check/harness")
                if r["source_before"]["digest"] != current["digest"] or not r["source_after"] or r["source_after"]["digest"] != current["digest"]:
                    ce.append("Evidence is stale or the source changed during execution")
                if r["exit_code"] not in check.get("expected_exit_codes", [0]):
                    ce.append(f"Unexpected exit code: {r['exit_code']}")
                if not r["passed"]: ce.extend(r["errors"] or ["Run failed"])
                for flag in ("timeout", "interrupted", "overflow", "spawn_error"):
                    if r.get(flag): ce.append(f"Invalid execution: {flag}")
                actual, art_errors = collect_artifacts(run, check)
                ce.extend(art_errors)
                if actual != r["artifacts"]: ce.append("Evidence files changed or disappeared after collection")
                ce.extend(evaluate_assertions(run, check))
                checks[cid] = {"passed": not ce, "run": latest["run"],
                               "receipt_hash": latest["receipt_hash"], "artifacts": actual, "errors": ce}
            except (ProofError, KeyError, TypeError, ValueError, OSError) as exc:
                ce.append(str(exc)); checks[cid] = {"passed": False, "errors": ce}
            errors.extend(f"{cid}: {x}" for x in ce)
        if (task / "review.json").exists():
            review = load(task / "review.json")
            if review.get("contract_hash") == digest(c) and review.get("source_digest") == current["digest"]:
                reviews = {r["requirement_id"]: r for r in review.get("requirements", [])}
        req_results = []
        for req in c["requirements"]:
            re_errors = []
            links = req["checks"] + req.get("negative_checks", [])
            if not all(checks[x]["passed"] for x in links): re_errors.append("Linked checks incomplete or failing")
            if req["review_required"]:
                rr = reviews.get(req["id"])
                if not rr or rr.get("verdict") != "pass":
                    re_errors.append("Missing, stale or nonpassing evidence inspection")
                else:
                    try:
                        meaningful(rr.get("observations"), "review observations", 30)
                        refs = rr.get("evidence", [])
                        if not refs: raise ProofError("Inspection must cite actual evidence files")
                        for ref in refs:
                            cid = ref["check_id"]
                            if cid not in req["checks"]: raise ProofError("Review cites an unrelated check")
                            cr = checks[cid]
                            if rr.get("receipt_hashes", {}).get(cid) != cr.get("receipt_hash"):
                                raise ProofError("Review refers to an earlier run")
                            if ref["file"] not in cr.get("artifacts", {}):
                                raise ProofError("Review cites a nonexistent/uncollected artifact")
                    except (ProofError, KeyError, TypeError) as exc: re_errors.append(str(exc))
            req_results.append({"id": req["id"], "claim": req["claim"], "passed": not re_errors, "errors": re_errors})
            errors.extend(f"{req['id']}: {x}" for x in re_errors)
        plan_results = []
        if include_plan:
            progress = load(task / "progress.json") if (task / "progress.json").exists() else {}
            for step in c["plan"]["tasks"]:
                entry = progress.get(step["id"], {})
                pe = []
                if entry.get("status") != "VERIFIED": pe.append("To-do item is not VERIFIED")
                if entry.get("source_digest") != current["digest"]: pe.append("Step verification is missing or stale")
                for cid in step["checks"]:
                    if not checks[cid]["passed"]: pe.append("Step check incomplete: " + cid)
                    if entry.get("receipt_hashes", {}).get(cid) != checks[cid].get("receipt_hash"):
                        pe.append("Step refers to an earlier or missing receipt: " + cid)
                if step["execution"] == "subagent":
                    if not entry.get("agent_ref"): pe.append("No actual subagent identity/invocation recorded")
                    try:
                        handoff = relative_file(task, entry.get("handoff", ""))
                        if file_hash(handoff) != entry.get("handoff_hash"): pe.append("Delegation handoff changed")
                    except (ProofError, OSError) as exc: pe.append(str(exc))
                plan_results.append({"id": step["id"], "status": entry.get("status", "TODO"), "passed": not pe, "errors": pe})
                errors.extend(step["id"] + ": " + e for e in pe)
        return {"schema": 1, "task_id": c["task_id"], "at": now(),
                "status": "EVIDENCE_GATE_PASSED" if not errors else "UNVERIFIED",
                "passed": not errors, "source_digest": current["digest"],
                "checks": checks, "requirements": req_results, "plan": plan_results, "errors": errors,
                "boundary": "Validates recorded execution, source freshness, coverage and artifact integrity; does not prove oracle quality, visual judgment or honesty of a same-user process."}
    except (ProofError, KeyError, TypeError, ValueError, OSError) as exc:
        return {"schema": 1, "at": now(), "status": "UNVERIFIED", "passed": False, "errors": [str(exc)]}


def render_todo(task: Path, c: dict, progress: dict, current_digest: str):
    rows = ["# Runtime-first task plan", "", "Strategy: " + c["plan"]["strategy"],
            "", c["plan"]["rationale"], "", "Implemented is not verified. Source changes invalidate verification.",
            "", "| ID | State | Owner | Depends on | Outcome |", "| --- | --- | --- | --- | --- |"]
    for step in c["plan"]["tasks"]:
        entry = progress.get(step["id"], {})
        state = entry.get("status", "TODO")
        if state == "VERIFIED" and entry.get("source_digest") != current_digest: state = "STALE"
        values = [step["id"], state, step["owner"], ", ".join(step["depends_on"]) or "none", step["outcome"]]
        rows.append("| " + " | ".join(x.replace("|", r"\|").replace("\n", " ") for x in values) + " |")
    (task / "TODO.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def update_step(task: Path, tid: str, status: str, note: str, agent_ref=None, handoff=None):
    task, project, c = task_context(task)
    meaningful(note, "step progress note", 15)
    steps = {x["id"]: x for x in c["plan"]["tasks"]}
    if tid not in steps: raise ProofError("Unknown plan task: " + tid)
    step = steps[tid]
    path = task / "progress.json"
    progress = load(path) if path.exists() else {}
    old = progress.get(tid, {})
    if status in {"IN_PROGRESS", "IMPLEMENTED", "VERIFIED"}:
        for dep in step["depends_on"]:
            if progress.get(dep, {}).get("status") not in {"IMPLEMENTED", "VERIFIED"}:
                raise ProofError("Dependency has no deliverable yet: " + dep)
    entry = {"status": status, "note": note, "at": now(),
             "agent_ref": agent_ref or old.get("agent_ref"), "handoff": handoff or old.get("handoff")}
    if step["execution"] == "subagent" and status in {"IN_PROGRESS", "IMPLEMENTED", "VERIFIED"}:
        meaningful(entry["agent_ref"], "actual subagent invocation/session id", 3)
        if status != "IN_PROGRESS":
            evidence = relative_file(task, entry["handoff"] or "")
            if not evidence.is_file() or not evidence.stat().st_size: raise ProofError("Subagent handoff is missing")
            entry["handoff_hash"] = file_hash(evidence)
    if status == "VERIFIED":
        result = verify(task, include_plan=False)
        for cid in step["checks"]:
            cr = result.get("checks", {}).get(cid, {})
            if not cr.get("passed"): raise ProofError("Cannot verify a task without a current passing execution receipt: " + cid)
        entry["source_digest"] = result["source_digest"]
        entry["receipt_hashes"] = {cid: result["checks"][cid]["receipt_hash"] for cid in step["checks"]}
    if old: save(task / "history" / ("step-" + tid + "-" + uuid.uuid4().hex + ".json"), old, exclusive=True)
    progress[tid] = entry
    save(path, progress)
    render_todo(task, c, progress, snapshot(project, c)["digest"])
    return entry


def record_review(task: Path, input_file: Path):
    task, project, c = task_context(task)
    raw = load(input_file)
    meaningful(raw.get("reviewer"), "reviewer", 3)
    if raw.get("independence") not in {"same-agent", "fresh-context-agent", "human", "external-verifier"}:
        raise ProofError("Record the actual reviewer's independence, not an invented reviewer")
    entries = raw.get("requirements", [])
    if not entries: raise ProofError("Review is empty")
    known = {r["id"]: r for r in c["requirements"]}
    seen = set()
    for entry in entries:
        rid = entry.get("requirement_id")
        if rid not in known or rid in seen: raise ProofError("Unknown or duplicate reviewed requirement")
        seen.add(rid)
        if entry.get("verdict") not in {"pass", "fail", "not-reviewed"}: raise ProofError("Invalid review verdict")
        meaningful(entry.get("observations"), "observations", 30)
        entry["receipt_hashes"] = {}
        for ref in entry.get("evidence", []):
            cid = ref["check_id"]
            if cid not in known[rid]["checks"]: raise ProofError("Review points to an unrelated check")
            latest = load(task / "latest" / (cid + ".json"))
            run = relative_file(task, latest["run"])
            receipt = load(run / "receipt.json")
            if ref["file"] not in receipt["artifacts"]: raise ProofError("Review artifact was not collected")
            entry["receipt_hashes"][cid] = latest["receipt_hash"]
        if entry["verdict"] == "pass" and not entry.get("evidence"):
            raise ProofError("Passing review needs file-level evidence references")
    raw.update({"at": now(), "contract_hash": digest(c), "source_digest": snapshot(project, c)["digest"]})
    if (task / "review.json").exists():
        save(task / "history" / ("review-" + uuid.uuid4().hex + ".json"), load(task / "review.json"), exclusive=True)
    save(task / "review.json", raw)


def find_active(cwd: Path):
    for project in [cwd.resolve(), *cwd.resolve().parents]:
        p = project / STATE / "active.json"
        if p.exists():
            active = load(p)
            task = relative_file(project / STATE, active["task"])
            return task, active
    return None, None


def hook(payload: dict) -> dict:
    cwd = Path(payload.get("cwd") or os.getcwd())
    task, active = find_active(cwd)
    if task is None: return {}  # Deliberately inactive outside an opted-in task.
    sid = payload.get("sessionId") or payload.get("session_id")
    if active.get("session_id") and sid != active["session_id"]: return {}
    result = verify(task)
    save(task / "gate.json", result)
    if result["passed"]: return {}
    if (task / "blocked.json").exists(): return {}  # A truthful blocked handoff is not success.
    signature = digest({"errors": result["errors"], "checks": result.get("checks", {}),
                        "source_digest": result.get("source_digest"), "plan": result.get("plan", [])})
    previous = load(task / "hook-state.json") if (task / "hook-state.json").exists() else {}
    forced = bool(payload.get("stop_hook_active") or payload.get("stopHookActive"))
    if forced and previous.get("signature") == signature:
        save(task / "needs-attention.json", {"at": now(), "status": "PAUSED_UNVERIFIED",
             "reason": "Same failed gate after a forced continuation. Host stop is allowed to prevent an infinite loop; completion is NOT verified.",
             "errors": result["errors"]})
        return {}
    save(task / "hook-state.json", {"at": now(), "signature": signature})
    reason = ("PROVE-IT: completion evidence is incomplete. Do not claim done. "
              "Continue the next executable runtime validation/fix, inspect the actual artifacts, "
              "then run proof.py verify. Do not edit the contract, harness or receipts to pass. "
              "For a genuine external blocker, record BLOCKED_UNVERIFIED with the exact evidence and required action. "
              "Task: " + str(task) + ". Failures: " + "; ".join(result["errors"][:6]))
    return {"decision": "block", "reason": reason}


def doctor():
    return {"python": sys.version.split()[0], "platform": sys.platform,
            "tools": {x: shutil.which(x) for x in ("git", "node", "npm", "nvidia-smi", "ffmpeg", "ffprobe", "copilot", "codex", "claude")},
            "display_environment_present": bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or os.name == "nt"),
            "note": "Presence is not functional proof. No simulator/browser/network is started by doctor."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    p = sub.add_parser("init")
    p.add_argument("--project", default="."); p.add_argument("--id", required=True)
    p.add_argument("--goal", required=True); p.add_argument("--kind", choices=sorted(KINDS), required=True)
    p.add_argument("--session-id")
    for name in ("seal", "verify", "resume", "activate"):
        p = sub.add_parser(name); p.add_argument("--task", type=Path, required=True)
        if name == "verify": p.add_argument("--write-report", action="store_true")
        if name == "resume": p.add_argument("--reason", required=True)
        if name == "activate": p.add_argument("--session-id")
    p = sub.add_parser("step"); p.add_argument("--task", type=Path, required=True)
    p.add_argument("--id", required=True); p.add_argument("--status", choices=sorted(planning.STATES), required=True)
    p.add_argument("--note", required=True); p.add_argument("--agent-ref"); p.add_argument("--handoff")
    p = sub.add_parser("todo"); p.add_argument("--task", type=Path, required=True)
    p = sub.add_parser("run"); p.add_argument("--task", type=Path, required=True); p.add_argument("--check", required=True)
    p = sub.add_parser("review"); p.add_argument("--task", type=Path, required=True); p.add_argument("--input", type=Path, required=True)
    p = sub.add_parser("block"); p.add_argument("--task", type=Path, required=True)
    p.add_argument("--reason", required=True); p.add_argument("--action", required=True); p.add_argument("--evidence", required=True)
    p = sub.add_parser("hook"); p.add_argument("--host", choices=["copilot", "claude"], required=True)
    args = parser.parse_args()
    try:
        if args.command == "doctor": print(json.dumps(doctor(), indent=2)); return 0
        if args.command == "hook":
            try:
                payload = json.load(sys.stdin)
                if not isinstance(payload, dict): raise ProofError("Hook input is not an object")
                decision = hook(payload)
            except Exception as exc:
                decision = {"decision": "block", "reason": "PROVE-IT hook failed; no completion clearance. Repair hook configuration: " + str(exc)}
            print(json.dumps(decision)); return 0
        if args.command == "init":
            identifier(args.id, "task id")
            project = Path(args.project).resolve()
            if not project.is_dir(): raise ProofError("Project directory does not exist")
            active_path = project / STATE / "active.json"
            if active_path.exists():
                old = relative_file(project / STATE, load(active_path)["task"])
                if not verify(old)["passed"] and not (old / "blocked.json").exists():
                    raise ProofError("Another unfinished task is active in this checkout; resume it or explicitly record its blocked state")
            task = project / STATE / args.id
            task.mkdir(parents=True, exist_ok=False)
            template = load(SKILL / "assets" / "templates" / "contract.json")
            template.update({"task_id": args.id, "goal": args.goal, "kind": args.kind})
            save(task / "contract.json", template, exclusive=True)
            save(task / "context.json", {"project": str(project), "created_at": now()}, exclusive=True)
            save(active_path, {"task": args.id, "session_id": args.session_id})
            print(f"Created UNVERIFIED task: {task}\nCustomize contract.json, then seal. No acceptance is implied."); return 0
        if args.command == "activate":
            task, project, c = task_context(args.task, sealed=False)
            active_path = project / STATE / "active.json"
            if active_path.exists():
                old = relative_file(project / STATE, load(active_path)["task"])
                if old != task and not verify(old)["passed"] and not (old / "blocked.json").exists():
                    raise ProofError("Another unfinished task is active")
            save(active_path, {"task": task.name, "session_id": args.session_id}); return 0
        if args.command == "seal":
            task, project, c = task_context(args.task, sealed=False)
            s = {"at": now(), "contract_hash": digest(c), "engine_hash": engine_hash(),
                 "source_at_seal": snapshot(project, c)}
            save(task / "seal.json", s, exclusive=True)
            render_todo(task, c, {}, s["source_at_seal"]["digest"])
            print("Contract and task DAG sealed. Requirements/oracles are fixed; implementation may change."); return 0
        if args.command == "step":
            print(json.dumps(update_step(args.task, args.id, args.status, args.note, args.agent_ref, args.handoff), indent=2)); return 0
        if args.command == "todo":
            task, project, c = task_context(args.task)
            progress = load(task / "progress.json") if (task / "progress.json").exists() else {}
            render_todo(task, c, progress, snapshot(project, c)["digest"])
            print((task / "TODO.md").read_text(encoding="utf-8")); return 0
        if args.command == "run": return 0 if run_check(args.task, args.check)["passed"] else 1
        if args.command == "verify":
            result = verify(args.task)
            if args.write_report: save(args.task / "gate.json", result)
            print(json.dumps(result, indent=2)); return 0 if result["passed"] else 1
        if args.command == "review": record_review(args.task, args.input); print("Evidence inspection recorded; run verify next."); return 0
        task = args.task.resolve()
        if not (task / "context.json").exists(): raise ProofError("Not a task directory")
        if args.command == "block":
            meaningful(args.reason, "blocker reason", 20); meaningful(args.action, "required action", 10)
            evidence = relative_file(task, args.evidence)
            if not evidence.is_file() or evidence.stat().st_size == 0: raise ProofError("Blocker needs a nonempty raw evidence file")
            save(task / "blocked.json", {"at": now(), "status": "BLOCKED_UNVERIFIED", "reason": args.reason,
                 "required_action": args.action, "evidence": args.evidence, "sha256": file_hash(evidence)})
            print("BLOCKED_UNVERIFIED. Stopping is permitted; success is not."); return 0
        if args.command == "resume":
            meaningful(args.reason, "resume reason", 10)
            if (task / "blocked.json").exists():
                save(task / "history" / ("block-" + uuid.uuid4().hex + ".json"), load(task / "blocked.json"), exclusive=True)
                (task / "blocked.json").unlink()
            for filename in ("hook-state.json", "needs-attention.json"):
                (task / filename).unlink(missing_ok=True)
            save(task / "history" / ("resume-" + uuid.uuid4().hex + ".json"), {"at": now(), "reason": args.reason}, exclusive=True)
            print("Resumed without granting new OS, spending or simulator permissions."); return 0
    except (ProofError, OSError, KeyError, ValueError, TypeError) as exc:
        print(f"UNVERIFIED: {exc}", file=sys.stderr); return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
