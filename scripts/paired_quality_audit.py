"""Compare independent outcomes on a frozen arm-by-case grid.

Protocol JSON:
  schema: 1
  evidence_mode: "fixture", "offline", or "live" (a supplied label)
  tool_authority: the shared authority profile ID
  arms: [{id, limits: {max_model_calls, max_tool_calls, max_elapsed_seconds}}]
  cases: [{id, oracle_id}]
At least two arms and one case are required. Call limits are nonnegative
integers; elapsed seconds must be finite and positive. Freeze the protocol
before collecting outcomes, with one case ID per planned pairing/repetition.

Results JSON:
  schema: 1
  protocol_sha256: SHA-256 of the exact protocol file bytes
  records: [{arm_id, case_id, outcome, evidence_id, oracle_id?}]
The external evaluator supplies "pass" or "fail" and the frozen oracle ID.
The collector may instead record "blocked" or "timeout" without a verdict.
Evidence IDs refer to retained records outside this tool; they are not opened.
An absent record is "missing"; a second record for a pair is an error.

The report uses all planned cases for every denominator. Only an independent
"pass" earns credit; pairwise differences are right minus left in declared arm
order. A valid report exits 0 regardless of outcomes; invalid input exits 2.
This CLI does not run models or verify actual budgets or provenance.
"""

import argparse
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path


_OBSERVED = ("pass", "fail", "blocked", "timeout")
_OUTCOMES = (*_OBSERVED, "missing")
_CALL_LIMITS = ("max_model_calls", "max_tool_calls")
_TIME_LIMIT = "max_elapsed_seconds"


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate JSON key {key!r}")
        obj[key] = value
    return obj


def _invalid_constant(value):
    raise ValueError(f"{value} is not a JSON number")


def _load(path):
    raw = path.read_bytes()
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1:
        raise ValueError(f"{path}: expected a schema 1 JSON object")
    return data, hashlib.sha256(raw).hexdigest()


def _id(value, name):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a nonempty string without surrounding whitespace")
    return value


def _index(entries, kind, minimum):
    if not isinstance(entries, list) or len(entries) < minimum:
        raise ValueError(f"protocol must declare at least {minimum} {kind} entries")
    indexed = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"each {kind} entry must be an object")
        key = _id(entry.get("id"), f"{kind} id")
        if key in indexed:
            raise ValueError(f"duplicate {kind} id {key!r}")
        indexed[key] = entry
    return indexed


def _limits(value, arm):
    if not isinstance(value, dict) or set(value) != {*_CALL_LIMITS, _TIME_LIMIT}:
        raise ValueError(f"arm {arm!r} must declare exactly {', '.join((*_CALL_LIMITS, _TIME_LIMIT))}")
    for key in _CALL_LIMITS:
        if type(value[key]) is not int or value[key] < 0:
            raise ValueError(f"arm {arm!r}: {key} must be a nonnegative integer")
    seconds = value[_TIME_LIMIT]
    if (
        type(seconds) not in (int, float) or seconds <= 0
        or (type(seconds) is float and not math.isfinite(seconds))
    ):
        raise ValueError(f"arm {arm!r}: {_TIME_LIMIT} must be finite and positive")
    return value


def _validate_protocol(protocol):
    if protocol.get("evidence_mode") not in ("fixture", "offline", "live"):
        raise ValueError("evidence_mode must be fixture, offline, or live")
    authority = _id(protocol.get("tool_authority"), "tool_authority")
    arms = _index(protocol.get("arms"), "arm", 2)
    cases = _index(protocol.get("cases"), "case", 1)
    for case_id, case in cases.items():
        _id(case.get("oracle_id"), f"case {case_id!r} oracle_id")
    limits = None
    for arm_id, arm in arms.items():
        if arm.get("tool_authority", authority) != authority:
            raise ValueError(f"arm {arm_id!r} does not use the shared tool_authority")
        arm_limits = _limits(arm.get("limits"), arm_id)
        if limits is None:
            limits = arm_limits
        elif arm_limits != limits:
            raise ValueError(f"unequal declared limits for arm {arm_id!r}")
    return arms, cases, limits


