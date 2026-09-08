import json
import tempfile
import unittest
from pathlib import Path

import mini
from hivo import context_sufficiency as stage7
from hivo.semantic_evidence import (
    CALLER_EXPECTATION,
    CALLEE_DEPENDENCY,
    CONFIGURATION_DEPENDENCY,
    CONTRACT,
    EXPORT_OR_PUBLIC_SURFACE,
    STATE_INVARIANT,
    STATE_TRANSITION,
    TEST_EXPECTATION,
    TYPE_OR_SCHEMA,
    SYMBOL_DEFINITION,
    SIBLING_IMPLEMENTATION,
    SemanticEvidenceResolver,
)


class SemanticEvidenceResolverTests(unittest.TestCase):
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

    def resolver(self, **kwargs):
        return SemanticEvidenceResolver(self.root, [self.root], **kwargs)

    @staticmethod
    def request(kind, target, why=None):
        return {
            "kind": kind,
            "target": target,
            "why": why or f"Need the {str(kind).casefold()} evidence to make the bounded semantic decision.",
        }

    @staticmethod
    def anchor(root):
        return {
            "root_goal": "Ship the token refresh fix without changing the public API",
            "parent_goal": "Repair token refresh behavior",
            "local_task": "Update refresh_token implementation",
            "requirements": ["callers continue to receive the declared token value"],
            "constraints": ["preserve the existing return contract"],
            "allowed_inspection_paths": [str(root)],
        }

    def test_relevance_is_not_enough_actual_behavior_defining_caller_wins(self):
        self.write("src/auth.py", "def refresh_token(value):\n    return value\n")
        self.write("src/refresh_token_notes.py", "# refresh_token is mentioned in a note only\n")
        self.write(
            "src/session.py",
            "from src.auth import refresh_token\n"
            "def load_session(value):\n"
            "    result = refresh_token(value)\n"
            "    return result[\"access_token\"]\n",
        )

        result = self.resolver().resolve(self.request(CALLER_EXPECTATION, "refresh_token callers"))

        self.assertEqual(result["resolution_status"], "resolved")
        self.assertTrue(result["structural_search"])
        self.assertTrue(result["evidence"])
        self.assertEqual(result["evidence"][0]["source_identity"].split(":")[0], "src/session.py")
        self.assertIn("access_token", " ".join(result["facts_established"]))
        self.assertNotIn("refresh_token_notes.py", " ".join(item["source_identity"] for item in result["evidence"]))

    def test_contract_prefers_authoritative_interface_or_type_over_implementation_and_comment(self):
        self.write("src/auth.py", "def refresh_token(value):\n    return value\n")
        self.write("src/refresh_token_comments.py", "# refresh_token returns whatever the implementation currently returns\n")
        self.write(
            "src/api.ts",
            "export interface TokenApi {\n"
            "  refresh_token(value: string): TokenResponse;\n"
            "}\n"
            "export type TokenResponse = { access_token: string };\n",
        )

        result = self.resolver().resolve(self.request(CONTRACT, "refresh_token contract"))

        self.assertEqual(result["resolution_status"], "resolved")
        self.assertEqual(result["evidence"][0]["source_identity"].split(":")[0], "src/api.ts")
        self.assertEqual(result["evidence"][0]["authority_tier"], "HIGH")
        self.assertNotIn("src/auth.py", result["evidence"][0]["source_identity"])

    def test_test_expectation_prefers_direct_behavior_assertion(self):
        self.write("src/auth.py", "def refresh_token(value):\n    return {\"token\": value}\n")
        self.write("tests/test_mentions.py", "# refresh_token is part of the auth component\n")
        self.write(
            "tests/test_direct_refresh.py",
            "from src.auth import refresh_token\n"
            "def test_refresh_shape():\n"
            "    assert refresh_token(\"x\")[\"token\"] == \"x\"\n",
        )

        result = self.resolver().resolve(self.request(TEST_EXPECTATION, "refresh_token output"))

        self.assertEqual(result["resolution_status"], "resolved")
        self.assertEqual(result["evidence"][0]["source_identity"].split(":")[0], "tests/test_direct_refresh.py")
        self.assertEqual(result["evidence"][0]["relationship"], "direct_call_site")
        self.assertIn("token", " ".join(result["facts_established"]))

    def test_return_shape_expectation_establishes_mapping_and_required_field(self):
        self.write("src/auth.py", "def refresh_token(value):\n    return {\"token\": value}\n")
        self.write(
            "src/session.py",
            "def load(value):\n"
            "    result = refresh_token(value)\n"
            "    return result[\"token\"]\n",
        )

        result = self.resolver().resolve(self.request(CALLER_EXPECTATION, "refresh_token return value"))

        self.assertEqual(result["resolution_status"], "resolved")
        self.assertIn("mapping/object with field token", result["evidence"][0]["claim_value"])
        self.assertIn("mapping/object", " ".join(result["facts_established"]))
        self.assertIn("token", " ".join(result["facts_established"]))
        self.assertEqual(len(result["evidence"]), 1)

    def test_destructuring_and_return_annotation_are_structural_evidence(self):
        self.write(
            "src/auth.py",
            "def refresh_token(value) -> TokenResponse:\n"
            "    return {\"access_token\": value}\n",
        )
        self.write(
            "src/session.ts",
            "const { access_token } = refresh_token(value);\n",
        )

        caller = self.resolver().resolve(self.request(CALLER_EXPECTATION, "refresh_token caller expectation"))
        contract = self.resolver().resolve(self.request(CONTRACT, "refresh_token contract"))

        self.assertEqual(caller["resolution_status"], "resolved")
        self.assertIn("access_token", " ".join(caller["facts_established"]))
        self.assertEqual(caller["evidence"][0]["source_identity"].split(":")[0], "src/session.ts")
        self.assertEqual(contract["resolution_status"], "resolved")
        self.assertEqual(contract["evidence"][0]["role"], "contract_declaration")

    def test_state_transition_selects_transition_logic_not_independent_mentions(self):
        self.write(
            "src/state_machine.py",
            "def advance(state):\n"
            "    if state == IDLE: state = RUNNING\n"
            "    if state == RUNNING: state = COMPLETE\n"
            "    return state\n",
        )
        self.write("docs/state_notes.md", "# IDLE RUNNING COMPLETE are mentioned independently here\n")

        result = self.resolver().resolve(
            self.request(STATE_TRANSITION, "IDLE -> RUNNING -> COMPLETE transition")
        )

        self.assertEqual(result["resolution_status"], "resolved")
        self.assertEqual(result["evidence"][0]["source_identity"].split(":")[0], "src/state_machine.py")
        self.assertIn("IDLE -> RUNNING -> COMPLETE", " ".join(result["facts_established"]))
        self.assertEqual(result["evidence"][0]["relationship"], "before_after_transition")

    def test_export_public_surface_finds_barrel_or_init_reexport(self):
        self.write("src/auth.py", "def refresh_token(value):\n    return value\n")
        self.write(
            "pkg/__init__.py",
            "from src.auth import refresh_token\n"
            "__all__ = [\"refresh_token\"]\n",
        )

        result = self.resolver().resolve(
            self.request(EXPORT_OR_PUBLIC_SURFACE, "refresh_token public export")
        )

        self.assertEqual(result["resolution_status"], "resolved")
        self.assertEqual(result["evidence"][0]["source_identity"].split(":")[0], "pkg/__init__.py")
        self.assertIn("exports or re-exports", result["facts_established"][0])

    def test_remaining_semantic_request_classes_use_structural_handlers(self):
        self.write(
            "src/auth.py",
            "from src.crypto import encode\n"
            "import os\n"
            "def refresh_token(value):\n"
            "    assert value is not None\n"
            "    return encode(value)\n"
            "TOKEN_NAME = os.environ.get(\"REFRESH_TOKEN\")\n",
        )
        self.write("src/crypto.py", "def encode(value):\n    return value\n")
        self.write("src/types.py", "class TokenResponse(TypedDict):\n    token: str\n")
        self.write("src/siblings.py", "def refresh_password(value):\n    return value\n")

        cases = [
            (CALLEE_DEPENDENCY, "refresh_token", "callee_dependency", "resolved"),
            (TYPE_OR_SCHEMA, "TokenResponse", "type_schema", "resolved"),
            (STATE_INVARIANT, "refresh_token", "state_invariant", "resolved"),
            (SYMBOL_DEFINITION, "refresh_token", "symbol_definition", "resolved"),
            (SIBLING_IMPLEMENTATION, "refresh_token", "sibling_implementation", "resolved"),
            (CONFIGURATION_DEPENDENCY, "refresh_token", "configuration_dependency", "resolved"),
        ]
        resolver = self.resolver()
        for kind, target, role, expected in cases:
            with self.subTest(kind=kind):
                result = resolver.resolve(self.request(kind, target))
                self.assertEqual(result["resolution_status"], expected)
                self.assertTrue(any(item.get("role") == role for item in result["evidence"]))

    def test_conflicting_authority_is_retained_and_gate_stays_blocked(self):
        self.write(
            "src/session.py",
            "def read(value):\n"
            "    result = refresh_token(value)\n"
            "    return result[\"token\"]\n",
        )
        self.write(
            "tests/test_none.py",
            "def test_none():\n"
            "    assert refresh_token(\"x\") is None\n",
        )

        resolved = self.resolver().resolve(self.request(CALLER_EXPECTATION, "refresh_token expectation"))
        self.assertEqual(resolved["resolution_status"], "conflicting")
        self.assertGreaterEqual(len(resolved["evidence"]), 2)
        self.assertGreaterEqual(len(resolved["conflicts"]), 1)
        self.assertEqual(
            len({item["claim_value"] for item in resolved["evidence"]}),
            2,
        )
        self.assertNotIn("reconciled", json.dumps(resolved).casefold())

        requests = []
        gate = stage7.ContextSufficiencyGate(
            self.anchor(self.root),
            initial_evidence=resolved["evidence"],
            evidence_provider=lambda request, context: requests.append(request) or [],
        )
        result = gate.evaluate({
            "context_status": "sufficient",
            "reason": "The worker saw evidence but the return expectations disagree.",
        })

        self.assertFalse(result["mutation_allowed"])
        self.assertTrue(requests)
        self.assertEqual(requests[0]["kind"], "authoritative_contract")
        self.assertEqual(requests[0]["target"], "refresh_token")
        self.assertIn("conflict", result["reason"])

    def test_contract_with_only_implementation_is_partial(self):
        self.write("src/auth.py", "def refresh_token(value):\n    return value\n")

        result = self.resolver().resolve(self.request(CONTRACT, "refresh_token contract"))

        self.assertEqual(result["resolution_status"], "partial")
        self.assertEqual(result["evidence"][0]["role"], "implementation")
        self.assertFalse(result["evidence"][0]["authoritative"])
        self.assertIn("implementation", " ".join(result["facts_established"]))

    def test_relationship_and_candidate_expansion_is_bounded(self):
        for index in range(30):
            next_name = f"chain_{index + 1}.js"
            import_line = f"import './{next_name}';\n" if index < 29 else ""
            self.write(
                f"chain_{index}.js",
                import_line + f"// unrelated chain mention {index}\n",
            )
        self.write("src/service.py", "def service(value):\n    return value\n")

        result = self.resolver(max_candidates=5, max_files_scanned=10).resolve(
            self.request(CONTRACT, "service contract")
        )

        self.assertLessEqual(result["candidate_files_considered"], 10)
        self.assertLessEqual(result["candidates_considered"], 5)
        self.assertLessEqual(result["relationship_hops"], stage7_semantic_hop_limit())
        self.assertLessEqual(len(result["evidence"]), 3)

    def test_minimal_bundle_does_not_consume_all_valid_callers(self):
        self.write("src/auth.py", "def refresh_token(value):\n    return {\"token\": value}\n")
        for index in range(20):
            self.write(
                f"src/consumer_{index}.py",
                "def consume(value):\n"
                "    result = refresh_token(value)\n"
                "    return result[\"token\"]\n",
            )

        result = self.resolver().resolve(self.request(CALLER_EXPECTATION, "refresh_token callers"))

        self.assertEqual(result["resolution_status"], "resolved")
        self.assertLess(len(result["evidence"]), 20)
        self.assertLessEqual(len(result["evidence"]), 3)
        self.assertEqual(len(result["provenance"]), len(result["evidence"]))

    def test_every_fact_and_evidence_item_keeps_provenance(self):
        self.write(
            "src/session.py",
            "def read(value):\n"
            "    result = refresh_token(value)\n"
            "    return result[\"token\"]\n",
        )

        result = self.resolver().resolve(self.request(CALLER_EXPECTATION, "refresh_token caller"))

        self.assertTrue(result["facts_established"])
        self.assertTrue(result["provenance"])
        for item in result["evidence"]:
            self.assertTrue(item["source_identity"])
            self.assertTrue(item["excerpt"])
            self.assertTrue(item["provenance"])
            self.assertTrue(all("(source:" in fact for fact in item["facts_established"]))
        self.assertTrue(all(item.get("source_identity") for item in result["provenance"]))

    def test_gate_integration_resolves_targeted_request_before_authorization(self):
        self.write(
            "src/session.py",
            "def read(value):\n"
            "    result = refresh_token(value)\n"
            "    return result[\"token\"]\n",
        )
        saved_workspace, saved_run = mini.WORKSPACE, mini.RUN
        try:
            mini.WORKSPACE = self.root
            mini.RUN = {"repository_map": None}
            gate = stage7.ContextSufficiencyGate(
                self.anchor(self.root),
                evidence_provider=lambda request, context: mini._provide_targeted_context_evidence(request, context),
            )
            incomplete = gate.evaluate({
                "context_status": "insufficient",
                "reason": "The implementation is present but the caller return shape is missing.",
                "needed_evidence": [{
                    "kind": "CALLER_EXPECTATION",
                    "target": "refresh_token",
                    "why": "Need the caller access pattern to preserve the required returned token field.",
                }],
            })

            self.assertFalse(incomplete["mutation_allowed"])
            self.assertEqual(incomplete["semantic_resolutions"][0]["resolution_status"], "resolved")
            self.assertEqual(incomplete["evidence"][0]["source_identity"].split(":")[0], "src/session.py")

            authorized = gate.evaluate({
                "context_status": "sufficient",
                "reason": "The targeted caller evidence establishes the return shape.",
            })
            self.assertTrue(authorized["mutation_allowed"])
            self.assertEqual(authorized["lifecycle_state"], stage7.MUTATION_ALLOWED)
        finally:
            mini.WORKSPACE, mini.RUN = saved_workspace, saved_run

    def test_unresolvable_request_stops_after_gate_budget_and_never_authorizes(self):
        self.write("src/auth.py", "def refresh_token(value):\n    return value\n")
        calls = []
        resolver = self.resolver()

        def provider(request, context):
            calls.append(request)
            return resolver.resolve(request, context)

        gate = stage7.ContextSufficiencyGate(
            self.anchor(self.root),
            evidence_provider=provider,
        )
        incomplete = {
            "context_status": "insufficient",
            "reason": "The public contract is not available.",
            "needed_evidence": [{
                "kind": "CONTRACT",
                "target": "refresh_token",
                "why": "Need an authoritative return contract before changing the implementation.",
            }],
        }
        gate.evaluate(incomplete)
        result = None
        for _ in range(stage7.MAX_CONTEXT_COMPLETION_ROUNDS):
            result = gate.evaluate({
                "context_status": "sufficient",
                "reason": "The resolver still has no authoritative contract.",
            })

        self.assertEqual(len(calls), stage7.MAX_CONTEXT_COMPLETION_ROUNDS)
        self.assertEqual(result["failure_code"], stage7.CONTEXT_INSUFFICIENT_FAILURE)
        self.assertFalse(result["mutation_allowed"])
        self.assertEqual(result["semantic_resolutions"][-1]["resolution_status"], "partial")

    def test_semantic_benchmark_reports_actual_fixture_metrics(self):
        self.write("src/auth.py", "def refresh_token(value):\n    return {\"token\": value}\n")
        self.write(
            "src/session.py",
            "def read(value):\n"
            "    result = refresh_token(value)\n"
            "    return result[\"token\"]\n",
        )
        self.write(
            "src/api.ts",
            "export interface TokenApi {\n"
            "  refresh_token(value: string): TokenResponse;\n"
            "}\n"
            "export type TokenResponse = { token: string };\n",
        )
        self.write(
            "tests/test_refresh.py",
            "def test_refresh():\n"
            "    assert refresh_token(\"x\")[\"token\"] == \"x\"\n",
        )
        self.write(
            "src/state.py",
            "def advance(state):\n"
            "    if state == IDLE: state = RUNNING\n"
            "    if state == RUNNING: state = COMPLETE\n"
            "    return state\n",
        )
        self.write("pkg/__init__.py", "from src.auth import refresh_token\n")
        self.write("src/only_impl.py", "def local_api(value):\n    return value\n")

        cases = [
            (CALLER_EXPECTATION, "refresh_token callers", "resolved"),
            (CONTRACT, "refresh_token contract", "resolved"),
            (TEST_EXPECTATION, "refresh_token output", "resolved"),
            (STATE_TRANSITION, "IDLE -> RUNNING -> COMPLETE", "resolved"),
            (EXPORT_OR_PUBLIC_SURFACE, "refresh_token public export", "resolved"),
            (CONTRACT, "local_api contract", "partial"),
            (CONTRACT, "missing_api contract", "unresolved"),
        ]
        resolver = self.resolver()
        measured = [
            resolver.resolve(self.request(kind, target))
            for kind, target, _expected in cases
        ]
        correct = sum(
            actual["resolution_status"] == expected
            for actual, (_kind, _target, expected) in zip(measured, cases)
        )
        correctly_resolved = sum(
            expected == "resolved" and actual["resolution_status"] == "resolved"
            for actual, (_kind, _target, expected) in zip(measured, cases)
        )
        metrics = {
            "semantic_request_count": len(cases),
            "correctly_resolved_requests": correctly_resolved,
            "correctly_classified_requests": correct,
            "partial_requests": sum(item["resolution_status"] == "partial" for item in measured),
            "unresolved_requests": sum(item["resolution_status"] == "unresolved" for item in measured),
            "incorrect_semantic_resolutions": len(cases) - correct,
            "average_evidence_items": round(
                sum(len(item["evidence"]) for item in measured) / len(measured),
                3,
            ),
        }
        print("SEMANTIC_BENCHMARK " + json.dumps(metrics, sort_keys=True))
        self.assertEqual(metrics["incorrect_semantic_resolutions"], 0)


def stage7_semantic_hop_limit():
    from hivo.semantic_evidence import MAX_RELATIONSHIP_HOPS

    return MAX_RELATIONSHIP_HOPS


if __name__ == "__main__":
    unittest.main()
