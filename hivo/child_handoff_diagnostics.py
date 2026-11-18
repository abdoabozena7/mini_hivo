"""Read-only Experiment 10 tracing. Decisions remain with existing gates."""

import copy

from hivo.integration_gate import canonical_hash
from hivo import verification_routing as routing


def evidence_match_audit(artifact, evidence, browser_result):
    """Explain the existing matcher's inputs without changing their results."""
    audits = []
    for route in routing._authority_routes(artifact or {}):
        matched = [i for i, item in enumerate(evidence) if routing._evidence_matches(route, item)]
        related = [i for i, item in enumerate(evidence) if routing._evidence_is_related(route, item)]
        audits.append({
            "kind": route.get("kind"), "target": route.get("target"),
            "matched_evidence_indices": matched, "related_evidence_indices": related,
            "matched_tools": [evidence[i].get("tool") for i in matched],
            "related_tools": [evidence[i].get("tool") for i in related],
            "separate_browser_pass": bool(route.get("kind") == routing.BROWSER
                                          and (browser_result or {}).get("passed") is True),
            "related_without_match": bool(related and not matched),
        })
    return audits


def trace_handoff(snapshot, backend):
    """Replay verification entry and aggregation, with no Worker or Repairer.

    This diagnostic stops at the evidence gate. It cannot mark a child done,
    commit a transaction, issue a receipt, or invoke parent integration.
    """
    task, contract = copy.deepcopy(snapshot["task"]), copy.deepcopy(snapshot["tool_contract"])
    builder, falsifier = copy.deepcopy(snapshot["builder"]), copy.deepcopy(snapshot["falsifier"])
    events = []

    def emit(kind, **fields):
        event = {"kind": kind, "sequence": len(events) + 1, **fields}
        events.append(event)

    def finish(stage=None, reason=None, **fields):
        if stage:
            emit("BLOCKED", stage=stage, reason=reason)
        decision = {"first_blocker": {"stage": stage, "reason": reason} if stage else None,
                    "verification_started": any(e["kind"] == "VERIFICATION_STARTED" for e in events),
                    "evidence_gate_passed": fields.get("gate", {}).get("passed") is True,
                    "terminal_classification": fields.get("terminal_classification"),
                    "route_results": [{key: r.get(key) for key in ("kind", "target", "result")}
                                      for r in (fields.get("gate", {}).get("verification_aggregation") or {}).get("verification_routes", [])]}
        return {"events": events, **decision, "decision_hash": canonical_hash(decision), **fields}

    emit("CHILD_EXECUTION_FINISHED", child_id=task["id"], status=builder.get("status"),
         input_hash=canonical_hash(snapshot))
    if not snapshot.get("records_complete"):
        return finish("SNAPSHOT_COMPLETENESS", "HANDOFF_SNAPSHOT_INCOMPLETE")
    authority = backend._authority_terminal_failure(task)
    if authority:
        return finish("EXECUTION_AUTHORITY", authority)
    if backend._context_sufficiency_failed(builder):
        return finish("WORKER_CONTEXT", backend.CONTEXT_INSUFFICIENT_FAILURE)
    if builder.get("status") != "done":
        return finish("WORKER_COMPLETION", builder.get("failure_type") or builder.get("status"))
    if falsifier.get("status") == "provider_failure":
        return finish("FALSIFIER_PROVIDER", "ENVIRONMENT_ERROR")

    evidence = backend.merged_verification_evidence(builder, falsifier)
    artifact = backend.analyze_verification_applicability(task, contract, execution_evidence=evidence)
    if artifact is None:
        return finish("VERIFICATION_AUTHORITY", "APPLICABILITY_ARTIFACT_UNAVAILABLE")
    route = backend._verification_route(artifact, backend.BROWSER_VERIFICATION)
    if route is None:
        return finish("VERIFICATION_APPLICABILITY", "NO_BROWSER_ROUTE", applicability=artifact)
    if route.get("required") and not route.get("target"):
        return finish("VERIFICATION_TARGET", backend.REQUIRED_VERIFICATION_TARGET_UNRESOLVED,
                      applicability=artifact)
    if route.get("target"):
        emit("VERIFICATION_TARGET_RESOLVED", target=route["target"],
             source=route.get("resolution_source"))
    if not route.get("required") and not route.get("applicable"):
        return finish("VERIFICATION_APPLICABILITY", "SKIPPED_NOT_APPLICABLE", applicability=artifact)
    emit("VERIFICATION_APPLICABLE", required=route.get("required"), reason_codes=route.get("reason_codes"))
    emit("VERIFICATION_CONTEXT_SUFFICIENT", context_status=(builder.get("context_sufficiency") or {}).get("context_status"),
         source="existing_worker_context_guard")
    browser = backend.observed_browser_check(
        task, contract, syntax_failures=backend._combined_syntax_validation_failures(builder, falsifier),
        execution_evidence=evidence, on_start=lambda **fields: emit("VERIFICATION_STARTED", **fields),
    )
    emit("VERIFICATION_FINISHED", passed=(browser or {}).get("passed"),
         behavior_test_executed=(browser or {}).get("behavior_test_executed", False))
    gate = backend.evidence_gate(builder, falsifier, browser)
    audit = evidence_match_audit((browser or {}).get("verification_applicability") or artifact, evidence, browser)
    fields = {"applicability": artifact, "browser": browser, "gate": gate, "evidence_match_audit": audit}
    if not gate.get("passed"):
        aggregation = gate.get("verification_aggregation") or {}
        first = next((r for r in aggregation.get("actual_failures", []) if r.get("required")), {})
        reason = first.get("result") or next(iter(aggregation.get("failure_codes", [])), "EVIDENCE_GATE_FAILED")
        fields["terminal_classification"] = backend.classify_failure(builder, gate, browser, falsifier)
        return finish("VERIFICATION_EVIDENCE_AGGREGATION", reason, **fields)
    emit("VERIFICATION_HANDOFF_ACCEPTED")
    emit("RECEIPT_NOT_REPLAYED", reason="POST_VERIFICATION_COMMIT_AND_RECEIPT_LIFECYCLE_OUTSIDE_DIAGNOSTIC")
    return finish(**fields)
