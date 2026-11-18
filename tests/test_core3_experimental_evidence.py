from __future__ import annotations

import hashlib
import tempfile
import time
import unittest
from pathlib import Path

from hivo.diagnostic_hypotheses import (
    DiagnosticBudget,
    DiagnosticFailureEvidence,
    DiagnosticHypothesis,
    ELIMINATED,
    STRONGLY_WEAKENED,
    SUPPORTED,
    seed_hypotheses,
)
from hivo.experiment_sandbox import (
    DNT_PROTECTED,
    EPHEMERAL_PROBE_ALLOWED,
    EXPERIMENTAL_PROBE_BLOCKED_DNT,
    CounterfactualMutationSpec,
    ExperimentalSandbox,
    SandboxSecurityError,
    canonical_subject_hash,
    classify_probe_permission,
)
from hivo.experiment_selector import (
    COUNTERFACTUAL_MUTATION,
    DiagnosticExperiment,
    ExperimentSelector,
)
from hivo.experimental_evidence import (
    BASELINE_NOT_REPRODUCED,
    BASELINE_REPRODUCED,
    BASELINE_UNSTABLE_STATUS,
    EVIDENCE_INVALID,
    EVIDENCE_SUFFICIENT,
    ExperimentalEvidenceEngine,
    MASKING_RISK,
    TARGET_TEST_FAILS,
    TARGET_TEST_PASSES,
    generate_dependency_stub_experiment,
    generate_input_perturbation_experiment,
    generate_test_failure_experiments,
)
from hivo.lexical_index import build_lexical_index
from hivo.project_brain_refs import ProjectBrainEntity, TypedReference
from hivo.repo_intelligence import search_repository
from hivo.repository_map import build_repository_map


