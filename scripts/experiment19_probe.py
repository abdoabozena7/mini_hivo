"""Offline same-input verification-outcome protocol; no model/browser calls.

Load pinned pure routing/evidence modules from Git without checking out either
revision. The supplied output directory must not exist. Raw logs stay local.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "2a8b94590734cec3375047a18e0dc71df2476f85"
TREATMENT = "f8bf65ece895f70c1b572b59df229314de09afbe"


def load(revision, path, suffix):
    source = subprocess.check_output(
        ["git", "show", revision + ":" + path], cwd=ROOT
    )
    name = "hivo._experiment19_" + suffix
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / path)
    sys.modules[name] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module, hashlib.sha256(source).hexdigest()


def protocol(fixture, routing, evidence, treatment):
    failed = fixture["failed_payload"]
    profile = failed["verification_profile"]
    assert len(json.dumps(failed)) > 1600, "Overflow fixture must actually exceed the storage bound"
    try:
        json.loads(json.dumps(failed)[:1600])
    except ValueError:
        pass
    else:
        raise AssertionError("Overflow prefix must be incomplete JSON")

    def payload(passed, kind="game"):
        value = copy.deepcopy(failed)
        value.update(passed=passed, failures=[] if passed else failed["failures"])
        value["verification_status"] = "PASS" if passed else "FAIL"
        if kind == "web":
            value["verification_profile"] = {"kind": "web", "require_game_bridge": False}
        return value

    def receipt(value, role="Falsifier", target="index.html"):
        # Only the dedicated overflow case uses the complete long payload.
        # Other cases isolate parser/identity/supersession instead of clipping.
        if isinstance(value, dict):
            fields = ("passed", "verification_status", "status", "verification_profile",
                      "failures", "resolved_entrypoint", "environment_error")
            value = {k: v for k, v in value.items() if k in fields}
            assert len(json.dumps(value)) <= 1600
        return {"tool": "verify_web_app", "target": target, "role": role,
                "result": value if isinstance(value, str) else json.dumps(value)}

    cases = [
        ("run010_long_failed_json", [receipt(json.dumps(failed))], None, False, "PENDING"),
        ("valid_structured_pass", [receipt(payload(True))], None, True, "PENDING"),
        ("malformed_structured_pass", [receipt('{"passed": true')], None, False, "PENDING"),
        ("missing_required_evidence", [], None, False, "PENDING"),
        ("wrong_target_pass", [receipt(payload(True), target="other.html")], None, False, "PENDING"),
        ("cached_pass_without_proof", [], None, False, "PASS"),
        ("controller_fail_vs_basic_pass", [receipt(payload(True, "web"))], failed, False, "PENDING"),
        ("controller_fail_vs_old_pass", [receipt(payload(True))], failed, False, "PENDING"),
        ("failure_then_null", [receipt(failed), receipt({"passed": None, "verification_profile": profile})], payload(True), False, "PENDING"),
        ("failure_then_unavailable", [receipt(failed), receipt({"verification_status": "NOT_RUN", "verification_profile": profile})], payload(True), False, "PENDING"),
        ("failure_then_valid_matching_pass", [receipt(failed), receipt(payload(True))], payload(True), True, "PENDING"),
        ("failure_then_weaker_pass", [receipt(failed), receipt(payload(True, "web"))], payload(True), False, "PENDING"),
        ("failure_then_other_role_pass", [receipt(failed), receipt(payload(True), role="Builder")], payload(True), False, "PENDING"),
        ("new_failure_after_pass", [receipt(payload(True)), receipt(failed)], None, False, "PENDING"),
        ("conflicting_explicit_status", [receipt({"passed": False, "status": "PASS"})], None, False, "PENDING"),
        ("unavailable_only", [receipt({"passed": None, "verification_profile": profile})], None, False, "PENDING"),
    ]
    rows = []
    for name, inputs, controller, expected, cached in cases:
        projected = copy.deepcopy(inputs)
        for item in projected:
            raw = item["result"]
            item["result"] = (evidence.project_tool_evidence_result(item["tool"], raw)
                              if treatment else str(raw)[:1600])
        artifact = {"child_id": "1", "verification_routes": [{
            "kind": "BROWSER", "required": True, "applicable": True,
            "target": "index.html", "result": cached,
            "reason_codes": [], "evidence_refs": []}]}
        result = routing.aggregate_verification_evidence(artifact, projected, controller)
        rows.append({"case_id": name, "input_sha256": hashlib.sha256(
            json.dumps([inputs, controller, cached], sort_keys=True).encode()).hexdigest(),
            "expected_passed": expected, "actual_passed": result["passed"],
            "route_result": result["verification_routes"][0]["result"],
            "matches_expected": result["passed"] == expected})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    fixture_path = ROOT / "reports/experiment19/supporting/run010-fixture.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    result = {"experiment": 19, "boundary": "offline pure-module paired protocol",
              "model_calls": 0, "browser_calls": 0, "full_e2e": False,
              "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
              "baseline": BASELINE, "treatment": TREATMENT, "arms": {}}
    for label, revision in (("baseline", BASELINE), ("treatment", TREATMENT)):
        routing, rh = load(revision, "hivo/verification_routing.py", label + "_routing")
        evidence, eh = load(revision, "hivo/evidence.py", label + "_evidence")
        rows = protocol(fixture, routing, evidence, label == "treatment")
        result["arms"][label] = {"source_sha256": {"routing": rh, "evidence": eh},
            "cases": rows, "case_count": len(rows),
            "matching_expected": sum(r["matches_expected"] for r in rows),
            "false_passes": sum(r["actual_passed"] and not r["expected_passed"] for r in rows),
            "false_rejections": sum(not r["actual_passed"] and r["expected_passed"] for r in rows)}
    left, right = (result["arms"][a]["cases"] for a in ("baseline", "treatment"))
    result["same_input_hashes"] = all(a["input_sha256"] == b["input_sha256"] for a, b in zip(left, right))
    path = args.output_dir / "comparison.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({a: {k: v for k, v in result["arms"][a].items()
                         if k not in ("cases", "source_sha256")} for a in result["arms"]}))
    return 0 if result["same_input_hashes"] and all(r["matches_expected"] for r in right) else 1


if __name__ == "__main__":
    raise SystemExit(main())
