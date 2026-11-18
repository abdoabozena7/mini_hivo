import copy
import unittest

from hivo import evidence_monotonic, evidence_compatibility as semantic
from hivo.verification_routing import aggregate_verification_evidence
from tests import test_experiment13_monotonic as fixtures


class StrictBrowserTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.MonotonicBrowserTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.f = self.base.fixture

    def aggregate(self, raw=None, browser=None, records=None, artifact=None):
        f = self.f
        assessment = evidence_monotonic.assess(f.claims, f.records() if records is None else records,
                                              required_requirement_ids=["REQ-001"])
        return aggregate_verification_evidence(artifact or f.artifact, f.raw if raw is None else raw,
            f.payload if browser is None else browser, semantic_browser_evidence={"index.html":assessment},
            semantic_evidence_policy="strict", strict_evidence_context={"workspace":str(f.workspace), "requirement_ids":["REQ-001"]})

    def test_exact_and_cross_tool_behavior_remain_valid_in_unchanged_final_gate(self):
        for raw in (self.f.raw, [{"tool":"verify_web_app", "target":"index.html", "result":self.f.payload}]):
            agg = self.aggregate(raw=raw)
            self.assertTrue(agg["passed"])
            from hivo.atomic_child_receipt import validate_atomic_child_receipt
            self.assertTrue(validate_atomic_child_receipt(self.base.receipt(agg, raw), workspace=self.f.workspace)["valid"])

    def test_foreign_requirement_target_text_and_provenance_rejected_by_aggregation(self):
        for field, value in (("requirement_id","OTHER"), ("target","other.html"),
                             ("requirement_text_hash","different"), ("subject_hash","stale")):
            records = copy.deepcopy(self.f.records())
            for r in records:
                r[field] = value
                r["record_hash"] = semantic.canonical_hash({k:v for k,v in r.items() if k != "record_hash"})
            self.assertFalse(self.aggregate(records=records)["passed"], field)
        records = copy.deepcopy(self.f.records())
        for r in records:
            r["provenance"]["tool"] = "worker_prose"
            r["record_hash"] = semantic.canonical_hash({k:v for k,v in r.items() if k != "record_hash"})
        self.assertFalse(self.aggregate(records=records)["passed"])

    def test_native_full_payload_can_prove_unknown_extra_inventory(self):
        self.assertTrue(self.aggregate(records=[])["passed"])
        payload = copy.deepcopy(self.f.payload)
        payload["interaction_checks"] = []
        self.assertFalse(self.aggregate(records=[], browser=payload)["passed"])

    def test_cached_pass_cannot_replace_wrong_fresh_behavior_or_missing_execution(self):
        for change in ("behavior", "execution", "fail", "target"):
            payload = copy.deepcopy(self.f.payload)
            if change == "behavior":payload["interaction_checks"] = [{"name":"other_behavior", "passed":True,"executed":True}]
            elif change == "execution":payload["behavior_test_executed"] = False
            elif change == "fail":payload["passed"] = False
            else:payload["resolved_entrypoint"] = "other.html"
            self.assertFalse(self.aggregate(browser=payload)["passed"], change)

    def test_declared_wrong_identity_not_laundered_by_controller_pass(self):
        for field, value in (("requirement_id","OTHER"), ("behavior","other_behavior"), ("target","other.html")):
            raw = [{"tool":"verify_web_app", "target":"index.html", "result":self.f.payload, field:value}]
            self.assertFalse(self.aggregate(raw=raw)["passed"], field)

    def test_unknown_required_claims_do_not_match(self):
        self.assertFalse(aggregate_verification_evidence(self.f.artifact,self.f.raw,self.f.payload,
            semantic_evidence_policy="strict")["passed"])

    def test_bound_authority_is_not_rescued(self):
        artifact = copy.deepcopy(self.f.artifact)
        artifact["verification_routes"][0].update(authority_id="approved",authority_type="APPROVED")
        self.assertFalse(self.aggregate(artifact=artifact)["passed"])


class StrictSuiteTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.MonotonicUnitTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)

    def aggregate(self, raw):
        return aggregate_verification_evidence(self.base.artifact,raw,semantic_browser_evidence={},
            semantic_evidence_policy="strict",strict_evidence_context={"workspace":str(self.base.workspace),"requirement_ids":["REQ-001"]})

    def test_exact_native_suite_preserves_node_without_extra_inventory(self):
        self.assertTrue(self.aggregate(self.base.raw)["passed"])
        raw = [{**self.base.raw[0], "tool":"run_file", "target":"./tests/unique.test.js"}]
        self.assertTrue(self.aggregate(raw)["passed"])

    def test_nonapplicable_browser_cannot_add_empty_semantic_receipt_inventory(self):
        artifact = copy.deepcopy(self.base.artifact)
        artifact["verification_routes"].append({"kind":"BROWSER", "target":None,
            "required":False,"applicable":False,"result":"SKIPPED_NOT_APPLICABLE"})
        agg = aggregate_verification_evidence(artifact,self.base.raw,
            semantic_evidence_policy="strict",strict_evidence_context={"requirement_ids":["REQ-001"]})
        self.assertTrue(agg["passed"])
        self.assertNotIn("semantic_browser_evidence",agg)
        self.assertEqual(agg["semantic_compatibility_audit"]["browser_assessments"],{})

    def test_wrong_declared_requirement_behavior_or_target_rejected_early(self):
        for field,value in (("requirement_id","OTHER"),("behavior","other_behavior"),("target","node tests/other.test.js")):
            self.assertFalse(self.aggregate([{**self.base.raw[0],field:value}])["passed"], field)

    def test_target_in_stdout_or_argument_or_substring_is_not_proof(self):
        for command in ("node tests/other.test.js", "node tests/unique.test.js.fake", "node other.js tests/unique.test.js",
                        "node --eval tests/unique.test.js", "node tests/unique.test.js ; echo ok"):
            raw=[{**self.base.raw[0],"target":command,"result":"[exit_code=0]\n4 tests passed tests/unique.test.js"}]
            self.assertFalse(self.aggregate(raw)["passed"],command)

    def test_unknown_target_provenance_execution_or_conflicting_fields_never_match(self):
        for update in ({"target":None},{"tool":"unit_test_result"},{"result":{"passed":True}},
                       {"path":"tests/other.test.js"},{"requirement_ids":[]},
                       {"provenance":{"source":"worker","executed":True,"tool":"run_command"}}):
            self.assertFalse(self.aggregate([{**self.base.raw[0],**update}])["passed"],update)

    def test_native_test_fail_beats_same_suite_pass(self):
        failed={**self.base.raw[0],"result":"[exit_code=1]\n1 failed"}
        self.assertFalse(self.aggregate([*self.base.raw,failed])["passed"])


if __name__ == "__main__":unittest.main()
