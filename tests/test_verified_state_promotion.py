import copy
import json
import tempfile
import unittest
from pathlib import Path

import mini
from hivo.integration_gate import (
    PARENT_VERIFIED,
    PASS,
    SKIPPED_NOT_APPLICABLE,
    aggregate_parent_integration,
    assess_integration_readiness,
    create_verified_child_receipt,
)
from hivo.memory import MemoryStore
from hivo.promotion import (
    ALREADY_PROMOTED,
    DURABLE_VERIFIED,
    PROMOTION_CONFLICT,
    PROMOTION_ELIGIBLE,
    PROMOTION_NOT_ELIGIBLE_AUTHORITY,
    PROMOTION_NOT_ELIGIBLE_PARENT_UNVERIFIED,
    PROMOTION_NOT_ELIGIBLE_PROVENANCE,
    PROMOTION_NOT_ELIGIBLE_SCOPE_VIOLATION,
    PROMOTION_NOT_ELIGIBLE_STALE_RECEIPT,
    PROMOTION_NOT_ELIGIBLE_STALE_SUBJECT_STATE,
    PROMOTED,
    STATE_BOUND_VERIFIED,
    assess_promotion_eligibility,
    build_promotion_candidate,
    build_task_brain_completion,
    contains_forbidden_transcript,
    mark_state_bound_fact_stale,
    promote_verified_parent,
    validate_parent_verification_receipt,
    validate_promotion_candidate,
)


class VerifiedStatePromotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hivo_v22_stage5c_")
        self.root = Path(self.temp.name)
        self.files = {
            "src/input.js": "export function readInput() { return 'pause'; }\n",
            "src/pause_controller.js": "export class PauseController { togglePause() {} }\n",
            "src/status_view.js": "export function renderStatus() {}\n",
            "tests/pause_flow.test.js": "test('pause flow', () => true);\n",
        }
        for relative, content in self.files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.contract = {
            "contract_hash": "PARENT-CONTRACT",
            "plan_hash": "PARENT-PLAN",
            "execution_contract_id": "PARENT",
            "project_id": "pause-project",
            "validated_child_plan": [
                {"child_id": "INPUT", "required": True, "execution_contract_id": "EXEC-INPUT", "contract_hash": "CONTRACT-INPUT", "plan_hash": "PARENT-PLAN", "plan_node_ids": ["NODE-INPUT"], "owned_plan_node_ids": ["NODE-INPUT"]},
                {"child_id": "PAUSE", "required": True, "execution_contract_id": "EXEC-PAUSE", "contract_hash": "CONTRACT-PAUSE", "plan_hash": "PARENT-PLAN", "plan_node_ids": ["NODE-PAUSE"], "owned_plan_node_ids": ["NODE-PAUSE"]},
                {"child_id": "STATUS", "required": True, "execution_contract_id": "EXEC-STATUS", "contract_hash": "CONTRACT-STATUS", "plan_hash": "PARENT-PLAN", "plan_node_ids": ["NODE-STATUS"], "owned_plan_node_ids": ["NODE-STATUS"]},
            ],
            "state_ownership": ["PauseController is the designated pause-state owner"],
            "interfaces_to_reuse": ["PauseController.togglePause()"],
            "preservation_constraints": ["movement behavior remains intact"],
            "structured_prohibitions": ["do not create a second pause-state owner"],
            "integration_routes": [
                {"kind": "INTEGRATION_TEST", "required": True, "applicable": True, "target": "tests/pause_flow.test.js", "result": "PENDING"},
                {"kind": "BROWSER", "required": False, "applicable": False, "target": None, "result": SKIPPED_NOT_APPLICABLE},
            ],
        }
        self.parent = {
            "id": "PARENT",
            "goal": "integrate pause responsibilities",
            "integration_routes": copy.deepcopy(self.contract["integration_routes"]),
        }
        self.plan = copy.deepcopy(self.contract["validated_child_plan"])
        self.child_receipts = {}
        self.child_pairs = []
        for child_id, source in (
            ("INPUT", "src/input.js"),
            ("PAUSE", "src/pause_controller.js"),
            ("STATUS", "src/status_view.js"),
        ):
            focused = "tests/pause_flow.test.js"
            execution_contract = {
                "execution_contract_id": f"EXEC-{child_id}",
                "contract_hash": f"CONTRACT-{child_id}",
                "plan_hash": "PARENT-PLAN",
                "allowed_mutation_paths": [source],
                "plan_node_ids": [f"NODE-{child_id}"],
                "owned_plan_node_ids": [f"NODE-{child_id}"],
                "done_when": [f"{child_id} is verified"],
            }
            task = {
                "id": child_id,
                "parent": "PARENT",
                "status": "done",
                "execution_contract_id": f"EXEC-{child_id}",
                "execution_contract_hash": f"CONTRACT-{child_id}",
                "approved_plan_hash": "PARENT-PLAN",
                "execution_contract": execution_contract,
                "plan_node_ids": [f"NODE-{child_id}"],
                "owned_plan_node_ids": [f"NODE-{child_id}"],
                "done_when": [f"{child_id} is verified"],
            }
            routes = [
                {"kind": "FOCUSED_TEST", "required": True, "applicable": True, "target": focused, "result": PASS},
                {"kind": "SYNTAX_STATIC_GATE", "required": True, "applicable": True, "target": source, "result": PASS},
                {"kind": "BROWSER", "required": False, "applicable": False, "target": None, "result": SKIPPED_NOT_APPLICABLE},
            ]
            aggregation = {
                "passed": True,
                "evidence_available": True,
                "failure_codes": [],
                "actual_passes": [copy.deepcopy(routes[0]), copy.deepcopy(routes[1])],
                "actual_failures": [],
                "skipped_not_applicable": [copy.deepcopy(routes[2])],
                "verification_routes": routes,
            }
            result = {
                "status": "done",
                "summary": f"{child_id} verified",
                "gate": {"verification_aggregation": aggregation},
                "builder": {
                    "status": "done",
                    "tool_evidence": [{
                        "tool": "run_command",
                        "target": f"node {focused}",
                        "result": "[exit_code=0] focused test passed",
                    }],
                },
            }
            receipt = create_verified_child_receipt(
                task, result, parent_id="PARENT", parent_contract=self.contract,
                workspace=self.root,
            )
            self.child_pairs.append((task, result))
            self.child_receipts[child_id] = receipt
        self.readiness = assess_integration_readiness(
            self.parent, self.child_pairs, self.child_receipts,
            parent_contract=self.contract, validated_child_plan=self.plan,
            workspace=self.root,
        )
        self.integration = aggregate_parent_integration(
            self.parent, self.contract, self.readiness,
            [{
                "tool": "run_command",
                "target": "node tests/pause_flow.test.js",
                "result": "[exit_code=0] pause integration passed",
            }],
            workspace=self.root,
        )
        self.assertEqual(self.integration["status"], PARENT_VERIFIED)
        self.parent_receipt = self.integration["parent_verification_receipt"]
        self.store = MemoryStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def eligibility(self, **kwargs):
        return assess_promotion_eligibility(
            self.parent, self.parent_receipt, self.contract,
            child_receipts=self.child_receipts, workspace=self.root, **kwargs,
        )

    def candidate(self, contract=None, **kwargs):
        return build_promotion_candidate(
            self.parent, self.parent_receipt, contract or self.contract,
            child_receipts=self.child_receipts, workspace=self.root,
            project_id="pause-project", **kwargs,
        )

    def promote(self, **kwargs):
        return promote_verified_parent(
            self.parent, self.parent_receipt, self.contract,
            child_receipts=self.child_receipts, workspace=self.root,
            project_id="pause-project", store=self.store, task_id="PARENT",
            **kwargs,
        )

    def test_valid_parent_is_eligible_and_candidate_is_zero_model(self):
        gate = self.eligibility()
        self.assertEqual(gate["status"], PROMOTION_ELIGIBLE)
        self.assertEqual(gate["model_calls"], 0)
        candidate = self.candidate()
        checked = validate_promotion_candidate(
            candidate, parent=self.parent, parent_receipt=self.parent_receipt,
            parent_contract=self.contract, child_receipts=self.child_receipts,
            workspace=self.root, project_id="pause-project",
        )
        self.assertTrue(checked["valid"], checked)
        self.assertEqual(checked["model_calls"], 0)
        self.assertTrue(any(
            fact.get("field") == "integration_test_evidence"
            for fact in candidate["verified_tests"]
        ))

    def test_missing_or_unverified_parent_receipt_is_denied(self):
        missing = assess_promotion_eligibility(
            self.parent, None, self.contract, child_receipts=self.child_receipts,
            workspace=self.root,
        )
        self.assertEqual(missing["status"], PROMOTION_NOT_ELIGIBLE_PARENT_UNVERIFIED)
        unverified = copy.deepcopy(self.parent_receipt)
        unverified["verified"] = False
        result = assess_promotion_eligibility(
            self.parent, unverified, self.contract, child_receipts=self.child_receipts,
            workspace=self.root,
        )
        self.assertEqual(result["status"], PROMOTION_NOT_ELIGIBLE_PARENT_UNVERIFIED)

    def test_missing_parent_receipt_creates_no_candidate_or_write(self):
        denied = promote_verified_parent(
            self.parent, None, self.contract, child_receipts=self.child_receipts,
            workspace=self.root, project_id="pause-project", store=self.store,
        )
        self.assertEqual(denied["promotion_status"], PROMOTION_NOT_ELIGIBLE_PARENT_UNVERIFIED)
        self.assertIsNone(denied["candidate"])
        self.assertEqual(self.store.project_brain_snapshot("pause-project")["records"], [])

    def test_parent_result_failure_cannot_be_overridden_by_receipt_string(self):
        denied = promote_verified_parent(
            self.parent, self.parent_receipt, self.contract,
            parent_result={"status": "failed", "integration_result": "INTEGRATION_FAILED"},
            child_receipts=self.child_receipts, workspace=self.root,
            project_id="pause-project", store=self.store,
        )
        self.assertEqual(denied["promotion_status"], PROMOTION_NOT_ELIGIBLE_PARENT_UNVERIFIED)
        self.assertIsNone(denied["candidate"])
        self.assertEqual(self.store.project_brain_snapshot("pause-project")["records"], [])

    def test_tampered_parent_receipt_fails_closed(self):
        tampered = copy.deepcopy(self.parent_receipt)
        tampered["plan_hash"] = "TAMPERED"
        gate = assess_promotion_eligibility(
            self.parent, tampered, self.contract, child_receipts=self.child_receipts,
            workspace=self.root,
        )
        self.assertEqual(gate["status"], PROMOTION_NOT_ELIGIBLE_STALE_RECEIPT)
        self.assertFalse(validate_parent_verification_receipt(
            tampered, parent=self.parent, parent_contract=self.contract,
            child_receipts=self.child_receipts, workspace=self.root,
        )["valid"])

    def test_invalid_child_reference_fails_closed(self):
        receipts = copy.deepcopy(self.child_receipts)
        receipts["INPUT"]["receipt_hash"] = "wrong"
        gate = self.eligibility()
        invalid = assess_promotion_eligibility(
            self.parent, self.parent_receipt, self.contract,
            child_receipts=receipts, workspace=self.root,
        )
        self.assertNotEqual(invalid["status"], PROMOTION_ELIGIBLE)
        self.assertFalse(invalid["eligible"])
        self.assertEqual(gate["status"], PROMOTION_ELIGIBLE)

    def test_stale_subject_state_denies_without_reverification(self):
        (self.root / "tests" / "pause_flow.test.js").write_text(
            "test('pause flow changed', () => false);\n", encoding="utf-8",
        )
        gate = self.eligibility()
        self.assertEqual(gate["status"], PROMOTION_NOT_ELIGIBLE_STALE_SUBJECT_STATE)
        self.assertEqual(gate["model_calls"], 0)
        denied = self.promote()
        self.assertEqual(denied["promotion_status"], PROMOTION_NOT_ELIGIBLE_STALE_SUBJECT_STATE)
        self.assertEqual(self.store.project_brain_snapshot("pause-project")["records"], [])

    def test_stale_authority_and_scope_dnt_violations_deny(self):
        stale = self.eligibility(authority_valid=False)
        self.assertEqual(stale["status"], PROMOTION_NOT_ELIGIBLE_AUTHORITY)
        scoped = self.eligibility(scope_violations=1)
        self.assertEqual(scoped["status"], PROMOTION_NOT_ELIGIBLE_SCOPE_VIOLATION)
        dnt = self.eligibility(dnt_violations=1)
        self.assertEqual(dnt["status"], PROMOTION_NOT_ELIGIBLE_SCOPE_VIOLATION)

    def test_authority_and_prohibitions_are_copied_without_escalation(self):
        candidate = self.candidate()
        self.assertEqual(self.contract["state_ownership"], ["PauseController is the designated pause-state owner"])
        self.assertTrue(all(fact.get("authority") == "USER/REQUIREMENT" for category in (
            "verified_facts", "verified_interfaces", "verified_preservations", "verified_prohibitions"
        ) for fact in candidate[category]))
        self.assertFalse(candidate["provenance"]["authority_escalation"])
        self.assertFalse(candidate["provenance"]["cross_project_memory"])
        self.assertEqual(candidate["verified_prohibitions"][0]["fact"], self.contract["structured_prohibitions"][0])

    def test_candidate_is_bounded_and_excludes_raw_worker_or_model_text(self):
        noisy = copy.deepcopy(self.contract)
        noisy["state_ownership"] = [{
            "fact": "PauseController remains the owner",
            "raw_worker_output": "private reasoning and model output",
        }]
        candidate = self.candidate(noisy)
        encoded = json.dumps(candidate, ensure_ascii=False)
        self.assertNotIn("raw_worker_output", encoded)
        self.assertNotIn("private reasoning", encoded)
        self.assertLessEqual(candidate["fact_count"], 48 * 4)
        bad = copy.deepcopy(candidate)
        bad["raw_worker_output"] = "Worker transcript"
        bad["candidate_hash"] = self._candidate_hash(bad)
        checked = validate_promotion_candidate(
            bad, parent=self.parent, parent_receipt=self.parent_receipt,
            parent_contract=noisy, child_receipts=self.child_receipts,
            workspace=self.root, project_id="pause-project",
        )
        self.assertFalse(checked["valid"])
        self.assertTrue(contains_forbidden_transcript(bad))

    def test_named_mission_compiler_and_decomposer_text_cannot_be_promoted(self):
        candidate = self.candidate()
        bad = copy.deepcopy(candidate)
        bad["mission_compiler_output"] = "MissionCompiler output: use a second state owner"
        bad["candidate_hash"] = self._candidate_hash(bad)
        bad["candidate_id"] = f"candidate-{bad['candidate_hash'][:24]}"
        checked = validate_promotion_candidate(
            bad, parent=self.parent, parent_receipt=self.parent_receipt,
            parent_contract=self.contract, child_receipts=self.child_receipts,
            workspace=self.root, project_id="pause-project",
        )
        self.assertFalse(checked["valid"])
        self.assertTrue(contains_forbidden_transcript(bad))

    @staticmethod
    def _candidate_hash(candidate):
        value = {key: item for key, item in candidate.items() if key not in {"candidate_hash", "candidate_id"}}
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        import hashlib
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def test_integration_provenance_is_retained_without_browser_pass(self):
        candidate = self.candidate()
        integration_facts = [
            fact for fact in candidate["verified_tests"]
            if fact.get("field") == "integration_test_evidence"
        ]
        self.assertEqual(len(integration_facts), 1)
        self.assertEqual(integration_facts[0]["durability_class"], STATE_BOUND_VERIFIED)
        self.assertEqual(integration_facts[0]["path"], "tests/pause_flow.test.js")
        self.assertEqual(integration_facts[0]["result"], PASS)
        self.assertTrue(integration_facts[0].get("evidence_hash"))
        self.assertTrue(any(ref.startswith("integration:") for ref in integration_facts[0]["evidence_refs"]))
        self.assertFalse(any(
            str(fact.get("kind", "")).upper() == "BROWSER"
            for fact in [*candidate["verified_facts"], *candidate["verified_tests"]]
        ))
        browser = next(item for item in self.parent_receipt["integration_route_results"] if item["kind"] == "BROWSER")
        self.assertEqual(browser["result"], SKIPPED_NOT_APPLICABLE)
        self.assertNotEqual(browser["result"], PASS)

    def test_candidate_hash_and_fact_hashes_are_deterministic(self):
        first = self.candidate(artifact_refs=["artifact:pause-flow"])
        second = self.candidate(artifact_refs=["artifact:pause-flow"])
        self.assertEqual(first, second)
        hashes = [
            fact["fact_hash"]
            for category in ("verified_facts", "verified_interfaces", "verified_preservations", "verified_prohibitions", "verified_tests")
            for fact in first[category]
        ]
        self.assertEqual(len(hashes), len(set(hashes)))

    def test_promotion_is_atomic_and_receipt_records_hashes(self):
        result = self.promote(artifact_refs=["artifact:pause-flow"])
        self.assertEqual(result["promotion_status"], PROMOTED)
        receipt = result["promotion_receipt"]
        self.assertEqual(receipt["promotion_status"], PROMOTED)
        self.assertEqual(receipt["eligibility_status"], PROMOTION_ELIGIBLE)
        self.assertEqual(receipt["project_brain_before_hash"], result["project_brain_before_hash"])
        self.assertEqual(receipt["project_brain_after_hash"], result["project_brain_after_hash"])
        self.assertNotEqual(receipt["project_brain_before_hash"], receipt["project_brain_after_hash"])
        self.assertGreater(len(receipt["promoted_record_ids"]), 0)
        self.assertTrue(all(
            record["status"] == "ACTIVE"
            for record in result["project_brain_records"]
        ))
        self.assertEqual(result["model_calls"], 0)

    def test_repeat_promotion_is_idempotent_and_does_not_duplicate_records(self):
        first = self.promote()
        before = self.store.project_brain_hash("pause-project")
        second = self.promote()
        self.assertEqual(first["promotion_status"], PROMOTED)
        self.assertEqual(second["promotion_status"], ALREADY_PROMOTED)
        self.assertTrue(second["no_op"])
        self.assertEqual(before, self.store.project_brain_hash("pause-project"))
        self.assertEqual(len(first["project_brain_records"]), len(second["project_brain_records"]))

    def test_same_semantic_fact_is_superseded_and_explicit_conflict_is_fail_closed(self):
        first = self.promote()
        changed = copy.deepcopy(self.contract)
        changed["state_ownership"] = [{
            "fact": "PauseController remains the designated pause-state owner",
            "conflict_key": "pause-state-owner",
        }]
        # Rebuild the first candidate with an explicit conflict domain so the
        # second candidate is tested against the persisted record.
        base = copy.deepcopy(self.contract)
        base["state_ownership"] = [{
            "fact": base["state_ownership"][0], "conflict_key": "pause-state-owner",
        }]
        self.store = MemoryStore(self.root)
        first_explicit = promote_verified_parent(
            self.parent, self.parent_receipt, base, child_receipts=self.child_receipts,
            workspace=self.root, project_id="explicit-project", store=self.store,
        )
        self.assertEqual(first_explicit["promotion_status"], PROMOTED)
        old_state = next(
            record for record in first_explicit["project_brain_records"]
            if record["fact"].get("field") == "state_ownership"
        )
        changed_candidate = build_promotion_candidate(
            self.parent, self.parent_receipt, changed,
            child_receipts=self.child_receipts, workspace=self.root,
            project_id="explicit-project",
        )
        # Align the changed fact to the same explicitly declared conflict key.
        changed_candidate["verified_facts"] = [
            dict(fact, conflict_key="pause-state-owner")
            if fact.get("field") == "state_ownership" else fact
            for fact in changed_candidate["verified_facts"]
        ]
        for fact in changed_candidate["verified_facts"]:
            if fact.get("field") == "state_ownership":
                fact["semantic_hash"] = self._semantic_hash(fact)
                fact["fact_hash"] = self._fact_hash(fact)
        changed_candidate["fact_count"] = sum(len(changed_candidate[key]) for key in (
            "verified_facts", "verified_interfaces", "verified_preservations", "verified_prohibitions", "verified_tests"
        ))
        changed_candidate["candidate_hash"] = self._candidate_hash(changed_candidate)
        changed_candidate["candidate_id"] = f"candidate-{changed_candidate['candidate_hash'][:24]}"
        checked = validate_promotion_candidate(
            changed_candidate, parent=self.parent, parent_receipt=self.parent_receipt,
            parent_contract=changed, child_receipts=self.child_receipts,
            workspace=self.root, project_id="explicit-project",
        )
        # The changed contract does not carry the old conflict key, so this
        # manual candidate is intentionally validated as a boundary artifact.
        self.assertTrue(checked["valid"], checked)
        conflict = self.store.commit_verified_promotion(changed_candidate)
        self.assertEqual(conflict["promotion_status"], PROMOTION_CONFLICT)
        self.assertEqual(conflict["project_brain_before_hash"], conflict["project_brain_after_hash"])
        approved = copy.deepcopy(changed_candidate)
        approved["authority_change"] = {
            "approved": True, "previous_fact_hash": old_state["fact_hash"],
            "reason": "explicit requirement authority change",
        }
        approved["source"] = dict(approved["source"], authority_change=approved["authority_change"], approved_authority_change=True)
        approved["candidate_hash"] = self._candidate_hash(approved)
        approved["candidate_id"] = f"candidate-{approved['candidate_hash'][:24]}"
        changed_result = self.store.commit_verified_promotion(approved)
        self.assertEqual(changed_result["promotion_status"], PROMOTED)
        self.assertIn(old_state["record_id"], changed_result["superseded_record_ids"])
        new_state = next(
            record for record in changed_result["project_brain_records"]
            if record["fact"].get("field") == "state_ownership"
            and record["status"] == "ACTIVE"
        )
        self.assertIn(old_state["record_id"], new_state["supersedes"])

    @staticmethod
    def _fact_hash(fact):
        value = {key: item for key, item in fact.items() if key != "fact_hash"}
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        import hashlib
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _semantic_hash(fact):
        value = {key: fact.get(key) for key in ("category", "field", "fact", "authority", "conflict_key")}
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        import hashlib
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def test_task_brain_completion_is_a_compact_pointer(self):
        result = self.promote(artifact_refs=["artifact:pause-flow"])
        pointer = result["task_brain_completion"]
        self.assertEqual(pointer["terminal_state"], "VERIFIED_AND_PROMOTED")
        self.assertEqual(pointer["promotion_hash"], result["promotion_receipt"]["promotion_hash"])
        self.assertEqual(pointer["parent_verification_hash"], self.parent_receipt["receipt_hash"])
        self.assertEqual(set(pointer), {
            "schema_version", "task_id", "terminal_state", "parent_verification_hash",
            "promotion_hash", "subject_state_hash", "artifact_refs",
            "project_brain_record_ids", "completion_hash",
        })
        self.assertNotIn("verified_facts", pointer)
        stored = self.store.get_task_brain_completion("pause-project", "PARENT")
        self.assertEqual(stored, pointer)

    def test_failed_promotion_never_claims_verified_and_promoted(self):
        failed = self.promote(authority_valid=False)
        self.assertNotEqual(failed["promotion_status"], PROMOTED)
        self.assertIsNone(failed.get("task_brain_completion"))
        self.assertEqual(self.store.project_brain_snapshot("pause-project")["records"], [])

    def test_state_bound_staleness_is_narrow_and_never_reverifies(self):
        result = self.promote()
        records = self.store.project_brain_snapshot("pause-project", include_inactive=False)["records"]
        state_bound = [record for record in records if record["durability_class"] == STATE_BOUND_VERIFIED]
        self.assertGreater(len(state_bound), 0)
        dependencies = state_bound[0]["fact"].get("dependency_paths", [])
        changed = mark_state_bound_fact_stale(
            self.store, changed_paths=[dependencies[0]] if dependencies else ["src/input.js"],
            project_id="pause-project",
        )
        self.assertGreaterEqual(changed["marked_stale"], 1)
        self.assertEqual(changed["model_calls"], 0)
        active = self.store.project_brain_snapshot("pause-project", include_inactive=False)["records"]
        self.assertLess(len(active), len(records))

    def test_unrelated_path_does_not_stale_narrow_state_fact(self):
        self.promote()
        before = self.store.project_brain_snapshot("pause-project", include_inactive=False)["records"]
        changed = mark_state_bound_fact_stale(
            self.store, changed_paths=["src/unrelated.js"], project_id="pause-project",
        )
        self.assertEqual(changed["marked_stale"], 0)
        after = self.store.project_brain_snapshot("pause-project", include_inactive=False)["records"]
        self.assertEqual(before, after)

    def test_cross_project_memory_is_separate(self):
        candidate = self.candidate()
        first = self.store.commit_verified_promotion(candidate)
        self.assertEqual(first["promotion_status"], PROMOTED)
        other = copy.deepcopy(candidate)
        other["project_id"] = "other-project"
        other["candidate_hash"] = self._candidate_hash(other)
        other["candidate_id"] = f"candidate-{other['candidate_hash'][:24]}"
        second = self.store.commit_verified_promotion(other)
        self.assertEqual(second["promotion_status"], PROMOTED)
        self.assertTrue(self.store.project_brain_snapshot("pause-project")["records"])
        self.assertTrue(self.store.project_brain_snapshot("other-project")["records"])
        self.assertNotEqual(
            self.store.project_brain_snapshot("pause-project")["records"][0]["project_id"],
            self.store.project_brain_snapshot("other-project")["records"][0]["project_id"],
        )

    def test_task_pointer_builder_is_deterministic(self):
        first = build_task_brain_completion(
            task_id="PARENT", parent_verification_hash="parent", promotion_hash="promotion",
            subject_state_hash="subject", artifact_refs=["a"], project_brain_record_ids=["r"],
        )
        second = build_task_brain_completion(
            task_id="PARENT", parent_verification_hash="parent", promotion_hash="promotion",
            subject_state_hash="subject", artifact_refs=["a"], project_brain_record_ids=["r"],
        )
        self.assertEqual(first, second)
        self.assertEqual(first["terminal_state"], "VERIFIED_AND_PROMOTED")

    def test_mini_runtime_hook_promotes_only_after_parent_verified(self):
        saved = {
            "WORKSPACE": mini.WORKSPACE,
            "RUN": mini.RUN,
            "TASKS": mini.TASKS,
            "RUN_ID": mini.RUN_ID,
            "MEMORY_STORE": mini.MEMORY_STORE,
        }
        try:
            mini.WORKSPACE = self.root
            mini.MEMORY_STORE = None
            mini.reset_run("recursive")
            mini.RUN["stage5c_enabled"] = True
            mini.RUN["child_receipts"] = copy.deepcopy(self.child_receipts)
            mini.RUN["source_contract"] = copy.deepcopy(self.contract)
            result = mini._stage5c_promote_parent(
                {"id": "PARENT", "goal": self.parent["goal"]},
                self.contract,
                copy.deepcopy(self.integration),
                {},
                self.root,
            )
            self.assertEqual(result["promotion_status"], PROMOTED)
            self.assertEqual(mini.RUN["promotion_model_calls"], 0)
            self.assertEqual(mini.RUN["task_brain_compaction_model_calls"], 0)
            self.assertEqual(mini.RUN["project_brain_promotions"], 1)
            self.assertEqual(result["task_brain_completion"]["terminal_state"], "VERIFIED_AND_PROMOTED")
        finally:
            mini.WORKSPACE = saved["WORKSPACE"]
            mini.RUN = saved["RUN"]
            mini.TASKS = saved["TASKS"]
            mini.RUN_ID = saved["RUN_ID"]
            mini.MEMORY_STORE = saved["MEMORY_STORE"]


if __name__ == "__main__":
    unittest.main()
