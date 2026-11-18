import copy
import itertools
import json
import tempfile
import unittest
from pathlib import Path

import mini
from hivo import execution_contracts as execution
from hivo import impact_planning as impact
from hivo import verified_planning


class LiveEquivalentCanonicalFinalPlanBoundClosureTests(unittest.TestCase):
    """Provider-free replay and worst-case closure for the V24.4.6 plan bound."""

    ROOT = Path(__file__).resolve().parents[1]
    ARTIFACT_ROOT = ROOT / "output" / "hivo-v24-4-5-stage6b-planning-live-1"

    @classmethod
    def _load(cls, name):
        return json.loads((cls.ARTIFACT_ROOT / name).read_text(encoding="utf-8"))

    @classmethod
    def _build_from_validated(cls, validated):
        reconciled, resolved, unresolved = impact.reconcile_impact_map(
            cls.compiled_map,
            validated,
            cls.requirements,
            cls.evidence,
            surface_registry=cls.registry,
            impact_seeds=cls.impact_seeds,
            obligation_ledger=cls.ledger,
            task_goal=cls.verified_context["task_goal"],
            task_brain=cls.fresh_task_brain,
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
            task_goal=cls.verified_context["task_goal"],
            obligation_aware=True,
        )
        lifecycle, resolved, unresolved = impact.re_evaluate_challenge_lifecycle(
            validated,
            expanded,
            cls.requirements,
            cls.evidence,
            surface_registry=cls.registry,
            obligation_ledger=cls.ledger,
            impact_map=reconciled,
            closure_actions=reconciled.get("behavior_anchor_closure_actions", []),
        )
        expanded["resolved_challenges"] = [
            impact.compact_challenge_record(item)
            for item in resolved[:impact.MAX_CHALLENGES]
        ]
        expanded["unresolved_challenges"] = [
            impact.compact_challenge_record(item)
            for item in unresolved[:impact.MAX_CHALLENGES]
        ]
        expanded = verified_planning.attach_plan_binding(
            expanded, cls.verified_context,
        )
        canonical = impact.canonicalize_final_plan(
            expanded,
            impact_map=reconciled,
            requirements=cls.requirements,
            evidence=cls.evidence,
            surface_registry=cls.registry,
            source_impact_map=cls.compiled_map,
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
            authoritative_task_goal=cls.verified_context["task_goal"],
            obligation_aware=True,
        )
        return {
            "validated": validated,
            "reconciled": reconciled,
            "expanded": expanded,
            "canonical": canonical,
            "gate": gate,
            "lifecycle": lifecycle,
            "resolved": resolved,
            "unresolved": unresolved,
        }

    @classmethod
    def _max_valid_challenges(cls):
        non_mutating = [
            item["impact_id"]
            for item in cls.compiled_map["impacts"]
            if item["impact_id"] != "IMPACT-003"
        ]
        claim = (
            "The pause responsibility does not establish a supported necessity "
            "for mutation. " + "C" * impact.MAX_TEXT_CHARS
        )
        resolution = (
            "Retain the verified non-mutating context responsibility. "
            + "R" * impact.MAX_TEXT_CHARS
        )
        result = []
        for index, ids in enumerate(
            itertools.combinations(non_mutating, 4), 1,
        ):
            if len(result) >= impact.MAX_CHALLENGES:
                break
            result.append({
                "challenge_id": f"MAX-{index:03d}",
                "challenge_type": "UNSUPPORTED_NECESSITY",
                "impact_ids": list(ids),
                "surface_ids": [],
                "requirement_ids": ["REQ-PAUSE-INDICATOR"],
                "repository_evidence_ids": [],
                "claim": claim,
                "proposed_resolution": resolution,
                "blocking": False,
                "source": "MODEL",
                "provenance": impact.DERIVED_PLAN_DECISION,
            })
        return result

    @classmethod
    def _minimal_valid_challenge(cls):
        return [{
            "challenge_id": "MIN-001",
            "challenge_type": "UNSUPPORTED_NECESSITY",
            "impact_ids": ["IMPACT-001"],
            "surface_ids": [],
            "requirement_ids": ["REQ-PAUSE-INDICATOR"],
            "repository_evidence_ids": [],
            "claim": "verified context",
            "proposed_resolution": "retain context",
            "blocking": False,
            "source": "MODEL",
            "provenance": impact.DERIVED_PLAN_DECISION,
        }]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not cls.ARTIFACT_ROOT.is_dir():
            raise AssertionError(
                f"required V24.4.5 live artifact directory is missing: {cls.ARTIFACT_ROOT}"
            )

        cls.verified_context = cls._load("verified_planning_context.json")
        current = cls._load("current_surface_evidence.json")
        cls.requirements = cls.verified_context["new_requirements"]
        cls.evidence = current["repository_evidence"]
        cls.registry = current["registry"]
        cls.impact_seeds = current["impact_seeds"]
        cls.ledger = cls._load("atomic_obligation_ledger.json")
        cls.compiled_map = cls._load("compiled_impact_map.json")["impact_map"]
        cls.fresh_task_brain = cls._load("fresh_task_brain.json")
        cls.challenge_validation = cls._load("challenger_validation.json")
        cls.live_baseline = cls._load("final_plan.json")
        cls.raw_challenger = cls._load("challenger_raw_output.json")

        cls.live = cls._build_from_validated(
            cls.challenge_validation["validated"],
        )
        cls.minimal_validation = impact.validate_challenges(
            cls._minimal_valid_challenge(),
            cls.compiled_map,
            cls.requirements,
            cls.evidence,
            surface_registry=cls.registry,
        )
        if len(cls.minimal_validation["validated"]) != 1:
            raise AssertionError(cls.minimal_validation)
        cls.minimum = cls._build_from_validated(
            cls.minimal_validation["validated"],
        )

        cls.maximum_validation = impact.validate_challenges(
            cls._max_valid_challenges(),
            cls.compiled_map,
            cls.requirements,
            cls.evidence,
            surface_registry=cls.registry,
        )
        if len(cls.maximum_validation["validated"]) != impact.MAX_CHALLENGES:
            raise AssertionError(cls.maximum_validation)
        cls.maximum = cls._build_from_validated(
            cls.maximum_validation["validated"],
        )

        # These are the frozen V24.4.5 provider-free maximum measurements,
        # captured before the V24.4.6 representation repair.  Re-running the
        # V24.4.5 fixture through the patched canonicalizer would exercise the
        # repair itself (and would replace the historical comparator with a
        # 3-node repaired plan), so keep the forensic baseline as immutable
        # measurements while deriving the live side from the exact persisted
        # V24.4.5 artifact above.
        cls.historical_offline_total = 17570
        cls.historical_offline_field_sizes = {
            "approved_change_nodes": 3695,
            "canonical_verification_contracts": 1306,
            "coverage": 590,
            "impact_references": 2364,
            "resolved_challenges": 620,
        }
        cls.delta_fields = {
            field: (
                cls.historical_offline_field_sizes[field],
                impact._json_size(cls.live_baseline.get(field)),
            )
            for field in (
                "approved_change_nodes", "canonical_verification_contracts",
                "coverage", "impact_references", "resolved_challenges",
            )
        }
        planner_response = copy.deepcopy(
            cls._load("impact_planner_raw_output.json")["normalized_return"]
        )
        challenger_response = copy.deepcopy(
            cls.raw_challenger["normalized_return"]
        )
        previous_workspace = mini.WORKSPACE
        previous_memory_store = mini.MEMORY_STORE
        try:
            with tempfile.TemporaryDirectory() as workspace:
                cls.entrypoint_result, cls.entrypoint_memory = (
                    mini.run_verified_state_aware_planning(
                        fresh_task_brain=copy.deepcopy(cls.fresh_task_brain),
                        memory={},
                        workspace=workspace,
                        expected_project_id=cls.verified_context["project_id"],
                        impact_planner_structured_call=lambda *_args: copy.deepcopy(
                            planner_response
                        ),
                        impact_challenger_structured_call=lambda *_args: copy.deepcopy(
                            challenger_response
                        ),
                        finish=False,
                    )
                )
                cls.entrypoint_run = copy.deepcopy(mini.RUN)
        finally:
            mini.WORKSPACE = previous_workspace
            mini.MEMORY_STORE = previous_memory_store

        # Provider-free Stage 4 contractability uses a test-only immutable
        # approval record.  It does not approve the live run or execute it.
        plan = cls.live["canonical"]
        cls.test_approval = {
            "approval_status": "APPROVED",
            "plan_id": plan["plan_id"],
            "plan_hash": plan["plan_hash"],
            "approval_source": "V24.4.6_TEST_CONTRACTABILITY_ONLY",
        }
        cls.snapshot = execution.create_approved_plan_snapshot(
            plan,
            cls.test_approval,
            authoritative_task_goal=cls.verified_context["task_goal"],
            requirements=cls.requirements,
            repository_evidence=cls.evidence,
            canonical_surface_registry=cls.registry,
        )
        cls.snapshot_validation = execution.validate_snapshot(
            cls.snapshot,
            plan,
            cls.test_approval,
            authoritative_task_goal=cls.verified_context["task_goal"],
        )
        cls.contractability = execution.compile_execution_contracts(cls.snapshot)
        cls.graph = execution.build_execution_graph(
            cls.snapshot, cls.contractability["contracts"],
        )
        cls.graph_validation = execution.validate_execution_graph(
            cls.snapshot, cls.graph, cls.contractability["contracts"],
        )

    def test_01_persisted_live_baseline_is_exactly_the_pre_fix_blocker(self):
        self.assertEqual(impact._json_size(self.live_baseline), 18183)
        self.assertEqual(len(self.live_baseline["approved_change_nodes"]), 4)
        self.assertEqual(
            self.live_baseline["plan_hash"],
            impact.plan_content_hash(self.live_baseline),
        )
        self.assertEqual(self.live_baseline["plan_id"], "PLAN-BC7413382FDB")

    def test_02_exact_live_replay_reproduces_expanded_plan_and_old_partition(self):
        self.assertEqual(impact._json_size(self.live["expanded"]), 18893)
        self.assertEqual(len(self.live["expanded"]["approved_change_nodes"]), 7)
        old_keys = [
            impact._canonical_final_plan_group_key(
                node, index, impact.canonical_surface_by_id(self.registry),
            )[0]
            for index, node in enumerate(
                self.live["expanded"]["approved_change_nodes"], 1
            )
        ]
        self.assertEqual(
            old_keys,
            [
                "DETERMINISTIC_CONTEXT", "INTERFACE_REUSE",
                "EXECUTION_CHANGE", "INTERFACE_REUSE", "EVIDENCE_ONLY",
                "EVIDENCE_ONLY", "EVIDENCE_ONLY",
            ],
        )
        self.assertEqual(
            [
                (node["responsibility_class"], node["impact_ids"])
                for node in self.live_baseline["approved_change_nodes"]
            ],
            [
                ("DETERMINISTIC_CONTEXT", ["IMPACT-001"]),
                ("INTERFACE_REUSE", ["IMPACT-002", "IMPACT-004"]),
                ("EXECUTION_CHANGE", ["IMPACT-003"]),
                ("EVIDENCE_ONLY", ["IMPACT-005", "IMPACT-006", "IMPACT-007"]),
            ],
        )

    def test_03_offline_live_delta_is_fully_accounted(self):
        expected = {
            "approved_change_nodes": (3695, 4602, 907),
            "canonical_verification_contracts": (1306, 1330, 24),
            "coverage": (590, 602, 12),
            "impact_references": (2364, 2346, -18),
            "resolved_challenges": (620, 308, -312),
        }
        actual = {
            field: (*sizes, sizes[1] - sizes[0])
            for field, sizes in self.delta_fields.items()
        }
        self.assertEqual(actual, expected)
        self.assertEqual(
            sum(item[2] for item in actual.values()),
            613,
        )
        self.assertEqual(
            impact._json_size(self.live_baseline)
            - self.historical_offline_total,
            613,
        )

    def test_04_interface_reuse_is_context_binding_not_duplicate_execution_work(self):
        plan = self.live["canonical"]
        self.assertEqual(len(plan["approved_change_nodes"]), 3)
        context = next(
            node for node in plan["approved_change_nodes"]
            if "IMPACT-002" in node["impact_ids"]
        )
        self.assertEqual(context["responsibility_class"], "DETERMINISTIC_CONTEXT")
        self.assertFalse(context["mutation_required"])
        self.assertTrue(context["verification_only"])
        self.assertIn("SURF-004", context["interface_surface_ids"])
        self.assertIn("PauseController.togglePause", context["interfaces_to_reuse"])
        self.assertEqual(
            plan["interfaces_to_reuse"], ["PauseController.togglePause"],
        )
        self.assertEqual(plan["interface_surface_ids"], ["SURF-004"])

    def test_05_live_replay_fits_and_validates_after_canonicalization(self):
        plan = self.live["canonical"]
        gate = self.live["gate"]
        self.assertLessEqual(impact._json_size(plan), impact.MAX_PLAN_CHARS)
        self.assertEqual(impact._json_size(plan), 17318)
        self.assertEqual(impact.MAX_PLAN_CHARS - impact._json_size(plan), 682)
        self.assertTrue(gate["valid"], gate)
        self.assertEqual(gate["serialized_chars"], impact._json_size(plan))
        self.assertEqual(
            plan["plan_hash"], impact.plan_content_hash(plan),
        )
        self.assertEqual(
            plan["plan_id"], f"PLAN-{plan['plan_hash'][:12].upper()}",
        )
        context_gate = verified_planning.validate_verified_plan(
            plan,
            self.verified_context,
            requirements=self.requirements,
            current_repository_evidence=self.evidence,
        )
        self.assertTrue(context_gate["valid"], context_gate)

    def test_06_provider_free_entrypoint_reaches_required_approval_only(self):
        result = self.entrypoint_result
        self.assertEqual(result["status"], "plan_approval_required")
        self.assertEqual(result["terminal_state"], mini.PLAN_APPROVAL_REQUIRED)
        self.assertEqual(result["approval"]["approval_status"], "REQUIRED")
        self.assertNotEqual(result["approval"]["approval_status"], "APPROVED")
        self.assertTrue(result["plan_gate"]["valid"], result["plan_gate"])
        self.assertLessEqual(
            impact._json_size(result["plan"]), impact.MAX_PLAN_CHARS,
        )
        self.assertEqual(len(result["plan"]["approved_change_nodes"]), 3)

    def test_07_minimum_representative_and_maximum_cases_fit(self):
        for label, case in (
            ("minimum", self.minimum),
            ("representative", self.live),
            ("maximum", self.maximum),
        ):
            self.assertTrue(case["gate"]["valid"], (label, case["gate"]))
            self.assertLessEqual(
                impact._json_size(case["canonical"]), impact.MAX_PLAN_CHARS,
                label,
            )
        self.assertEqual(impact._json_size(self.maximum["canonical"]), 17441)
        self.assertEqual(
            impact.MAX_PLAN_CHARS - impact._json_size(self.maximum["canonical"]),
            559,
        )

    def test_08_maximum_challenger_case_uses_frozen_schema_and_normalization(self):
        raw = self._max_valid_challenges()
        self.assertEqual(len(raw), impact.MAX_CHALLENGES)
        self.assertTrue(all(len(item["impact_ids"]) == 4 for item in raw))
        self.assertTrue(all(
            len(item["claim"]) > impact.MAX_TEXT_CHARS
            for item in raw
        ))
        normalized = impact.normalize_challenges({"challenges": raw})
        self.assertEqual(len(normalized), impact.MAX_CHALLENGES)
        self.assertTrue(all(
            len(item["claim"]) == impact.MAX_TEXT_CHARS
            and len(item["proposed_resolution"]) == impact.MAX_TEXT_CHARS
            for item in normalized
        ))
        self.assertEqual(
            len(self.maximum_validation["validated"]), impact.MAX_CHALLENGES,
        )
        self.assertEqual(self.maximum_validation["rejected"], [])

    def test_09_all_seven_impacts_remain_reachable(self):
        plan = self.live["canonical"]
        self.assertEqual(
            {item["impact_id"] for item in plan["impact_references"]},
            {f"IMPACT-{index:03d}" for index in range(1, 8)},
        )
        self.assertTrue(all(
            item.get("node_id") in {
                node["node_id"] for node in plan["approved_change_nodes"]
            }
            for item in plan["impact_references"]
        ))

    def test_10_atomic_requirement_coverage_remains_four_of_four(self):
        gate = self.live["gate"]
        self.assertEqual(gate["requirement_obligations_created"], 4)
        self.assertEqual(gate["behavior_obligations"], 1)
        self.assertEqual(gate["behavior_obligations_covered"], 1)
        self.assertEqual(gate["behavior_obligations_uncovered"], 0)
        coverage = self.live["canonical"]["coverage"][0]
        self.assertEqual(coverage["semantic_state"], "COVERED")
        self.assertEqual(len(coverage["obligation_ids"]), 4)

    def test_11_mutation_authority_and_dnt_are_unchanged(self):
        plan = self.live["canonical"]
        self.assertEqual(plan["mutation_surface_ids"], ["SURF-003"])
        self.assertEqual(
            {
                path for node in plan["approved_change_nodes"]
                for path in node.get("candidate_targets", [])
            },
            {"src/status_view.js"},
        )
        self.assertEqual(plan["do_not_touch_surface_ids"], ["SURF-004"])
        self.assertEqual(plan["do_not_touch"], ["src/pause_controller.js"])
        self.assertNotIn(
            "src/pause_controller.js",
            {
                path for node in plan["approved_change_nodes"]
                for path in node.get("candidate_targets", [])
            },
        )
        self.assertNotIn("NEW_OWNER", json.dumps(plan, sort_keys=True))
        self.assertNotIn("OWNER_MIGRATION", json.dumps(plan, sort_keys=True))

    def test_12_verification_contracts_are_fanned_in_without_loss(self):
        plan = self.live["canonical"]
        self.assertEqual(len(plan["canonical_verification_contracts"]), 3)
        baseline = {
            tuple(item["contract"]): (
                tuple(item.get("requirement_ids", [])),
                tuple(item.get("evidence_ids", [])),
                tuple(item.get("surface_ids", [])),
            )
            for item in self.live_baseline["canonical_verification_contracts"]
        }
        current = {
            tuple(item["contract"]): (
                tuple(item.get("requirement_ids", [])),
                tuple(item.get("evidence_ids", [])),
                tuple(item.get("surface_ids", [])),
            )
            for item in plan["canonical_verification_contracts"]
        }
        self.assertEqual(current, baseline)

    def test_13_empty_dependencies_remain_explicit(self):
        self.assertTrue(all(
            node.get("dependencies") == []
            for node in self.live["canonical"]["approved_change_nodes"]
        ))
        self.assertEqual(self.live["canonical"].get("dependencies", []), [])
        self.assertEqual(
            self.live["canonical"]["upstream_bindings"]["impact_map_hash"],
            self.live_baseline["upstream_bindings"]["impact_map_hash"],
        )

    def test_14_evidence_only_impacts_never_become_mutation_work(self):
        evidence = next(
            node for node in self.live["canonical"]["approved_change_nodes"]
            if node["responsibility_class"] == "EVIDENCE_ONLY"
        )
        self.assertFalse(evidence["mutation_required"])
        self.assertTrue(evidence["verification_only"])
        self.assertEqual(evidence["target_surface_ids"], [])
        self.assertTrue(evidence["inspect_surface_ids"])
        self.assertTrue(all(
            path.startswith("tests/") for path in evidence["inspect_targets"]
        ))

    def test_15_challenger_outcome_is_fanned_in_and_raw_prose_is_not_authority(self):
        plan = self.live["canonical"]
        summary = plan["challenger_reconciliation"]
        self.assertEqual(summary["resolved_challenge_ids"], ["CH-001"])
        self.assertEqual(summary["open_blocking_count"], 0)
        self.assertEqual(
            summary["reconciliation_hash"],
            plan["upstream_bindings"]["challenge_reconciliation_hash"],
        )
        self.assertNotIn("resolved_challenges", plan)
        self.assertNotIn("unresolved_challenges", plan)
        raw = self.raw_challenger["normalized_return"]
        serialized = json.dumps(plan, ensure_ascii=False, sort_keys=True)
        for item in raw:
            self.assertNotIn(item["claim"], serialized)
            self.assertNotIn(item["proposed_resolution"], serialized)
        self.assertTrue(
            self._load("challenger_validation.json")["rejected"],
        )

    def test_16_blocking_unresolved_challenge_cannot_reach_approval(self):
        candidate = copy.deepcopy(self.live["expanded"])
        candidate["unresolved_challenges"] = [{
            "challenge_id": "BLOCK-001",
            "challenge_type": "REQUIREMENT_GAP",
            "requirement_ids": ["REQ-PAUSE-INDICATOR"],
            "blocking": True,
            "applicability_status": "VALIDATED_APPLICABLE",
            "effect_status": "PENDING",
            "lifecycle_state": "OPEN",
            "resolution_status": "OPEN",
        }]
        blocked = impact.canonicalize_final_plan(
            candidate,
            impact_map=self.live["reconciled"],
            requirements=self.requirements,
            evidence=self.evidence,
            surface_registry=self.registry,
            source_impact_map=self.compiled_map,
        )
        blocked = impact.finalize_plan_identity(blocked)
        self.assertEqual(
            blocked["challenger_reconciliation"]["open_blocking_challenge_ids"],
            ["BLOCK-001"],
        )
        gate = impact.validate_change_plan(
            blocked,
            self.requirements,
            self.evidence,
            impact.EXISTING_PROJECT,
            surface_registry=self.registry,
            obligation_ledger=self.ledger,
            authoritative_task_goal=self.verified_context["task_goal"],
            obligation_aware=True,
        )
        self.assertFalse(gate["valid"], gate)
        self.assertIn("unresolved blocking challenge", gate["errors"])

    def test_17_interface_only_context_remains_an_interface_responsibility(self):
        candidate = copy.deepcopy(self.live["expanded"])
        candidate["approved_change_nodes"] = [
            node for node in candidate["approved_change_nodes"]
            if set(node.get("impact_ids", [])) & {"IMPACT-002", "IMPACT-004"}
        ]
        result = impact.canonicalize_final_plan(
            candidate,
            impact_map=self.live["reconciled"],
            requirements=self.requirements,
            evidence=self.evidence,
            surface_registry=self.registry,
            source_impact_map=self.compiled_map,
        )
        self.assertEqual(
            result["approved_change_nodes"][0]["responsibility_class"],
            "INTERFACE_REUSE",
        )
        self.assertIn("SURF-004", result["approved_change_nodes"][0]["interface_surface_ids"])

    def test_18_plan_hash_binds_target_dnt_and_verification(self):
        plan = self.live["canonical"]
        for mutate in (
            lambda value: value["approved_change_nodes"][1]["candidate_targets"].append(
                "src/other_view.js"
            ),
            lambda value: value["canonical_constraints"]["prohibitions"][0].update(
                text=value["canonical_constraints"]["prohibitions"][0]["text"] + " Keep it."
            ),
            lambda value: value["canonical_verification_contracts"][0]["contract"].append(
                "Additional verification."
            ),
        ):
            changed = copy.deepcopy(plan)
            mutate(changed)
            self.assertNotEqual(
                impact.finalize_plan_identity(changed)["plan_hash"],
                plan["plan_hash"],
            )
        self.assertEqual(
            impact.finalize_plan_identity(copy.deepcopy(plan))["plan_hash"],
            plan["plan_hash"],
        )

    def test_19_validator_measures_exact_canonical_object_without_json_slicing(self):
        plan = self.maximum["canonical"]
        encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True)
        self.assertEqual(len(encoded), impact._json_size(plan))
        self.assertLessEqual(len(encoded), impact.MAX_PLAN_CHARS)
        self.assertNotIn("C" * impact.MAX_TEXT_CHARS, encoded)
        self.assertNotIn("R" * impact.MAX_TEXT_CHARS, encoded)
        self.assertTrue(self.maximum["gate"]["valid"])

    def test_20_stage4_contractability_passes_without_execution(self):
        self.assertTrue(self.snapshot_validation["valid"], self.snapshot_validation)
        self.assertTrue(
            self.contractability["validation"]["valid"],
            self.contractability,
        )
        self.assertTrue(self.graph_validation["valid"], self.graph_validation)
        self.assertEqual(self.contractability["metrics"]["execution_contracts_created"], 1)
        contract = self.contractability["contracts"][0]
        self.assertEqual(contract["allowed_mutation_paths"], ["src/status_view.js"])
        self.assertNotIn("src/pause_controller.js", contract["allowed_mutation_paths"])
        self.assertIn("PauseController.togglePause", contract["interfaces_to_reuse"])
        self.assertEqual(contract["dependencies"], [])
        self.assertTrue(self.contractability["metrics"]["reference_nodes_attached"] >= 1)

    def test_21_subject_and_brain_artifacts_remain_immutable(self):
        brain = self._load("project_brain_immutability.json")
        self.assertEqual(brain["hash_before"], brain["hash_after"])
        self.assertEqual(brain["records_before"], 12)
        self.assertEqual(brain["records_after"], 12)
        self.assertEqual(brain["writes"], 0)
        before = self._load("subject_manifest_pre.json")
        after = self._load("subject_manifest_post.json")
        self.assertEqual(before["aggregate_hash"], after["aggregate_hash"])
        self.assertEqual(
            before["aggregate_hash"],
            "c00fc37444dc64f0f6aecbcd57a5972ddfb9fed495f2ce2ba39be7db1150bbac",
        )
        self.assertFalse(after["mutated"])

    def test_22_provider_free_accounting_has_no_execution_or_generation_calls(self):
        run = self.entrypoint_run
        for key in (
            "impact_plan_revision_calls", "ollama_http_200",
            "ollama_retry_count", "worker_calls", "verifier_calls",
            "promotion_calls", "mutation_calls", "stage6c_calls",
        ):
            self.assertEqual(run.get(key, 0) or 0, 0, key)
        self.assertEqual(run.get("impact_planner_calls"), 1)
        self.assertEqual(run.get("impact_challenger_calls"), 1)
        self.assertEqual(run.get("impact_plan_revision_calls", 0) or 0, 0)
        self.assertEqual(run.get("ollama_http_200", 0) or 0, 0)


if __name__ == "__main__":
    unittest.main()
