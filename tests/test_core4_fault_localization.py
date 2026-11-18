from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hivo.coverage_evidence import COVERAGE_AVAILABLE, COVERAGE_NOT_AVAILABLE, CoverageEvidence
from hivo.diagnostic_hypotheses import DiagnosticHypothesis
from hivo.experimental_evidence import EvidenceItem, ExperimentalEvidenceLedger
from hivo.fault_localization import (
    ASSERTION_FAILURE,
    BRAIN_CONTRACT_SIGNAL,
    CHANGE_PROXIMITY_SIGNAL,
    COVERAGE_SIGNAL,
    DNT_PROTECTED,
    ERROR_LOCATION_SIGNAL,
    EXPAND_WORKING_SET,
    EXPERIMENTAL_EVIDENCE_SIGNAL,
    FOCUS_ON_TOP_SUSPECT,
    GRAPH_PROXIMITY_SIGNAL,
    HIGH,
    INTEGRATION_FAILURE,
    LEXICAL_SIGNAL,
    LocalizationBudget,
    MEDIUM,
    RUN_DIAGNOSTIC_EXPERIMENTS,
    RUNTIME_EXCEPTION,
    STACK_TRACE_SIGNAL,
    TEST_DEPENDENCY_SIGNAL,
    TEST_FAILURE,
    FaultFailureEvidence,
    FaultLocalizationRequest,
    build_fault_localization_request,
    benchmark_fault_localization_scenarios,
    localize_fault,
    parse_stack_trace,
    rerank_with_experimental_evidence,
    seed_hypotheses_from_localization,
)
from hivo.lexical_index import build_lexical_index
from hivo.project_brain_refs import ProjectBrainEntity, TypedReference
from hivo.repo_intelligence import search_repository
from hivo.repository_map import build_repository_map


class _CoverageProvider:
    def __init__(self, evidence):
        self.evidence = evidence
        self.calls = 0

    def collect(self, failing_test_or_check, subject_identity, revision_identity, max_tests=5):
        self.calls += 1
        return self.evidence


