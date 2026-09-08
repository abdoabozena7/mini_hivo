import json
import unittest

from hivo.semantic_coupling import (
    ANALYSIS_CONFLICTING,
    ANALYSIS_PARTIAL,
    BLOCKED,
    CONFIGURATION_COUPLING,
    GROUP,
    INDEPENDENT,
    MERGE_REQUIRED,
    ORDER_DEPENDENT,
    PRODUCER_CONSUMER,
    PUBLIC_SURFACE_COUPLING,
    SHARED_INVARIANT,
    SHARED_CONTRACT,
    SHARED_STATE_TRANSITION,
    TYPE_SCHEMA_COUPLING,
    VERIFICATION_COUPLING,
    SemanticCouplingAnalyzer,
    analyze_semantic_coupling,
    benchmark_semantic_coupling_scenarios,
    refine_semantic_decomposition,
    verify_semantic_group,
)
from hivo.project_world_model import ProjectWorldModel


class FakeWorldModel:
    def __init__(self, facts, project_identity="fixture"):
        self.facts = list(facts)
        self.project_identity = project_identity
        self.calls = []

    @staticmethod
    def _matches(value, target):
        value = str(value or "").casefold().replace("\\", "/")
        target = str(target or "").casefold().replace("\\", "/")
        return target in value or value.rsplit("/", 1)[-1] == target

    def neighborhood(self, target, *, max_hops=2, max_facts=12, include_states=None):
        self.calls.append({"target": target, "max_hops": max_hops, "max_facts": max_facts})
        rows = [
            fact for fact in self.facts
            if self._matches(fact.get("subject"), target)
            or self._matches(fact.get("object"), target)
        ]
        return {"facts": rows[:max_facts], "hops": min(max_hops, 2)}


def fact(fact_id, subject, relation, object_value, *, state="VERIFIED", score=100, source=None):
    return {
        "fact_id": fact_id,
        "subject": subject,
        "relation": relation,
        "object": object_value,
        "state": state,
        "authority_tier": "HIGH" if score >= 90 else "MEDIUM",
        "authority_score": score,
        "provenance": [{"source_identity": source or f"src/{fact_id}.py:1"}],
    }


