import json
import tempfile
import unittest
from pathlib import Path

import mini
from hivo import context_sufficiency as stage7
from hivo.project_world_model import (
    CALLS,
    CONFLICTING,
    DEFINED_IN,
    DEPENDS_ON,
    EXPORTED_BY,
    EXPORTS,
    IMPLEMENTS_CONTRACT,
    IMPORTS,
    MAX_WORLD_MODEL_FACTS_PER_PROJECTION,
    MAX_WORLD_MODEL_HOPS,
    MODULE_CONTAINS,
    READS_FIELD,
    RETURNS_TYPE,
    TESTED_BY,
    TRANSITIONS,
    STALE,
    TEST_ASSERTS_BEHAVIOR_OF,
    VERIFIED,
    ProjectWorldModel,
)
from hivo.repository_map import build_repository_map
from hivo.semantic_evidence import CALLER_EXPECTATION, CONTRACT, SemanticEvidenceResolver


class ProjectWorldModelTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self):
        self._temp.cleanup()

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    @staticmethod
    def request(kind, target):
        return {
            "kind": kind,
            "target": target,
            "why": "Need this precise semantic fact before deciding the bounded local change.",
        }

    def provenance(self, path, excerpt="source evidence", line="line 1", kind="test"):
        return {
            "path": path,
            "location": line,
            "evidence_kind": kind,
            "excerpt": excerpt,
        }

    def test_shared_reuse_avoids_repository_rediscovery_and_preserves_provenance(self):
        self.write("src/auth.py", "def refresh_token(value):\n    return value\n")
        self.write(
            "src/session.py",
            "def load(value):\n"
            "    result = refresh_token(value)\n"
            "    return result[\"token\"]\n",
        )
        model = ProjectWorldModel(self.root)
        request = self.request(CALLER_EXPECTATION, "refresh_token")

        cold = SemanticEvidenceResolver(self.root, [self.root], world_model=model).resolve(request)
        warm = SemanticEvidenceResolver(self.root, [self.root], world_model=model).resolve(request)

        self.assertEqual(cold["resolution_status"], "resolved")
        self.assertFalse(cold["world_model_reused"])
        self.assertTrue(cold["world_model_update"]["facts_stored"])
        self.assertEqual(warm["resolution_status"], "resolved")
        self.assertTrue(warm["world_model_reused"])
        self.assertFalse(warm["source_scan_performed"])
        self.assertTrue(warm["provenance"])
        self.assertTrue(all(item.get("path") for item in warm["provenance"]))

    def test_workers_share_model_but_receive_only_task_local_projection(self):
        source = self.write("src/project.py", "# verified semantic source\n")
        model = ProjectWorldModel(self.root)
        model.add_fact("X", CALLS, "Y", self.provenance("src/project.py"), semantic_kind=CALLER_EXPECTATION)
        model.add_fact("Y", RETURNS_TYPE, "TokenResponse", self.provenance("src/project.py"), semantic_kind=CONTRACT)
        model.add_fact("UNRELATED", CALLS, "OTHER", self.provenance("src/project.py"), semantic_kind=CALLER_EXPECTATION)
        for index in range(30):
            model.add_fact(
                f"UNRELATED_{index}", DEPENDS_ON, f"DEP_{index}",
                self.provenance("src/project.py"), semantic_kind="CALLEE_DEPENDENCY",
            )

        worker_a = model.projection_for_target("X")
        worker_b = model.projection_for_target("UNRELATED")

        self.assertIsNotNone(source)
        self.assertEqual(worker_a["project_identity"], worker_b["project_identity"])
        self.assertLessEqual(len(worker_a["facts"]), 4)
        self.assertLessEqual(len(worker_b["facts"]), 4)
        self.assertLess(len(json.dumps(worker_a)), len(json.dumps(model.snapshot())))
        self.assertTrue(all(item["state"] == VERIFIED for item in worker_a["facts"]))
        self.assertNotIn("UNRELATED_0", json.dumps(worker_a))

    def test_goal_anchor_is_not_changed_by_model_projection_or_completion(self):
        self.write("src/session.py", "def load(value):\n    return refresh_token(value)[\"token\"]\n")
        model = ProjectWorldModel(self.root)
        resolver = SemanticEvidenceResolver(self.root, [self.root], world_model=model)
        anchor = {
            "root_goal": "Ship the token refresh fix",
            "parent_goal": "Preserve session behavior",
            "local_task": "Update refresh_token",
            "requirements": ["keep the token field"],
            "constraints": ["do not change the public surface"],
        }
        gate = stage7.ContextSufficiencyGate(
            anchor,
            evidence_provider=lambda request, context: resolver.resolve(request, context),
        )
        before = gate.anchor
        gate.evaluate({
            "context_status": "insufficient",
            "reason": "The caller contract is missing from the initial packet.",
            "needed_evidence": [self.request(CALLER_EXPECTATION, "refresh_token")],
        })
        after = gate.anchor
        self.assertEqual(before, after)
        self.assertEqual(after["root_goal"], "Ship the token refresh fix")
        self.assertEqual(after["parent_goal"], "Preserve session behavior")
        self.assertEqual(after["local_task"], "Update refresh_token")

    def test_repository_map_seeds_typed_module_symbol_and_dependency_facts(self):
        self.write("src/auth.js", "import { encode } from './crypto.js';\nexport function refresh_token(value) { return encode(value); }\n")
        self.write("src/crypto.js", "export function encode(value) { return value; }\n")
        self.write("pkg/index.js", "export { refresh_token } from '../src/auth.js';\n")
        repository_map = build_repository_map(self.root)
        model = ProjectWorldModel(self.root, repository_map=repository_map)
        relations = {fact.relation for fact in model.facts}

        self.assertIn(DEFINED_IN, relations)
        self.assertIn(MODULE_CONTAINS, relations)
        self.assertIn(IMPORTS, relations)
        self.assertIn(DEPENDS_ON, relations)
        self.assertIn(EXPORTS, relations)
        self.assertIn(EXPORTED_BY, relations)
        self.assertTrue(model.modules)
        self.assertTrue(model.symbols)
        self.assertTrue(all(fact.state == VERIFIED for fact in model.facts))

    def test_semantic_resolution_enriches_model_only_after_supported_evidence(self):
        self.write("src/api.ts", "export interface TokenApi {\n  refresh_token(value: string): TokenResponse;\n}\n")
        model = ProjectWorldModel(self.root)
        result = SemanticEvidenceResolver(self.root, [self.root], world_model=model).resolve(
            self.request(CONTRACT, "refresh_token")
        )
        relations = {(fact.relation, fact.object, fact.state) for fact in model.facts}

        self.assertEqual(result["resolution_status"], "resolved")
        self.assertIn((RETURNS_TYPE, "TokenResponse", VERIFIED), relations)
        self.assertIn((IMPLEMENTS_CONTRACT, "declared contract", VERIFIED), relations)
        self.assertTrue(all(fact.provenance for fact in model.facts))

    def test_caller_and_test_resolution_write_atomic_behavior_facts(self):
        self.write("src/auth.py", "def refresh_token(value):\n    return {\"token\": value}\n")
        self.write(
            "src/session.py",
            "def load(value):\n"
            "    result = refresh_token(value)\n"
            "    return result[\"token\"]\n",
        )
        self.write(
            "tests/test_refresh.py",
            "def test_refresh():\n"
            "    assert refresh_token(\"x\")[\"token\"] == \"x\"\n",
        )
        model = ProjectWorldModel(self.root)
        resolver = SemanticEvidenceResolver(self.root, [self.root], world_model=model)
        caller = resolver.resolve(self.request(CALLER_EXPECTATION, "refresh_token"))
        test = resolver.resolve(self.request("TEST_EXPECTATION", "refresh_token"))
        relations = {fact.relation for fact in model.facts}

        self.assertEqual(caller["resolution_status"], "resolved")
        self.assertEqual(test["resolution_status"], "resolved")
        self.assertIn(CALLS, relations)
        self.assertIn(READS_FIELD, relations)
        self.assertIn(TESTED_BY, relations)
        self.assertIn(TEST_ASSERTS_BEHAVIOR_OF, relations)

    def test_state_transition_and_public_surface_are_stored_as_typed_facts(self):
        self.write(
            "src/state.js",
            "export function advance(state) {\n"
            "  if (state === IDLE) state = RUNNING;\n"
            "  if (state === RUNNING) state = COMPLETE;\n"
            "  return state;\n"
            "}\n",
        )
        self.write("pkg/index.js", "export { advance } from '../src/state.js';\n")
        model = ProjectWorldModel(self.root)
        resolver = SemanticEvidenceResolver(self.root, [self.root], world_model=model)
        transition = resolver.resolve(self.request("STATE_TRANSITION", "IDLE -> RUNNING -> COMPLETE"))
        public = resolver.resolve(self.request("EXPORT_OR_PUBLIC_SURFACE", "advance public export"))
        relations = {fact.relation for fact in model.facts}

        self.assertEqual(transition["resolution_status"], "resolved")
        self.assertEqual(public["resolution_status"], "resolved")
        self.assertIn(TRANSITIONS, relations)
        self.assertIn(EXPORTED_BY, relations)
        self.assertNotIn("textual_match", relations)

    def test_ambiguous_implementation_is_not_stored_as_verified_contract(self):
        self.write("src/auth.py", "def refresh_token(value):\n    return value\n")
        model = ProjectWorldModel(self.root)
        result = SemanticEvidenceResolver(self.root, [self.root], world_model=model).resolve(
            self.request(CONTRACT, "refresh_token")
        )

        self.assertEqual(result["resolution_status"], "partial")
        self.assertFalse(any(
            fact.relation in {RETURNS_TYPE, IMPLEMENTS_CONTRACT} and fact.state == VERIFIED
            for fact in model.facts
        ))
        self.assertTrue(any(fact.relation == DEFINED_IN for fact in model.facts))

    def test_mutation_invalidates_affected_facts_through_real_transaction(self):
        path = self.write("src/auth.py", "def refresh_token(value):\n    return value\n")
        saved = (mini.WORKSPACE, mini.RUN, mini.ACTIVE_TRANSACTION,
                 mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_PROJECT_WORLD_MODEL)
        try:
            mini.WORKSPACE = self.root
            mini.RUN = {}
            mini.ACTIVE_TOOL_CONTRACT = {"task_id": "T"}
            model = mini._world_model_for_workspace()
            fact = model.add_fact(
                "refresh_token", DEFINED_IN, "src/auth.py",
                self.provenance("src/auth.py", "def refresh_token"),
                semantic_kind="SYMBOL_DEFINITION",
                authority_tier="HIGH",
            )
            mini.begin_transaction("T")
            mini.edit_file("src/auth.py", "return value", "return {\"token\": value}")
            self.assertEqual(fact.state, STALE)
            self.assertGreaterEqual(model.stats["facts_invalidated"], 1)
        finally:
            if mini.ACTIVE_TRANSACTION is not None:
                mini.rollback_transaction()
            mini.WORKSPACE, mini.RUN, mini.ACTIVE_TRANSACTION, mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_PROJECT_WORLD_MODEL = saved
        self.assertTrue(path.exists())

    def test_successful_commit_revalidates_only_affected_symbol(self):
        self.write("src/auth.py", "def refresh_token(value):\n    return value\n")
        self.write("src/other.py", "def unrelated(value):\n    return value\n")
        saved = (mini.WORKSPACE, mini.RUN, mini.ACTIVE_TRANSACTION,
                 mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_PROJECT_WORLD_MODEL)
        try:
            mini.WORKSPACE = self.root
            mini.RUN = {}
            mini.ACTIVE_TOOL_CONTRACT = {"task_id": "T"}
            model = mini._world_model_for_workspace()
            model.add_fact(
                "refresh_token", DEFINED_IN, "src/auth.py",
                self.provenance("src/auth.py", "def refresh_token"),
                semantic_kind="SYMBOL_DEFINITION", authority_tier="HIGH",
            )
            model.add_fact(
                "unrelated", DEFINED_IN, "src/other.py",
                self.provenance("src/other.py", "def unrelated"),
                semantic_kind="SYMBOL_DEFINITION", authority_tier="HIGH",
            )
            mini.begin_transaction("T")
            mini.edit_file("src/auth.py", "return value", "return value + 1")
            mini.commit_transaction()
            auth_fact = next(fact for fact in model.facts if fact.subject == "refresh_token")
            other_fact = next(fact for fact in model.facts if fact.subject == "unrelated")
            self.assertEqual(auth_fact.state, VERIFIED)
            self.assertEqual(other_fact.state, VERIFIED)
            self.assertGreaterEqual(mini.RUN.get("world_model_source_scans", 0), 1)
        finally:
            mini.WORKSPACE, mini.RUN, mini.ACTIVE_TRANSACTION, mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_PROJECT_WORLD_MODEL = saved

    def test_rollback_restores_exact_source_and_reenables_old_fact(self):
        self.write("src/auth.py", "def refresh_token(value):\n    return value\n")
        saved = (mini.WORKSPACE, mini.RUN, mini.ACTIVE_TRANSACTION,
                 mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_PROJECT_WORLD_MODEL)
        try:
            mini.WORKSPACE = self.root
            mini.RUN = {}
            mini.ACTIVE_TOOL_CONTRACT = {"task_id": "T"}
            model = mini._world_model_for_workspace()
            fact = model.add_fact(
                "refresh_token", DEFINED_IN, "src/auth.py",
                self.provenance("src/auth.py", "def refresh_token"),
                semantic_kind="SYMBOL_DEFINITION", authority_tier="HIGH",
            )
            mini.begin_transaction("T")
            mini.edit_file("src/auth.py", "return value", "return None")
            self.assertEqual(fact.state, STALE)
            mini.rollback_transaction()
            self.assertEqual(fact.state, VERIFIED)
            self.assertEqual((self.root / "src/auth.py").read_text(encoding="utf-8").splitlines()[-1], "    return value")
        finally:
            mini.WORKSPACE, mini.RUN, mini.ACTIVE_TRANSACTION, mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_PROJECT_WORLD_MODEL = saved

    def test_rollback_keeps_post_mutation_facts_stale(self):
        self.write("src/auth.py", "def refresh_token(value):\n    return value\n")
        saved = (mini.WORKSPACE, mini.RUN, mini.ACTIVE_TRANSACTION,
                 mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_PROJECT_WORLD_MODEL)
        try:
            mini.WORKSPACE = self.root
            mini.RUN = {}
            mini.ACTIVE_TOOL_CONTRACT = {"task_id": "T"}
            model = mini._world_model_for_workspace()
            old_fact = model.add_fact(
                "refresh_token", RETURNS_TYPE, "str",
                self.provenance("src/auth.py", "old return contract"),
                semantic_kind=CONTRACT, authority_tier="HIGH",
            )
            mini.begin_transaction("T")
            mini.edit_file("src/auth.py", "return value", "return {\"token\": value}")
            new_fact = model.add_fact(
                "refresh_token", RETURNS_TYPE, "TokenResponse",
                self.provenance("src/auth.py", "post-mutation return contract"),
                semantic_kind=CONTRACT, authority_tier="HIGH",
            )
            self.assertEqual(new_fact.state, VERIFIED)
            mini.rollback_transaction()

            self.assertEqual(old_fact.state, VERIFIED)
            self.assertEqual(new_fact.state, STALE)
            self.assertEqual(
                model.resolve_request(self.request(CONTRACT, "refresh_token"))["resolution_status"],
                "resolved",
            )
        finally:
            if mini.ACTIVE_TRANSACTION is not None:
                mini.rollback_transaction()
            mini.WORKSPACE, mini.RUN, mini.ACTIVE_TRANSACTION, mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_PROJECT_WORLD_MODEL = saved

    def test_current_authoritative_conflict_is_preserved_and_gate_stays_blocked(self):
        self.write("src/a.py", "# source A\n")
        self.write("src/b.py", "# source B\n")
        model = ProjectWorldModel(self.root)
        model.add_fact("X", RETURNS_TYPE, "str", self.provenance("src/a.py"), authority_tier="HIGH")
        model.add_fact("X", RETURNS_TYPE, "TokenResponse", self.provenance("src/b.py"), authority_tier="HIGH")
        result = model.resolve_request(self.request(CONTRACT, "X"))
        gate = stage7.ContextSufficiencyGate(
            {"root_goal": "preserve X", "local_task": "change X"},
            initial_evidence=result["evidence"],
            evidence_provider=lambda request, context: [],
        )
        checked = gate.evaluate({"context_status": "sufficient", "reason": "Try to proceed despite conflict."})

        self.assertEqual(result["resolution_status"], "conflicting")
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(len(result["provenance"]), 2)
        self.assertFalse(checked["mutation_allowed"])
        self.assertTrue(all(fact.state == CONFLICTING for fact in model.facts))

    def test_neighborhood_hops_and_fact_count_are_bounded(self):
        source = self.write("src/graph.py", "# graph evidence\n")
        model = ProjectWorldModel(self.root)
        for index in range(30):
            model.add_fact(
                f"N{index}", DEPENDS_ON, f"N{index + 1}",
                self.provenance("src/graph.py"), authority_tier="HIGH",
            )
        view = model.neighborhood("N0", max_hops=MAX_WORLD_MODEL_HOPS, max_facts=12)

        self.assertLessEqual(view["hops"], MAX_WORLD_MODEL_HOPS)
        self.assertLessEqual(len(view["facts"]), MAX_WORLD_MODEL_FACTS_PER_PROJECTION)
        self.assertFalse(any(fact.object == "N30" for fact in view["facts"]))
        self.assertTrue(source.exists())

    def test_projection_is_minimal_even_when_model_has_more_than_100_facts(self):
        self.write("src/facts.py", "# bounded fact provenance\n")
        model = ProjectWorldModel(self.root)
        model.add_fact("X", CALLS, "Y", self.provenance("src/facts.py"), semantic_kind=CALLER_EXPECTATION)
        model.add_fact("X", READS_FIELD, "Y:token", self.provenance("src/facts.py"), semantic_kind=CALLER_EXPECTATION)
        for index in range(110):
            model.add_fact(
                f"OTHER_{index}", DEPENDS_ON, f"DEPENDENCY_{index}",
                self.provenance("src/facts.py"), semantic_kind="CALLEE_DEPENDENCY",
            )
        projection = model.projection_for_target("X")

        self.assertGreaterEqual(model.fact_count, 100)
        self.assertLessEqual(len(projection["facts"]), 4)
        self.assertTrue(all(item["subject"] == "X" for item in projection["facts"]))

    def test_project_identities_isolate_same_named_symbols(self):
        other = tempfile.TemporaryDirectory()
        other_root = Path(other.name)
        try:
            self.write("src/x.py", "def refresh_token():\n    return 'A'\n")
            (other_root / "src").mkdir(parents=True)
            (other_root / "src/x.py").write_text("def refresh_token():\n    return 'B'\n", encoding="utf-8")
            left = ProjectWorldModel(self.root)
            right = ProjectWorldModel(other_root)
            left.add_fact("refresh_token", RETURNS_TYPE, "A", self.provenance("src/x.py"), authority_tier="HIGH")
            right.add_fact(
                "refresh_token", RETURNS_TYPE, "B",
                {"path": "src/x.py", "location": "line 2", "excerpt": "return 'B'"},
                authority_tier="HIGH",
            )
            self.assertNotEqual(left.project_identity, right.project_identity)
            self.assertEqual(left.resolve_request(self.request(CONTRACT, "refresh_token"))["evidence"][0]["claim_value"], "A")
            self.assertEqual(right.resolve_request(self.request(CONTRACT, "refresh_token"))["evidence"][0]["claim_value"], "B")
        finally:
            other.cleanup()

    def test_verified_fact_without_provenance_is_rejected(self):
        self.write("src/x.py", "x = 1\n")
        model = ProjectWorldModel(self.root)

        fact = model.add_fact("X", RETURNS_TYPE, "str", None, authority_tier="HIGH")

        self.assertIsNone(fact)
        self.assertEqual(model.fact_count, 0)
        self.assertEqual(model.stats["facts_rejected"], 1)

    def test_resolver_cache_is_invalidated_when_source_fingerprint_changes(self):
        api = self.write("src/api.ts", "export interface Api {\n  refresh_token(): TokenResponse;\n}\n")
        model = ProjectWorldModel(self.root)
        request = self.request(CONTRACT, "refresh_token")
        first = SemanticEvidenceResolver(self.root, [self.root], world_model=model).resolve(request)
        self.assertEqual(first["resolution_status"], "resolved")
        api.write_text("// the old contract is gone\n", encoding="utf-8")
        second = SemanticEvidenceResolver(self.root, [self.root], world_model=model).resolve(request)

        self.assertFalse(second["world_model_reused"])
        self.assertTrue(second["source_scan_performed"])
        self.assertNotEqual(second["resolution_status"], "resolved")
        self.assertTrue(any(fact.state == STALE for fact in model.facts))

    def test_cached_resolution_obeys_direct_resolver_inspection_scope(self):
        self.write("src/allowed.py", "# allowed source\n")
        self.write("src/private.py", "# private source\n")
        model = ProjectWorldModel(self.root)
        model.add_fact(
            "X", RETURNS_TYPE, "PrivateType",
            self.provenance("src/private.py"), authority_tier="HIGH",
            semantic_kind=CONTRACT,
        )
        result = SemanticEvidenceResolver(
            self.root, [self.root / "src" / "allowed.py"], world_model=model,
        ).resolve(self.request(CONTRACT, "X"))

        self.assertFalse(result["world_model_reused"])
        self.assertTrue(result["source_scan_performed"])
        self.assertNotEqual(result["resolution_status"], "resolved")

    def test_full_gate_model_mutation_invalidation_and_warm_followup(self):
        self.write("src/auth.py", "def refresh_token(value):\n    return value\n")
        self.write(
            "src/session.py",
            "def load(value):\n"
            "    result = refresh_token(value)\n"
            "    return result[\"token\"]\n",
        )
        saved = (mini.WORKSPACE, mini.RUN, mini.ACTIVE_TRANSACTION,
                 mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE,
                 mini.ACTIVE_PROJECT_WORLD_MODEL)
        try:
            mini.WORKSPACE = self.root
            mini.RUN = {}
            mini.ACTIVE_TOOL_CONTRACT = {"task_id": "A"}
            gate = stage7.ContextSufficiencyGate(
                {
                    "root_goal": "preserve token refresh",
                    "local_task": "change refresh_token",
                    "allowed_inspection_paths": [str(self.root)],
                },
                initial_evidence=[{
                    "kind": "implementation",
                    "source_identity": "src/auth.py:1",
                    "excerpt": "def refresh_token(value):",
                }],
                evidence_provider=mini._provide_targeted_context_evidence,
            )
            mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE = gate
            incomplete = gate.evaluate({
                "context_status": "insufficient",
                "reason": "The caller expectation is not in the initial packet.",
                "needed_evidence": [self.request(CALLER_EXPECTATION, "refresh_token")],
            })
            self.assertFalse(incomplete["mutation_allowed"])
            model = mini.ACTIVE_PROJECT_WORLD_MODEL
            self.assertIsNotNone(model)
            self.assertTrue(any(fact.relation == READS_FIELD for fact in model.facts))
            model.add_fact(
                "refresh_token", DEFINED_IN, "src/auth.py",
                self.provenance("src/auth.py", "def refresh_token"),
                semantic_kind="SYMBOL_DEFINITION", authority_tier="HIGH",
            )
            allowed = gate.evaluate({
                "context_status": "sufficient",
                "reason": "The cached caller evidence establishes the required field.",
            })
            self.assertTrue(allowed["mutation_allowed"])
            mini.begin_transaction("A")
            mini.run_tool("edit_file", {
                "path": "src/auth.py",
                "old": "return value",
                "new": "return {\"token\": value}",
            }, role="Builder")
            self.assertTrue(any(fact.state == STALE for fact in model.facts if "src/auth.py" in str(fact.provenance)))
            mini.commit_transaction()
            followup = SemanticEvidenceResolver(self.root, [self.root], world_model=model).resolve(
                self.request(CALLER_EXPECTATION, "refresh_token")
            )
            self.assertEqual(followup["resolution_status"], "resolved")
            self.assertTrue(followup["world_model_reused"])
        finally:
            if mini.ACTIVE_TRANSACTION is not None:
                mini.rollback_transaction()
            (mini.WORKSPACE, mini.RUN, mini.ACTIVE_TRANSACTION,
             mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE,
             mini.ACTIVE_PROJECT_WORLD_MODEL) = saved

    def test_cold_warm_reuse_benchmark_reports_actual_counts(self):
        self.write("src/auth.py", "def refresh_token(value) -> TokenResponse:\n    return value\n")
        self.write(
            "src/session.py",
            "def load(value):\n"
            "    result = refresh_token(value)\n"
            "    return result[\"token\"]\n",
        )
        requests = [self.request(CALLER_EXPECTATION, "refresh_token") for _ in range(5)]
        cold = [
            SemanticEvidenceResolver(self.root, [self.root], world_model=ProjectWorldModel(self.root)).resolve(request)
            for request in requests
        ]
        warm_model = ProjectWorldModel(self.root)
        warm = [
            SemanticEvidenceResolver(self.root, [self.root], world_model=warm_model).resolve(request)
            for request in requests
        ]
        metrics = {
            "semantic_request_count": len(requests),
            "cold_repository_scans": sum(bool(item.get("source_scan_performed")) for item in cold),
            "warm_repository_scans": sum(bool(item.get("source_scan_performed")) for item in warm),
            "warm_reused_verified_facts": sum(bool(item.get("world_model_reused")) for item in warm),
            "average_projected_evidence_items": round(
                sum(len(item.get("evidence", [])) for item in warm) / len(warm), 3,
            ),
            "incorrect_cached_facts_returned": sum(
                item.get("resolution_status") != "resolved" for item in warm
            ),
        }
        print("WORLD_MODEL_BENCHMARK " + json.dumps(metrics, sort_keys=True))

        self.assertGreater(metrics["cold_repository_scans"], metrics["warm_repository_scans"])
        self.assertGreater(metrics["warm_reused_verified_facts"], 0)
        self.assertLessEqual(metrics["average_projected_evidence_items"], MAX_WORLD_MODEL_FACTS_PER_PROJECTION)
        self.assertEqual(metrics["incorrect_cached_facts_returned"], 0)


if __name__ == "__main__":
    unittest.main()
