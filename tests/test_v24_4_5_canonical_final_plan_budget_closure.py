import copy
import json
import tempfile
import unittest

import mini
from hivo import execution_contracts as execution
from hivo import impact_planning as impact
from hivo import verified_planning
from tests import test_v24_4_2_current_surface_preservation_binding as current_surface_fixture


class CanonicalFinalPlanBudgetClosureTests(unittest.TestCase):
    """Provider-free V24.4.5 approval-plan compaction and contract tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        current_surface_fixture.CurrentSurfacePreservationBindingTests.setUpClass()
        source = current_surface_fixture.CurrentSurfacePreservationBindingTests
        cls.source = source
        cls.requirements = copy.deepcopy(source.requirements)
        cls.evidence = copy.deepcopy(source.context["current_repository_evidence"])
        cls.registry = copy.deepcopy(source.registry)
        cls.seeds = copy.deepcopy(source.seeds)
        cls.frame = copy.deepcopy(source.frame)
        cls.brain = copy.deepcopy(source.stage3_brain)
        cls.verified_context = copy.deepcopy(source.context)
        cls.ledger = impact.build_requirement_obligation_ledger(cls.requirements)

        cls.cases = {}
        for label, rationale, reason_code in (
            ("minimal", "Use the verified surface.", "V2445_MIN"),
            ("representative", "Use the bounded production-path choice.", "V2442_TEST"),
            ("maximum", "R" * 360, "Q" * 120),
        ):
            cls.cases[label] = cls._build_case(rationale, reason_code)

        cls.expanded_plan = cls.cases["representative"]["expanded_plan"]
        cls.canonical_plan = cls.cases["representative"]["canonical_plan"]
        cls.max_plan = cls.cases["maximum"]["canonical_plan"]
        cls.canonical_gate = cls.cases["representative"]["gate"]

        # Exercise the actual V24 entrypoint with provider-free structured
        # callbacks.  The temporary workspace keeps its run bookkeeping away
        # from the exact read-only subject and Brain.
        previous_workspace = mini.WORKSPACE
        previous_memory_store = mini.MEMORY_STORE
        try:
            with tempfile.TemporaryDirectory() as workspace:
                def planner(*_args):
                    return source._choices(
                        decision_by_role={"RENDER_SURFACE": "MUST_CHANGE"},
                    )

                cls.integration_result, cls.integration_memory = (
                    mini.run_verified_state_aware_planning(
                        fresh_task_brain=source.fresh,
                        memory={},
                        workspace=workspace,
                        expected_project_id=source.PROJECT_ID,
                        impact_planner_structured_call=planner,
                        impact_challenger_structured_call=lambda *_args: {"challenges": []},
                        finish=False,
                    )
                )
                cls.integration_metrics = copy.deepcopy(
                    mini.RUN.get("final_plan_canonicalization_metrics", {})
                )
                cls.integration_run = copy.deepcopy(mini.RUN)
        finally:
            mini.WORKSPACE = previous_workspace
            mini.MEMORY_STORE = previous_memory_store

    @classmethod
    def _build_case(cls, rationale, reason_code):
        source = cls.source
        choices = source._choices(
            decision_by_role={"RENDER_SURFACE": "MUST_CHANGE"},
        )
        for choice in choices["decisions"]:
            choice["bounded_rationale"] = rationale
            choice["reason_code"] = reason_code
        choice_check = impact.validate_impact_decision_choices(choices, cls.frame)
        if not choice_check.get("valid"):
            raise AssertionError(choice_check)
        compiled = impact.compile_impact_map_from_choices(
            cls.frame,
            choices,
            cls.requirements,
            cls.evidence,
            surface_registry=cls.registry,
            impact_seeds=cls.seeds,
            task_goal=cls.requirements[0]["text"],
        )
        if not compiled.get("valid"):
            raise AssertionError(compiled)
        impact_map = copy.deepcopy(compiled["impact_map"])
        challenges = impact.deterministic_challenges(
            impact_map,
            cls.requirements,
            cls.evidence,
            surface_registry=cls.registry,
        )
        challenge_validation = impact.validate_challenges(
            challenges,
            impact_map,
            cls.requirements,
            cls.evidence,
            surface_registry=cls.registry,
        )
        reconciled, resolved, unresolved = impact.reconcile_impact_map(
            impact_map,
            challenge_validation["validated"],
            cls.requirements,
            cls.evidence,
            surface_registry=cls.registry,
            impact_seeds=cls.seeds,
            obligation_ledger=cls.ledger,
            task_goal=cls.requirements[0]["text"],
            task_brain=cls.brain,
            obligation_aware=True,
        )
        expanded = impact.build_minimal_change_plan(
            reconciled,
            cls.requirements,
            cls.evidence,
            resolved_challenges=resolved,
            unresolved_challenges=unresolved,
            project_mode=impact.EXISTING_PROJECT,
            surface_registry=cls.registry,
            obligation_ledger=cls.ledger,
            task_goal=cls.requirements[0]["text"],
            obligation_aware=True,
        )
        lifecycle, final_resolved, final_unresolved = (
            impact.re_evaluate_challenge_lifecycle(
                challenge_validation["validated"],
                expanded,
                cls.requirements,
                cls.evidence,
                surface_registry=cls.registry,
                obligation_ledger=cls.ledger,
                impact_map=reconciled,
                closure_actions=reconciled.get(
                    "behavior_anchor_closure_actions", [],
                ),
            )
        )
        expanded["resolved_challenges"] = [
            impact.compact_challenge_record(item)
            for item in final_resolved[:impact.MAX_CHALLENGES]
        ]
        expanded["unresolved_challenges"] = [
            impact.compact_challenge_record(item)
            for item in final_unresolved[:impact.MAX_CHALLENGES]
        ]
        expanded = verified_planning.attach_plan_binding(
            expanded, cls.verified_context,
        )
        expanded = impact.finalize_plan_identity(expanded)
        canonical = impact.canonicalize_final_plan(
            expanded,
            impact_map=reconciled,
            requirements=cls.requirements,
            evidence=cls.evidence,
            surface_registry=cls.registry,
            source_impact_map=impact_map,
        )
        canonical = impact._fit_plan_to_serialized_bound(canonical)
        canonical = impact.finalize_plan_identity(canonical)
        gate = impact.validate_change_plan(
            canonical,
            cls.requirements,
            cls.evidence,
            impact.EXISTING_PROJECT,
            surface_registry=cls.registry,
            obligation_ledger=cls.ledger,
            authoritative_task_goal=cls.requirements[0]["text"],
            obligation_aware=True,
        )
        return {
            "choices": choices,
            "choice_check": choice_check,
            "impact_map": impact_map,
            "compiled": compiled,
            "challenge_validation": challenge_validation,
            "reconciled": reconciled,
            "expanded_plan": expanded,
            "canonical_plan": canonical,
            "gate": gate,
            "lifecycle": lifecycle,
        }

    @staticmethod
    def _serialized(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    @classmethod
    def _canonical_constraints(cls):
        return cls.canonical_plan["canonical_constraints"]

    @classmethod
    def _all_canonical_constraint_records(cls):
        constraints = cls._canonical_constraints()
        return [
            record
            for field in ("preservation", "prohibitions")
            for record in constraints.get(field, [])
            if isinstance(record, dict)
        ]

    @classmethod
    def _canonical_verification_texts(cls):
        return {
            text
            for record in cls.canonical_plan.get(
                "canonical_verification_contracts", [],
            )
            for text in record.get("contract", [])
        }

    def test_01_expanded_exact_semantic_plan_exceeds_frozen_bound(self):
        self.assertEqual(len(self.expanded_plan["approved_change_nodes"]), 7)
        self.assertGreater(
            impact._json_size(self.expanded_plan), impact.MAX_PLAN_CHARS,
        )

    def test_02_all_model_text_cases_are_valid_and_bounded(self):
        for label, case in self.cases.items():
            self.assertTrue(case["choice_check"]["valid"], label)
            self.assertTrue(case["compiled"]["valid"], label)
            self.assertLessEqual(
                impact._json_size(case["canonical_plan"]), impact.MAX_PLAN_CHARS,
                label,
            )
            self.assertTrue(case["gate"]["valid"], case["gate"])
        self.assertEqual(
            impact._json_size(self.cases["minimal"]["canonical_plan"]),
            impact._json_size(self.cases["maximum"]["canonical_plan"]),
        )

    def test_03_canonical_representation_has_meaningful_headroom(self):
        size = impact._json_size(self.canonical_plan)
        self.assertEqual(
            self.canonical_plan["representation"],
            impact.CANONICAL_FINAL_PLAN_REPRESENTATION,
        )
        self.assertEqual(
            self.canonical_plan["version"], impact.CANONICAL_FINAL_PLAN_VERSION,
        )
        self.assertGreaterEqual(impact.MAX_PLAN_CHARS - size, 100)

    def test_04_four_atomic_obligations_remain_covered(self):
        result = self.canonical_gate
        self.assertEqual(result["requirement_obligations_created"], 4)
        self.assertEqual(result["behavior_obligations"], 1)
        self.assertEqual(result["behavior_obligations_covered"], 1)
        self.assertEqual(result["behavior_obligations_uncovered"], 0)
        self.assertEqual(result["semantic_requirements_covered"], 1)
        coverage = self.canonical_plan["coverage"][0]
        self.assertEqual(coverage["semantic_state"], "COVERED")
        self.assertEqual(len(coverage["obligation_ids"]), 4)

    def test_05_mutation_surface_is_unchanged_and_controller_is_not_targeted(self):
        old_targets = {
            path
            for node in self.expanded_plan["approved_change_nodes"]
            for path in node.get("candidate_targets", [])
        }
        new_targets = {
            path
            for node in self.canonical_plan["approved_change_nodes"]
            for path in node.get("candidate_targets", [])
        }
        self.assertEqual(old_targets, new_targets)
        self.assertEqual(new_targets, {"src/status_view.js"})
        self.assertEqual(self.canonical_plan["mutation_surface_ids"], ["SURF-003"])
        self.assertNotIn("src/pause_controller.js", new_targets)

    def test_06_dnt_and_ownership_constraints_are_shared_once(self):
        records = self._all_canonical_constraint_records()
        dnt = [
            item for item in records
            if item.get("text") == "Do not modify src/pause_controller.js."
        ]
        self.assertEqual(len(dnt), 1)
        ownership = [
            item for item in records
            if "PauseController remains the sole pause-state owner." in item.get("text", "")
        ]
        self.assertEqual(len(ownership), 1)
        self.assertTrue(all(
            "preservation_constraints" not in node
            and "local_preservation_constraints" not in node
            and "prohibition_constraints" not in node
            for node in self.canonical_plan["approved_change_nodes"]
        ))
        self.assertTrue(all(
            node.get("constraint_ids")
            for node in self.canonical_plan["approved_change_nodes"]
        ))

    def test_07_repeated_preservation_semantics_fan_in_without_fake_work(self):
        obligations = {
            item["obligation_id"]
            for item in self.canonical_plan["requirement_obligation_ledger"]["requirements"][0]["obligations"]
            if item["obligation_type"] == "PRESERVATION"
        }
        referenced = {
            item
            for node in self.canonical_plan["approved_change_nodes"]
            for item in node.get("obligation_ids", [])
        }
        self.assertTrue(obligations.issubset(referenced))
        self.assertFalse(any(
            node.get("responsibility_class") == "PRESERVATION_ONLY"
            and node.get("mutation_required")
            for node in self.canonical_plan["approved_change_nodes"]
        ))

    def test_08_verification_contracts_fan_in_without_semantic_loss(self):
        old_texts = {
            text
            for node in self.expanded_plan["approved_change_nodes"]
            for field in ("local_test_contract", "test_contract")
            for text in node.get(field, []) or []
        }
        self.assertEqual(old_texts, self._canonical_verification_texts())
        self.assertEqual(
            len(self.canonical_plan["canonical_verification_contracts"]),
            len(self._canonical_verification_texts()),
        )
        valid_ids = {
            item["verification_id"]
            for item in self.canonical_plan["canonical_verification_contracts"]
        }
        self.assertTrue(all(
            set(node.get("verification_ids", [])) <= valid_ids
            for node in self.canonical_plan["approved_change_nodes"]
        ))

    def test_09_evidence_only_impacts_are_not_fake_mutations(self):
        evidence_node = next(
            node for node in self.canonical_plan["approved_change_nodes"]
            if node.get("responsibility_class") == "EVIDENCE_ONLY"
        )
        self.assertFalse(evidence_node["mutation_required"])
        self.assertEqual(evidence_node["target_surface_ids"], [])
        self.assertTrue(evidence_node["inspect_surface_ids"])
        self.assertTrue(all(
            path.startswith("tests/")
            for path in evidence_node["inspect_targets"]
        ))

    def test_10_relative_paths_are_canonical_and_deterministic(self):
        paths = [
            path
            for node in self.canonical_plan["approved_change_nodes"]
            for field in ("candidate_targets", "inspect_targets")
            for path in node.get(field, [])
        ]
        self.assertTrue(paths)
        self.assertTrue(all(
            not path.startswith(("/", "\\"))
            and not (len(path) > 1 and path[1] == ":")
            for path in paths
        ))
        again = impact.canonicalize_final_plan(
            self.expanded_plan,
            impact_map=self.cases["representative"]["reconciled"],
            requirements=self.requirements,
            evidence=self.evidence,
            surface_registry=self.registry,
            source_impact_map=self.cases["representative"]["impact_map"],
        )
        self.assertEqual(self.canonical_plan, again)

    def test_11_plan_hash_is_deterministic_and_binds_semantic_changes(self):
        self.assertEqual(
            self.canonical_plan["plan_hash"],
            impact.plan_content_hash(self.canonical_plan),
        )
        same = impact.finalize_plan_identity(copy.deepcopy(self.canonical_plan))
        self.assertEqual(same["plan_hash"], self.canonical_plan["plan_hash"])

        changed_target = copy.deepcopy(self.canonical_plan)
        changed_target["approved_change_nodes"][1]["candidate_targets"] = [
            "src/other_view.js",
        ]
        self.assertNotEqual(
            impact.finalize_plan_identity(changed_target)["plan_hash"],
            self.canonical_plan["plan_hash"],
        )

        changed_dnt = copy.deepcopy(self.canonical_plan)
        changed_dnt["canonical_constraints"]["prohibitions"][0]["text"] += " Keep it unchanged."
        self.assertNotEqual(
            impact.finalize_plan_identity(changed_dnt)["plan_hash"],
            self.canonical_plan["plan_hash"],
        )

        changed_requirement = copy.deepcopy(self.canonical_plan)
        changed_requirement["requirements"][0]["text"] += " Keep the indicator bounded."
        self.assertNotEqual(
            impact.finalize_plan_identity(changed_requirement)["plan_hash"],
            self.canonical_plan["plan_hash"],
        )

    def test_12_upstream_frame_choice_map_and_reconciliation_bindings_remain(self):
        upstream = self.canonical_plan["upstream_bindings"]
        for key in (
            "planning_context_hash", "impact_decision_frame_hash",
            "impact_decision_choice_hash", "impact_map_hash",
            "challenge_reconciliation_hash", "requirements_hash",
        ):
            self.assertTrue(upstream.get(key), key)
        self.assertEqual(
            upstream["impact_decision_frame_hash"],
            self.cases["representative"]["impact_map"]["impact_decision_frame_hash"],
        )
        self.assertEqual(
            upstream["impact_decision_choice_hash"],
            self.cases["representative"]["impact_map"]["impact_decision_choice_hash"],
        )
        refs = self.canonical_plan["impact_references"]
        self.assertEqual(
            {item["impact_id"] for item in refs},
            {item["impact_id"] for item in self.cases["representative"]["impact_map"]["impacts"]},
        )
        self.assertTrue(all(
            item.get("provenance") == impact.DERIVED_PLAN_DECISION
            for item in refs
        ))

    def test_13_dependencies_are_preserved_after_node_grouping(self):
        old_edges = {
            (node["node_id"], dependency)
            for node in self.expanded_plan["approved_change_nodes"]
            for dependency in node.get("dependencies", [])
        }
        node_map = {
            source_id: node["node_id"]
            for node in self.canonical_plan["approved_change_nodes"]
            for source_id in node.get("source_node_ids", [])
        }
        new_edges = {
            (node_map.get(source_id), dependency)
            for node in self.canonical_plan["approved_change_nodes"]
            for source_id in node.get("source_node_ids", [])
            for dependency in node.get("dependencies", [])
            if node_map.get(source_id)
        }
        expected_edges = {
            (node_map.get(source), node_map.get(dependency))
            for source, dependency in old_edges
            if node_map.get(source) and node_map.get(dependency)
        }
        self.assertEqual(new_edges, expected_edges)

    def test_14_explicit_test_change_remains_test_work_when_present(self):
        candidate = copy.deepcopy(self.expanded_plan)
        candidate["approved_change_nodes"].append({
            "node_id": "NODE-TEST-EXPLICIT",
            "goal": "test rationale",
            "requirement_ids": [self.source.REQUIREMENT_ID],
            "impact_ids": ["IMPACT-005"],
            "obligation_ids": [],
            "evidence_ids": ["REPO-006"],
            "surface_ids": ["SURF-005"],
            "target_surface_ids": ["SURF-005"],
            "inspect_surface_ids": [],
            "interface_surface_ids": [],
            "candidate_targets": ["tests/input.test.js"],
            "inspect_targets": [],
            "current_owner": "PauseController",
            "interfaces_to_reuse": [],
            "mutation_required": True,
            "verification_only": False,
            "local_test_contract": ["Run the explicit test-change contract."],
            "test_contract": ["Run the explicit test-change contract."],
            "done_when": ["Run the explicit test-change contract."],
            "dependencies": [],
            "do_not_touch": [],
            "impact_kind": "TEST_CHANGE",
            "necessity_status": "TEST_CHANGE",
            "disposition": "TEST_CHANGE",
            "provenance": impact.DERIVED_PLAN_DECISION,
        })
        result = impact.canonicalize_final_plan(
            candidate,
            impact_map=self.cases["representative"]["reconciled"],
            requirements=self.requirements,
            evidence=self.evidence,
            surface_registry=self.registry,
            source_impact_map=self.cases["representative"]["impact_map"],
        )
        test_nodes = [
            node for node in result["approved_change_nodes"]
            if node.get("responsibility_class") == "TEST_CHANGE"
        ]
        self.assertEqual(len(test_nodes), 1)
        self.assertTrue(test_nodes[0]["mutation_required"])
        self.assertEqual(test_nodes[0]["target_surface_ids"], ["SURF-005"])

    def test_15_real_canonical_plan_keeps_legacy_size_gate_fail_closed(self):
        check = impact.validate_change_plan(
            self.expanded_plan,
            self.requirements,
            self.evidence,
            impact.EXISTING_PROJECT,
            surface_registry=self.registry,
            obligation_ledger=self.ledger,
            authoritative_task_goal=self.requirements[0]["text"],
            obligation_aware=True,
        )
        self.assertFalse(check["valid"])
        self.assertIn("plan serialized-size bound exceeded", check["errors"])

    def test_16_legacy_plans_are_not_rewritten(self):
        requirements, evidence, brain, registry, seeds, legacy_frame = (
            self.source._legacy_behavior_fixture()
        )
        legacy_plan = impact.build_minimal_change_plan(
            impact.deterministic_impact_map(
                requirements[0]["text"], requirements, evidence, registry=registry,
            ),
            requirements,
            evidence,
            project_mode=impact.EXISTING_PROJECT,
            surface_registry=registry,
        )
        self.assertNotIn("representation", legacy_plan)
        rewritten = impact.canonicalize_final_plan(
            legacy_plan,
            impact_map={},
            requirements=requirements,
            evidence=evidence,
            surface_registry=registry,
        )
        self.assertEqual(rewritten, legacy_plan)

    def test_17_stage4_snapshot_contracts_and_graph_remain_valid(self):
        approval = {
            "approval_status": "APPROVED",
            "plan_id": self.canonical_plan["plan_id"],
            "plan_hash": self.canonical_plan["plan_hash"],
            "approval_source": "TEST_ONLY",
        }
        snapshot = execution.create_approved_plan_snapshot(
            self.canonical_plan,
            approval,
            authoritative_task_goal=self.requirements[0]["text"],
            requirements=self.requirements,
            repository_evidence=self.evidence,
            canonical_surface_registry=self.registry,
        )
        snapshot_check = execution.validate_snapshot(
            snapshot,
            self.canonical_plan,
            approval,
            authoritative_task_goal=self.requirements[0]["text"],
        )
        self.assertTrue(snapshot_check["valid"], snapshot_check)
        compiled = execution.compile_execution_contracts(snapshot)
        self.assertTrue(compiled["validation"]["valid"], compiled)
        contracts = compiled["contracts"]
        mutation = [item for item in contracts if item["responsibility_type"] == execution.MUTATION]
        self.assertEqual(len(mutation), 1)
        self.assertEqual(mutation[0]["allowed_mutation_paths"], ["src/status_view.js"])
        self.assertNotIn("src/pause_controller.js", mutation[0]["allowed_mutation_paths"])
        self.assertIn(
            "Do not modify src/pause_controller.js.",
            mutation[0]["structured_prohibitions"],
        )
        self.assertTrue(any(
            "tests/input.test.js" in text
            for contract in contracts
            for text in contract.get("test_contract", [])
        ))
        graph = execution.build_execution_graph(snapshot, contracts)
        self.assertTrue(
            execution.validate_execution_graph(snapshot, graph, contracts)["valid"],
        )

    def test_18_provider_free_entrypoint_reaches_approval_without_fabricating_it(self):
        self.assertEqual(self.integration_result["status"], "plan_approval_required")
        self.assertEqual(
            self.integration_result["terminal_state"], mini.PLAN_APPROVAL_REQUIRED,
        )
        self.assertEqual(
            self.integration_result["approval"]["approval_status"],
            "REQUIRED",
        )
        self.assertEqual(self.integration_result["plan"]["representation"], impact.CANONICAL_FINAL_PLAN_REPRESENTATION)
        self.assertLessEqual(
            impact._json_size(self.integration_result["plan"]), impact.MAX_PLAN_CHARS,
        )

    def test_19_canonicalization_metrics_are_compact_and_zero_model(self):
        expected = {
            "final_plan_chars_before_canonicalization",
            "final_plan_chars_after_canonicalization",
            "final_plan_semantic_units",
            "final_plan_deduplicated_units",
            "final_plan_shared_constraints",
            "final_plan_shared_verification_contracts",
            "final_plan_provenance_refs",
        }
        self.assertEqual(set(self.integration_metrics), expected)
        self.assertGreater(
            self.integration_metrics["final_plan_chars_before_canonicalization"],
            impact.MAX_PLAN_CHARS,
        )
        self.assertEqual(
            self.integration_metrics["final_plan_chars_after_canonicalization"],
            impact._json_size(self.integration_result["plan"]),
        )
        self.assertEqual(self.integration_metrics["final_plan_semantic_units"], 4)
        self.assertEqual(self.integration_metrics["final_plan_deduplicated_units"], 4)
        self.assertEqual(self.integration_metrics["final_plan_shared_constraints"], 8)
        self.assertEqual(self.integration_metrics["final_plan_shared_verification_contracts"], 3)
        self.assertEqual(self.integration_metrics["final_plan_provenance_refs"], 7)
        self.assertEqual(self.integration_run.get("model_calls", 0), 0)
        self.assertEqual(self.integration_run.get("planning_context_compiler_model_calls", 0), 0)
        self.assertEqual(self.integration_run.get("planning_readiness_model_calls", 0), 0)
        self.assertEqual(self.integration_run.get("ollama_http_200", 0), 0)
        self.assertEqual(self.integration_run.get("ollama_retry_count", 0), 0)

    def test_20_model_rationale_is_not_authority_or_repeated_in_final_plan(self):
        serialized = self._serialized(self.max_plan)
        self.assertNotIn("R" * 360, serialized)
        self.assertNotIn("Q" * 120, serialized)
        self.assertTrue(self.max_plan["upstream_bindings"]["impact_decision_choice_hash"])
        self.assertTrue(all(
            node["goal"] == impact._canonical_final_plan_short_done_when(
                node["responsibility_class"],
            )
            for node in self.max_plan["approved_change_nodes"]
        ))


if __name__ == "__main__":
    unittest.main()
