import copy
from pathlib import Path
import tempfile
import unittest

from hivo import evidence_monotonic
from hivo.atomic_child_receipt import create_atomic_child_receipt, validate_atomic_child_receipt
from hivo.verification_routing import aggregate_verification_evidence
from tests import test_experiment11_evidence_compatibility as fixtures


class MonotonicBrowserTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SemanticEvidenceCompatibilityTests()
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def aggregation(self, records, raw=None, browser=None):
        f=self.fixture
        assessment=evidence_monotonic.assess(f.claims,records,required_requirement_ids=["REQ-001"])
        return aggregate_verification_evidence(f.artifact, f.raw if raw is None else raw,
            f.payload if browser is None else browser, semantic_browser_evidence={"index.html":assessment},
            semantic_evidence_policy="monotonic")

    def receipt(self, aggregation, raw=None):
        f=self.fixture
        contract={"execution_contract_id":"EXEC-001","contract_hash":"approved-contract","plan_hash":"plan",
            "allowed_mutation_paths":["index.html"],"allowed_inspection_paths":["index.html"],
            "plan_node_ids":["NODE-001"],"requirement_ids":["REQ-001"],"requirements":f.requirements}
        task={"id":"EXEC-001","parent":"ROOT","execution_contract":contract,"plan_node_ids":["NODE-001"]}
        return create_atomic_child_receipt(task,{"status":"done","gate":{"verification_aggregation":aggregation},
            "verification_evidence":f.raw if raw is None else raw},
            workspace=f.workspace,verification_applicability=f.artifact)

    def test_cross_tool_rescue_and_current_matching_are_separate_decisions(self):
        f=self.fixture
        rescued=self.aggregation(f.records())
        self.assertTrue(rescued["passed"])
        self.assertEqual(rescued["semantic_compatibility_audit"]["decisions"][0]["decision"],"SEMANTIC_RESCUE")
        exact=self.aggregation(f.records(),raw=[{"tool":"verify_web_app","target":"index.html","result":f.payload}])
        self.assertTrue(exact["passed"])
        self.assertEqual(exact["semantic_compatibility_audit"]["decisions"][0]["decision"],"CURRENT")

    def test_unknown_inventory_cannot_rescue_invalid_current_matching(self):
        self.assertFalse(self.aggregation([])["passed"])

    def test_metadata_loss_cannot_unverify_a_correct_current_browser_match(self):
        f=self.fixture
        raw=[{"tool":"verify_web_app","target":"index.html","result":f.payload}]
        aggregation=self.aggregation([],raw=raw)
        self.assertTrue(aggregation["passed"])
        self.assertEqual(aggregation["semantic_compatibility_audit"]["decisions"][0]["metadata_status"],"UNKNOWN")
        self.assertTrue(validate_atomic_child_receipt(self.receipt(aggregation,raw),workspace=f.workspace)["valid"])

    def test_real_fail_cannot_be_rescued_by_cached_pass(self):
        failed=copy.deepcopy(self.fixture.payload);failed["passed"]=False
        self.assertFalse(self.aggregation(self.fixture.records(),browser=failed)["passed"])

    def test_known_foreign_semantics_rejected_at_final_gate_even_if_current_accepts(self):
        f=self.fixture
        for field,value in (("requirement_id","OTHER"),("target","other.html"),("requirement_text_hash","other")):
            records=copy.deepcopy(f.records())
            from hivo.evidence_compatibility import canonical_hash
            for r in records:
                r[field]=value;r["record_hash"]=canonical_hash({k:v for k,v in r.items() if k!="record_hash"})
            aggregated=self.aggregation(records,raw=[{"tool":"verify_web_app","target":"index.html","result":f.payload}])
            self.assertTrue(aggregated["passed"])
            self.assertFalse(validate_atomic_child_receipt(self.receipt(aggregated),workspace=f.workspace)["valid"])

    def test_scope_staleness_and_bound_authority_gates_remain(self):
        f=self.fixture
        receipt=self.receipt(self.aggregation(f.records()))
        self.assertTrue(validate_atomic_child_receipt(receipt,workspace=f.workspace)["valid"])
        (f.workspace/"index.html").write_text("changed",encoding="utf-8")
        self.assertFalse(validate_atomic_child_receipt(receipt,workspace=f.workspace)["valid"])
        artifact=copy.deepcopy(f.artifact);artifact["verification_routes"][0].update(authority_id="approved",authority_type="APPROVED")
        self.assertFalse(aggregate_verification_evidence(artifact,f.raw,f.payload,
            semantic_browser_evidence={"index.html":evidence_monotonic.assess(f.claims,f.records(),required_requirement_ids=["REQ-001"])},
            semantic_evidence_policy="monotonic")["passed"])


class MonotonicUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.workspace=Path(self.temp.name)
        (self.workspace/"values.js").write_text("export const value=1",encoding="utf-8")
        self.requirements=[{"requirement_id":"REQ-001","text":"Return unique values preserving input order."}]
        self.contract={"execution_contract_id":"EXEC-001","contract_hash":"approved","plan_hash":"plan",
            "allowed_mutation_paths":["values.js"],"allowed_inspection_paths":["values.js"],
            "plan_node_ids":["NODE-001"],"requirement_ids":["REQ-001"],"requirements":self.requirements}
        self.artifact={"child_id":"EXEC-001","verification_routes":[{"kind":"FOCUSED_TEST","target":"tests/unique.test.js",
            "required":True,"applicable":True,"result":"PENDING"}]}
        self.raw=[{"tool":"run_command","target":"node tests/unique.test.js","result":"[exit_code=0]\n4 tests passed"}]

    def receipt(self, raw, policy="monotonic", **scope):
        aggregation=aggregate_verification_evidence(self.artifact,raw,semantic_browser_evidence={} if policy=="monotonic" else None,
            semantic_evidence_policy=policy)
        task={"id":"EXEC-001","parent":"ROOT","execution_contract":self.contract,"plan_node_ids":["NODE-001"]}
        receipt=create_atomic_child_receipt(task,{"status":"done","gate":{"verification_aggregation":aggregation},
            "verification_evidence":raw},workspace=self.workspace,verification_applicability=self.artifact,**scope)
        return aggregation,validate_atomic_child_receipt(receipt,workspace=self.workspace)

    def test_current_valid_unit_receipt_preserved_with_empty_inventory(self):
        self.assertTrue(self.receipt(self.raw,policy="current")[1]["valid"])
        self.assertTrue(self.receipt(self.raw)[1]["valid"])

    def test_permissive_unit_aggregation_is_unchanged_but_foreign_receipt_is_invalid(self):
        for field,value in (("target","node tests/other.test.js"),("requirement_id","OTHER"),("behavior","other_behavior")):
            raw=[{**self.raw[0],field:value}]
            aggregation,checked=self.receipt(raw)
            self.assertTrue(aggregation["passed"])
            self.assertFalse(checked["valid"])
            self.assertNotIn("semantic evidence hash or inventory is invalid",checked["errors"])

    def test_unknown_metadata_never_bypasses_missing_evidence_or_scope(self):
        self.assertFalse(self.receipt([])[1]["valid"])
        self.assertFalse(self.receipt(self.raw,scope_violations=1)[1]["valid"])


if __name__=="__main__":unittest.main()
