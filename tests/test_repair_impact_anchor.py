"""Real greenfield Builder -> repair_task handoff, without provider inference."""
import copy
import unittest
from unittest.mock import patch
import mini
import test_greenfield_context_progress as g

class RepairImpactAnchorTests(unittest.TestCase):
    def setUp(self):
        self.case=g.GreenfieldContextProgressTests("test_long_greenfield_mission_retains_gate_success_and_can_write")
        self.case.setUp()
    def tearDown(self):self.case.tearDown()
    def attempt(self, parent=None):
        if parent:self.case.task["parent_goal"]=parent
        builder=self.case.run_greenfield_worker()
        self.case.task["impact_contract"]=copy.deepcopy(builder["impact_contract"])
        (self.case.root/"artifact.txt").write_text("defective output",encoding="utf-8")
        responses=[g.tool_call("context_sufficiency_check",{"context_status":"sufficient"}),g.tool_call("read_file",{"path":"artifact.txt"}),g.tool_call("edit_file",{"path":"artifact.txt","old":"defective output","new":"approved output"}),{"role":"assistant","content":"Repair complete.","tool_calls":[]}]
        with patch.object(mini,"ask_ollama",side_effect=lambda *a,**k:responses.pop(0)):
            return mini.repair_task(self.case.task,self.case.contract,[{"name":"demonstrated defect","status":"FAIL"}],{},"Repair only the demonstrated artifact content defect.",parent_goal="Ancestor execution summary, not a goal-authority field")
    def test_absent_parent_anchor_is_not_replaced_by_execution_summary(self):
        result=self.attempt()
        self.assertTrue(result["impact_authorized"],result.get("impact_validation"))
        self.assertEqual((self.case.root/"artifact.txt").read_text(),"approved output")
    def test_explicit_parent_anchor_remains_authoritative(self):
        result=self.attempt("Approved parent objective")
        self.assertTrue(result["impact_authorized"],result.get("impact_validation"))
        self.assertEqual((self.case.root/"artifact.txt").read_text(),"approved output")
    def test_real_anchor_drift_is_still_rejected(self):
        builder=self.case.run_greenfield_worker()
        result=mini.stage10_impact.validate_pre_mutation_impact_contract(builder["impact_contract"],parent_goal="Different unauthorized goal")
        self.assertFalse(result["accepted"] if "accepted" in result else result["valid"])
        self.assertTrue(any(e.get("code")=="GOAL_ANCHOR_DRIFT" for e in result["errors"]))
