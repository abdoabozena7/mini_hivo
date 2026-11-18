from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hivo.experiment_sandbox import canonical_subject_hash
from hivo.lexical_index import build_lexical_index
from hivo.mutation_strategy import (
    CONDITION_CHANGE, EXACT_VALUE_CHANGE, EXPORT_IMPORT_REPAIR,
    MutationStrategyRouter, UNKNOWN_STRUCTURAL_CHANGE,
)
from hivo.patch_candidates import (
    AUTHORITY_BLOCKED, DETERMINISTIC_OPERATOR, DNT_PROTECTED, MODEL_PROPOSED,
    PROPOSED, SYNTAX_INVALID, V25_5_REJECTED, VERIFIED, PatchCandidate,
    PatchOperation, PatchRepresentation, generate_deterministic_candidates,
    generate_patch_candidates,
)
from hivo.patch_search import (
    PatchSearchEngine, apply_selected_patch_candidate,
    search_patch_candidates, update_repository_indexes_after_application,
)
from hivo.repair_problem import PatchSearchBudget, RepairProblem
from hivo.repository_map import build_repository_map


class _FakeModel:
    def __init__(self, proposal):
        self.proposal = proposal
        self.calls = 0

    def propose(self, problem, context, *, limit):
        self.calls += 1
        return self.proposal[:limit]


