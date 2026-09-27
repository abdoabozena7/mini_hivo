"""Small, authority-free responsibility split for Experiment 1.

The split may assign existing requirement IDs to children. It cannot grant
repository access or mutation scope; Stage 3 and approval do that later.
"""

from __future__ import annotations

import copy
import re


class EarlySplitError(ValueError):
    pass


_PATH_OR_CODE = re.compile(
    r"(?:\b(?:src|test|tests|lib|app|hivo|components|pages)[/\\][\w./\\-]+"
    r"|\b[\w-]+\.(?:py|js|jsx|ts|tsx|html|css|json|md)\b|[{};`])",
    re.IGNORECASE,
)


def validate_split(candidate, requirements, max_children=4):
    """Require complete requirement coverage without accepting solution scope."""
    children = candidate.get("children") if isinstance(candidate, dict) else None
    if not isinstance(children, list) or not 2 <= len(children) <= max_children:
        raise EarlySplitError("early split must contain 2-4 responsibilities")
    known = {str(item["requirement_id"]) for item in requirements}
    covered = set()
    result = []
    for index, child in enumerate(children, 1):
        if not isinstance(child, dict) or set(child) != {"responsibility", "requirement_ids"}:
            raise EarlySplitError("early split contains fields other than responsibility and requirement_ids")
        responsibility = str(child.get("responsibility") or "").strip()
        ids = child.get("requirement_ids")
        if not responsibility or len(responsibility) > 300 or _PATH_OR_CODE.search(responsibility):
            raise EarlySplitError("early split responsibility contains a path, code, or invalid text")
        if not isinstance(ids, list) or not ids or any(not isinstance(value, str) for value in ids):
            raise EarlySplitError("each responsibility needs existing requirement IDs")
        selected = set(ids)
        if len(selected) != len(ids) or not selected.issubset(known):
            raise EarlySplitError("early split has duplicate or unknown requirement IDs")
        covered.update(selected)
        result.append({"child_id": f"EARLY-{index}", "responsibility": responsibility,
                       "requirement_ids": list(ids)})
    if covered != known:
        raise EarlySplitError("early split omitted source requirements")
    return result


def local_contract(root_contract, child):
    """Project the frozen source ledger; keep global constraints available."""
    contract = copy.deepcopy(root_contract)
    selected = set(child["requirement_ids"])
    ledger = contract.get("source_requirement_ledger")
    if isinstance(ledger, dict):
        ledger["requirements"] = [item for item in ledger.get("requirements", [])
                                  if item.get("requirement_id") in selected]
        ledger["confirmed_requirements"] = [item for item in ledger.get("confirmed_requirements", [])
                                            if item.get("requirement_id") in selected]
        contract["source_requirement_ledger"] = ledger
        contract["requirements"] = [item["text"] for item in
                                    ledger["requirements"] + ledger["confirmed_requirements"]]
    contract["goal"] = child["responsibility"]
    contract["original_goal"] = child["responsibility"]
    contract.pop("source_contract", None)
    return contract


def local_task_brain(root_brain, child):
    brain = copy.deepcopy(root_brain)
    selected = set(child["requirement_ids"])
    brain["task_id"] = child["child_id"]
    brain["source_requirement_ids"] = list(child["requirement_ids"])
    brain["task_goal"] = {
        "text": child["responsibility"], "provenance": "DERIVED_TASK_ASSUMPTION",
        "requirement_ids": list(child["requirement_ids"]), "evidence_ids": [],
    }
    for key, values in list(brain.items()):
        if isinstance(values, list):
            for item in values:
                if isinstance(item, dict) and isinstance(item.get("requirement_ids"), list):
                    item["requirement_ids"] = [value for value in item["requirement_ids"]
                                               if value in selected]
    return brain


