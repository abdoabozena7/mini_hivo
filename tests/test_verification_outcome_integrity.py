"""Offline fixtures reduced from Run-010's failed game-verification evidence."""
import copy
import json
import unittest
from unittest.mock import patch

import mini
from hivo import evidence
from hivo import verification_routing as routing
import test_greenfield_context_progress as greenfield


def browser_result(passed=False, kind="game", long=False):
    return {"resolved_entrypoint": "index.html", "passed": passed,
            "environment_error": False, "text": "Score: 0 " * (400 if long else 1),
            "verification_profile": {"kind": kind, "require_game_bridge": kind == "game",
                                     "required_interactions": ["keyboard_movement", "collection_updates_state"] if kind == "game" else []},
            "failures": [] if passed else [{"code": "missing_game_bridge", "evidence": "window.AGENT_GAME verification bridge is unavailable"}],
            "verification_status": "PASS" if passed else "FAIL"}


def artifact():
    return {"child_id": "1", "verification_routes": [
        {"kind": routing.BROWSER, "required": True, "applicable": True,
         "target": "index.html", "result": "PENDING", "reason_codes": [], "evidence_refs": []}]}


def item(result, tool="verify_web_app", target="index.html"):
    return {"tool": tool, "target": target, "result": result}


class VerificationOutcomeIntegrityTests(unittest.TestCase):
    def test_run010_clipped_failed_json_is_never_a_pass(self):
        clipped = json.dumps(browser_result(long=True))[:1600]
        with self.assertRaises(ValueError): json.loads(clipped)
        self.assertNotEqual(routing._parse_result(clipped), (routing.PASS, True))
        result = routing.aggregate_verification_evidence(artifact(), [item(clipped)], browser_result())
        self.assertFalse(result["passed"])
        self.assertEqual(result["verification_routes"][0]["result"], routing.FAIL)

    def test_malformed_structured_and_statusless_objects_fail_closed(self):
        values = ['{"passed": false', '{"passed": true', '{"status": "PASS"',
                  '[{"passed": true}]', '"passed": false', '```json\n{"passed":true}',
                  {"message": "passed"}, {"passed": None}, {"passed": "true"}]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(routing._parse_result(value), (None, False))

    def test_explicit_structured_failure_dominates_success_text_or_status(self):
        for value in ({"passed": False, "status": "PASS"},
                      {"passed": True, "verification_status": "FAIL"},
                      {"passed": False, "message": "previous test passed"}):
            with self.subTest(value=value):
                self.assertEqual(routing._parse_result(value), (routing.FAIL, True))

    def test_unknown_explicit_status_cannot_be_promoted_by_pass_boolean(self):
        for value in (
            {"status": "ERROR", "passed": True},
            {"verification_status": "BLOCKED", "passed": True},
            {"result": "WARN", "passed": True},
            '{"status": "ERROR", "passed": true}',
            {"verification_status": "PASS", "status": "ERROR", "passed": True},
        ):
            with self.subTest(value=value):
                self.assertEqual(routing._parse_result(value), (None, False))
        self.assertEqual(routing._parse_result({"status": "ERROR", "passed": False}),
                         (routing.FAIL, True))
        self.assertEqual(routing._parse_result({"verification_status": "PASS", "status": "FAIL"}),
                         (routing.FAIL, True))
        invalid = {"status": "ERROR", "passed": True}
        aggregate = routing.aggregate_verification_evidence(
            artifact(), [item(json.dumps(invalid))], invalid
        )
        self.assertFalse(aggregate["passed"])

    def test_valid_success_and_legacy_exit_receipts_remain_supported(self):
        for value in ({"passed": True}, json.dumps({"passed": True}), {"status": "PASS"}, "[exit_code=0]\nAll checks passed"):
            with self.subTest(value=value):self.assertEqual(routing._parse_result(value), (routing.PASS, True))
        self.assertEqual(routing._parse_result("[exit_code=2]\nfailed"), (routing.FAIL, True))

    def test_missing_required_evidence_cannot_satisfy_route(self):
        for values in ([], [item('{"passed": true')], [item(json.dumps({"message": "passed"}))]):
            with self.subTest(values=values):
                self.assertFalse(routing.aggregate_verification_evidence(artifact(), values)["passed"])

    def test_other_target_pass_cannot_satisfy_required_route(self):
        result=routing.aggregate_verification_evidence(artifact(), [item(json.dumps(browser_result(True)), target="other.html")])
        self.assertFalse(result["passed"])

    def test_explicit_current_game_failure_dominates_weaker_web_pass(self):
        for tool in ("run_file", "verify_web_app"):
            with self.subTest(tool=tool):
                result=routing.aggregate_verification_evidence(artifact(), [item(json.dumps(browser_result(True, "web")), tool=tool)], browser_result())
                self.assertFalse(result["passed"])
                self.assertEqual(result["verification_routes"][0]["result"], routing.FAIL)

    def test_current_failed_browser_beats_old_pass_for_same_target(self):
        result=routing.aggregate_verification_evidence(artifact(), [item(json.dumps(browser_result(True)))], browser_result())
        self.assertFalse(result["passed"])

    def test_fresh_successful_scope_after_repair_is_not_poisoned_by_previous_scope(self):
        previous=routing.aggregate_verification_evidence(artifact(), [item(json.dumps(browser_result()))], browser_result())
        self.assertFalse(previous["passed"])
        # execute_leaf intentionally supplies only the fresh Repairer evidence.
        current=routing.aggregate_verification_evidence(artifact(), [item(json.dumps(browser_result(True)))], browser_result(True))
        self.assertTrue(current["passed"])
        self.assertTrue(previous["actual_failures"])

    def test_optional_skip_does_not_become_success(self):
        self.assertEqual(routing._parse_result({"verification_status":routing.SKIPPED_NOT_APPLICABLE}), (None,False))


    def test_cached_route_pass_without_execution_evidence_is_not_proof(self):
        routes=artifact();routes["verification_routes"][0]["result"]="PASS"
        self.assertFalse(routing.aggregate_verification_evidence(routes,[])["passed"])

    def test_fresh_same_role_same_profile_pass_supersedes_old_failure(self):
        old=item(json.dumps(browser_result()));old["role"]="Repairer"
        fresh=item(json.dumps(browser_result(True)));fresh["role"]="Repairer"
        current=routing.aggregate_verification_evidence(artifact(),[old,fresh],browser_result(True))
        self.assertTrue(current["passed"])

    def test_weaker_profile_or_other_role_cannot_clear_outstanding_failure(self):
        for role,kind in (("Repairer","web"),("Falsifier","game")):
            with self.subTest(role=role,kind=kind):
                old=item(json.dumps(browser_result()));old["role"]="Repairer"
                fresh=item(json.dumps(browser_result(True,kind)));fresh["role"]=role
                self.assertFalse(routing.aggregate_verification_evidence(artifact(),[old,fresh],browser_result(True))["passed"])

    def test_incomplete_same_role_receipt_cannot_displace_failure(self):
        failed=item(json.dumps(browser_result()));failed["role"]="Falsifier"
        profile=browser_result()["verification_profile"]
        unavailable=[{"passed":None,"verification_profile":profile},
                     {"verification_status":"NOT_RUN","verification_profile":profile},
                     {"verification_status":"PENDING","verification_profile":profile},
                     {"verification_profile":profile},
                     '{"passed": true, "verification_profile":']
        for payload in unavailable:
            with self.subTest(payload=payload):
                fresh=item(json.dumps(payload) if isinstance(payload,dict) else payload)
                fresh["role"]="Falsifier"
                result=routing.aggregate_verification_evidence(artifact(),[failed,fresh],browser_result(True))
                self.assertFalse(result["passed"])
                self.assertEqual(result["verification_routes"][0]["result"],routing.FAIL)

    def test_valid_repair_pass_can_follow_unavailable_receipt(self):
        receipts=[]
        for payload in (browser_result(),
                        {"passed":None,"verification_profile":browser_result()["verification_profile"]},
                        browser_result(True)):
            receipt=item(json.dumps(payload));receipt["role"]="Repairer";receipts.append(receipt)
        result=routing.aggregate_verification_evidence(artifact(),receipts,browser_result(True))
        self.assertTrue(result["passed"])
        # Chronological receipt order matters: a subsequent failure remains live.
        result=routing.aggregate_verification_evidence(artifact(),[receipts[2],receipts[0]],browser_result(True))
        self.assertFalse(result["passed"])

    def test_unavailable_receipts_alone_cannot_manufacture_pass(self):
        for payload in ({"passed":None,"verification_profile":browser_result()["verification_profile"]},
                        {"verification_status":"NOT_RUN"},'{"passed":true'):
            with self.subTest(payload=payload):
                receipt=item(json.dumps(payload) if isinstance(payload,dict) else payload)
                receipt["role"]="Falsifier"
                self.assertFalse(routing.aggregate_verification_evidence(artifact(),[receipt])["passed"])

    def test_new_pass_for_other_target_cannot_displace_failure(self):
        failed=item(json.dumps(browser_result()));failed["role"]="Repairer"
        fresh=item(json.dumps(browser_result(True)),target="other.html");fresh["role"]="Repairer"
        self.assertFalse(routing.aggregate_verification_evidence(artifact(),[failed,fresh],browser_result(True))["passed"])

    def test_falsifier_failure_is_not_cleared_by_current_controller_pass(self):
        failed=item(json.dumps(browser_result()));failed["role"]="Falsifier"
        fresh=item(json.dumps(browser_result(True)));fresh["role"]="Builder"
        self.assertFalse(routing.aggregate_verification_evidence(artifact(),[failed,fresh],browser_result(True))["passed"])


