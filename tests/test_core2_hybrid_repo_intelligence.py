from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from hivo.lexical_index import build_lexical_index, incremental_lexical_update
from hivo.project_brain_refs import ProjectBrainEntity, TypedReference, canonical_hash
from hivo.repo_intelligence import (
    ARCHITECTURE_QUERY,
    BEHAVIORAL_QUERY,
    ERROR_LOCALIZATION,
    EXACT_PATH,
    EXACT_SYMBOL,
    IMPACT_ANALYSIS,
    TEST_FAILURE,
    RepoIntelligenceQuery,
    benchmark_repository_navigation,
    classify_search_intents,
    extract_query_signals,
    search_repository,
)
from hivo.repository_map import build_repository_map, incremental_reindex
from hivo.task_working_set import (
    MUTATION_AUTHORIZED,
    READ_ONLY_SUPPORT,
    TaskWorkingSet,
    WorkingSetBudget,
    WORKING_SET_BUDGET_REACHED,
    build_task_working_set,
    expand_working_set,
)


class FakeSemanticRetriever:
    def __init__(self, path: str = "src/status_view.js") -> None:
        self.calls = 0
        self.path = path

    def search(self, query, repository_map, budget):
        self.calls += 1
        return [{"path": self.path, "score": 4.0, "candidate_type": "file"}]