def _validate_results(results, protocol_sha256, arms, cases):
    if results.get("protocol_sha256") != protocol_sha256:
        raise ValueError("results protocol_sha256 does not match the exact protocol bytes")
    if not isinstance(results.get("records"), list):
        raise ValueError("results records must be an array")
    records = {}
    for record in results["records"]:
        if not isinstance(record, dict):
            raise ValueError("each result record must be an object")
        arm_id = _id(record.get("arm_id"), "result arm_id")
        case_id = _id(record.get("case_id"), "result case_id")
        pair = arm_id, case_id
        if arm_id not in arms or case_id not in cases:
            raise ValueError(f"unplanned arm/case pair {pair!r}")
        if pair in records:
            raise ValueError(f"duplicate result for arm/case pair {pair!r}")
        outcome = record.get("outcome")
        if outcome not in _OBSERVED:
            raise ValueError(f"result {pair!r} outcome must be one of {', '.join(_OBSERVED)}")
        oracle_id = record.get("oracle_id")
        if (outcome in ("pass", "fail") or oracle_id is not None) and (
            oracle_id != cases[case_id]["oracle_id"]
        ):
            raise ValueError(f"result {pair!r} must name the frozen oracle_id")
        evidence_id = _id(record.get("evidence_id"), f"result {pair!r} evidence_id")
        records[pair] = {"outcome": outcome, "evidence_id": evidence_id}
    return records


def _compare(arms, cases, records):
    by_arm = {arm: {outcome: [] for outcome in _OUTCOMES} for arm in arms}
    rows = []
    for case_id, case in cases.items():
        outcomes = {}
        for arm_id in arms:
            result = records.get((arm_id, case_id), {"outcome": "missing", "evidence_id": None})
            outcomes[arm_id] = result
            by_arm[arm_id][result["outcome"]].append(case_id)
        rows.append({"case_id": case_id, "oracle_id": case["oracle_id"], "outcomes": outcomes})

    summaries = {
        arm: {
            "counts": {outcome: len(ids) for outcome, ids in groups.items()},
            "case_ids_by_outcome": groups,
            "pass_rate": len(groups["pass"]) / len(cases),
        }
        for arm, groups in by_arm.items()
    }
    passes = {arm: set(groups["pass"]) for arm, groups in by_arm.items()}
    pairs = []
    for left, right in combinations(arms, 2):
        left_only = len(passes[left] - passes[right])
        right_only = len(passes[right] - passes[left])
        delta = right_only - left_only
        pairs.append({
            "left_arm": left,
            "right_arm": right,
            "both_pass": len(passes[left] & passes[right]),
            "left_only_pass": left_only,
            "right_only_pass": right_only,
            "neither_pass": len(cases) - len(passes[left] | passes[right]),
            "pass_count_delta": delta,
            "pass_rate_delta": delta / len(cases),
        })
    return rows, summaries, pairs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("protocol", type=Path, help="frozen protocol JSON")
    parser.add_argument("results", type=Path, help="independently collected result records JSON")
    args = parser.parse_args(argv)
    try:
        protocol, protocol_sha256 = _load(args.protocol)
        arms, cases, limits = _validate_protocol(protocol)
        results, results_sha256 = _load(args.results)
        records = _validate_results(results, protocol_sha256, arms, cases)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    rows, summaries, pairs = _compare(arms, cases, records)
    print(json.dumps({
        "schema": 1,
        "protocol_sha256": protocol_sha256,
        "results_sha256": results_sha256,
        "evidence_mode": protocol["evidence_mode"],
        "scope": "Declared limits and supplied outcomes only; no runtime or live-model verification.",
        "tool_authority": protocol["tool_authority"],
        "declared_limits": limits,
        "planned_cases": len(cases),
        "arms": summaries,
        "cases": rows,
        "pairs": pairs,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