class EvidenceProjectionTests(unittest.TestCase):
    def project(self, result, tool="verify_web_app"):
        projected=evidence.project_tool_evidence_result(tool, result)
        self.assertLessEqual(len(projected),1600)
        return json.loads(projected)

    def test_long_failed_json_remains_valid_bounded_failure(self):
        result=self.project(json.dumps(browser_result(long=True)))
        self.assertIs(result["passed"],False)
        self.assertEqual(result["failures"][0]["code"],"missing_game_bridge")
        self.assertEqual(result["verification_profile"]["kind"],"game")
        self.assertEqual(result["resolved_entrypoint"],"index.html")
        self.assertEqual(routing._parse_result(result),(routing.FAIL,True))

    def test_long_success_keeps_profile_and_valid_pass(self):
        result=self.project(json.dumps(browser_result(True,long=True)))
        self.assertIs(result["passed"],True)
        self.assertEqual(result["verification_profile"]["kind"],"game")
        self.assertEqual(routing._parse_result(result),(routing.PASS,True))

    def test_failed_interaction_details_survive_projection(self):
        raw=browser_result(long=True)
        raw["interaction_checks"]=[{"name":"keyboard_movement","passed":False,"before_x":1,"after_x":1}]
        result=self.project(json.dumps(raw))
        self.assertFalse(result["interaction_checks"][0]["passed"])

    def test_unrepresentable_proof_is_unavailable_not_a_truncated_pass(self):
        raw=browser_result(True,long=True)
        raw["verification_profile"]["required_interactions"]=["required_"+str(i)*60 for i in range(100)]
        result=self.project(json.dumps(raw))
        self.assertNotEqual(routing._parse_result(result),(routing.PASS,True))
        self.assertIn("evidence_error",result)

    def test_receipt_identity_is_not_truncated_or_invented(self):
        raw=browser_result(True,long=True)
        raw.update(authority_id="TEST-1",oracle_id="ORACLE-1",oracle_hash="a"*64,receipt_channel="direct_oracle",receipt_identity="receipt-1")
        result=self.project(json.dumps(raw))
        for key in ("authority_id","oracle_id","oracle_hash","receipt_channel","receipt_identity"):
            self.assertEqual(result[key],raw[key])

    def test_long_command_receipts_keep_exit_status_without_keyword_promotion(self):
        for code in (0,2):
            result=self.project("[exit_code="+str(code)+"]\n"+"diagnostic "*500,tool="run_command")
            self.assertEqual(routing._parse_result(result),(routing.PASS if code==0 else routing.FAIL,True))
        result=self.project("passed "*500,tool="run_command")
        self.assertNotEqual(routing._parse_result(result),(routing.PASS,True))
        result=self.project("[exit_code=0]\n"+"diagnostic "*500+"SyntaxError",tool="run_command")
        self.assertEqual(routing._parse_result(result),(routing.FAIL,True))

    def test_malformed_structured_input_cannot_gain_authority_in_projection(self):
        result=self.project('{"passed":true,'+'"text":"'+'passed '*500)
        self.assertNotEqual(routing._parse_result(result),(routing.PASS,True))

    def test_nonverification_tool_projection_remains_display_only(self):
        raw="source "*500
        self.assertEqual(evidence.project_tool_evidence_result("read_file",raw),raw[:1600])


class WorkerEvidenceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=greenfield.GreenfieldContextProgressTests("test_long_greenfield_mission_retains_gate_success_and_can_write")
        self.fixture.setUp()
    def tearDown(self):self.fixture.tearDown()

    def test_real_worker_producer_stores_valid_failed_verification_json(self):
        responses=[greenfield.tool_call("verify_web_app",{"path":"index.html"}),
                   {"role":"assistant","content":"Worker stopped; verification failed.","tool_calls":[]}]
        raw=json.dumps(browser_result(long=True))
        with patch.object(mini,"ask_ollama",side_effect=responses),patch.object(mini,"run_tool",return_value=raw):
            result=mini.execute_agent_task("Check the browser artifact",{},role="Builder",task_id="1",max_steps=2)
        saved=result["tool_evidence"][0]["result"]
        self.assertLessEqual(len(saved),1600)
        self.assertFalse(json.loads(saved)["passed"])
        self.assertFalse(mini.evidence_gate(result,browser_result=browser_result())["passed"])

    def test_failed_quality_gate_does_not_commit_provisional_file(self):
        builder=self.fixture.run_greenfield_worker()
        gate=mini.evidence_gate(builder,browser_result=browser_result())
        self.assertFalse(gate["passed"])
        self.assertTrue(any(x["name"]=="browser_contract" for x in gate["deterministic_failures"]))
        # The normal execute_leaf branch commits only when this gate passes.
        self.assertIsNotNone(mini.ACTIVE_TRANSACTION)
        self.assertIsNone(mini.LAST_COMMITTED_TRANSACTION)

    def run_actual_repair_and_commit(self, explicit_target):
        if explicit_target:
            # Controller-declared expected file, not a fabricated accepted contract.
            self.fixture.contract["expected_targets"]=[{"target":"artifact.txt","path":"artifact.txt"}]
        builder=self.fixture.run_greenfield_worker()
        self.fixture.task["impact_contract"]=copy.deepcopy(builder["impact_contract"])
        path=self.fixture.root/"artifact.txt"
        path.write_text("defective output",encoding="utf-8")
        builder["tool_evidence"].append(item('{"passed":false}',tool="run_command",target="verify artifact.txt"))
        self.assertFalse(mini.evidence_gate(builder)["passed"])
        responses=[greenfield.tool_call("context_sufficiency_check",{"context_status":"sufficient"}),
                   greenfield.tool_call("read_file",{"path":"artifact.txt"}),
                   greenfield.tool_call("edit_file",{"path":"artifact.txt","old":"defective output","new":"approved output"}),
                   greenfield.tool_call("run_command",{"command":"verify artifact.txt"}),
                   {"role":"assistant","content":"Repair verified.","tool_calls":[]}]
        real_tool=mini.run_tool
        def tools(name,args,role="Builder"):
            if name=="run_command":
                return "[exit_code=0]" if path.read_text()=="approved output" else "[exit_code=1]"
            return real_tool(name,args,role=role)
        with patch.object(mini,"ask_ollama",side_effect=responses),patch.object(mini,"run_tool",side_effect=tools):
            repaired=mini.repair_task(self.fixture.task,self.fixture.contract,[],{},"Restore the required artifact contents.")
        self.assertTrue(repaired["impact_authorized"])
        self.assertEqual(path.read_text(),"approved output")
        # Mirror execute_leaf's fresh-only post-repair gate; do not merge old failures.
        gate=mini.evidence_gate(repaired)
        self.assertTrue(gate["passed"],gate)
        committed=mini._commit_verified_leaf(self.fixture.task,self.fixture.contract,repaired,None,None,gate,{})
        self.assertFalse(mini.evidence_gate(builder)["passed"])
        return committed

    def test_actual_repair_then_fresh_verification_can_commit_without_stale_failure(self):
        committed=self.run_actual_repair_and_commit(explicit_target=True)
        self.assertEqual(committed["status"],"done",committed)
        self.assertIsNone(mini.ACTIVE_TRANSACTION)
        self.assertIsNotNone(mini.LAST_COMMITTED_TRANSACTION)

    def test_fresh_verification_does_not_bypass_unmet_impact_targets(self):
        committed=self.run_actual_repair_and_commit(explicit_target=False)
        self.assertEqual(committed["status"],"failed")
        self.assertEqual(committed["failure_type"],"IMPACT_CONTRACT_VERIFICATION_FAILED")
        self.assertTrue(committed["impact_comparison"]["missing"])
        self.assertIsNone(mini.LAST_COMMITTED_TRANSACTION)