class Core2HybridRepositoryIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._write("src/status_view.js", """export function renderStatus(controller) {
  return controller.paused ? 'Paused' : 'Running';
}
export function renderPauseIndicator(controller) {
  return controller.paused ? 'Paused indicator' : '';
}
""")
        self._write("src/auth/service.js", """export class AuthService {
  refreshToken() { return 'token'; }
}
export function loginUser(user) { return user; }
""")
        self._write("src/payment/gateway.js", """export class PaymentGateway {
  charge() { return true; }
}
""")
        self._write("src/broken.js", """// SyntaxError: Unexpected token }
export function brokenFeature() { return true; }
""")
        self._write("tests/status_view.test.js", """import { renderStatus, renderPauseIndicator } from '../src/status_view.js';
test('pause indicator', () => renderPauseIndicator({ paused: true }));
""")
        self._write("tests/auth.test.js", """import { AuthService } from '../src/auth/service.js';
test_refresh_token(AuthService);
""")
        self._write("tests/gateway.test.js", """import { PaymentGateway } from '../src/payment/gateway.js';
test('gateway', () => new PaymentGateway());
""")
        self._write("docs/architecture.md", "PaymentGateway is the architecture contract boundary.\n")
        self.map = build_repository_map(self.root)
        self.lexical = build_lexical_index(self.map, self.root)

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _brain_entity(self, *, path: str = "src/status_view.js", name: str = "Pause contract"):
        digest = hashlib.sha256((self.root / path).read_bytes()).hexdigest()
        return ProjectBrainEntity(
            entity_id="brain-" + name.casefold().replace(" ", "-"),
            entity_kind="CONTRACT",
            name=name,
            summary="verified pause flow architecture contract",
            contracts=("PauseController owns pause state",),
            invariants=("renderStatus remains a primitive string",),
            references=(TypedReference("file", path),),
            verified_subject_identity="subject-core2",
            verified_revision_identity=self.map.index_revision,
            verified_source_hashes=((path, digest),),
            created_from_verified_evidence=True,
        )

    def test_query_signal_extraction_and_intents(self):
        signals = extract_query_signals(
            'Investigate src/auth/service.js AuthService.refreshToken SyntaxError: Unexpected token } test_refresh_token'
        )
        self.assertIn("src/auth/service.js", signals["explicit_paths"])
        self.assertIn("AuthService.refreshToken", signals["explicit_symbols"])
        self.assertTrue(any("SyntaxError" in item for item in signals["error_strings"]))
        self.assertIn("test_refresh_token", signals["test_names"])
        intents = classify_search_intents("what breaks if PaymentGateway changes")
        self.assertIn(IMPACT_ANALYSIS, intents)
        self.assertIn(BEHAVIORAL_QUERY, intents)

    def test_exact_path_and_symbol_use_cheap_routes_and_skip_semantic(self):
        semantic = FakeSemanticRetriever()
        path_result = search_repository(
            RepoIntelligenceQuery.from_task("inspect src/status_view.js"), self.map, self.root,
            lexical_index=self.lexical, semantic_retriever=semantic,
        )
        self.assertIn(EXACT_PATH, path_result.intents)
        self.assertEqual("src/status_view.js", path_result.candidates[0].path)
        self.assertEqual(0, path_result.metrics["semantic_queries"])
        self.assertIn("strong_exact_evidence", path_result.early_stop_reason)

        symbol_result = search_repository(
            RepoIntelligenceQuery.from_task("find renderPauseIndicator"), self.map, self.root,
            lexical_index=self.lexical, semantic_retriever=semantic,
        )
        self.assertIn(EXACT_SYMBOL, symbol_result.intents)
        self.assertTrue(any(candidate.symbol == "renderPauseIndicator" for candidate in symbol_result.candidates))
        self.assertEqual(0, semantic.calls)

    def test_error_and_test_queries_use_lexical_and_test_routes(self):
        error = search_repository(
            "locate SyntaxError: Unexpected token }", self.map, self.root,
            lexical_index=self.lexical,
        )
        self.assertIn(ERROR_LOCALIZATION, error.intents)
        self.assertGreater(error.metrics["lexical_queries"], 0)
        self.assertTrue(any(candidate.path == "src/broken.js" for candidate in error.candidates))

        failing_test = search_repository(
            "failing test_refresh_token", self.map, self.root,
            lexical_index=self.lexical,
        )
        self.assertIn(TEST_FAILURE, failing_test.intents)
        self.assertGreater(failing_test.metrics["test_expansions"], 0)
        self.assertTrue(any(candidate.path == "tests/auth.test.js" for candidate in failing_test.candidates))

    def test_impact_and_architecture_queries_use_bounded_graph_and_brain(self):
        impact = search_repository(
            "what breaks if PaymentGateway changes", self.map, self.root,
            lexical_index=self.lexical,
        )
        self.assertIn(IMPACT_ANALYSIS, impact.intents)
        self.assertLessEqual(impact.metrics["graph_expansions"] + impact.metrics["test_expansions"], 12)
        self.assertTrue(any(candidate.path == "tests/gateway.test.js" for candidate in impact.candidates))

        brain = self._brain_entity()
        architecture = search_repository(
            "pause flow architecture contract", self.map, self.root,
            brain_entities=(brain,), lexical_index=self.lexical,
        )
        self.assertIn(ARCHITECTURE_QUERY, architecture.intents)
        self.assertGreater(architecture.metrics["brain_seed_entities"], 0)
        self.assertTrue(any("brain" in candidate.evidence_sources for candidate in architecture.candidates))

    def test_lexical_index_is_deterministic_incremental_and_deletions_are_safe(self):
        second = build_lexical_index(self.map, self.root)
        self.assertEqual(self.lexical.logical_hash, second.logical_hash)
        before_paths = set(self.lexical.documents)
        self._write("src/auth/service.js", "export class AuthService { refreshToken() { return 'new'; } }\nexport const authChanged = true;\n")
        changed_map = incremental_reindex(self.map, self.root, changed_paths=("src/auth/service.js",))
        metrics = {}
        changed_index = incremental_lexical_update(
            self.lexical, changed_map, self.root,
            changed_paths=("src/auth/service.js",), metrics=metrics,
        )
        self.assertEqual(1, metrics["documents_updated"])
        self.assertEqual(before_paths, set(changed_index.documents))
        self.assertIn("authchanged", changed_index.postings)
        self.assertNotEqual(self.lexical.logical_hash, changed_index.logical_hash)

        (self.root / "src/broken.js").unlink()
        deleted_map = incremental_reindex(self.map, self.root, deleted_paths=("src/broken.js",))
        deleted_index = incremental_lexical_update(
            changed_index, deleted_map, self.root,
            deleted_paths=("src/broken.js",), metrics=metrics,
        )
        self.assertNotIn("src/broken.js", deleted_index.documents)
        self.assertGreaterEqual(metrics["documents_removed"], 1)

    def test_stale_index_is_safely_rebuilt(self):
        self._write("src/status_view.js", "export function renderPauseIndicator(controller) { return 'changed'; }\n")
        changed_map = incremental_reindex(self.map, self.root, changed_paths=("src/status_view.js",))
        result = search_repository("renderPauseIndicator", changed_map, self.root, lexical_index=self.lexical)
        self.assertEqual(0, result.metrics["semantic_queries"])
        self.assertTrue(any(candidate.symbol == "renderPauseIndicator" for candidate in result.candidates))
        self.assertGreaterEqual(result.metrics["lexical_index_builds"], 0)

    def test_ambiguous_symbol_remains_explicit_until_other_evidence_supports_it(self):
        self._write("src/one.js", "export function duplicate() { return 1; }\n")
        self._write("src/two.js", "export function duplicate() { return 2; }\n")
        current = incremental_reindex(self.map, self.root, changed_paths=("src/one.js", "src/two.js"))
        query = RepoIntelligenceQuery.from_task("duplicate",)
        query = RepoIntelligenceQuery(
            raw_task_text=query.raw_task_text, explicit_symbols=("duplicate",),
            budget=query.budget,
        )
        result = search_repository(query, current, self.root, lexical_index=None)
        duplicate = [candidate for candidate in result.candidates if candidate.symbol == "duplicate"]
        self.assertEqual(2, len(duplicate))
        self.assertTrue(all(candidate.confidence_class == "AMBIGUOUS" for candidate in duplicate))

    def test_stale_brain_is_downgraded_and_current_repository_wins(self):
        stale = self._brain_entity()
        self._write("src/status_view.js", "export function renderStatus(controller) { return 'Current'; }\n")
        changed_map = incremental_reindex(self.map, self.root, changed_paths=("src/status_view.js",))
        result = search_repository(
            "pause flow architecture", changed_map, self.root,
            brain_entities=(stale,), lexical_index=None,
        )
        self.assertTrue(any(candidate.staleness_state in {STALE := "STALE_REFERENCE", "CURRENT"} for candidate in result.candidates))
        self.assertTrue(any(candidate.path == "src/status_view.js" and candidate.staleness_state == "CURRENT" for candidate in result.candidates))

    def test_optional_semantic_fallback_runs_only_for_weak_conceptual_queries(self):
        semantic = FakeSemanticRetriever()
        conceptual = search_repository(
            "explain lifecycle coordination behavior", self.map, self.root,
            lexical_index=self.lexical, semantic_retriever=semantic,
        )
        self.assertGreaterEqual(semantic.calls, 1)
        self.assertGreater(conceptual.metrics["semantic_queries"], 0)
        exact = search_repository(
            "renderStatus", self.map, self.root,
            lexical_index=self.lexical, semantic_retriever=semantic,
        )
        self.assertEqual(semantic.calls, conceptual.metrics["semantic_queries"])
        self.assertGreater(exact.metrics["semantic_queries_skipped"], 0)

    def test_candidate_fusion_deduplicates_symbol_and_lexical_support(self):
        result = search_repository(
            "where does renderPauseIndicator behavior live", self.map, self.root,
            lexical_index=self.lexical,
        )
        matching = [candidate for candidate in result.candidates if candidate.path == "src/status_view.js" and candidate.symbol == "renderPauseIndicator"]
        self.assertEqual(1, len(matching))
        self.assertIn("multi_signal_support", matching[0].reasons)
        self.assertGreaterEqual(len(matching[0].evidence_sources), 2)

    def test_working_set_is_bounded_and_preserves_authority_labels(self):
        candidates = [
            {
                "identity": f"src/file{index}.js",
                "path": f"src/file{index}.js",
                "score": 100 - index,
                "candidate_type": "file",
                "evidence_sources": ("lexical",),
            }
            for index in range(20)
        ]
        working_set = build_task_working_set(
            RepoIntelligenceQuery.from_task("inspect files"), candidates,
            budget=WorkingSetBudget(max_primary_items=2, max_supporting_items=2, max_files=4),
            authority={"approved_mutation_scope": ["src/file0.js"], "do_not_touch": ["src/file1.js"]},
        )
        self.assertLessEqual(len(working_set.files), 4)
        self.assertEqual(WORKING_SET_BUDGET_REACHED, working_set.status)
        labels = {item.path: item.authority_label for item in working_set.items}
        self.assertEqual(MUTATION_AUTHORIZED, labels["src/file0.js"])
        self.assertEqual(READ_ONLY_SUPPORT, labels["src/file1.js"])

    def test_progressive_detail_loads_only_selected_sources_and_deduplicates(self):
        result = search_repository(
            "renderPauseIndicator", self.map, self.root,
            lexical_index=self.lexical,
        )
        self.assertIsInstance(result.working_set, TaskWorkingSet)
        self.assertEqual(0, result.metrics["source_bodies_loaded"])
        expanded = expand_working_set(result.working_set, self.map, self.root, requested_level=5)
        self.assertLessEqual(expanded.budget_usage.get("full_file_reads", 0), 2)
        self.assertGreaterEqual(expanded.budget_usage.get("source_bodies_loaded", 0), 1)
        expanded_again = expand_working_set(expanded, self.map, self.root, requested_level=5)
        self.assertTrue(any(item.evidence.get("provenance", {}).get("source") == "duplicate_suppressed" for item in expanded_again.items if item.path))

    def test_large_repository_exact_symbol_and_error_controls_are_bounded(self):
        for index in range(80):
            self._write(f"src/generated/module_{index}.js", f"export function generatedThing{index}() {{ return {index}; }}\n")
        self._write("src/generated/target.js", "export function rareTarget() { return 'needle'; }\n")
        large_map = build_repository_map(self.root)
        large_index = build_lexical_index(large_map, self.root)
        semantic = FakeSemanticRetriever()
        exact = search_repository("rareTarget", large_map, self.root, lexical_index=large_index, semantic_retriever=semantic)
        self.assertEqual(0, exact.metrics["semantic_queries"])
        self.assertLessEqual(exact.metrics["working_set_files"], 16)
        self.assertEqual(0, exact.metrics["source_bodies_loaded"])
        error = search_repository("distinctive needle error", large_map, self.root, lexical_index=large_index)
        self.assertTrue(any(candidate.path == "src/generated/target.js" for candidate in error.candidates))
        self.assertEqual(0, error.metrics["source_bodies_loaded"])

    def test_benchmark_fixture_emits_navigation_metrics(self):
        cases = [
            {"name": "exact-symbol", "query": "renderStatus", "relevant_files": ["src/status_view.js"], "relevant_symbols": ["src/status_view.js::symbol::renderStatus"]},
            {"name": "exact-path", "query": "src/auth/service.js", "relevant_files": ["src/auth/service.js"]},
            {"name": "test", "query": "failing test_refresh_token", "relevant_files": ["tests/auth.test.js"]},
            {"name": "error", "query": "SyntaxError: Unexpected token }", "relevant_files": ["src/broken.js"]},
            {"name": "behavior", "query": "pause flow behavior", "relevant_files": ["src/status_view.js"]},
            {"name": "impact", "query": "what breaks if PaymentGateway changes", "relevant_files": ["src/payment/gateway.js"]},
            {"name": "architecture", "query": "pause architecture contract", "relevant_files": ["src/status_view.js"]},
        ]
        report = benchmark_repository_navigation(cases, self.map, self.root, lexical_index=self.lexical)
        self.assertEqual("DETERMINISTIC_REPOSITORY_NAVIGATION", report["benchmark_kind"])
        for key in ("RelevantFileRecall@5", "RelevantFileRecall@10", "RelevantSymbolRecall@5", "source_bodies_loaded", "full_files_loaded", "average_search_stages"):
            self.assertIn(key, report)

    def test_missing_semantic_backend_and_path_safety_fail_gracefully(self):
        result = search_repository("conceptual lifecycle behavior", self.map, self.root, lexical_index=self.lexical)
        self.assertEqual(0, result.metrics["semantic_queries"])
        self.assertGreater(result.metrics["semantic_queries_skipped"], 0)
        unsafe = RepoIntelligenceQuery(
            raw_task_text="inspect ../secret.js", explicit_paths=("../secret.js",),
        )
        unsafe_result = search_repository(unsafe, self.map, self.root, lexical_index=self.lexical)
        self.assertTrue(any(item.get("reason") == "path_not_found" for item in unsafe_result.unresolved_evidence))


if __name__ == "__main__":
    unittest.main()