def combine_impact_maps(local_maps, root_goal, max_impacts=12):
    """Union local claims without silently discarding any impact or protection."""
    merged = {}
    order = []
    integration = []
    insufficient = []
    proposals = []
    proposal_keys = {}
    prohibitions = []
    id_maps = []
    for impact_map in local_maps:
        child_ids = {}
        proposal_ids = {}
        for proposal in impact_map.get("new_surface_proposals", []) or []:
            key = (proposal.get("kind"), proposal.get("parent_scope"),
                   proposal.get("intended_responsibility"))
            if key not in proposal_keys:
                if len(proposals) >= 4:
                    raise EarlySplitError("combined new surface proposals exceed existing Stage 3 bound")
                proposed = copy.deepcopy(proposal)
                proposed["proposal_id"] = f"NEW-{len(proposals) + 1:03d}"
                proposals.append(proposed)
                proposal_keys[key] = proposed
            else:
                target = proposal_keys[key]
                target["requirement_ids"] = list(dict.fromkeys(
                    list(target.get("requirement_ids", []) or [])
                    + list(proposal.get("requirement_ids", []) or [])
                ))
            proposal_ids[proposal.get("proposal_id")] = proposal_keys[key]["proposal_id"]
        for item in impact_map.get("impacts", []):
            item = copy.deepcopy(item)
            for field in ("new_surface_proposal_ids", "target_new_surface_proposal_ids",
                          "inspect_new_surface_proposal_ids"):
                if field in item:
                    item[field] = [proposal_ids[value] for value in item.get(field, [])
                                   if value in proposal_ids]
            key = (item.get("surface_id") or item.get("path")
                   or tuple(item.get("new_surface_proposal_ids", []) or []),
                   item.get("disposition"))
            if not key[0]:
                raise EarlySplitError("local impact lacks a surface identity")
            if key not in merged:
                if len(order) >= max_impacts:
                    raise EarlySplitError("combined local impacts exceed existing Stage 3 bound")
                order.append(key)
                merged[key] = copy.deepcopy(item)
                merged[key]["impact_id"] = f"IMP-{len(order):03d}"
            else:
                target = merged[key]
                for field in ("requirement_ids", "repository_evidence_ids", "preserve",
                              "local_preservation_constraints", "prohibition_constraints",
                              "verification", "local_verification", "interfaces_to_reuse",
                              "existing_interfaces_to_reuse", "new_surface_proposal_ids"):
                    target[field] = list(dict.fromkeys(list(target.get(field, []) or [])
                                                      + list(item.get(field, []) or [])))
            child_ids[item["impact_id"]] = merged[key]["impact_id"]
        id_maps.append(child_ids)
        integration.extend(impact_map.get("integration_verification", []) or [])
        insufficient.extend(impact_map.get("insufficient_evidence", []) or [])
        prohibitions.extend(impact_map.get("prohibition_constraints", []) or [])
    result = copy.deepcopy(local_maps[0])
    result["task_goal"] = root_goal
    result["impacts"] = [merged[key] for key in order]
    result["integration_verification"] = list(dict.fromkeys(integration))
    result["insufficient_evidence"] = list(dict.fromkeys(insufficient))
    result["new_surface_proposals"] = proposals
    result["prohibition_constraints"] = list(dict.fromkeys(prohibitions))
    for key in ("requirement_obligation_ledger", "semantic_obligation_coverage",
                "challenge_lifecycle", "behavior_anchor_closure_actions",
                "obligation_closure_actions"):
        result.pop(key, None)
    return result, id_maps


def compact_attached_reuse(impact_map, id_maps):
    """Attach same-surface reuse claims to an already required mutation node."""
    result = copy.deepcopy(impact_map)
    remap = {}
    kept = []
    impacts = result.get("impacts", [])
    for item in impacts:
        if item.get("disposition") != "INTERFACE_REUSE":
            kept.append(item)
            continue
        target = next((other for other in impacts
                       if other is not item
                       and other.get("disposition") in {"MUST_CHANGE", "TEST_CHANGE"}
                       and other.get("surface_id") == item.get("surface_id")
                       and other.get("surface_id")), None)
        if target is None:
            kept.append(item)
            continue
        for field in ("requirement_ids", "repository_evidence_ids", "preserve",
                      "local_preservation_constraints", "prohibition_constraints",
                      "verification", "local_verification", "interfaces_to_reuse",
                      "existing_interfaces_to_reuse", "interface_surface_ids"):
            target[field] = list(dict.fromkeys(list(target.get(field, []) or [])
                                                   + list(item.get(field, []) or [])))
        remap[item["impact_id"]] = target["impact_id"]
    result["impacts"] = kept
    projected_ids = [{old: remap.get(new, new) for old, new in mapping.items()}
                     for mapping in id_maps]
    return result, projected_ids
