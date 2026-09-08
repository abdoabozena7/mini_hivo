import copy
import json
import tempfile
import unittest
from pathlib import Path

import mini
from hivo import pre_mutation_impact as impact
from hivo.context_sufficiency import ContextSufficiencyGate
from hivo.project_world_model import (
    CALLS,
    DEFINED_IN,
    EXPORTS,
    READS_CONFIG,
    RETURNS_TYPE,
    TRANSITIONS,
    ProjectWorldModel,
)


class PreMutationImpactContractTests(unittest.TestCase):
    def setUp(self):
        self._saved = {
            "workspace": mini.WORKSPACE,
            "run": mini.RUN,
            "run_id": mini.RUN_ID,
            "active_contract": mini.ACTIVE_CONTRACT,
            "active_tool_contract": mini.ACTIVE_TOOL_CONTRACT,
            "active_context_gate": mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE,
            "active_world_model": mini.ACTIVE_PROJECT_WORLD_MODEL,
            "active_impact": mini.ACTIVE_IMPACT_CONTRACT,
            "impact_required": mini.ACTIVE_IMPACT_REQUIRED,
            "active_transaction": mini.ACTIVE_TRANSACTION,
            "last_transaction": mini.LAST_COMMITTED_TRANSACTION,
        }
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        mini.WORKSPACE = self.root
        mini.reset_run("pre-mutation-impact-test")
        mini.ACTIVE_TOOL_CONTRACT = {
            "task_id": "impact-test",
            "goal": "keep the bounded impact contract test focused",
        }

    def tearDown(self):
        mini.WORKSPACE = self._saved["workspace"]
        mini.RUN = self._saved["run"]
        mini.RUN_ID = self._saved["run_id"]
        mini.ACTIVE_CONTRACT = self._saved["active_contract"]
        mini.ACTIVE_TOOL_CONTRACT = self._saved["active_tool_contract"]
        mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE = self._saved["active_context_gate"]
        mini.ACTIVE_PROJECT_WORLD_MODEL = self._saved["active_world_model"]
        mini.ACTIVE_IMPACT_CONTRACT = self._saved["active_impact"]
        mini.ACTIVE_IMPACT_REQUIRED = self._saved["impact_required"]
        mini.ACTIVE_TRANSACTION = self._saved["active_transaction"]
        mini.LAST_COMMITTED_TRANSACTION = self._saved["last_transaction"]
        self._temp.cleanup()

    def write(self, relative, content="source\n"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def provenance(self, relative, *, kind="test", excerpt="authoritative source"):
        return {
            "path": relative,
            "location": "line 1",
            "evidence_kind": kind,
            "excerpt": excerpt,
        }

    def model(self, files=()):
        for relative, content in files:
            self.write(relative, content)
        return ProjectWorldModel(self.root)

    def contract(
        self,
        *,
        goal="modify function X",
        targets=("src/a.py",),
        allowed=("src/a.py",),
        model=None,
        relationships=None,
        preservations=None,
        obligations=None,
        root_goal="Ship the bounded change",
        parent_goal="Preserve the existing behavior",
    ):
        target_rows = [
            {"target": item, "path": item, "kind": "path"}
            if isinstance(item, str) else item
            for item in targets
        ]
        task = {
            "id": "impact-test",
            "goal": goal,
            "root_goal": root_goal,
            "parent_goal": parent_goal,
            "allowed_mutation_paths": list(allowed),
            "done_when": ["the intended bounded behavior is verified"],
        }
        return impact.build_pre_mutation_impact_contract(
            task,
            root_goal=root_goal,
            parent_goal=parent_goal,
            local_task=goal,
            expected_targets=target_rows,
            expected_relationship_changes=relationships,
            required_preservations=preservations,
            verification_obligations=obligations,
            world_model=model,
        )

    @staticmethod
    def accept(candidate, **kwargs):
        accepted = impact.accept_pre_mutation_impact_contract(candidate, **kwargs)
        if not accepted.get("accepted"):
            raise AssertionError(accepted)
        return accepted["contract"]

    @staticmethod
    def sufficient_gate():
        gate = ContextSufficiencyGate(
            {
                "root_goal": "Ship the bounded change",
                "parent_goal": "Preserve the existing behavior",
                "local_task": "modify the bounded target",
                "requirements": ["the intended behavior remains verified"],
                "constraints": ["do not touch unrelated files"],
            },
            initial_evidence=[{
                "kind": "contract",
                "source_identity": "src/a.py:1",
                "excerpt": "The target contract and preservation behavior are known.",
            }],
        )
        result = gate.evaluate({
            "context_status": "sufficient",
            "reason": "the bounded contract and preservation evidence are present",
        })
        assert result["mutation_allowed"]
        return gate

    def activate_runtime_gate(self, candidate, gate=None):
        mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE = gate or self.sufficient_gate()
        mini.ACTIVE_IMPACT_REQUIRED = True
        mini.RUN["impact_contract_required"] = True
        mini.ACTIVE_IMPACT_CONTRACT = candidate

    def test_simple_valid_impact_contract_is_accepted(self):
        self.write("src/a.py")
        candidate = self.contract()
        accepted = self.accept(candidate)
        self.assertEqual(accepted["status"], impact.IMPACT_ACCEPTED)
        self.assertTrue(accepted["change_intent"]["text"])
        self.assertTrue(accepted["expected_targets"])
        self.assertTrue(accepted["verification_obligations"])
        self.assertIsNone(impact.impact_mutation_block_reason(accepted))

    def test_missing_known_consumer_rejects_contract_before_mutation(self):
        model = self.model([
            ("src/a.py", "def A(value):\n    return value\n"),
            ("src/b.py", "def B(value):\n    return A(value)\n"),
        ])
        model.add_fact("B", CALLS, "A", self.provenance("src/b.py"), authority_tier="HIGH", authority_score=100)
        candidate = self.contract(
            goal="change A public return contract",
            targets=({"target": "A", "kind": "symbol"},),
            allowed=("src/a.py",),
            model=None,
        )
        validation = impact.validate_pre_mutation_impact_contract(
            candidate, world_model=model, allowed_mutation_paths=["src/a.py"],
        )
        self.assertFalse(validation["valid"])
        self.assertTrue(any(item["code"] == impact.EXPECTED_BUT_MISSING for item in validation["errors"]))
        self.assertIn("b", json.dumps(validation["errors"]).casefold())

    def test_context_sufficient_but_unaccepted_impact_blocks_runtime_mutation(self):
        path = self.write("src/a.py", "old\n")
        self.activate_runtime_gate(self.contract(), self.sufficient_gate())
        result = mini.run_tool(
            "edit_file",
            {"path": "src/a.py", "old": "old", "new": "new"},
            role="Builder",
        )
        self.assertIn(impact.IMPACT_REQUIRED, result)
        self.assertEqual(path.read_text(encoding="utf-8"), "old\n")

    def test_impact_contract_cannot_substitute_for_context_gate(self):
        path = self.write("src/a.py", "old\n")
        candidate = self.accept(self.contract())
        mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE = None
        mini.ACTIVE_IMPACT_REQUIRED = True
        mini.ACTIVE_IMPACT_CONTRACT = candidate
        mini.RUN["impact_contract_required"] = True
        result = mini.run_tool(
            "edit_file",
            {"path": "src/a.py", "old": "old", "new": "new"},
            role="Builder",
        )
        self.assertIn("CONTEXT_SUFFICIENCY_REQUIRED", result)
        self.assertEqual(path.read_text(encoding="utf-8"), "old\n")

    def test_worker_claimed_acceptance_without_controller_marker_is_forged(self):
        path = self.write("src/a.py", "old\n")
        candidate = self.contract()
        candidate.update({
            "status": impact.IMPACT_ACCEPTED,
            "controller_accepted": True,
            "accepted_contract_hash": "worker-claimed",
            "authorization_token": "worker-claimed",
        })
        self.activate_runtime_gate(candidate)
        result = mini.run_tool(
            "edit_file",
            {"path": "src/a.py", "old": "old", "new": "new"},
            role="Builder",
        )
        self.assertIn(impact.IMPACT_INVALID, result)
        self.assertEqual(path.read_text(encoding="utf-8"), "old\n")

    def test_expected_exact_impact_passes(self):
        self.write("src/a.py")
        self.write("src/b.py")
        candidate = self.accept(self.contract(targets=("src/a.py", "src/b.py"), allowed=("src/a.py", "src/b.py")))
        actual = impact.capture_actual_mutation_impact(
            before={"files": {"src/a.py": "a", "src/b.py": "b"}},
            after={"files": {"src/a.py": "a2", "src/b.py": "b2"}},
            changed_paths=["src/a.py", "src/b.py"],
        )
        comparison = impact.compare_pre_mutation_impact(
            candidate, actual, verification_result={"passed": True},
        )
        self.assertTrue(comparison["passed"])
        self.assertFalse(comparison["missing"])

    def test_missing_expected_impact_is_reported_even_if_verification_passes(self):
        candidate = self.accept(self.contract(targets=("src/a.py", "src/b.py"), allowed=("src/a.py", "src/b.py")))
        actual = {"changed_paths": ["src/a.py"], "verification_evidence": [{"status": "PASS"}]}
        comparison = impact.compare_pre_mutation_impact(
            candidate, actual, verification_result={"passed": True},
        )
        self.assertFalse(comparison["passed"])
        self.assertTrue(any(row["target"] == "src/b.py" for row in comparison["missing"]))
        self.assertIn(impact.EXPECTED_BUT_MISSING, json.dumps(comparison["comparisons"]))

    def test_unrelated_extra_mutation_is_out_of_scope(self):
        candidate = self.accept(self.contract())
        comparison = impact.compare_pre_mutation_impact(
            candidate,
            {"changed_paths": ["src/a.py", "billing/invoice.py"]},
            verification_result={"passed": True},
        )
        self.assertFalse(comparison["passed"])
        self.assertEqual(comparison["out_of_scope"][0]["status"], impact.UNEXPECTED_AND_OUT_OF_SCOPE)

    def test_related_unexpected_target_can_be_added_only_by_bounded_revision(self):
        model = self.model([
            ("src/a.py", "def A():\n    return 1\n"),
            ("pkg/__init__.py", "from src.a import A\n"),
        ])
        model.add_fact(
            "pkg/__init__.py", EXPORTS, "A", self.provenance("pkg/__init__.py"),
            authority_tier="HIGH", authority_score=100,
        )
        model.add_fact(
            "A", DEFINED_IN, "src/a.py", self.provenance("src/a.py"),
            authority_tier="HIGH", authority_score=100,
        )
        candidate = self.accept(self.contract(allowed=(), model=model), world_model=model)
        comparison = impact.compare_pre_mutation_impact(
            candidate,
            {"changed_paths": ["src/a.py", "pkg/__init__.py"]},
            world_model=model,
            verification_result={"passed": True},
        )
        self.assertTrue(comparison["unexpected_related"])
        self.assertFalse(comparison["out_of_scope"])
        revision = impact.revise_pre_mutation_impact_contract(
            candidate,
            [{
                "target": "pkg/__init__.py",
                "path": "pkg/__init__.py",
                "provenance": [self.provenance("pkg/__init__.py", kind="export")],
            }],
            world_model=model,
        )
        self.assertTrue(revision["revised"])
        revised = self.accept(revision["contract"], world_model=model)
        self.assertIsNone(impact.impact_mutation_block_reason(revised, world_model=model))
        final = impact.compare_pre_mutation_impact(
            revised,
            {"changed_paths": ["src/a.py", "pkg/__init__.py"]},
            world_model=model,
            verification_result={"passed": True},
        )
        self.assertTrue(final["passed"])

    def test_revision_stops_at_configured_limit(self):
        candidate = self.accept(self.contract())
        current = candidate
        for index in range(impact.MAX_IMPACT_REVISIONS):
            revision = impact.revise_pre_mutation_impact_contract(
                current,
                [{"target": f"src/a.py::related_{index}", "path": "src/a.py"}],
            )
            self.assertTrue(revision["revised"])
            current = revision["contract"]
        exhausted = impact.revise_pre_mutation_impact_contract(
            current, [{"target": "src/a.py::one_more", "path": "src/a.py"}],
        )
        self.assertFalse(exhausted["revised"])
        self.assertEqual(exhausted["status"], impact.IMPACT_REPLAN_REQUIRED)

    def test_goal_drift_cannot_expand_contract_to_unrelated_billing(self):
        candidate = self.accept(self.contract(goal="repair auth contract"))
        revision = impact.revise_pre_mutation_impact_contract(
            candidate,
            [{"target": "billing_refactor", "path": "billing/invoice.py"}],
            reason="the worker claims billing is also important",
        )
        self.assertFalse(revision["revised"])
        self.assertEqual(revision["status"], impact.IMPACT_REPLAN_REQUIRED)
        self.assertNotIn("billing_refactor", json.dumps(revision["contract"]))

    def test_contract_relationship_delta_requires_new_semantic_value(self):
        candidate = self.accept(self.contract(
            goal="change A return contract from OldType to NewType",
            relationships=[{
                "subject": "A",
                "relation": RETURNS_TYPE,
                "before": "OldType",
                "after": "NewType",
                "required": True,
            }],
        ))
        comparison = impact.compare_pre_mutation_impact(
            candidate,
            {
                "changed_paths": ["src/a.py"],
                "observed_relationships": [{
                    "subject": "A", "relation": RETURNS_TYPE, "after": "NewType",
                }],
            },
            verification_result={"passed": True},
        )
        self.assertTrue(comparison["passed"])

    def test_editing_the_expected_file_with_old_semantics_fails(self):
        candidate = self.accept(self.contract(
            goal="change A return contract from OldType to NewType",
            relationships=[{
                "subject": "A", "relation": RETURNS_TYPE,
                "before": "OldType", "after": "NewType", "required": True,
            }],
        ))
        comparison = impact.compare_pre_mutation_impact(
            candidate,
            {
                "changed_paths": ["src/a.py"],
                "observed_relationships": [{
                    "subject": "A", "relation": RETURNS_TYPE, "after": "OldType",
                }],
            },
            verification_result={"passed": True},
        )
        self.assertFalse(comparison["passed"])
        self.assertTrue(comparison["missing"])

    def test_preservation_violation_blocks_completion(self):
        candidate = self.accept(self.contract(
            preservations=[{
                "id": "auth-failure",
                "meaning": "authentication failure still raises AuthError",
                "target": "A",
            }],
        ))
        comparison = impact.compare_pre_mutation_impact(
            candidate,
            {
                "changed_paths": ["src/a.py"],
                "preservation_violations": [{
                    "id": "auth-failure", "meaning": "AuthError failure path disappeared",
                }],
            },
            verification_result={"passed": True},
        )
        self.assertFalse(comparison["passed"])
        self.assertEqual(comparison["preservation_violations"][0]["status"], impact.PRESERVATION_VIOLATED)

    def test_required_obligation_remains_unresolved_without_evidence(self):
        candidate = self.accept(self.contract(
            obligations=[{
                "id": "caller-contract",
                "category": "CALLER_CONSUMER",
                "meaning": "caller B consumes the token field",
                "target": "B",
                "required": True,
            }],
        ))
        comparison = impact.compare_pre_mutation_impact(
            candidate,
            {"changed_paths": ["src/a.py"]},
            verification_result={"passed": True},
        )
        self.assertFalse(comparison["passed"])
        self.assertEqual(comparison["unresolved_obligations"][0]["status"], impact.UNRESOLVED)

    def test_required_obligation_can_be_satisfied_by_current_structural_fact(self):
        model = self.model([
            ("src/b.py", "def B():\n    return A()\n"),
            ("src/a.py", "def A():\n    return 1\n"),
        ])
        model.add_fact("B", CALLS, "A", self.provenance("src/b.py"), authority_tier="HIGH", authority_score=100)
        candidate = self.accept(self.contract(
            model=model,
            obligations=[{
                "id": "caller-contract", "meaning": "caller B consumes A", "target": "B",
            }],
        ), world_model=model)
        comparison = impact.compare_pre_mutation_impact(
            candidate,
            {"changed_paths": ["src/a.py"]},
            world_model=model,
            verification_result={"passed": True},
        )
        self.assertTrue(comparison["passed"])
        self.assertEqual(comparison["obligations"][0]["status"], impact.SATISFIED)

    def _member_contract(self, relative):
        self.write(relative)
        return self.accept(self.contract(
            goal=f"modify {relative} in the semantic group",
            targets=(relative,), allowed=(relative,),
        ))

    def test_semantic_group_local_success_does_not_override_group_failure(self):
        child_a = self._member_contract("src/producer.py")
        child_b = self._member_contract("src/consumer.py")
        group = {
            "group_id": "token-migration",
            "member_ids": ["producer", "consumer"],
            "goal": "migrate the shared token contract",
            "invariant": "producer and consumer agree on one token shape",
        }
        completed = [
            {"task": {"id": "producer"}, "result": {
                "status": "done", "changed_files": ["src/producer.py"],
                "impact_contract": child_a,
                "impact_comparison": {"passed": True, "status": impact.IMPACT_PASSED},
            }},
            {"task": {"id": "consumer"}, "result": {
                "status": "done", "changed_files": ["src/consumer.py"],
                "impact_contract": child_b,
                "impact_comparison": {"passed": True, "status": impact.IMPACT_PASSED},
            }},
        ]
        result = mini._semantic_group_impact_verification(
            group, completed, {"id": "parent", "goal": "finish token migration"},
            semantic_result={"passed": False},
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["comparison"]["status"], impact.IMPACT_VERIFICATION_FAILED)

    def test_semantic_group_integrated_success_requires_group_comparison(self):
        child_a = self._member_contract("src/producer.py")
        child_b = self._member_contract("src/consumer.py")
        group = {
            "group_id": "token-migration",
            "member_ids": ["producer", "consumer"],
            "goal": "migrate the shared token contract",
            "invariant": "producer and consumer agree on one token shape",
        }
        completed = [
            {"task": {"id": "producer"}, "result": {
                "status": "done", "changed_files": ["src/producer.py"],
                "impact_contract": child_a,
                "impact_comparison": {"passed": True, "status": impact.IMPACT_PASSED},
            }},
            {"task": {"id": "consumer"}, "result": {
                "status": "done", "changed_files": ["src/consumer.py"],
                "impact_contract": child_b,
                "impact_comparison": {"passed": True, "status": impact.IMPACT_PASSED},
            }},
        ]
        result = mini._semantic_group_impact_verification(
            group, completed, {"id": "parent", "goal": "finish token migration"},
            semantic_result={"passed": True},
        )
        self.assertTrue(result["passed"])
        self.assertTrue(result["comparison"]["passed"])

    def test_stale_world_model_cannot_satisfy_impact_authorization(self):
        path = self.write("src/a.py", "old\n")
        model = ProjectWorldModel(self.root)
        model.add_fact("A", RETURNS_TYPE, "OldType", self.provenance("src/a.py"), authority_tier="HIGH", authority_score=100)
        candidate = self.accept(self.contract(
            model=model,
            targets=({"target": "A", "kind": "symbol", "path": "src/a.py"},),
        ), world_model=model)
        path.write_text("changed\n", encoding="utf-8")
        model.refresh_currentness()
        self.assertIsNotNone(impact.impact_mutation_block_reason(candidate, world_model=model))
        comparison = impact.compare_pre_mutation_impact(
            candidate,
            {"changed_paths": ["src/a.py"]},
            world_model=model,
            verification_result={"passed": True},
        )
        self.assertFalse(comparison["passed"])
        self.assertEqual(comparison["status"], impact.IMPACT_INVALID)

    def test_rollback_restores_world_model_without_ghost_post_state(self):
        path = self.write("src/a.py", "old\n")
        model = ProjectWorldModel(self.root)
        source = self.provenance("src/a.py")
        model.add_fact("A", DEFINED_IN, "src/a.py", source, authority_tier="HIGH", authority_score=100)
        mini.ACTIVE_PROJECT_WORLD_MODEL = model
        mini.begin_transaction("rollback-impact")
        result = mini.edit_file("src/a.py", "old", "new")
        self.assertIn("edited file", result)
        model.add_fact(
            "A", RETURNS_TYPE, "GhostPostState", self.provenance("src/a.py"),
            authority_tier="HIGH", authority_score=100,
        )
        mini.rollback_transaction()
        self.assertEqual(path.read_text(encoding="utf-8"), "old\n")
        states = {(fact.relation, fact.object): fact.state for fact in model.facts}
        self.assertEqual(states[(DEFINED_IN, "src/a.py")], "VERIFIED")
        self.assertNotEqual(states.get((RETURNS_TYPE, "GhostPostState")), "VERIFIED")

    def test_trivial_task_has_small_contract(self):
        candidate = self.contract(goal="change one help string", targets=("src/a.py",), allowed=("src/a.py",))
        accepted = self.accept(candidate)
        projection = impact.project_impact_contract(accepted)
        self.assertLessEqual(len(accepted["expected_targets"]), 2)
        self.assertLessEqual(len(accepted["verification_obligations"]), 1)
        self.assertLessEqual(len(projection["rendered"]), impact.MAX_IMPACT_PROJECTION_CHARS)

    def test_lexically_similar_out_of_scope_path_is_not_related(self):
        candidate = self.accept(self.contract(goal="modify refresh_token", targets=("src/auth.py",), allowed=("src/auth.py",)))
        comparison = impact.compare_pre_mutation_impact(
            candidate,
            {"changed_paths": ["src/refresh_token_legacy.py"]},
            verification_result={"passed": True},
        )
        self.assertFalse(comparison["passed"])
        self.assertEqual(comparison["out_of_scope"][0]["status"], impact.UNEXPECTED_AND_OUT_OF_SCOPE)

    def test_configuration_relation_is_recorded(self):
        model = self.model([("src/auth.py", "AUTH_MODE = 'strict'\n")])
        model.add_fact("A", READS_CONFIG, "AUTH_MODE", self.provenance("src/auth.py"), authority_tier="HIGH", authority_score=100)
        candidate = self.contract(
            goal="change configuration-dependent authentication behavior",
            targets=({"target": "A", "kind": "symbol"},), allowed=("src/auth.py",), model=model,
        )
        relations = {(row["subject"], row["relation"], row["object"]) for row in candidate["expected_relationship_changes"]}
        self.assertIn(("A", READS_CONFIG, "AUTH_MODE"), relations)

    def test_public_surface_relation_is_recorded(self):
        model = self.model([
            ("src/auth.py", "def A():\n    return 1\n"),
            ("pkg/__init__.py", "from src.auth import A\n"),
        ])
        model.add_fact("pkg.__init__", EXPORTS, "A", self.provenance("pkg/__init__.py"), authority_tier="HIGH", authority_score=100)
        candidate = self.contract(
            goal="preserve the public export surface for A",
            targets=({"target": "A", "kind": "symbol"},), allowed=("src/auth.py",), model=model,
        )
        self.assertTrue(any(row["relation"] == EXPORTS for row in candidate["expected_relationship_changes"]))

    def test_state_transition_relation_is_recorded(self):
        model = self.model([("src/state.py", "state = 'RUNNING'\n")])
        model.add_fact("worker", TRANSITIONS, "RUNNING -> COMPLETE", self.provenance("src/state.py"), authority_tier="HIGH", authority_score=100)
        candidate = self.contract(
            goal="change the RUNNING to COMPLETE state transition",
            targets=({"target": "worker", "kind": "symbol"},), allowed=("src/state.py",), model=model,
        )
        self.assertTrue(any(row["relation"] == TRANSITIONS for row in candidate["expected_relationship_changes"]))

    def test_context_gate_alone_never_unlocks_mutation(self):
        path = self.write("src/a.py", "old\n")
        gate = self.sufficient_gate()
        mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE = gate
        mini.ACTIVE_IMPACT_CONTRACT = None
        mini.ACTIVE_IMPACT_REQUIRED = True
        mini.RUN["impact_contract_required"] = True
        result = mini.run_tool(
            "edit_file",
            {"path": "src/a.py", "old": "old", "new": "new"},
            role="Builder",
        )
        self.assertIn(impact.IMPACT_REQUIRED, result)
        self.assertEqual(path.read_text(encoding="utf-8"), "old\n")

    def test_benchmark_reports_zero_incorrectly_allowed_mutations(self):
        metrics = impact.benchmark_impact_contract_scenarios()
        print("IMPACT_BENCHMARK " + json.dumps(metrics, sort_keys=True))
        self.assertEqual(metrics["incorrect_successful_mutations_allowed"], 0)
        self.assertTrue(metrics["bounded"])
        self.assertGreaterEqual(metrics["contracts_evaluated"], 10)


if __name__ == "__main__":
    unittest.main()
