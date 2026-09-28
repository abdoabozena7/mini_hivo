"""Experiment 11: controller evidence identity by obligation, subject and claim.

Only executed structured browser observations can be normalized. Tool names
are provenance; Worker prose and a page-load PASS cannot prove behavior.
"""

import copy
import hashlib
import json
import posixpath

from hivo.verification import infer_web_profile
from hivo.verification_surfaces import requested_key


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def target_identity(value):
    path = posixpath.normpath(str(value or "").replace("\\", "/"))
    if path in {"", ".", ".."} or path.startswith(("../", "/")) or ":" in path:
        return None
    return path.casefold()


def required_claims(requirements, *, contract_hash, child_id, target, subject_hash, subject_paths):
    claims = []
    for requirement in requirements:
        rid, text = requirement.get("requirement_id"), requirement.get("text")
        if not rid or not text:
            continue
        profile = infer_web_profile(text)
        # Unsupported requirements have no invented behavioral oracle.
        names = list(profile.required_interactions)
        if not names:
            continue
        for name in ["browser_contract", *names]:
            parameters = {}
            if name == "restart_resets_state" and (key := requested_key(text)):
                parameters["input"] = key
                if "game over" in text.casefold() and "win" in text.casefold():
                    parameters["terminal_cases"] = ["forceCollision", "forceWin"]
            identity = {"child_id": child_id, "requirement_id": rid,
                        "requirement_text_hash": canonical_hash(text), "contract_hash": contract_hash,
                        "target": target_identity(target), "surface_id": "file:" + str(target_identity(target)),
                        "assertion": {"name": name, "parameters": parameters}}
            claims.append({**identity, "obligation_id": "CLAIM-" + canonical_hash(identity),
                           "subject_hash": subject_hash, "subject_paths": list(subject_paths)})
    return claims


def _assertion(check):
    parameters = {}
    if check.get("name") == "restart_resets_state":
        parameters["input"] = str(check.get("input") or "").casefold()
        if check.get("cases"):
            parameters["terminal_cases"] = sorted({c["setup"] for c in check["cases"]
                if isinstance(c, dict) and isinstance(c.get("setup"), str)
                and c.get("precondition_met") is True})
    return {"name": check.get("name"), "parameters": parameters}


def normalize_browser_result(payload, claims, *, tool, source, subject_before_hash, subject_after_hash):
    """Called by the controller with its actual full verifier return value."""
    if (not isinstance(payload, dict) or payload.get("behavior_test_executed") is not True
            or payload.get("environment_error") or subject_before_hash != subject_after_hash):
        return []
    observed_target = target_identity(payload.get("resolved_entrypoint") or payload.get("entry_path"))
    checks = [c for c in payload.get("interaction_checks", []) if isinstance(c, dict) and c.get("executed") is True]
    records = []
    for claim in claims:
        if claim["target"] != observed_target or claim["subject_hash"] != subject_after_hash:
            continue
        name = claim["assertion"]["name"]
        if name == "browser_contract":
            observations = [(claim["assertion"], payload.get("passed"))]
        else:
            observations = []
            for check in checks:
                if check.get("name") != name:
                    continue
                passed = check.get("passed")
                if check.get("cases") and any(not isinstance(case, dict) or case.get("passed") is not True
                                               for case in check["cases"]):
                    passed = False
                observations.append((_assertion(check), passed))
        for assertion, passed in observations:
            if passed is not True and passed is not False:
                continue
            value = {"artifact_type": "CanonicalEvidenceRecord", **copy.deepcopy(claim),
                     "assertion": assertion, "result": "PASS" if passed else "FAIL",
                     "raw_result_hash": canonical_hash(payload),
                     "provenance": {"tool": tool, "source": source, "executed": True},
                     "subject_before_hash": subject_before_hash, "subject_after_hash": subject_after_hash}
            value["record_hash"] = canonical_hash(value)
            records.append(value)
    return records


def record_valid(record):
    return (record.get("artifact_type") == "CanonicalEvidenceRecord"
            and record.get("result") in {"PASS", "FAIL"}
            and record.get("record_hash") == canonical_hash({k: v for k, v in record.items() if k != "record_hash"})
            and record.get("provenance", {}).get("executed") is True
            and record.get("provenance", {}).get("source") in {"controller_tool_result", "controller_child_browser"}
            and record.get("subject_before_hash") == record.get("subject_hash") == record.get("subject_after_hash"))


def compatible(claim, record):
    if not record_valid(record):
        return False
    for key in ("child_id", "requirement_id", "requirement_text_hash", "contract_hash", "obligation_id",
                "target", "surface_id", "subject_hash"):
        if claim.get(key) != record.get(key):
            return False
    expected, observed = claim["assertion"], record["assertion"]
    return expected["name"] == observed.get("name") and all(
        observed.get("parameters", {}).get(key) == value for key, value in expected.get("parameters", {}).items())


def assess(claims, records, *, required_requirement_ids):
    decisions, used = [], {}
    for claim in claims:
        matches = [r for r in records if compatible(claim, r)]
        statuses = {r["result"] for r in matches}
        result = "FAIL" if "FAIL" in statuses else "PASS" if "PASS" in statuses else "PENDING"
        decisions.append({"obligation_id": claim["obligation_id"], "requirement_id": claim["requirement_id"],
                          "assertion": claim["assertion"], "result": result,
                          "record_hashes": [r["record_hash"] for r in matches]})
        used.update({r["record_hash"]: r for r in matches})
    required = set(required_requirement_ids)
    covered = {rid for rid in required if any(d["requirement_id"] == rid for d in decisions)
               and all(d["result"] == "PASS" for d in decisions if d["requirement_id"] == rid)}
    status = ("FAIL" if any(d["result"] == "FAIL" for d in decisions)
              else "PASS" if required and covered == required else "PENDING")
    return {"status": status, "required_requirement_ids": sorted(required),
            "covered_requirement_ids": sorted(covered), "claim_decisions": decisions,
            "canonical_evidence_records": list(used.values()), "required_claims": copy.deepcopy(claims),
            "tool_used_as_identity": False}
