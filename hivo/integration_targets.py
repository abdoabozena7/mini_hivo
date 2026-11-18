"""Experiment 9: resolve parent execution locations without reusing child proof."""

import copy
from pathlib import Path
import re

from hivo.integration_gate import canonical_hash, validate_verified_child_receipt


_PATH = re.compile(r"[\w./\\-]+\.(?:html?|mjs|cjs|js|py)\b", re.IGNORECASE)
_COMMAND = re.compile(r"^(?:npm(?:\.cmd)?|node|python(?:3)?|pytest|npx)\s+", re.IGNORECASE)


def _descriptor(workspace, value, *, explicit=False):
    text = str(value or "").strip()
    if not text:
        return None
    if explicit and _COMMAND.match(text):
        return {"target": text, "tool": "run_command", "command": text}
    root = Path(workspace).resolve()
    try:
        path = (root / text).resolve()
        relative = path.relative_to(root).as_posix()
        if any(part in {".agent_backups", ".agent_evidence", ".agent_runs", ".hivo"}
               for part in Path(relative).parts):
            return None
        if not path.is_file():
            return None
    except (OSError, ValueError):
        return None
    suffix = path.suffix.casefold()
    if suffix in {".html", ".htm"}:
        return {"target": relative, "tool": "verify_web_app"}
    if explicit and suffix in {".py", ".js", ".mjs", ".cjs"} and (
        "test" in path.name.casefold() or "tests" in Path(relative).parts
    ):
        executable = "python" if suffix == ".py" else "node"
        return {"target": relative, "tool": "run_command", "command": f'{executable} "{relative}"'}
    return None


def _values(value):
    if isinstance(value, dict):
        if value.get("command"):
            return [str(value["command"])]
        return [str(value[key]) for key in ("target", "path", "entrypoint", "command") if value.get(key)]
    if isinstance(value, (list, tuple)):
        return [item for entry in value for item in _values(entry)]
    text = str(value or "")
    if _COMMAND.match(text):
        return [text]
    return [text] + _PATH.findall(text)


def _choose(workspace, candidates):
    valid = {}
    for value, source, rank, explicit in candidates:
        descriptor = _descriptor(workspace, value, explicit=explicit)
        if descriptor is None:
            continue
        key = (descriptor["tool"], descriptor["target"])
        candidate = {**descriptor, "source": source, "rank": rank}
        if key not in valid or rank > valid[key]["rank"]:
            valid[key] = candidate
    if not valid:
        return None, []
    best_rank = max(item["rank"] for item in valid.values())
    best = sorted((item for item in valid.values() if item["rank"] == best_rank), key=lambda item: item["target"])
    return (best[0] if len(best) == 1 else None), best


def resolve_integration_targets(parent, contract, readiness, receipts, *, workspace, repository_snapshot=None):
    """Resolve every required route after READY. Receipts supply locations only."""
    snapshot = repository_snapshot if isinstance(repository_snapshot, dict) else {}
    result = {"artifact_type": "IntegrationTargetResolution", "parent_id": parent.get("id"),
              "input_readiness_hash": readiness.get("readiness_hash"), "status": "UNRESOLVED",
              "routes": copy.deepcopy(readiness.get("integration_routes", [])),
              "executions": [], "resolutions": [], "model_calls": 0,
              "child_evidence_reused_as_proof": 0}
    if readiness.get("readiness") != "READY":
        result["reason"] = "PARENT_NOT_READY"
        result["resolution_hash"] = canonical_hash(result)
        return result
    explicit = [(value, "explicit_parent_target", 100, True)
                for source in (parent, contract) for value in _values(source.get("integration_test_target")) if value]
    surfaces = [(value, "parent_integration_surface", 100, True)
                for source in (parent, contract)
                for key in ("integration_surfaces", "integration_verification", "integration_responsibility", "test_contract")
                for value in _values(source.get(key)) if value]
    child_candidates = []
    for reference in readiness.get("child_receipts", []):
        receipt = (receipts or {}).get(str(reference.get("child_id")), {})
        if (receipt.get("receipt_hash") != reference.get("receipt_hash")
                or not validate_verified_child_receipt(receipt, workspace=workspace)["verified"]):
            result["reason"] = "STALE_OR_INVALID_CHILD_RECEIPT"
            result["resolution_hash"] = canonical_hash(result)
            return result
        browser_target = (receipt.get("browser") or {}).get("resolved_target")
        if browser_target:
            child_candidates.append((browser_target, "verified_child_browser_target", 100, False))
        child_candidates.extend((value, "verified_child_mutation_path", 60, False)
                                for value in receipt.get("mutation_paths", []))
        child_candidates.extend((item.get("path"), "verified_child_dependency_path", 40, False)
                                for item in (receipt.get("evidence_dependency_fingerprint") or {}).get("paths", [])
                                if isinstance(item, dict))
    entrypoints = [(value, "project_entrypoint", 100 if str(value) == "index.html" else 80, False)
                  for value in snapshot.get("entrypoints", [])]
    failures = []
    for index, route in enumerate(result["routes"]):
        if not route.get("required") or route.get("applicable") is False:
            continue
        chosen, candidates = None, []
        if route.get("target"):
            chosen, candidates = _choose(workspace, [(route["target"], "explicit_parent_route", 100, True)])
        else:
            for group in (explicit, surfaces, child_candidates, entrypoints):
                chosen, candidates = _choose(workspace, group)
                if chosen or candidates or group is explicit and explicit:
                    break
        resolution = {"route_index": index, "kind": route.get("kind"), "resolved": chosen is not None,
                      "candidates": candidates}
        if chosen:
            route.update({"target": chosen["target"], "result": "PENDING",
                          "resolution_source": chosen["source"], "resolution_status": "RESOLVED"})
            resolution.update({"target": chosen["target"], "source": chosen["source"], "tool": chosen["tool"]})
            if not any(item["target"] == chosen["target"] and item["tool"] == chosen["tool"] for item in result["executions"]):
                result["executions"].append({key: value for key, value in chosen.items() if key != "rank"})
        else:
            failures.append(index)
        result["resolutions"].append(resolution)
    result["status"] = "RESOLVED" if not failures and result["executions"] else "UNRESOLVED"
    result["reason"] = None if result["status"] == "RESOLVED" else "REQUIRED_INTEGRATION_TARGET_UNRESOLVED"
    result["resolution_hash"] = canonical_hash(result)
    return result


def resolved_readiness(readiness, resolution):
    updated = copy.deepcopy(readiness)
    updated["integration_routes"] = copy.deepcopy(resolution["routes"])
    updated["integration_routes_hash"] = canonical_hash({
        "parent_id": updated.get("parent_id"), "parent_contract_hash": updated.get("parent_contract_hash"),
        "routes": updated["integration_routes"], "resolution_hash": resolution["resolution_hash"],
    })
    updated["integration_target_resolution_hash"] = resolution["resolution_hash"]
    updated["readiness_hash"] = canonical_hash({key: value for key, value in updated.items() if key != "readiness_hash"})
    return updated