class Core3ExperimentalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._write("src/checkout.js", "export function total() { return 10; }\n")
        self._write("src/tax.js", "export function tax() { return 2; }\n")
        self._write("src/display.js", "export function display(value) { return String(value); }\n")
        self._write("src/dnt.js", "export function protectedValue() { return 1; }\n")
        self._write("tests/checkout.test.js", "import { total } from '../src/checkout.js';\ntest('checkout total', () => total());\n")
        self._write("tests/checkout.guard.test.js", "import { display } from '../src/display.js';\ntest('display guard', () => display(10));\n")
        self.map = build_repository_map(self.root)
        self.index = build_lexical_index(self.map, self.root)
        self.search = search_repository("checkout total", self.map, self.root, lexical_index=self.index)

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _failure(self, expected=TARGET_TEST_FAILS):
        return DiagnosticFailureEvidence(
            failure_id="failure-1", source_type="TEST_FAILURE",
            expected_outcome=expected, message="checkout total is incorrect",
            references=(TypedReference("symbol", "src/checkout.js", "total"),),
            test_name="checkout total",
        )

    def _engine_session(self, hypotheses, *, budget=None):
        engine = ExperimentalEvidenceEngine(
            self.root, repository_map=self.map, working_set=self.search.working_set,
            dnt_paths=("src/dnt.js",), budget=budget,
        )
        session = engine.create_session("checkout-failure", self._failure(), hypotheses=hypotheses)
        return engine, session

    def _runner(self, sandbox: Path, check: str):
        checkout = (sandbox / "src/checkout.js").read_text(encoding="utf-8")
        if check == "target":
            passed = "return 20" in checkout
            return {"passed": passed, "outcome": TARGET_TEST_PASSES if passed else TARGET_TEST_FAILS}
        if check == "masking-target":
            passed = "return 999" in checkout or "return 20" in checkout
            return {"passed": passed, "outcome": TARGET_TEST_PASSES if passed else TARGET_TEST_FAILS}
        if check == "guard":
            passed = "return 999" not in checkout
            return {"passed": passed, "outcome": TARGET_TEST_PASSES if passed else "GUARD_TEST_FAILS"}
        return {"passed": False, "outcome": TARGET_TEST_FAILS}

    def _spec(self, replacement: str, *, hypotheses=("H1",), path="src/checkout.js"):
        target = self.root / path
        return CounterfactualMutationSpec(
            TypedReference("file", path),
            expected_current_hash=hashlib.sha256(target.read_bytes()).hexdigest(),
            expected_anchor="return 10",
            temporary_replacement=replacement,
            reason="test bounded diagnostic probe",
            hypothesis_ids=hypotheses,
        )

    def test_canonical_models_are_deterministic_and_brain_is_not_copied(self):
        failure = self._failure()
        h = DiagnosticHypothesis("H1", "checkout implementation is suspect", failure.references)
        engine, session = self._engine_session((h,))
        self.assertEqual(session.canonical_hash, session.canonical_hash)
        self.assertEqual(h.canonical_hash, DiagnosticHypothesis("H1", "checkout implementation is suspect", failure.references).canonical_hash)
        self.assertEqual(session.working_set_identity, self.search.working_set.canonical_hash)
        self.assertNotIn("source_body", h.to_dict())
        self.assertEqual(engine.ledger.entries, ())

    def test_hypotheses_seed_from_core2_working_set_with_bounded_references(self):
        seeded = seed_hypotheses(self._failure(), self.search.working_set, max_seeds=6)
        self.assertGreaterEqual(len(seeded), 1)
        self.assertLessEqual(len(seeded), 6)
        self.assertTrue(all(item.target_references for item in seeded))
        self.assertTrue(all(item.initial_confidence_class == "SUSPECT" for item in seeded))

    def test_reproducible_baseline_precedes_probe_and_canonical_is_unchanged(self):
        h1 = DiagnosticHypothesis("H1", "checkout total implementation is wrong", (TypedReference("file", "src/checkout.js"),))
        h2 = DiagnosticHypothesis("H2", "tax output is wrong", (TypedReference("file", "src/tax.js"),))
        engine, session = self._engine_session((h1, h2))
        spec = self._spec("return 20", hypotheses=("H1",))
        experiment = DiagnosticExperiment(
            "E1", COUNTERFACTUAL_MUTATION, "change checkout total temporarily",
            ("H1", "H2"), (TypedReference("file", "src/checkout.js"),),
            (("H1", TARGET_TEST_PASSES), ("H2", TARGET_TEST_FAILS)),
            "anchored replacement", ("target",), ("isolated_copy", "syntax_validation"),
            "MEDIUM", "CONTROLLED", 2, mutation_spec=spec,
            metadata={"guard_checks": ("guard",)},
        )
        before = canonical_subject_hash(self.root)
        result = engine.run(session, (experiment,), expected_baseline_outcome=TARGET_TEST_FAILS, runner=self._runner)
        self.assertEqual(BASELINE_REPRODUCED, result.baseline_receipt.status)
        self.assertEqual(EVIDENCE_SUFFICIENT, result.status)
        self.assertEqual(1, len(result.experiments_executed))
        self.assertEqual("VALID", result.experiments_executed[0].validity)
        self.assertEqual(SUPPORTED, result.hypotheses_after[0].status)
        self.assertIn(result.hypotheses_after[1].status, {STRONGLY_WEAKENED, ELIMINATED})
        self.assertTrue(result.canonical_subject_unchanged)
        self.assertEqual(before, canonical_subject_hash(self.root))
        self.assertEqual(0, result.metrics["provider_calls"])

    def test_wrong_but_passing_probe_is_masking_risk(self):
        h1 = DiagnosticHypothesis("H1", "checkout implementation is wrong", (TypedReference("file", "src/checkout.js"),))
        engine, session = self._engine_session((h1,))
        experiment = DiagnosticExperiment(
            "E-mask", COUNTERFACTUAL_MUTATION, "bypass checkout behavior", ("H1",),
            (TypedReference("file", "src/checkout.js"),), (("H1", TARGET_TEST_PASSES),),
            "replace with bypass", ("masking-target",), ("isolated_copy",),
            "MEDIUM", "CONTROLLED", 1, mutation_spec=self._spec("return 999"),
            metadata={"guard_checks": ("guard",), "bypass_feature": True},
        )
        result = engine.run(session, (experiment,), expected_baseline_outcome=TARGET_TEST_FAILS, runner=self._runner)
        receipt = result.experiments_executed[0]
        self.assertEqual(("guard_regression",), receipt.masking_risks)
        self.assertIn(MASKING_RISK, result.masking_risks[0]["risk"])
        self.assertNotEqual(SUPPORTED, result.hypotheses_after[0].status)
        self.assertEqual(EVIDENCE_INVALID if False else "VALID", receipt.validity)

    def test_non_reproducing_and_unstable_baselines_block_causal_updates(self):
        h = DiagnosticHypothesis("H1", "checkout implementation is wrong")
        engine, session = self._engine_session((h,))
        no_repro = engine.run(session, (), expected_baseline_outcome=TARGET_TEST_FAILS, runner=lambda _root, _check: True)
        self.assertEqual(BASELINE_NOT_REPRODUCED, no_repro.baseline_receipt.status)
        self.assertEqual("BLOCKED", no_repro.status)
        self.assertEqual(0, len(no_repro.experiments_executed))
        engine2, session2 = self._engine_session((h,))
        unstable = engine2.run(
            session2, (), expected_baseline_outcome=TARGET_TEST_FAILS,
            runner=lambda _root, _check: False,
            confirmation_runner=lambda _root, _check: True,
        )
        self.assertEqual(BASELINE_UNSTABLE_STATUS, unstable.baseline_receipt.status)
        self.assertEqual("BASELINE_UNSTABLE", unstable.status)
        self.assertEqual(0, unstable.metrics["hypotheses_supported"])

    def test_invalid_syntax_probe_is_invalid_and_does_not_update_hypothesis(self):
        h = DiagnosticHypothesis("H1", "checkout implementation is wrong")
        engine, session = self._engine_session((h,))
        experiment = DiagnosticExperiment(
            "E-invalid", COUNTERFACTUAL_MUTATION, "invalid probe", ("H1",),
            (TypedReference("file", "src/checkout.js"),), (("H1", TARGET_TEST_PASSES),),
            "unbalanced replacement", ("target",), ("isolated_copy",),
            "MEDIUM", "CONTROLLED", 1, mutation_spec=self._spec("return 20 }")
        )
        result = engine.run(session, (experiment,), expected_baseline_outcome=TARGET_TEST_FAILS, runner=self._runner)
        receipt = result.experiments_executed[0]
        self.assertEqual(EVIDENCE_INVALID, receipt.validity)
        self.assertEqual("INVALID_INTERVENTION", receipt.status)
        self.assertEqual(0, result.hypotheses_after[0].current_evidence_score)

    def test_dnt_and_outside_root_probes_are_rejected(self):
        permission = classify_probe_permission("src/dnt.js", self.root, dnt_paths=("src/dnt.js",))
        self.assertEqual(DNT_PROTECTED, permission.classification)
        self.assertFalse(permission.probe_allowed)
        with self.assertRaises((ValueError, SandboxSecurityError)):
            classify_probe_permission("../outside.js", self.root)
        with ExperimentalSandbox(self.root, session_id="dnt", dnt_paths=("src/dnt.js",)) as sandbox:
            spec = CounterfactualMutationSpec(
                TypedReference("file", "src/dnt.js"), expected_anchor="return 1",
                temporary_replacement="return 2", reason="must be blocked",
            )
            result = sandbox.apply_mutation(spec)
            self.assertEqual(EXPERIMENTAL_PROBE_BLOCKED_DNT, result.status)
            self.assertFalse(result.filesystem_changed)

    def test_ephemeral_permission_does_not_authorize_final_mutation(self):
        permission = classify_probe_permission("src/checkout.js", self.root, authority={"allow_ephemeral_probes": True})
        self.assertEqual(EPHEMERAL_PROBE_ALLOWED, permission.classification)
        self.assertTrue(permission.probe_allowed)
        self.assertFalse(permission.final_mutation_authorized)

    def test_sandbox_is_destroyed_and_canonical_tree_unchanged(self):
        before = canonical_subject_hash(self.root)
        with ExperimentalSandbox(self.root, session_id="cleanup") as sandbox:
            self.assertTrue(sandbox.sandbox_root.exists())
            self.assertGreater(sandbox.sandbox_files_materialized, 0)
            self.assertEqual(before, canonical_subject_hash(self.root))
        self.assertTrue(sandbox.destroyed)
        self.assertIsNone(sandbox.sandbox_root)
        self.assertEqual(before, canonical_subject_hash(self.root))

    def test_selector_uses_discrimination_cost_and_suppresses_duplicates(self):
        hypotheses = tuple(DiagnosticHypothesis(f"H{i}", f"hypothesis {i}") for i in range(1, 5))
        cheap = DiagnosticExperiment(
            "E-cheap", "TARGETED_TEST", "cheap discriminating", tuple(item.hypothesis_id for item in hypotheses),
            predicted_outcomes=(("H1", TARGET_TEST_PASSES), ("H2", TARGET_TEST_FAILS), ("H3", TARGET_TEST_PASSES), ("H4", TARGET_TEST_FAILS)),
            estimated_cost_class="CHEAP", risk_class="LOW", expected_discrimination_score=2,
        )
        expensive = DiagnosticExperiment(
            "E-expensive", "COUNTERFACTUAL_MUTATION", "expensive uniform", tuple(item.hypothesis_id for item in hypotheses),
            predicted_outcomes=(("H1", TARGET_TEST_PASSES), ("H2", TARGET_TEST_PASSES), ("H3", TARGET_TEST_PASSES), ("H4", TARGET_TEST_PASSES)),
            estimated_cost_class="EXPENSIVE", risk_class="CONTROLLED", expected_discrimination_score=0,
        )
        selector = ExperimentSelector()
        decision = selector.rank((expensive, cheap), hypotheses)
        self.assertEqual("E-cheap", decision.selected.experiment_id)
        duplicate = selector.rank((cheap,), hypotheses, executed_hashes=(cheap.canonical_hash,))
        self.assertIsNone(duplicate.selected)
        self.assertEqual("duplicate_experiment", duplicate.skipped[0]["reason"])

    def test_generators_cover_baseline_input_dependency_and_counterfactual_paths(self):
        h = DiagnosticHypothesis("H1", "dependency output is wrong")
        engine, session = self._engine_session((h,))
        generated = generate_test_failure_experiments(session, target_check="target", guard_checks=("guard",), mutation_specs=(self._spec("return 20"),))
        self.assertIn("BASELINE_REPRODUCTION", {item.kind for item in generated})
        self.assertIn(COUNTERFACTUAL_MUTATION, {item.kind for item in generated})
        dependency = generate_dependency_stub_experiment(session, check="target", stub_description="stub dependency A", predicted_outcomes={"H1": TARGET_TEST_PASSES})
        perturbation = generate_input_perturbation_experiment(session, check="target", description="perturb input", predicted_outcomes={"H1": TARGET_TEST_FAILS})
        self.assertEqual("DEPENDENCY_STUB", dependency.kind)
        self.assertEqual("INPUT_PERTURBATION", perturbation.kind)
        self.assertEqual(engine.budget.max_total_experiments, 6)

    def test_ledger_is_separate_from_brain_and_receipts_are_hash_bound(self):
        h = DiagnosticHypothesis("H1", "checkout implementation is wrong")
        engine, session = self._engine_session((h,))
        experiment = DiagnosticExperiment("E-observe", "OBSERVATION_ONLY", "observe", ("H1",), predicted_outcomes=(("H1", TARGET_TEST_FAILS),), verification_checks=("target",))
        result = engine.run(session, (experiment,), expected_baseline_outcome=TARGET_TEST_FAILS, runner=self._runner)
        self.assertEqual(session.evidence_ledger_identity, result.session.evidence_ledger_identity)
        self.assertEqual(1, len(result.evidence_ledger.entries))
        self.assertEqual(result.evidence_ledger.ledger_hash, result.evidence_ledger.canonical_hash)
        self.assertNotIn("ProjectBrain", result.evidence_ledger.to_dict())
        self.assertNotIn("ROOT_CAUSE_PROVEN", result.to_dict())

    def test_budget_reaches_without_unbounded_experiments(self):
        h = DiagnosticHypothesis("H1", "checkout implementation is wrong")
        budget = DiagnosticBudget(max_total_experiments=1, max_counterfactual_mutations=1)
        engine, session = self._engine_session((h,), budget=budget)
        experiment = DiagnosticExperiment("E-one", "TARGETED_TEST", "one bounded test", ("H1",), predicted_outcomes=(("H1", TARGET_TEST_FAILS),), verification_checks=("target",))
        result = engine.run(session, (experiment,), expected_baseline_outcome=TARGET_TEST_FAILS, runner=self._runner)
        self.assertEqual("BUDGET_REACHED", result.status)
        self.assertEqual(1, result.metrics["diagnostic_budget_reached"])

    def test_runner_timeout_is_invalid_diagnostic_evidence(self):
        h = DiagnosticHypothesis("H1", "checkout implementation is wrong")
        engine, session = self._engine_session((h,), budget=DiagnosticBudget(max_total_experiments=1, timeout_seconds=1))
        experiment = DiagnosticExperiment("E-timeout", "TARGETED_TEST", "bounded timeout", ("H1",), predicted_outcomes=(("H1", TARGET_TEST_FAILS),), verification_checks=("target",))
        calls = [0]
        def slow_after_baseline(_root, _check):
            calls[0] += 1
            if calls[0] == 1:
                return TARGET_TEST_FAILS
            time.sleep(2)
            return TARGET_TEST_FAILS
        result = engine.run(
            session, (experiment,), expected_baseline_outcome=TARGET_TEST_FAILS,
            runner=slow_after_baseline,
        )
        self.assertEqual(EVIDENCE_INVALID, result.experiments_executed[0].validity)
        self.assertEqual("EXECUTION_INVALID", result.experiments_executed[0].observed_outcome)

    def test_diagnostic_benchmark_reports_architecture_metrics_without_truth_guidance(self):
        from hivo.experimental_evidence import benchmark_diagnostic_scenarios
        h = DiagnosticHypothesis("H1", "checkout implementation is wrong")
        engine, session = self._engine_session((h,))
        experiment = DiagnosticExperiment("E-bench", "TARGETED_TEST", "benchmark test", ("H1",), predicted_outcomes=(("H1", TARGET_TEST_FAILS),), verification_checks=("target",))
        report = benchmark_diagnostic_scenarios([{
            "name": "wrong-condition", "engine": engine, "session": session,
            "experiments": (experiment,), "expected_baseline_outcome": TARGET_TEST_FAILS,
            "runner": self._runner, "known_hypothesis_id": "H1",
        }])
        self.assertEqual("DETERMINISTIC_DIAGNOSTIC_ARCHITECTURE", report["benchmark_kind"])
        self.assertEqual(0, report["provider_calls"])
        self.assertEqual(1, len(report["scenarios"]))
        self.assertIn("known_root_cause_rank_after", report["scenarios"][0])

    def test_recovery_failure_seam_does_not_change_recovery_behavior(self):
        from hivo.experimental_evidence import session_from_recovery_failure
        engine = ExperimentalEvidenceEngine(self.root, repository_map=self.map, working_set=self.search.working_set)
        session = session_from_recovery_failure(engine, {"failure_id": "r1", "source_type": "RECOVERY_DERIVED", "message": "worker failure"})
        self.assertEqual("RECOVERY_DERIVED", session.failure_evidence[0].source_type)
        self.assertEqual(0, engine.metrics["provider_calls"])


if __name__ == "__main__":
    unittest.main()
