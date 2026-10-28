"""Validate an explicit work DAG. This module never spawns or invents agents."""
from __future__ import annotations
import re

STATES = {"TODO", "IN_PROGRESS", "IMPLEMENTED", "VERIFIED", "BLOCKED"}
ROLES = {"investigate", "implement", "integrate", "review"}


def concrete(value, label, minimum=8):
    if not isinstance(value, str) or len(value.strip()) < minimum or re.search(r"\bREPLACE_ME\b|\[TODO[:\]]", value, re.I) or value.strip().upper() in {"TODO", "TBD"}:
        raise ValueError(f"{label} needs a concrete description")


def validate(plan, requirement_ids, check_ids):
    if not isinstance(plan, dict):
        raise ValueError("An explicit plan is mandatory before execution")
    if plan.get("strategy") not in {"serial", "parallel", "hybrid"}:
        raise ValueError("plan.strategy must be serial, parallel, or hybrid")
    concrete(plan.get("rationale"), "plan.rationale")
    capability = plan.get("delegation")
    if not isinstance(capability, dict) or type(capability.get("available")) is not bool:
        raise ValueError("Declare whether a real delegation tool is available")
    concrete(capability.get("evidence"), "plan.delegation.evidence")
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Plan must contain at least one task")
    index = {}
    for task in tasks:
        tid = task.get("id")
        if not isinstance(tid, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", tid):
            raise ValueError("Invalid plan task id")
        if tid in index: raise ValueError(f"Duplicate plan task {tid}")
        index[tid] = task
        for field in ("title", "outcome", "owner", "acceptance"):
            concrete(task.get(field), f"{tid}.{field}", 3 if field == "owner" else 8)
        if task.get("role") not in ROLES: raise ValueError(f"{tid}: invalid role")
        if task.get("execution") not in {"serial", "subagent"}: raise ValueError(f"{tid}: invalid execution")
        if task["execution"] == "subagent" and not capability["available"]:
            raise ValueError(f"{tid}: a subagent was planned without an available delegation tool")
        for field in ("depends_on", "write_scope", "outputs", "requirements", "checks"):
            if not isinstance(task.get(field), list): raise ValueError(f"{tid}.{field} must be a list")
            if any(not isinstance(x, str) or not x for x in task[field]): raise ValueError(f"{tid}.{field} has an invalid item")
        if not task["outputs"]: raise ValueError(f"{tid}: define concrete outputs")
        if not task["checks"] or any(x not in check_ids for x in task["checks"]):
            raise ValueError(f"{tid}: verification checks are missing or unknown")
        if not task["requirements"] or any(x not in requirement_ids for x in task["requirements"]):
            raise ValueError(f"{tid}: requirements are missing or unknown")
    for task in tasks:
        if len(task["depends_on"]) != len(set(task["depends_on"])):
            raise ValueError(f"{task['id']}: repeated dependency")
        if any(x not in index or x == task["id"] for x in task["depends_on"]):
            raise ValueError(f"{task['id']}: unknown or self dependency")
    visiting, visited, ancestor_cache = set(), set(), {}
    def visit(tid):
        if tid in visiting: raise ValueError("Plan dependency cycle detected")
        if tid in visited: return ancestor_cache[tid]
        visiting.add(tid)
        parents = set(index[tid]["depends_on"])
        for dep in index[tid]["depends_on"]: parents |= visit(dep)
        visiting.remove(tid); visited.add(tid); ancestor_cache[tid] = parents
        return parents
    for tid in index: visit(tid)
    covered = {rid for task in tasks for rid in task["requirements"]}
    if covered != set(requirement_ids): raise ValueError("Plan leaves a requirement uncovered")
    implementation = {t["id"] for t in tasks if t["role"] in {"implement", "investigate"}}
    integrations = [t for t in tasks if t["role"] == "integrate"]
    if not integrations or not any(implementation.issubset(ancestor_cache[t["id"]]) for t in integrations):
        raise ValueError("An integration task must depend transitively on every implementation/investigation task")
    if plan["strategy"] == "serial" and any(t["execution"] == "subagent" for t in tasks):
        raise ValueError("A serial-only plan cannot claim delegated execution; choose hybrid or serial steps")
    return index