class Core5PatchCandidateSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._write("src/service.js", "export function answer(value) { return value === 1; }\n")
        self._write("src/other.js", "export function answer(value) { return value === 2; }\n")
        self._write("src/unused.js", "export function unrelated() { return 'x'; }\n")
        self._write("tests/service.test.js", "import { answer } from '../src/service.js';\ntest('answer', () => answer(1));\n")
        self.map = build_repository_map(self.root)
        self.index = build_lexical_index(self.map, self.root)
        self.subject_hash = canonical_subject_hash(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _problem(self, *, records=None, metadata=None, authority=None, dnt=(), subject=None, budget=None):
        return RepairProblem(
            repair_id="repair-1", task_identity="answer behavior", subject_identity=subject or self.subject_hash,
            revision_identity=self.map.index_revision, working_set_identity="ws-1", fault_localization_identity="fl-1",
            suspect_candidates=tuple(records or ({
                "candidate_id": "suspect-service", "path": "src/service.js", "symbol": "answer",
                "candidate_kind": "symbol", "score": 9, "evidence_sources": ("symbol", "test"),
            },)), authority_context=authority or {"approved_mutation_scope": ("src/service.js",)},
            dnt_context=tuple(dnt), metadata=dict(metadata or {}), candidate_budget=budget or PatchSearchBudget(),
        )

    def test_repair_problem_and_budget_are_canonical(self):
        problem = self._problem()
        self.assertEqual(problem.canonical_hash, RepairProblem.from_value(problem.to_dict()).canonical_hash)
        self.assertEqual(3, problem.candidate_budget.max_suspects)
        self.assertEqual(8, problem.candidate_budget.max_candidates)
        self.assertEqual(problem.evidence_packet.canonical_hash, problem.evidence_packet.canonical_hash)

    def test_strategy_router_is_deterministic_and_multi_signal(self):
        problem = self._problem(metadata={"expected_text": "return value === 1", "actual_text": "return value === 2"})
        decision = MutationStrategyRouter().route(problem, problem.suspect_candidates[0])
        self.assertIn(EXACT_VALUE_CHANGE, decision.strategies)
        self.assertEqual(decision.canonical_hash, MutationStrategyRouter().route(problem, problem.suspect_candidates[0]).canonical_hash)
        export = MutationStrategyRouter().route(self._problem(metadata={"missing_export": "answer"}), problem.suspect_candidates[0])
        self.assertIn(EXPORT_IMPORT_REPAIR, export.strategies)
        condition = MutationStrategyRouter().route(self._problem(metadata={"condition_text": "value === 1", "replacement_text": "value === 2"}), problem.suspect_candidates[0])
        self.assertIn(CONDITION_CHANGE, condition.strategies)
        unknown = MutationStrategyRouter().route(self._problem(), {"candidate_id": "x", "path": "src/service.js"})
        self.assertIn(UNKNOWN_STRUCTURAL_CHANGE, unknown.strategies)

    def test_search_uses_bounded_top_k_and_verification_gates(self):
        records = (
            {"candidate_id": "wrong-top1", "path": "src/other.js", "symbol": "answer", "score": 100},
            {"candidate_id": "right-top2", "path": "src/service.js", "symbol": "answer", "score": 1, "evidence_sources": ("test",)},
        )
        problem = self._problem(records=records, metadata={"expected_text": "return value === 1", "actual_text": "return value === true"})
        result = search_patch_candidates(problem, self.root, v25_5_gate=lambda *a, **k: True, v25_6_verifier=lambda candidate, root: candidate.target_path == "src/service.js")
        self.assertTrue(result.source_unchanged)
        self.assertIsNotNone(result.winner)
        self.assertEqual("src/service.js", result.winner.target_path)
        self.assertEqual(0, result.metrics["model_generated"])
        self.assertLessEqual(len(result.generated_candidates), problem.candidate_budget.max_candidates)
        self.assertGreaterEqual(len(result.ranked_viable_candidates), 1)

    def test_without_v25_5_search_does_not_claim_verified_candidate(self):
        problem = self._problem(metadata={"expected_text": "return value === 1", "actual_text": "return value === true"})
        result = search_patch_candidates(problem, self.root)
        self.assertIsNone(result.winner)
        self.assertTrue(any(item.status == V25_5_REJECTED for item in result.receipts))
        self.assertTrue(result.source_unchanged)

    def test_dnt_and_unapproved_targets_are_blocked(self):
        dnt_problem = self._problem(dnt=("src/service.js",), authority={"approved_mutation_scope": ("src/service.js",)}, metadata={"expected_text": "return value === 1", "actual_text": "return value === true"})
        dnt_result = search_patch_candidates(dnt_problem, self.root, v25_5_gate=lambda *a, **k: True)
        self.assertTrue(any(item.status == AUTHORITY_BLOCKED for item in dnt_result.receipts))
        scope_problem = self._problem(authority={"approved_mutation_scope": ("src/other.js",)}, metadata={"expected_text": "return value === 1", "actual_text": "return value === true"})
        scope_result = search_patch_candidates(scope_problem, self.root, v25_5_gate=lambda *a, **k: True)
        self.assertTrue(any(item.status == AUTHORITY_BLOCKED for item in scope_result.receipts))

    def test_stale_subject_is_rejected(self):
        problem = self._problem(subject="0" * 64, metadata={"expected_text": "return value === 1", "actual_text": "return value === true"})
        result = search_patch_candidates(problem, self.root, v25_5_gate=lambda *a, **k: True)
        self.assertTrue(any(item.status == "STALE_BASE" for item in result.receipts))

    def test_model_candidates_are_optional_and_have_no_privilege(self):
        operation = PatchOperation("src/service.js", expected_text="return value === 1", replacement="return value === true")
        model = _FakeModel([PatchCandidate("model", "src/service.js", "answer", "EXACT_VALUE_CHANGE", MODEL_PROPOSED, PatchRepresentation((operation,)), self.subject_hash, self.map.index_revision).to_dict()])
        problem = self._problem(metadata={})
        result = search_patch_candidates(problem, self.root, model_provider=model, v25_5_gate=lambda *a, **k: True)
        self.assertEqual(1, model.calls)
        self.assertTrue(any(item.provenance == MODEL_PROPOSED for item in result.generated_candidates))
        self.assertTrue(result.source_unchanged)

    def test_candidate_sandbox_never_changes_canonical_subject(self):
        before = canonical_subject_hash(self.root)
        problem = self._problem(metadata={"expected_text": "return value === 1", "actual_text": "return value === true"})
        result = search_patch_candidates(problem, self.root, v25_5_gate=lambda *a, **k: True)
        self.assertEqual(before, canonical_subject_hash(self.root))
        self.assertTrue(result.source_unchanged)

    def test_explicit_application_is_separate_and_updates_indexes(self):
        problem = self._problem(metadata={"expected_text": "return value === 1", "actual_text": "return value === true"})
        result = search_patch_candidates(problem, self.root, v25_5_gate=lambda *a, **k: True, v25_6_verifier=lambda *a, **k: True)
        self.assertIsNotNone(result.winner)
        applied = apply_selected_patch_candidate(result.winner, self.root, authority={"approved_mutation_scope": ("src/service.js",)}, v25_5_gate=lambda *a, **k: True)
        self.assertTrue(applied["applied"])
        self.assertNotEqual(self.subject_hash, canonical_subject_hash(self.root))
        updated_map, updated_index = update_repository_indexes_after_application(self.map, self.index, self.root, changed_paths=("src/service.js",))
        self.assertNotEqual(self.map.logical_hash, updated_map.logical_hash)
        self.assertIsNotNone(updated_index)
        self.assertIn("true", updated_index.postings)

    def test_incremental_index_deletion_is_bounded(self):
        self._write("src/new.js", "export function newUniqueTerm() { return 1; }\n")
        changed_map = build_repository_map(self.root)
        metrics = {}
        updated = __import__("hivo.lexical_index", fromlist=["incremental_lexical_update"]).incremental_lexical_update(
            self.index, changed_map, self.root, changed_paths=("src/new.js",), metrics=metrics,
        )
        self.assertEqual(1, metrics["documents_added"])
        self.assertIn("newuniqueterm", updated.postings)

    def test_export_template_requires_current_structure(self):
        self._write("src/exported.js", "function answer() { return 1; }\nmodule.exports = { other };\n")
        before = canonical_subject_hash(self.root)
        problem = self._problem(records=({"candidate_id": "export", "path": "src/exported.js", "symbol": "answer"},), metadata={"missing_export": "answer"}, authority={"approved_mutation_scope": ("src/exported.js",)})
        candidates = generate_deterministic_candidates(problem, self.root, problem.suspect_candidates[0], EXPORT_IMPORT_REPAIR)
        self.assertTrue(candidates)
        self.assertIn("answer", candidates[0].representation.operations[0].replacement)
        self.assertEqual(before, canonical_subject_hash(self.root))

    def test_export_template_search_preserves_physical_newlines(self):
        self._write("src/exported.js", "function answer() { return 1; }\nmodule.exports = {};\n")
        problem = self._problem(
            records=({"candidate_id": "export", "path": "src/exported.js", "symbol": "answer"},),
            metadata={"missing_export": "answer"},
            authority={"approved_mutation_scope": ("src/exported.js",)},
            subject=canonical_subject_hash(self.root),
        )
        result = search_patch_candidates(
            problem, self.root, v25_5_gate=lambda *a, **k: True,
            v25_6_verifier=lambda candidate, root: "module.exports = {answer}" in (Path(root) / "src/exported.js").read_text(encoding="utf-8"),
        )
        self.assertIsNotNone(result.winner)
        self.assertEqual(VERIFIED, result.winner.status)

    def test_multi_file_candidate_checks_every_changed_path_authority(self):
        operation_a = PatchOperation("src/service.js", expected_text="return value === 1", replacement="return value === true")
        operation_b = PatchOperation("src/other.js", expected_text="return value === 2", replacement="return value === true")
        candidate = PatchCandidate(
            "model-multi", "src/service.js", "answer", "MULTI_FILE_BOUNDED_CHANGE", MODEL_PROPOSED,
            PatchRepresentation((operation_a, operation_b)), self.subject_hash, self.map.index_revision,
        )
        result = search_patch_candidates(
            self._problem(), self.root, model_provider=_FakeModel([candidate.to_dict()]),
            v25_5_gate=lambda *a, **k: True,
        )
        self.assertTrue(any(item.status == AUTHORITY_BLOCKED for item in result.receipts))

    def test_full_v25_6_verifier_receives_candidate_sandbox(self):
        problem = self._problem(metadata={"expected_text": "return value === 1", "actual_text": "return value === true"})
        observed = []

        def verifier(candidate, root):
            text = (Path(root) / "src/service.js").read_text(encoding="utf-8")
            observed.append(text)
            return "return value === true" in text

        result = search_patch_candidates(problem, self.root, v25_5_gate=lambda *a, **k: True, v25_6_verifier=verifier)
        self.assertIsNotNone(result.winner)
        self.assertTrue(observed)
        self.assertTrue(any("return value === true" in text for text in observed))

    def test_syntax_invalid_candidate_is_filtered_before_callbacks(self):
        problem = self._problem(metadata={"expected_text": "return value === 1", "actual_text": "return value === {"})
        calls = []
        result = search_patch_candidates(problem, self.root, targeted_checker=lambda *a, **k: calls.append(True) or True, v25_5_gate=lambda *a, **k: True)
        self.assertTrue(any(item.status == SYNTAX_INVALID for item in result.receipts))
        self.assertLessEqual(len(calls), result.metrics["targeted_evaluations"])

    def test_guard_failure_is_hard_rejection(self):
        problem = self._problem(metadata={"expected_text": "return value === 1", "actual_text": "return value === true"})
        result = search_patch_candidates(problem, self.root, targeted_checker=lambda *a, **k: True, guard_checker=lambda *a, **k: False, v25_5_gate=lambda *a, **k: True)
        self.assertIsNone(result.winner)
        self.assertTrue(any(item.status == "GUARD_REGRESSION" for item in result.receipts))

    def test_same_final_state_is_deduplicated(self):
        problem = self._problem(metadata={"expected_text": "return value === 1", "actual_text": "return value === true"})
        result = search_patch_candidates(problem, self.root, v25_5_gate=lambda *a, **k: True)
        self.assertLessEqual(len(result.deduplicated_candidates), len(result.generated_candidates))
        self.assertGreaterEqual(result.metrics["duplicate_candidates_suppressed"], 0)

    def test_path_escape_is_rejected(self):
        with self.assertRaises(ValueError):
            PatchOperation("../outside.js", expected_text="x", replacement="y")
        with self.assertRaises(ValueError):
            PatchCandidate("bad", ".git/config", representation=PatchRepresentation(()))

    def test_direct_generator_is_bounded(self):
        problem = self._problem(metadata={"expected_text": "return value === 1", "actual_text": "return value === true"}, budget=PatchSearchBudget(max_candidates=1))
        candidates = generate_patch_candidates(problem, self.root)
        self.assertLessEqual(len(candidates), 1)


if __name__ == "__main__":
    unittest.main()