class SemanticCouplingTests(unittest.TestCase):
    def test_independent_tasks_remain_separate(self):
        plan = analyze_semantic_coupling(
            "small maintenance batch",
            [
                {"id": "logging", "goal": "add unrelated logging metric", "targets": ["metrics"]},
                {"id": "cli", "goal": "fix unrelated CLI help text", "targets": ["cli_help"]},
            ],
        )
        self.assertEqual(plan["classification"], INDEPENDENT)
        self.assertEqual(plan["groups"], [])

    def test_producer_consumer_contract_is_grouped(self):
        model = FakeWorldModel([
            fact("call", "consumer", "CALLS", "producer", source="src/consumer.py:4"),
            fact("field", "consumer", "READS_FIELD", "producer:token", source="src/consumer.py:5"),
        ])
        plan = analyze_semantic_coupling(
            "migrate producer return contract",
            [
                {"id": "producer_change", "goal": "change producer return contract", "targets": ["producer"]},
                {"id": "consumer_change", "goal": "update consumer field access", "targets": ["consumer"]},
            ],
            world_model=model,
        )
        kinds = {item["kind"] for item in plan["couplings"]}
        self.assertEqual(plan["classification"], GROUP)
        self.assertIn(PRODUCER_CONSUMER, kinds)
        self.assertIn(SHARED_CONTRACT, kinds)
        self.assertEqual(len(plan["groups"]), 1)

    def test_type_schema_coupling_prefers_authoritative_declaration(self):
        model = FakeWorldModel([
            fact("impl", "producer", "RETURNS_TYPE", "TokenResponse", score=60, source="src/producer.py:2"),
            fact("contract", "producer", "IMPLEMENTS_CONTRACT", "TokenResponse", score=110, source="src/api.pyi:3"),
            fact("schema", "TokenResponse", "DECLARES_FIELD", "token", score=110, source="src/types.py:4"),
        ])
        plan = analyze_semantic_coupling(
            "change the TokenResponse contract",
            [
                {"id": "producer", "goal": "modify producer", "targets": ["producer"]},
                {"id": "schema", "goal": "modify TokenResponse schema", "targets": ["TokenResponse"]},
            ],
            world_model=model,
        )
        kinds = {item["kind"] for item in plan["couplings"]}
        self.assertIn(TYPE_SCHEMA_COUPLING, kinds)
        evidence = next(item for item in plan["couplings"] if item["kind"] == TYPE_SCHEMA_COUPLING)["evidence"]
        self.assertEqual(evidence[0]["provenance"][0]["source_identity"], "src/api.pyi:3")

    def test_direct_behavior_test_outranks_indirect_test_mention(self):
        model = FakeWorldModel([
            fact("direct", "test_refresh", "TEST_ASSERTS_BEHAVIOR_OF", "refresh_token", score=110, source="tests/test_refresh.py:8"),
            fact("mention", "test_other", "TESTED_BY", "refresh_token", score=40, source="tests/test_other.py:2"),
        ])
        plan = analyze_semantic_coupling(
            "change refresh_token behavior",
            [
                {"id": "implementation", "goal": "modify refresh_token", "targets": ["refresh_token"]},
                {"id": "tests", "goal": "update direct behavior test", "targets": ["test_refresh"]},
            ],
            world_model=model,
        )
        evidence = [
            item for coupling in plan["couplings"]
            if coupling["kind"] == VERIFICATION_COUPLING
            for item in coupling["evidence"]
        ]
        self.assertTrue(evidence)
        self.assertEqual(evidence[0]["provenance"][0]["source_identity"], "tests/test_refresh.py:8")

    def test_state_transition_chain_is_structural(self):
        model = FakeWorldModel([
            fact("ab", "step_a", "TRANSITIONS", "IDLE -> RUNNING", source="src/state_a.py:10"),
            fact("bc", "step_b", "TRANSITIONS", "RUNNING -> COMPLETE", source="src/state_b.py:12"),
            fact("noise", "docs", "DEFINED_IN", "IDLE COMPLETE", score=20, source="README.md:2"),
        ])
        plan = analyze_semantic_coupling(
            "change lifecycle IDLE -> RUNNING -> COMPLETE",
            [
                {"id": "a", "goal": "modify A transition", "targets": ["step_a"]},
                {"id": "b", "goal": "modify B transition", "targets": ["step_b"]},
            ],
            world_model=model,
        )
        self.assertIn(SHARED_STATE_TRANSITION, {item["kind"] for item in plan["couplings"]})

    def test_public_surface_coupling_uses_export_relation(self):
        model = FakeWorldModel([
            fact("export", "auth.__init__", "EXPORTS", "refresh_token", source="auth/__init__.py:1"),
            fact("import", "session", "IMPORTS", "auth.__init__", source="session.py:2"),
        ])
        plan = analyze_semantic_coupling(
            "preserve public refresh_token API",
            [
                {"id": "implementation", "goal": "modify refresh_token", "targets": ["refresh_token"]},
                {"id": "public", "goal": "update auth export", "targets": ["auth.__init__"]},
            ],
            world_model=model,
        )
        self.assertIn(PUBLIC_SURFACE_COUPLING, {item["kind"] for item in plan["couplings"]})

    def test_execution_dependency_alone_does_not_group(self):
        plan = analyze_semantic_coupling(
            "generate then consume a file",
            [
                {"id": "generate", "goal": "generate an artifact", "targets": ["generator"]},
                {"id": "consume", "goal": "consume the artifact", "targets": ["consumer"]},
            ],
            known_dependencies={"consume": ["generate"]},
        )
        self.assertEqual(plan["classification"], INDEPENDENT)
        self.assertEqual(plan["couplings"], [])

    def test_shared_invariant_and_configuration_relationships_group_only_matching_children(self):
        model = FakeWorldModel([
            fact("left-invariant", "producer", "HAS_INVARIANT", "auth_state", source="src/producer.py:4"),
            fact("right-invariant", "consumer", "HAS_INVARIANT", "auth_state", source="src/consumer.py:6"),
            fact("left-config", "producer", "READS_CONFIG", "AUTH_MODE", source="src/producer.py:8"),
            fact("right-config", "consumer", "READS_CONFIG", "AUTH_MODE", source="src/consumer.py:9"),
        ])
        plan = analyze_semantic_coupling(
            "preserve the authentication state configuration invariant",
            [
                {"id": "p", "goal": "change producer auth state", "targets": ["producer"]},
                {"id": "c", "goal": "change consumer auth state", "targets": ["consumer"]},
                {"id": "cli", "goal": "fix unrelated CLI text", "targets": ["cli"]},
            ],
            world_model=model,
        )
        kinds = {item["kind"] for item in plan["couplings"]}
        self.assertIn(SHARED_INVARIANT, kinds)
        self.assertIn(CONFIGURATION_COUPLING, kinds)
        self.assertEqual(len(plan["groups"]), 1)
        self.assertNotIn("cli", plan["groups"][0]["member_ids"])

    def test_order_dependency_is_annotation_not_semantic_coupling_by_itself(self):
        model = FakeWorldModel([
            fact("call", "consumer", "CALLS", "producer", source="src/consumer.py:4"),
        ])
        plan = analyze_semantic_coupling(
            "change the producer contract and consumer",
            [
                {"id": "p", "goal": "change producer contract", "targets": ["producer"]},
                {"id": "c", "goal": "update consumer", "targets": ["consumer"]},
            ],
            world_model=model,
            known_dependencies={"c": ["p"]},
        )
        self.assertEqual(plan["classification"], GROUP)
        self.assertIn(ORDER_DEPENDENT, {item["kind"] for item in plan["couplings"]})

    def test_state_transition_evidence_must_belong_to_both_children(self):
        model = FakeWorldModel([
            fact("ab", "step_a", "TRANSITIONS", "IDLE -> RUNNING", source="src/state_a.py:10"),
            fact("bc", "step_a", "TRANSITIONS", "RUNNING -> COMPLETE", source="src/state_a.py:11"),
        ])
        plan = analyze_semantic_coupling(
            "change lifecycle IDLE -> RUNNING -> COMPLETE",
            [
                {"id": "state", "goal": "modify state machine", "targets": ["step_a"]},
                {"id": "docs", "goal": "update unrelated documentation", "targets": ["docs"]},
            ],
            world_model=model,
        )
        self.assertEqual(plan["classification"], INDEPENDENT)
        self.assertEqual(plan["groups"], [])

    def test_global_verification_target_does_not_group_unrelated_children(self):
        plan = analyze_semantic_coupling(
            "complete two unrelated maintenance changes",
            [
                {"id": "a", "goal": "change logging", "targets": ["logging"]},
                {"id": "b", "goal": "change CLI", "targets": ["cli"]},
            ],
            verification_targets=["tests/test_integration.py"],
        )
        self.assertEqual(plan["classification"], INDEPENDENT)
        self.assertEqual(plan["groups"], [])

    def test_same_explicit_verification_target_can_establish_verification_coupling(self):
        plan = analyze_semantic_coupling(
            "complete one integrated migration",
            [
                {
                    "id": "producer", "goal": "change producer", "targets": ["producer"],
                    "verification_targets": ["tests/test_integration.py"],
                },
                {
                    "id": "consumer", "goal": "change consumer", "targets": ["consumer"],
                    "verification_targets": ["tests/test_integration.py"],
                },
            ],
        )
        self.assertEqual(plan["classification"], GROUP)
        self.assertIn(VERIFICATION_COUPLING, {item["kind"] for item in plan["couplings"]})

    def test_three_part_schema_migration_is_one_connected_semantic_group(self):
        model = FakeWorldModel([
            fact("return", "producer", "RETURNS_TYPE", "TokenResponse", source="src/producer.py:3"),
            fact("field", "TokenResponse", "DECLARES_FIELD", "token", source="src/types.py:4"),
            fact("call", "consumer", "CALLS", "producer", source="src/consumer.py:5"),
        ])
        plan = analyze_semantic_coupling(
            "migrate the TokenResponse contract",
            [
                {"id": "schema", "goal": "modify TokenResponse schema", "targets": ["TokenResponse"]},
                {"id": "producer", "goal": "modify producer", "targets": ["producer"]},
                {"id": "consumer", "goal": "modify consumer", "targets": ["consumer"]},
            ],
            world_model=model,
        )
        self.assertEqual(plan["classification"], GROUP)
        self.assertEqual(set(plan["groups"][0]["member_ids"]), {"schema", "producer", "consumer"})

    def test_project_world_model_facts_drive_coupling_with_provenance(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            source = root / "src" / "relations.py"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("# authoritative relation fixture\n", encoding="utf-8")
            model = ProjectWorldModel(root)
            provenance = {"path": "src/relations.py", "location": "line 1", "evidence_kind": "fixture"}
            model.add_fact("consumer", "CALLS", "producer", provenance, authority_tier="HIGH")
            model.add_fact("consumer", "READS_FIELD", "producer:token", provenance, authority_tier="HIGH")
            plan = analyze_semantic_coupling(
                "migrate producer contract",
                [
                    {"id": "p", "goal": "change producer", "targets": ["producer"]},
                    {"id": "c", "goal": "update consumer", "targets": ["consumer"]},
                ],
                world_model=model,
            )
            self.assertEqual(plan["world_model_project_identity"], model.project_identity)
            self.assertEqual(plan["classification"], GROUP)
            self.assertTrue(all(item["provenance"] for item in plan["groups"][0]["evidence"]))

    def test_unsafe_split_is_blocked_when_replan_budget_is_exhausted(self):
        analyzer = SemanticCouplingAnalyzer(max_replan_attempts=0)
        result = analyzer.refine_decomposition(
            "one inseparable change",
            [
                {"id": "a", "goal": "change first half of X", "targets": ["X"]},
                {"id": "b", "goal": "change second half of X", "targets": ["X"]},
            ],
        )
        self.assertEqual(result["plan"]["classification"], MERGE_REQUIRED)
        self.assertFalse(result["plan"]["accepted"])
        self.assertTrue(result["replan_exhausted"])

    def test_merged_child_executes_as_child_not_as_unbounded_parent_fallback(self):
        import mini

        saved = (mini.WORKSPACE, mini.RUN, mini.TASKS, mini.RUN_ID, mini.DASHBOARD)
        try:
            mini.WORKSPACE = None
            mini.RUN = mini.new_metrics("test")
            mini.TASKS = {}
            mini.RUN_ID = ""
            mini.DASHBOARD = {}
            parent = mini.make_task("P", "one inseparable change")
            children = []
            for child_id, marker in (("a", "first"), ("b", "second")):
                child = mini.make_task(
                    child_id, f"change {marker} half of same function", parent="P",
                )
                child["targets"] = ["same_function"]
                mini.TASKS[child_id] = child
                parent["children"].append(child_id)
                children.append(child)
            refined_children, _specs, _plan = mini._apply_semantic_coupling_refinement(
                parent, children, {}, [],
            )
            self.assertEqual([child["id"] for child in refined_children], ["a"])
            calls = []

            def leaf(child, *_args):
                calls.append(child["id"])
                return {"status": "done", "summary": "merged child verified", "memory": {}}

            def aggregate(*_args, **_kwargs):
                calls.append("aggregate")
                return {"status": "done", "summary": "parent verified", "memory": {}}

            result = mini._execute_children(
                parent, refined_children, 0, {}, {}, {"files": []}, "", [],
                lambda *_args: {"decision": "execute"}, leaf, aggregate,
            )
            self.assertEqual(result["status"], "done")
            self.assertEqual(calls, ["a", "aggregate"])
        finally:
            mini.WORKSPACE, mini.RUN, mini.TASKS, mini.RUN_ID, mini.DASHBOARD = saved

    def test_unsafe_micro_split_is_merged_before_execution(self):
        model = FakeWorldModel([
            fact("transition", "same_machine", "TRANSITIONS", "IDLE -> RUNNING", source="src/state.py:10"),
        ])
        refined = refine_semantic_decomposition(
            "change one state machine",
            [
                {"id": "first", "goal": "change first half of same_machine", "targets": ["same_machine"]},
                {"id": "second", "goal": "change second half of same_machine", "targets": ["same_machine"]},
            ],
            world_model=model,
        )
        self.assertEqual(refined["plan"]["classification"], INDEPENDENT)
        self.assertTrue(refined["refined"])
        self.assertEqual(len(refined["children"]), 1)
        self.assertEqual(refined["children"][0]["id"], "first")

    def test_conflicting_current_facts_block_analysis(self):
        model = FakeWorldModel([
            fact("str", "producer", "RETURNS_TYPE", "str", state="CONFLICTING", source="src/old_api.py:2"),
            fact("obj", "producer", "RETURNS_TYPE", "TokenResponse", state="CONFLICTING", source="src/new_api.py:2"),
        ])
        plan = analyze_semantic_coupling(
            "change producer contract",
            [
                {"id": "producer", "goal": "modify producer", "targets": ["producer"]},
                {"id": "schema", "goal": "modify TokenResponse", "targets": ["TokenResponse"]},
            ],
            world_model=model,
        )
        self.assertEqual(plan["status"], ANALYSIS_CONFLICTING)
        self.assertEqual(plan["classification"], BLOCKED)
        self.assertEqual(len(plan["conflicts"]), 2)
        self.assertEqual(plan["groups"], [])

    def test_partial_or_stale_facts_never_create_strong_group(self):
        model = FakeWorldModel([
            fact("partial", "producer", "RETURNS_TYPE", "TokenResponse", state="PARTIAL"),
            fact("stale", "consumer", "CALLS", "producer", state="STALE"),
        ])
        plan = analyze_semantic_coupling(
            "change producer and consumer",
            [
                {"id": "producer", "goal": "modify producer", "targets": ["producer"]},
                {"id": "consumer", "goal": "modify consumer", "targets": ["consumer"]},
            ],
            world_model=model,
        )
        self.assertEqual(plan["status"], ANALYSIS_PARTIAL)
        self.assertEqual(plan["groups"], [])

    def test_evidence_bundle_is_minimal(self):
        rows = [
            fact(f"call-{index}", "consumer", "CALLS", "producer", source=f"src/caller_{index}.py:2")
            for index in range(20)
        ]
        rows.append(fact("field", "consumer", "READS_FIELD", "producer:token", source="src/consumer.py:4"))
        model = FakeWorldModel(rows)
        plan = analyze_semantic_coupling(
            "migrate producer contract",
            [
                {"id": "producer", "goal": "change producer return", "targets": ["producer"]},
                {"id": "consumer", "goal": "update consumer", "targets": ["consumer"]},
            ],
            world_model=model,
        )
        group = plan["groups"][0]
        self.assertLessEqual(len(group["evidence"]), 3)
        self.assertLess(len(group["evidence"]), len(rows))

    def test_provenance_is_retained_for_each_fact(self):
        model = FakeWorldModel([
            fact("call", "consumer", "CALLS", "producer", source="src/consumer.py:4"),
        ])
        plan = analyze_semantic_coupling(
            "preserve producer contract",
            [
                {"id": "p", "goal": "change producer", "targets": ["producer"]},
                {"id": "c", "goal": "update consumer", "targets": ["consumer"]},
            ],
            world_model=model,
        )
        for group in plan["groups"]:
            for evidence in group["evidence"]:
                self.assertTrue(evidence["fact_id"])
                self.assertTrue(evidence["provenance"])
                self.assertTrue(evidence["provenance"][0].get("source_identity"))

    def test_unproven_verified_rows_cannot_drive_semantic_grouping(self):
        model = FakeWorldModel([
            {
                "fact_id": "unproven-call",
                "subject": "consumer",
                "relation": "CALLS",
                "object": "producer",
                "state": "VERIFIED",
                "authority_tier": "HIGH",
                "authority_score": 100,
                "provenance": [],
            },
        ])
        plan = analyze_semantic_coupling(
            "change producer and consumer",
            [
                {"id": "p", "goal": "change producer", "targets": ["producer"]},
                {"id": "c", "goal": "change consumer", "targets": ["consumer"]},
            ],
            world_model=model,
        )
        self.assertEqual(plan["classification"], INDEPENDENT)
        self.assertEqual(plan["groups"], [])

    def test_verified_fact_without_provenance_cannot_enter_world_model(self):
        import tempfile
        with tempfile.TemporaryDirectory() as raw_root:
            model = ProjectWorldModel(raw_root)
            self.assertIsNone(model.add_fact("X", "CALLS", "Y", None, authority_tier="HIGH"))
            self.assertEqual(model.stats["facts_rejected"], 1)

    def test_group_verification_requires_all_members_and_can_fail_semantically(self):
        group = {
            "group_id": "G1",
            "member_ids": ["producer", "consumer"],
            "coupling_types": [PRODUCER_CONSUMER, SHARED_CONTRACT],
            "verification_required": True,
        }
        incomplete = verify_semantic_group(
            group,
            child_results={"producer": {"status": "done"}, "consumer": {"status": "failed"}},
        )
        self.assertFalse(incomplete["passed"])
        self.assertEqual(incomplete["status"], "INCOMPLETE")
        failed = verify_semantic_group(
            group,
            child_results={"producer": {"status": "done"}, "consumer": {"status": "done"}},
            verification_runner=lambda *_: False,
        )
        self.assertFalse(failed["passed"])
        self.assertEqual(failed["status"], "FAILED")

    def test_bounded_neighborhood_is_used(self):
        model = FakeWorldModel([
            fact(str(index), "node", "DEPENDS_ON", f"node_{index}")
            for index in range(30)
        ])
        analyzer = SemanticCouplingAnalyzer(model, max_hops=2, max_facts_per_child=8)
        analyzer.analyze(
            "bounded local analysis",
            [
                {"id": "a", "goal": "modify node", "targets": ["node"]},
                {"id": "b", "goal": "modify other", "targets": ["other"]},
            ],
        )
        self.assertTrue(model.calls)
        self.assertTrue(all(call["max_hops"] <= 2 for call in model.calls))
        self.assertTrue(all(call["max_facts"] <= 8 for call in model.calls))

    def test_benchmark_reports_actual_counts(self):
        result = benchmark_semantic_coupling_scenarios([
            {
                "parent_goal": "independent maintenance",
                "children": [
                    {"id": "a", "goal": "change logging", "targets": ["logging"]},
                    {"id": "b", "goal": "change CLI", "targets": ["cli"]},
                ],
                "expected": INDEPENDENT,
            },
        ])
        self.assertEqual(result["candidate_decompositions"], 1)
        self.assertEqual(result["false_positive_groups"], 0)
        self.assertIn("average_group_size", result)

    def test_decomposition_benchmark_covers_independent_and_coupled_shapes(self):
        model = FakeWorldModel([
            fact("pc-call", "warm_consumer", "CALLS", "warm_producer", source="src/warm_consumer.py:4"),
            fact("pc-field", "warm_consumer", "READS_FIELD", "warm_producer:token", source="src/warm_consumer.py:5"),
            fact("schema-return", "schema_producer", "RETURNS_TYPE", "SchemaResponse", source="src/schema_producer.py:3"),
            fact("schema-field", "SchemaResponse", "DECLARES_FIELD", "token", source="src/schema.py:4"),
            fact("schema-call", "schema_consumer", "CALLS", "schema_producer", source="src/schema_consumer.py:5"),
            fact("state-ab", "state_a", "TRANSITIONS", "IDLE -> RUNNING", source="src/state_a.py:10"),
            fact("state-bc", "state_b", "TRANSITIONS", "RUNNING -> COMPLETE", source="src/state_b.py:12"),
            fact("public-export", "public_index", "EXPORTS", "public_api", source="pkg/index.py:1"),
            fact("public-import", "public_consumer", "IMPORTS", "public_index", source="src/public_consumer.py:2"),
        ])
        scenarios = [
            {
                "parent_goal": "independent maintenance",
                "children": [
                    {"id": "log", "goal": "change logging", "targets": ["logging"]},
                    {"id": "cli", "goal": "change CLI", "targets": ["cli"]},
                ],
                "expected": INDEPENDENT,
            },
            {
                "parent_goal": "migrate warm producer contract",
                "children": [
                    {"id": "warm_p", "goal": "change warm producer", "targets": ["warm_producer"]},
                    {"id": "warm_c", "goal": "update warm consumer", "targets": ["warm_consumer"]},
                ],
                "expected": GROUP,
                "verification_failure": True,
                "child_results": {"warm_p": {"status": "done"}, "warm_c": {"status": "done"}},
            },
            {
                "parent_goal": "migrate SchemaResponse contract",
                "children": [
                    {"id": "schema", "goal": "modify SchemaResponse", "targets": ["SchemaResponse"]},
                    {"id": "schema_p", "goal": "modify schema producer", "targets": ["schema_producer"]},
                    {"id": "schema_c", "goal": "modify schema consumer", "targets": ["schema_consumer"]},
                ],
                "expected": GROUP,
            },
            {
                "parent_goal": "change state lifecycle IDLE -> RUNNING -> COMPLETE",
                "children": [
                    {"id": "state_a", "goal": "modify first state transition", "targets": ["state_a"]},
                    {"id": "state_b", "goal": "modify second state transition", "targets": ["state_b"]},
                ],
                "expected": GROUP,
            },
            {
                "parent_goal": "preserve public API",
                "children": [
                    {"id": "api", "goal": "modify public API", "targets": ["public_api"]},
                    {"id": "index", "goal": "update public export", "targets": ["public_index"]},
                ],
                "expected": GROUP,
            },
            {
                "parent_goal": "generate then consume an artifact",
                "children": [
                    {"id": "generate", "goal": "generate artifact", "targets": ["generator"]},
                    {"id": "consume", "goal": "consume artifact", "targets": ["consumer"]},
                ],
                "known_dependencies": {"consume": ["generate"]},
                "expected": INDEPENDENT,
            },
            {
                "parent_goal": "one inseparable change",
                "children": [
                    {"id": "first", "goal": "change first half of same function", "targets": ["same_function"]},
                    {"id": "second", "goal": "change second half of same function", "targets": ["same_function"]},
                ],
                "expected": MERGE_REQUIRED,
            },
        ]
        result = benchmark_semantic_coupling_scenarios(
            scenarios, analyzer=SemanticCouplingAnalyzer(model),
        )
        print("COUPLING_BENCHMARK " + json.dumps(result, sort_keys=True))
        self.assertEqual(result["candidate_decompositions"], 7)
        self.assertEqual(result["correctly_independent_children"], 4)
        self.assertEqual(result["semantic_groups_detected"], 4)
        self.assertEqual(result["merge_required_cases_detected"], 1)
        self.assertEqual(result["false_positive_groups"], 0)
        self.assertEqual(result["missed_known_couplings"], 0)
        self.assertEqual(result["group_verification_failures_caught"], 1)

    def test_worker_projection_keeps_group_anchor_bounded(self):
        import mini

        saved = (mini.WORKSPACE, mini.RUN, mini.RUN_ID, mini.DASHBOARD)
        try:
            mini.WORKSPACE = None
            mini.RUN = {"project_brain": {}, "project_invariants": []}
            mini.RUN_ID = ""
            mini.DASHBOARD = {}
            task = mini.make_task("child", "update consumer", parent="P")
            task.update({
                "semantic_group_id": "G1",
                "semantic_group_goal": "Migrate producer and consumer together",
                "semantic_group_invariant": "Producer and consumer agree on one return shape",
                "semantic_group_members": ["producer", "consumer", "test"],
                "semantic_group_coupling_types": [PRODUCER_CONSUMER, SHARED_CONTRACT],
                "semantic_group_verification_targets": ["tests/test_contract.py"],
            })
            packet = mini.build_node_context(
                task, {"goal": "root goal", "constraints": []}, None, {"files": []},
            )
            self.assertIn("SEMANTIC WORK GROUP", packet)
            self.assertIn("Migrate producer and consumer together", packet)
            self.assertLessEqual(len(packet), mini.MAX_NODE_PACKET_CHARS)
            anchor = mini._context_anchor_for_worker(
                task["goal"], task["id"], {
                    "root_goal": "root goal",
                    "parent_goal": "parent goal",
                    "group_goal": task["semantic_group_goal"],
                    "group_invariant": task["semantic_group_invariant"],
                },
            )
            self.assertEqual(anchor["root_goal"], "root goal")
            self.assertEqual(anchor["parent_goal"], "parent goal")
            self.assertEqual(anchor["group_goal"], task["semantic_group_goal"])
            self.assertEqual(anchor["group_invariant"], task["semantic_group_invariant"])
        finally:
            mini.WORKSPACE, mini.RUN, mini.RUN_ID, mini.DASHBOARD = saved

    def test_group_verification_passes_only_before_parent_aggregation(self):
        import mini

        saved = (mini.WORKSPACE, mini.RUN, mini.TASKS, mini.RUN_ID, mini.DASHBOARD)
        try:
            mini.WORKSPACE = None
            mini.RUN = mini.new_metrics("test")
            mini.TASKS = {}
            mini.RUN_ID = ""
            mini.DASHBOARD = {}
            parent = mini.make_task("P", "complete coupled change")
            parent["semantic_groups"] = [{
                "group_id": "G1", "goal": "coupled change", "invariant": "one invariant",
                "member_ids": ["a", "b"], "coupling_types": [SHARED_CONTRACT],
                "verification_targets": [], "verification_required": True,
            }]
            parent["semantic_group_verification_runner"] = lambda *_: True
            children = []
            for child_id in ("a", "b"):
                child = mini.make_task(child_id, f"change {child_id}", parent="P")
                child.update({
                    "semantic_group_id": "G1", "semantic_group_goal": "coupled change",
                    "semantic_group_invariant": "one invariant", "semantic_group_members": ["a", "b"],
                    "semantic_group_coupling_types": [SHARED_CONTRACT],
                    "semantic_group_required": True,
                })
                children.append(child)
            calls = []

            def leaf(child, contract, memory, repo_snapshot, parent_summary, dependency_summaries):
                calls.append(f"leaf:{child['id']}")
                return {"status": "done", "summary": "member verified", "memory": memory}

            def aggregate(*_args, **_kwargs):
                calls.append("aggregate")
                return {"status": "done", "summary": "parent verified", "memory": {}}

            result = mini._execute_children(
                parent, children, 0, {}, {}, {"files": []}, "", [],
                lambda *_args: {"decision": "execute"}, leaf, aggregate,
            )
            self.assertEqual(result["status"], "done")
            self.assertEqual(calls[-1], "aggregate")
            self.assertEqual(parent["semantic_group_status"], "COMPLETE")
        finally:
            mini.WORKSPACE, mini.RUN, mini.TASKS, mini.RUN_ID, mini.DASHBOARD = saved

    def test_group_semantic_failure_stops_parent_aggregation_and_requests_recovery(self):
        import mini

        saved = (mini.WORKSPACE, mini.RUN, mini.TASKS, mini.RUN_ID, mini.DASHBOARD)
        try:
            mini.WORKSPACE = None
            mini.RUN = mini.new_metrics("test")
            mini.TASKS = {}
            mini.RUN_ID = ""
            mini.DASHBOARD = {}
            parent = mini.make_task("P", "complete coupled change")
            parent["semantic_groups"] = [{
                "group_id": "G1", "goal": "coupled change", "invariant": "one invariant",
                "member_ids": ["a", "b"], "coupling_types": [SHARED_CONTRACT],
                "verification_targets": [], "verification_required": True,
            }]
            parent["semantic_group_verification_runner"] = lambda *_: False
            children = []
            for child_id in ("a", "b"):
                child = mini.make_task(child_id, f"change {child_id}", parent="P")
                child.update({
                    "semantic_group_id": "G1", "semantic_group_goal": "coupled change",
                    "semantic_group_invariant": "one invariant", "semantic_group_members": ["a", "b"],
                    "semantic_group_coupling_types": [SHARED_CONTRACT],
                    "semantic_group_required": True,
                })
                children.append(child)
            aggregate_calls = []

            def leaf(child, contract, memory, repo_snapshot, parent_summary, dependency_summaries):
                return {"status": "done", "summary": "member locally verified", "memory": memory}

            def aggregate(*_args, **_kwargs):
                aggregate_calls.append(True)
                return {"status": "done", "summary": "unsafe", "memory": {}}

            result = mini._execute_children(
                parent, children, 0, {}, {}, {"files": []}, "", [],
                lambda *_args: {"decision": "execute"}, leaf, aggregate,
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["failure_type"], "SEMANTIC_GROUP_VERIFICATION_FAILED")
            self.assertFalse(aggregate_calls)
            self.assertTrue(result["semantic_group_recovery_required"])
            self.assertTrue(parent["semantic_group_recovery_required"])
        finally:
            mini.WORKSPACE, mini.RUN, mini.TASKS, mini.RUN_ID, mini.DASHBOARD = saved

    def test_replan_attempts_are_bounded_and_reported(self):
        analyzer = SemanticCouplingAnalyzer(max_replan_attempts=99)
        self.assertEqual(analyzer.max_replan_attempts, 2)
        refined = analyzer.refine_decomposition(
            "one inseparable change",
            [
                {"id": "a", "goal": "change first half of X", "targets": ["X"]},
                {"id": "b", "goal": "change second half of X", "targets": ["X"]},
            ],
        )
        self.assertLessEqual(refined["plan"].get("replan_attempts", 0), 2)


if __name__ == "__main__":
    unittest.main()
