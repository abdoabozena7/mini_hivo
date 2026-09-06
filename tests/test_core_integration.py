from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hivo.core_execution import (
    BUILD, COMPLETE, CoreBudget, CoreExecutionState, INITIALIZING,
    PATCH_SEARCHING, PROMOTABLE, REPAIR, STALE_CONTEXT,
)
from hivo.core_orchestrator import (
    CORE_COMPLETE, CORE_BLOCKED, CoreIntelligenceCoordinator,
    ModelPatchCandidateProviderAdapter, adapt_candidate_failure_evidence,
    classify_core_task,
)
from hivo.generation_units import GenerationUnit, GeneratedArtifactCandidate
from hivo.patch_candidates import (
    DETERMINISTIC_OPERATOR, PatchCandidate, PatchOperation, PatchRepresentation,
    VIABLE,
)
from hivo.project_blueprint import ModuleContract, ProjectBlueprint, ProjectRequirement
from hivo.project_brain_refs import canonical_hash
from hivo.project_builder import DeterministicFakeProvider
from hivo.repair_problem import RepairProblem, RepairTargetSet


class CoreIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hivo_core_integration_")
        self.root = Path(self.temp.name)
        self._write("README.md", "integrated fixture")

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, relative: str, text: str):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _blueprint_units_provider(self, count: int = 2):
        requirements = []
        contracts = []
        units = []
        candidates = {}
        previous = None
        for index in range(count):
            module = f"m{index:02d}"
            path = f"src/{module}.py"
            requirements.append(ProjectRequirement(f"REQ-{module}", "FUNCTIONAL", f"Expose {module}", ("callable",), module_hints=(module,)))
            contracts.append(ModuleContract(module, module, f"Own {module}", public_interfaces=(module,), dependencies=((previous,) if previous else ()), target_paths=(path,), requirement_ids=(f"REQ-{module}",)))
            dependency = (previous,) if previous else ()
            units.append(GenerationUnit(f"unit-{module}", module, f"Generate {module}", target_paths=(path,), dependencies=dependency, authority_scope=(path,)))
            candidates[f"unit-{module}"] = (GeneratedArtifactCandidate(f"candidate-{module}", f"unit-{module}", content={path: f"def {module}(value=1):\n    return value\n"}),)
            previous = module
        blueprint = ProjectBlueprint("integration-fixture", requirements=tuple(requirements), module_contracts=tuple(contracts), revision_identity="integration-rev")
        scope = tuple(f"src/m{index:02d}.py" for index in range(count))
        provider = DeterministicFakeProvider(candidates)
        return blueprint, tuple(units), provider, {
            "approved_generation_scope": scope,
            "approved_mutation_scope": scope,
        }

    def _repair_problem(self, coordinator: CoreIntelligenceCoordinator, path: str = "src/m00.py"):
        current = (self.root / path).read_text(encoding="utf-8")
        old = "return value"
        replacement = "return value + 1"
        return RepairProblem(
            repair_id="REPAIR-INTEGRATION-1", task_identity="change leaf behavior",
            subject_identity=coordinator.subject_identity, revision_identity=coordinator.revision_identity,
            working_set_identity="", fault_localization_identity="LOCALIZATION-INTEGRATION-1",
            target_set=RepairTargetSet(candidate_files=(path,)),
            suspect_candidates=({
                "candidate_id": "suspect-m00", "path": path, "symbol": "m00", "score": 9.0,
                "authority_label": "FINAL_MUTATION_AUTHORIZED",
                "evidence_sources": ("exact_symbol",),
                "metadata": {"expected_text": old, "actual_text": replacement},
            },),
            authority_context={"approved_mutation_scope": (path,)},
            project_root=str(self.root),
            metadata={"expected_text": old, "actual_text": replacement, "current_source_hash": canonical_hash(current)},
        )

    def test_classifier_and_state_machine_are_deterministic(self):
        self.assertEqual(BUILD, classify_core_task("new", project_root=self.root, blueprint={"project_id": "p"}))
        self.assertEqual(REPAIR, classify_core_task("fix", project_root=self.root, repair_problem={}))
        self.assertEqual("DIAGNOSE", classify_core_task("failure", project_root=self.root, failure_evidence={"message": "bad"}))
        state = CoreExecutionState("E", "MAINTAIN", "s", "r", "a")
        state = state.transition("CONTEXT_BUILDING")
        with self.assertRaises(ValueError):
            state.transition(PROMOTABLE)
        self.assertEqual(INITIALIZING, CoreExecutionState("E2", "BUILD", "s", "r", "a").current_phase)

    def test_build_uses_core6_and_preserves_final_verification_authority(self):
        blueprint, units, provider, authority = self._blueprint_units_provider()
        coordinator = CoreIntelligenceCoordinator(self.root, authority=authority, generation_provider=provider)
        result = coordinator.execute(
            "build the integration fixture", mode=BUILD, blueprint=blueprint, units=units,
            v25_5_validator=lambda *args, **kwargs: True,
            v25_6_validator=lambda *args, **kwargs: True,
        )
        self.assertEqual(CORE_COMPLETE, result.status)
        self.assertEqual(COMPLETE, result.state.current_phase)
        self.assertTrue(result.verification_state["full_v25_6_passed"])
        self.assertEqual(coordinator.subject_identity, result.state.subject_identity)
        self.assertTrue((self.root / "src/m00.py").exists())
        self.assertEqual(2, result.metrics["generation_units_processed"])
        self.assertGreaterEqual(result.metrics["repository_map_incremental_updates"], 2)
        self.assertGreaterEqual(result.metrics["verified_brain_updates"], 2)
        self.assertEqual(2, result.provider_accounting["generation_requests"])
        self.assertFalse(result.source_unchanged)

    def test_build_failure_does_not_poison_canonical_subject_or_brain(self):
        blueprint, units, provider, authority = self._blueprint_units_provider()
        before = canonical_hash(sorted(path.name for path in self.root.iterdir()))
        coordinator = CoreIntelligenceCoordinator(self.root, authority=authority, generation_provider=provider)
        result = coordinator.build(
            "build", blueprint, units,
            v25_5_validator=lambda *args, **kwargs: True,
            v25_6_validator=lambda *args, **kwargs: False,
        )
        self.assertEqual(CORE_BLOCKED, result.status)
        self.assertEqual(before, canonical_hash(sorted(path.name for path in self.root.iterdir())))
        self.assertEqual(0, len(coordinator.brain_entities))
        self.assertFalse((self.root / "src/m00.py").exists())

    def test_generated_project_is_searchable_then_maintained_incrementally(self):
        blueprint, units, provider, authority = self._blueprint_units_provider()
        coordinator = CoreIntelligenceCoordinator(self.root, authority=authority, generation_provider=provider)
        built = coordinator.build("build", blueprint, units, v25_5_validator=lambda *a, **k: True, v25_6_validator=lambda *a, **k: True)
        self.assertEqual(CORE_COMPLETE, built.status)
        context = coordinator.maintain("find m00", blueprint=blueprint)
        self.assertEqual(CORE_COMPLETE, context.status)
        self.assertIn("core2", context.component_results)
        self.assertGreaterEqual(context.metrics["working_sets_created"], 1)
        self.assertEqual(0, context.metrics["full_repository_context_loads"])

    def test_core5_repair_requires_explicit_candidate_and_full_verification(self):
        blueprint, units, provider, authority = self._blueprint_units_provider()
        coordinator = CoreIntelligenceCoordinator(self.root, authority=authority, generation_provider=provider)
        coordinator.build("build", blueprint, units, v25_5_validator=lambda *a, **k: True, v25_6_validator=lambda *a, **k: True)
        problem = self._repair_problem(coordinator)
        searched = coordinator.search_repair_candidates(problem, v25_5_gate=lambda *a, **k: True, v25_6_verifier=lambda *a, **k: True)
        self.assertIsNotNone(searched.winner)
        self.assertTrue(searched.winner.status in {VIABLE, "VERIFIED"})
        before = coordinator.subject_identity
        maintained = coordinator.maintain(
            "repair m00", repair_problem=problem, apply_candidate=True,
            selected_candidate_id=searched.winner.candidate_id,
            v25_5_gate=lambda *a, **k: True, v25_6_verifier=lambda *a, **k: True,
        )
        self.assertEqual(CORE_COMPLETE, maintained.status)
        self.assertNotEqual(before, coordinator.subject_identity)
        self.assertGreaterEqual(maintained.metrics["successful_repairs"], 1)
        self.assertGreaterEqual(maintained.metrics["repository_map_incremental_updates"], 1)
        self.assertGreaterEqual(maintained.metrics["verified_brain_updates"], 1)
        self.assertFalse(maintained.source_unchanged)

    def test_failed_candidate_does_not_change_indexes_or_brain(self):
        blueprint, units, provider, authority = self._blueprint_units_provider()
        coordinator = CoreIntelligenceCoordinator(self.root, authority=authority, generation_provider=provider)
        coordinator.build("build", blueprint, units, v25_5_validator=lambda *a, **k: True, v25_6_validator=lambda *a, **k: True)
        problem = self._repair_problem(coordinator)
        before_subject = coordinator.subject_identity
        before_map = coordinator.repository_map.logical_hash
        before_lexical = coordinator.lexical_index.logical_hash
        result = coordinator.maintain(
            "repair", repair_problem=problem, apply_candidate=True,
            v25_5_gate=lambda *a, **k: True, v25_6_verifier=lambda *a, **k: False,
        )
        self.assertEqual(CORE_BLOCKED, result.status)
        self.assertEqual(before_subject, coordinator.subject_identity)
        self.assertEqual(before_map, coordinator.repository_map.logical_hash)
        self.assertEqual(before_lexical, coordinator.lexical_index.logical_hash)
        self.assertEqual(0, result.metrics["verified_brain_updates"])

    def test_authority_and_dnt_are_hard_boundaries(self):
        blueprint, units, provider, authority = self._blueprint_units_provider()
        coordinator = CoreIntelligenceCoordinator(self.root, authority=authority, generation_provider=provider, dnt_paths=("src/m00.py",))
        result = coordinator.build("build", blueprint, units, v25_5_validator=lambda *a, **k: True, v25_6_validator=lambda *a, **k: True)
        self.assertEqual(CORE_BLOCKED, result.status)
        self.assertFalse((self.root / "src/m00.py").exists())

    def test_stale_repair_problem_is_rejected(self):
        blueprint, units, provider, authority = self._blueprint_units_provider()
        coordinator = CoreIntelligenceCoordinator(self.root, authority=authority, generation_provider=provider)
        coordinator.build("build", blueprint, units, v25_5_validator=lambda *a, **k: True, v25_6_validator=lambda *a, **k: True)
        problem = self._repair_problem(coordinator)
        self._write("revision.txt", "changed")
        result = coordinator.maintain("repair", repair_problem=problem, apply_candidate=True, v25_5_gate=lambda *a, **k: True, v25_6_verifier=lambda *a, **k: True)
        self.assertEqual(CORE_BLOCKED, result.status)
        self.assertTrue(any(item["category"] == STALE_CONTEXT for item in result.failure_evidence))

    def test_candidate_failure_adapter_is_non_authoritative(self):
        failure = {"candidate_id": "c", "status": "TARGET_FAILED", "stage": "targeted", "reason": "failed", "target_path": "src/m00.py"}
        adapted = adapt_candidate_failure_evidence(failure, subject_identity="s", revision_identity="r")
        self.assertEqual("src/m00.py", adapted.path)
        self.assertEqual("s", adapted.subject_identity)
        self.assertIn("candidate_failure_evidence", adapted.metadata)

    def test_model_patch_adapter_receives_bounded_packet_only(self):
        seen = []

        class FakePatchProvider:
            def generate(self, problem, context, *, limit):
                seen.append((problem, context, limit))
                return ()

        coordinator = CoreIntelligenceCoordinator(self.root, patch_provider=FakePatchProvider())
        problem = RepairProblem("r", "task", coordinator.subject_identity, coordinator.revision_identity, "w", "l", project_root=str(self.root))
        adapter = ModelPatchCandidateProviderAdapter(coordinator.patch_provider, coordinator)
        self.assertEqual((), tuple(adapter.generate(problem, {"source_slices": [{"path": "src/x.py", "body": "bounded"}]}, limit=1)))
        self.assertEqual(1, len(seen))
        self.assertIn("repair_evidence_packet", seen[0][1])
        self.assertNotIn("full_repository", seen[0][1])

    def test_state_cannot_jump_from_patch_search_to_promotable(self):
        state = CoreExecutionState("E", "REPAIR", "s", "r", "a")
        state = state.transition("CONTEXT_BUILDING").transition("PATCH_SEARCHING")
        with self.assertRaises(ValueError):
            state.transition(PROMOTABLE, verification_state={"full_v25_6_passed": True})

    def test_explicit_candidate_application_still_requires_real_gates(self):
        self._write("src/x.py", "def x():\n    return 1\n")
        coordinator = CoreIntelligenceCoordinator(self.root, authority={"approved_mutation_scope": ("src/x.py",)})
        operation = PatchOperation("src/x.py", expected_text="return 1", replacement="return 2")
        candidate = PatchCandidate(
            "candidate-x", "src/x.py", strategy="EXACT_VALUE_CHANGE", provenance=DETERMINISTIC_OPERATOR,
            representation=PatchRepresentation((operation,)), status=VIABLE,
            base_subject_hash=coordinator.subject_identity, candidate_source_hash=coordinator.subject_identity,
            target_authority="FINAL_MUTATION_AUTHORIZED",
        )
        blocked = coordinator.apply_patch_candidate(candidate, v25_5_gate=None, v25_6_verifier=lambda *a: True)
        self.assertFalse(blocked["applied"])
        self.assertEqual("FINAL_VERIFICATION_FAILED", blocked["status"])

    def test_execution_state_and_result_containers_are_immutable(self):
        coordinator = CoreIntelligenceCoordinator(self.root)
        result = coordinator.maintain("locate the integration fixture")
        with self.assertRaises(TypeError):
            result.metrics["core_stages"] = 99
        with self.assertRaises(TypeError):
            result.state.budget_usage["core_stages"] = 99
        self.assertEqual(result.canonical_hash, result.canonical_hash)

    def test_generation_packet_stale_state_is_rejected(self):
        blueprint, units, provider, authority = self._blueprint_units_provider(count=1)
        coordinator = CoreIntelligenceCoordinator(self.root, authority=authority, generation_provider=provider)
        built = coordinator.build("build", blueprint, units, v25_5_validator=lambda *a, **k: True, v25_6_validator=lambda *a, **k: True)
        self.assertEqual(CORE_COMPLETE, built.status)
        packet = coordinator.request_generation_unit_context("unit-m00")
        candidate = GeneratedArtifactCandidate(
            "candidate-stale", "unit-m00", content={"src/m00.py": "def m00(value=1):\n    return value + 1\n"},
            packet_id=packet.packet_id,
        )
        self._write("unrelated.txt", "subject changed")
        rejected = coordinator.submit_generation_candidate("unit-m00", candidate)
        self.assertEqual(STALE_CONTEXT, rejected["status"])

    def test_patch_submission_is_a_proposal_until_explicitly_applied(self):
        self._write("src/x.py", "def x():\n    return 1\n")
        coordinator = CoreIntelligenceCoordinator(self.root, authority={"approved_mutation_scope": ("src/x.py",)})
        operation = PatchOperation("src/x.py", expected_text="return 1", replacement="return 2")
        candidate = PatchCandidate(
            "candidate-proposal", "src/x.py", strategy="EXACT_VALUE_CHANGE", provenance=DETERMINISTIC_OPERATOR,
            representation=PatchRepresentation((operation,)), status=VIABLE,
            base_subject_hash=coordinator.subject_identity, candidate_source_hash=coordinator.subject_identity,
            target_authority="FINAL_MUTATION_AUTHORIZED",
        )
        before = coordinator.subject_identity
        proposal = coordinator.submit_patch_candidate(candidate)
        self.assertEqual("PROPOSAL_RECEIVED", proposal["status"])
        self.assertFalse(proposal["applied"])
        self.assertEqual(before, coordinator.subject_identity)


if __name__ == "__main__":
    unittest.main()