class Core4FaultLocalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._write("src/parser.js", "export function parse(value) { return JSON.parse(value); }\n")
        self._write("src/display.js", "export function display(value) { return String(value); }\n")
        self._write("src/service.js", "import { parse } from './parser.js';\nexport function load(value) { return display(parse(value)); }\n")
        self._write("src/dnt.js", "export function protectedBoundary(value) { return value; }\n")
        self._write("tests/parser.test.js", "import { parse } from '../src/parser.js';\ntest('parse input', () => parse('{}'));\n")
        self._write("tests/service.test.js", "import { load } from '../src/service.js';\ntest('load input', () => load('{}'));\n")
        self.map = build_repository_map(self.root)
        self.index = build_lexical_index(self.map, self.root)
        self.search = search_repository("parse input", self.map, self.root, lexical_index=self.index)

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _request(self, failure, **kwargs):
        return build_fault_localization_request(
            "parse input failure", failure, subject_identity="subject-1",
            revision_identity=self.map.index_revision, **kwargs,
        )

    def test_request_candidate_and_stack_are_canonical(self):
        failure = FaultFailureEvidence(
            "f1", RUNTIME_EXCEPTION, message="SyntaxError: Unexpected token parse",
            path="src/parser.js", line=1, symbol="parse",
            stack_trace="at parse (src/parser.js:1:10)\nat display (src/display.js:1:10)",
        )
        request = self._request(failure)
        self.assertEqual(request.canonical_hash, FaultLocalizationRequest.from_value(request.to_dict()).canonical_hash)
        frames = parse_stack_trace(failure.stack_trace, self.root, self.map)
        self.assertEqual(2, len(frames))
        self.assertTrue(frames[0].project_internal)
        self.assertEqual("parse", frames[0].symbol)
        self.assertEqual(request.canonical_hash, request.canonical_hash)

    def test_exact_error_symbol_is_ranked_and_stack_is_explainable(self):
        failure = FaultFailureEvidence(
            "f1", RUNTIME_EXCEPTION, message="parser failed", path="src/parser.js", line=1, symbol="parse",
            stack_trace="at parse (src/parser.js:1:10)\n    at node:internal/run:1:1",
        )
        result = localize_fault(self._request(failure), self.map, self.root, working_set=self.search.working_set, lexical_index=self.index)
        self.assertTrue(result.candidates)
        self.assertEqual("src/parser.js::symbol::parse", result.candidates[0].candidate_id)
        self.assertIn(ERROR_LOCATION_SIGNAL, result.candidates[0].signal_contributions)
        self.assertIn(STACK_TRACE_SIGNAL, result.signals_available)
        self.assertTrue(result.ranking_explanations[0]["reasons"])
        self.assertIn(FOCUS_ON_TOP_SUSPECT, result.recommended_next_action)

    def test_stack_top_is_not_automatic_root_cause(self):
        failure = FaultFailureEvidence(
            "f2", RUNTIME_EXCEPTION, message="bad parsed value", path="src/display.js", line=1,
            stack_trace="at display (src/display.js:1:4)\nat load (src/service.js:2:20)\nat parse (src/parser.js:1:10)",
            test_name="load input",
        )
        result = localize_fault(self._request(failure), self.map, self.root, working_set=self.search.working_set, lexical_index=self.index)
        self.assertTrue(any(item.path == "src/parser.js" for item in result.candidates))
        h_display = DiagnosticHypothesis("H-display", "display is a symptom boundary", (TypedReference("symbol", "src/display.js", "display"),))
        h_parser = DiagnosticHypothesis("H-parser", "parser produced the bad value", (TypedReference("symbol", "src/parser.js", "parse"),))
        ledger = ExperimentalEvidenceLedger("ledger-symptom", (
            EvidenceItem("e-symptom", "receipt-symptom", (("H-display", "STRONGLY_WEAKENS"), ("H-parser", "SUPPORTS")), "STRONG", "CORE3", "VALID"),
        ))
        reranked = rerank_with_experimental_evidence(result, ledger, hypotheses=(h_display, h_parser))
        parser = next(item for item in reranked.candidates if item.candidate_id == "src/parser.js::symbol::parse")
        display = next(item for item in reranked.candidates if item.candidate_id == "src/display.js::symbol::display")
        original_display = next(item for item in result.candidates if item.candidate_id == "src/display.js::symbol::display")
        self.assertLess(display.score, original_display.score)
        self.assertIn("EXPERIMENTAL_EVIDENCE_SIGNAL", parser.evidence_sources)

    def test_failing_test_and_graph_signals_are_bounded(self):
        failure = FaultFailureEvidence("f3", TEST_FAILURE, message="load input failed", test_name="service.test.js")
        budget = LocalizationBudget(max_graph_nodes=2, max_candidates=12)
        result = localize_fault(self._request(failure, budget=budget), self.map, self.root, working_set=self.search.working_set, lexical_index=self.index)
        self.assertIn(TEST_DEPENDENCY_SIGNAL, result.signals_available)
        self.assertLessEqual(result.metrics["graph_nodes_examined"], 2)
        self.assertLessEqual(len(result.candidates), 12)

    def test_coverage_is_optional_and_spectrum_is_revision_bound(self):
        failure = FaultFailureEvidence("f4", TEST_FAILURE, message="parse input failed", test_name="parser.test.js")
        unavailable = localize_fault(self._request(failure), self.map, self.root, working_set=self.search.working_set, lexical_index=self.index)
        self.assertEqual(COVERAGE_NOT_AVAILABLE, unavailable.coverage_status)
        provider = _CoverageProvider(CoverageEvidence(
            "cov-1", "subject-1", self.map.index_revision, COVERAGE_AVAILABLE,
            failing_tests=("parser.test.js",), passing_tests=("guard.test.js",),
            files_executed=("src/parser.js",), hit_counts={"src/parser.js": {"failing": 1, "passing": 0}},
        ))
        covered = localize_fault(self._request(failure), self.map, self.root, working_set=self.search.working_set, lexical_index=self.index, coverage_provider=provider)
        self.assertEqual(COVERAGE_AVAILABLE, covered.coverage_status)
        self.assertEqual(1, provider.calls)
        self.assertIn(COVERAGE_SIGNAL, covered.signals_available)

    def test_change_bias_is_bounded_and_does_not_hide_unchanged_candidate(self):
        failure = FaultFailureEvidence("f5", RUNTIME_EXCEPTION, message="parser failed", path="src/parser.js", symbol="parse")
        result = localize_fault(self._request(failure), self.map, self.root, working_set=self.search.working_set, lexical_index=self.index, change_evidence={"changed_paths": ["src/display.js"]})
        self.assertIn(CHANGE_PROXIMITY_SIGNAL, result.signals_available)
        self.assertTrue(any(item.path == "src/parser.js" for item in result.candidates))
        changed = next(item for item in result.candidates if item.path == "src/display.js")
        self.assertLessEqual(changed.signal_contributions.get(CHANGE_PROXIMITY_SIGNAL, 0), 3)

    def test_brain_is_supporting_evidence_and_stale_reference_is_downgraded(self):
        entity = ProjectBrainEntity(
            "parser-contract", "CONTRACT", "parser ownership", "parser owns input parsing",
            contracts=("parser is the input boundary",), references=(TypedReference("symbol", "src/parser.js", "parse"),),
            verified_revision_identity=self.map.index_revision, created_from_verified_evidence=True,
        )
        failure = FaultFailureEvidence("f6", INTEGRATION_FAILURE, message="parser boundary failed")
        result = localize_fault(self._request(failure), self.map, self.root, working_set=self.search.working_set, lexical_index=self.index, brain_entities=(entity,))
        self.assertIn(BRAIN_CONTRACT_SIGNAL, result.signals_available)
        stale = entity.with_staleness("STALE_REFERENCE")
        stale_result = localize_fault(self._request(failure), self.map, self.root, working_set=self.search.working_set, lexical_index=self.index, brain_entities=(stale,))
        stale_candidate = next((item for item in stale_result.candidates if item.candidate_id == "src/parser.js::symbol::parse"), None)
        self.assertIsNotNone(stale_candidate)
        self.assertNotEqual(HIGH, stale_candidate.confidence_class)

    def test_experimental_evidence_reranks_without_promoting_truth(self):
        failure = FaultFailureEvidence("f7", TEST_FAILURE, message="parse input failed", test_name="parser.test.js")
        result = localize_fault(self._request(failure), self.map, self.root, working_set=self.search.working_set, lexical_index=self.index)
        parser = next(item for item in result.candidates if item.path == "src/parser.js")
        other = next(item for item in result.candidates if item.path != "src/parser.js")
        h1 = DiagnosticHypothesis("H1", "parser suspect", (TypedReference("file", "src/parser.js"),))
        h2 = DiagnosticHypothesis("H2", "other suspect", (TypedReference("file", other.path),))
        ledger = ExperimentalEvidenceLedger("ledger-1", (
            EvidenceItem("e1", "receipt-1", (("H1", "SUPPORTS"), ("H2", "STRONGLY_WEAKENS")), "STRONG", "CORE3", "VALID"),
        ))
        reranked = rerank_with_experimental_evidence(result, ledger, hypotheses=(h1, h2))
        self.assertGreaterEqual(next(item for item in reranked.candidates if item.path == "src/parser.js").score, parser.score)
        self.assertIn(EXPERIMENTAL_EVIDENCE_SIGNAL, next(item for item in reranked.candidates if item.path == "src/parser.js").signal_contributions)
        self.assertEqual(result.request.working_set_identity, reranked.request.working_set_identity)

    def test_dnt_and_authority_labels_never_change_from_ranking(self):
        failure = FaultFailureEvidence("f8", RUNTIME_EXCEPTION, message="protected boundary failed", path="src/dnt.js", symbol="protectedBoundary")
        result = localize_fault(self._request(failure), self.map, self.root, working_set=self.search.working_set, lexical_index=self.index, dnt_paths=("src/dnt.js",), authority={"approved_mutation_scope": ("src/parser.js",)})
        candidate = next(item for item in result.candidates if item.path == "src/dnt.js")
        self.assertEqual(DNT_PROTECTED, candidate.authority_label)
        self.assertNotEqual("MUTATION_AUTHORIZED", candidate.authority_label)

    def test_stale_failure_is_reported_not_silently_used(self):
        failure = FaultFailureEvidence("f9", ASSERTION_FAILURE, message="old subject", path="src/parser.js", subject_identity="old", revision_identity="old")
        result = localize_fault(self._request(failure), self.map, self.root, working_set=self.search.working_set, lexical_index=self.index)
        self.assertFalse(any(item.path == "src/parser.js" and ERROR_LOCATION_SIGNAL in item.signal_contributions for item in result.candidates))
        self.assertTrue(any(item.get("kind") == "STALE_FAULT_EVIDENCE" for item in result.unresolved_evidence))

    def test_hypotheses_are_bounded_and_diverse(self):
        failure = FaultFailureEvidence("f10", TEST_FAILURE, message="parse input failed", test_name="parser.test.js")
        result = localize_fault(self._request(failure), self.map, self.root, working_set=self.search.working_set, lexical_index=self.index)
        hypotheses = seed_hypotheses_from_localization(result, max_hypotheses=3)
        self.assertLessEqual(len(hypotheses), 3)
        self.assertTrue(all(item.target_references for item in hypotheses))
        self.assertEqual(len({item.hypothesis_id for item in hypotheses}), len(hypotheses))

    def test_no_signal_returns_bounded_low_confidence_action(self):
        failure = FaultFailureEvidence("f11", INTEGRATION_FAILURE, message="")
        request = self._request(failure, available_signal_types=())
        result = localize_fault(request, self.map, self.root, working_set=self.search.working_set, lexical_index=self.index)
        self.assertTrue(result.recommended_next_action in {EXPAND_WORKING_SET, RUN_DIAGNOSTIC_EXPERIMENTS})
        self.assertLessEqual(len(result.candidates), request.budget.max_candidates)

    def test_benchmark_reports_navigation_metrics_without_provider(self):
        failure = FaultFailureEvidence("f12", RUNTIME_EXCEPTION, message="parser failed", path="src/parser.js", symbol="parse")
        report = benchmark_fault_localization_scenarios([{
            "name": "parser", "request": self._request(failure), "repository_map": self.map,
            "project_root": self.root, "working_set": self.search.working_set,
            "lexical_index": self.index, "relevant": ("src/parser.js::symbol::parse",),
        }])
        self.assertEqual("DETERMINISTIC_CORE4_FAULT_LOCALIZATION", report["benchmark_kind"])
        self.assertEqual(1, report["scenario_count"])
        self.assertEqual(0, report["provider_calls"])
        self.assertIn("MRR", report)

    def test_external_stack_path_is_not_a_repository_candidate(self):
        failure = FaultFailureEvidence("f13", RUNTIME_EXCEPTION, message="external", stack_trace="at x (../outside.js:1:1)\nat y (node_modules/pkg/index.js:2:1)")
        result = localize_fault(self._request(failure), self.map, self.root, working_set=self.search.working_set, lexical_index=self.index)
        self.assertEqual(0, result.metrics["project_stack_frames"])
        self.assertTrue(all(not item.path.startswith("..") for item in result.candidates))


if __name__ == "__main__":
    unittest.main()
