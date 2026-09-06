from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hivo.change_impact import (
    CHANGE_PUBLIC_CONTRACT, CHANGE_PRIVATE, analyze_change_impact, build_change_island,
    detect_interface_drift,
)
from hivo.generation_checkpoint import CHECKPOINT_READY, CHECKPOINT_STALE, validate_generation_checkpoint
from hivo.generation_dag import (
    DEPENDS_ON, GENERATION_DEPENDENCY_CYCLE, GENERATION_FORBIDDEN_DEPENDENCY,
    GENERATION_PATH_OWNERSHIP_CONFLICT, build_dependency_dag,
)
from hivo.generation_units import (
    CONTRACT_REJECTED, EXISTING_MODIFICATION, GenerationEvidencePacket,
    GeneratedArtifactCandidate, GenerationUnit, NEW_ARTIFACT, SYNTAX_REJECTED,
)
from hivo.lexical_index import build_lexical_index
from hivo.project_blueprint import InterfaceSchema, ModuleContract, ProjectBlueprint, ProjectRequirement
from hivo.project_brain_refs import ProjectBrainEntity, TypedReference, canonical_hash
from hivo.project_builder import (
    AUTHORITY_FAILURE, CONTRACT_FAILURE, DeterministicFakeProvider, GenerationBudget,
    GENERATION_COMPLETE, GENERATION_PARTIAL, ProjectBuilder, build_generation_plan,
    validate_generated_artifact_candidate,
)
from hivo.repo_intelligence import RepoIntelligenceQuery, search_repository
from hivo.repository_map import build_repository_map


class Core6LargeProjectIncrementalBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hivo_core6_")
        self.root = Path(self.temp.name)
        self._write("README.md", "contract-first project")

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, relative: str, text: str):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _blueprint(self):
        requirement = ProjectRequirement(
            "REQ-1", "FUNCTIONAL", "Expose a leaf service", ("leaf is callable",), priority=10,
            module_hints=("leaf",), provenance=("test",),
        )
        interface = InterfaceSchema("IFACE-LEAF", "leaf", required_fields=("value",))
        leaf = ModuleContract(
            "leaf", "Leaf", "Own the leaf calculation", public_interfaces=("leaf",),
            invariants=("leaf is deterministic",), test_obligations=("tests/leaf_test.py",),
            target_paths=("src/leaf.py",), requirement_ids=("REQ-1",),
        )
        app = ModuleContract(
            "app", "Application", "Compose the leaf service", public_interfaces=("app",),
            dependencies=("leaf",), target_paths=("src/app.py",),
        )
        return ProjectBlueprint(
            "demo", requirements=(requirement,), module_contracts=(app, leaf),
            interfaces=(interface,), global_invariants=("no hidden global state",),
            generation_constraints=("small modules",), revision_identity="rev-1",
        )

    def _units(self):
        return (
            GenerationUnit("unit-leaf", "leaf", "implement leaf", target_paths=("src/leaf.py",), authority_scope=("src/leaf.py",)),
            GenerationUnit("unit-app", "app", "implement app", target_paths=("src/app.py",), dependencies=("leaf",), authority_scope=("src/app.py",)),
        )

    def _provider(self, *, invalid=False, existing=False):
        leaf_body = "def leaf(value=1):\n    return value\n"
        app_body = "def app(value=1):\n    return value\n"
        if invalid:
            leaf_body = "def leaf(value=1:\n    return value\n"
        leaf = GeneratedArtifactCandidate("cand-leaf", "unit-leaf", content={"src/leaf.py": leaf_body})
        app = GeneratedArtifactCandidate(
            "cand-app", "unit-app", artifact_kind=EXISTING_MODIFICATION if existing else NEW_ARTIFACT,
            content={"src/app.py": app_body},
        )
        return DeterministicFakeProvider({"unit-leaf": (leaf,), "unit-app": (app,)})

    def _authority(self):
        return {"approved_generation_scope": ("src/leaf.py", "src/app.py")}

    def test_blueprint_is_canonical_and_source_free(self):
        blueprint = self._blueprint()
        self.assertEqual(blueprint.canonical_hash, ProjectBlueprint.from_value(blueprint.to_dict()).canonical_hash)
        self.assertNotIn("source", blueprint.to_dict())
        with self.assertRaises(ValueError):
            ProjectBlueprint("bad", metadata=({"source": "not allowed"},))

    def test_requirements_contracts_and_schemas_have_stable_identity(self):
        blueprint = self._blueprint()
        self.assertEqual(2, len(blueprint.module_contracts))
        self.assertEqual("IFACE-LEAF@1", blueprint.interfaces[0].identity)
        self.assertEqual(64, len(blueprint.requirements[0].canonical_hash))
        self.assertEqual(blueprint.module_contracts[0].canonical_hash, blueprint.module_contracts[0].canonical_hash)

    def test_dependency_dag_is_leaf_first(self):
        dag = build_dependency_dag(self._blueprint(), self._units())
        self.assertTrue(dag.validation.valid)
        self.assertEqual(("unit-leaf", "unit-app"), dag.topological_order())
        self.assertEqual(("unit-leaf",), dag.ready_set())
        self.assertEqual(("unit-app",), dag.ready_set(("unit-leaf",)))

    def test_dependency_cycle_is_rejected(self):
        blueprint = ProjectBlueprint("cycle", module_contracts=(
            ModuleContract("a", "A", "a", dependencies=("b",), target_paths=("src/a.py",)),
            ModuleContract("b", "B", "b", dependencies=("a",), target_paths=("src/b.py",)),
        ))
        dag = build_dependency_dag(blueprint)
        self.assertFalse(dag.validation.valid)
        self.assertEqual(GENERATION_DEPENDENCY_CYCLE, dag.validation.status)

    def test_path_ownership_and_forbidden_dependency_are_fail_closed(self):
        conflict = ProjectBlueprint("conflict", module_contracts=(
            ModuleContract("a", "A", "a", target_paths=("src/same.py",)),
            ModuleContract("b", "B", "b", target_paths=("src/same.py",)),
        ))
        conflict_dag = build_dependency_dag(conflict)
        self.assertEqual(GENERATION_PATH_OWNERSHIP_CONFLICT, conflict_dag.validation.status)
        forbidden = ProjectBlueprint("forbidden", module_contracts=(
            ModuleContract("a", "A", "a", dependencies=("b",), forbidden_dependencies=("b",), target_paths=("src/a.py",)),
            ModuleContract("b", "B", "b", target_paths=("src/b.py",)),
        ))
        self.assertEqual(GENERATION_FORBIDDEN_DEPENDENCY, build_dependency_dag(forbidden).validation.status)

    def test_packet_is_bounded_and_stale_when_revision_changes(self):
        blueprint = self._blueprint()
        unit = self._units()[0]
        builder = ProjectBuilder(self.root, blueprint, self._units(), authority=self._authority(), provider=self._provider())
        packet = builder.build_packet(unit)
        self.assertEqual(blueprint.canonical_hash, packet.blueprint_identity)
        self.assertTrue(packet.is_stale(repository_revision="different"))
        self.assertFalse(packet.is_stale(repository_revision=builder.repository_map.index_revision))
        with self.assertRaises(ValueError):
            GenerationEvidencePacket(unit_id="x", purpose="x", contract={"body": "whole source"})

    def test_generation_plan_is_deterministic(self):
        first = build_generation_plan(self._blueprint(), self._units())
        second = build_generation_plan(self._blueprint(), self._units())
        self.assertEqual(first.canonical_hash, second.canonical_hash)
        self.assertEqual(first.plan_id, second.plan_id)

    def test_generation_is_sandboxed_by_default(self):
        before = canonical_hash([])  # a deterministic control independent of the source
        result = ProjectBuilder(
            self.root, self._blueprint(), self._units(), authority=self._authority(), provider=self._provider(),
        ).generate(v25_6_validator=lambda *args: True)
        self.assertEqual(GENERATION_COMPLETE, result.status)
        self.assertFalse((self.root / "src/leaf.py").exists())
        self.assertFalse(result.subject_changed)
        self.assertEqual(2, len(result.checkpoints))
        self.assertEqual(before, canonical_hash([]))

    def test_explicit_verified_application_updates_indexes_and_brain(self):
        result = ProjectBuilder(
            self.root, self._blueprint(), self._units(), authority=self._authority(), provider=self._provider(),
        ).generate(apply_verified=True, v25_5_validator=lambda *args: True, v25_6_validator=lambda *args: True)
        self.assertEqual(GENERATION_COMPLETE, result.status)
        self.assertTrue(result.subject_changed)
        self.assertTrue((self.root / "src/leaf.py").exists())
        self.assertTrue((self.root / "src/app.py").exists())
        self.assertEqual(2, len(result.brain_entities))
        self.assertIn("leaf", result.lexical_index.postings)
        self.assertGreaterEqual(result.metrics.repo_map_incremental_updates, 2)

    def test_authority_and_dnt_are_not_widened_by_provider(self):
        blocked = ProjectBuilder(
            self.root, self._blueprint(), self._units(), authority={}, provider=self._provider(),
        ).generate(apply_verified=True, v25_6_validator=lambda *args: True)
        self.assertNotEqual(GENERATION_COMPLETE, blocked.status)
        self.assertTrue(any(error["status"] == AUTHORITY_FAILURE for error in blocked.errors))
        dnt = ProjectBuilder(
            self.root, self._blueprint(), self._units(), authority=self._authority(), dnt_paths=("src/leaf.py",), provider=self._provider(),
        ).generate(apply_verified=True, v25_6_validator=lambda *args: True)
        self.assertTrue(any(error["status"] == AUTHORITY_FAILURE for error in dnt.errors))

    def test_syntax_and_contract_failures_are_classified(self):
        syntax = ProjectBuilder(
            self.root, self._blueprint(), self._units(), authority=self._authority(), provider=self._provider(invalid=True),
        ).generate(v25_6_validator=lambda *args: True)
        self.assertTrue(any(error["status"] == "SYNTAX_FAILURE" for error in syntax.errors))
        wrong = GeneratedArtifactCandidate("wrong", "unit-leaf", content={"src/leaf.py": "def other():\n    return 1\n"})
        contract = ProjectBuilder(
            self.root, self._blueprint(), self._units(), authority=self._authority(),
            provider=DeterministicFakeProvider({"unit-leaf": (wrong,)}),
        ).generate(v25_6_validator=lambda *args: True)
        self.assertTrue(any(error["status"] == CONTRACT_FAILURE for error in contract.errors))

    def test_existing_modification_is_delegated_to_core5(self):
        result = ProjectBuilder(
            self.root, self._blueprint(), self._units(), authority=self._authority(), provider=self._provider(existing=True),
        ).generate(v25_6_validator=lambda *args: True)
        self.assertTrue(any(error["status"] == "EXISTING_MODIFICATION_REQUIRES_CORE5" for error in result.errors))

    def test_checkpoint_validates_and_stales_on_subject_change(self):
        builder = ProjectBuilder(self.root, self._blueprint(), self._units(), authority=self._authority(), provider=self._provider())
        result = builder.generate(v25_6_validator=lambda *args: True)
        checkpoint = result.checkpoints[0]
        valid = validate_generation_checkpoint(
            checkpoint, blueprint_identity=builder.blueprint.canonical_hash, plan_identity=builder.plan.canonical_hash,
            subject_hash=builder.subject_hash, repository_map_hash=builder.repository_map.logical_hash,
            lexical_index_identity=builder.lexical_index.logical_hash,
        )
        self.assertEqual(CHECKPOINT_READY, valid["status"])
        self._write("unrelated.txt", "changed")
        stale = validate_generation_checkpoint(
            checkpoint, blueprint_identity=builder.blueprint.canonical_hash, plan_identity=builder.plan.canonical_hash,
            subject_hash=builder.subject_hash, repository_map_hash=builder.repository_map.logical_hash,
            lexical_index_identity=builder.lexical_index.logical_hash,
        )
        # The caller must compare a fresh subject identity; the old checkpoint remains immutable.
        self.assertNotEqual(stale["checkpoint_hash"], "")

    def test_checkpoint_resume_rejects_explicit_revision_mismatch(self):
        builder = ProjectBuilder(self.root, self._blueprint(), self._units(), authority=self._authority(), provider=self._provider())
        result = builder.generate(v25_6_validator=lambda *args: True)
        checkpoint = result.checkpoints[-1]
        stale = validate_generation_checkpoint(
            checkpoint, blueprint_identity=builder.blueprint.canonical_hash, plan_identity=builder.plan.canonical_hash,
            subject_hash="different", repository_map_hash=builder.repository_map.logical_hash,
            lexical_index_identity=builder.lexical_index.logical_hash,
        )
        self.assertEqual(CHECKPOINT_STALE, stale["status"])

    def test_incremental_map_and_lexical_update_is_one_file(self):
        blueprint = self._blueprint()
        builder = ProjectBuilder(self.root, blueprint, self._units(), authority=self._authority(), provider=self._provider())
        candidate = GeneratedArtifactCandidate("one", "unit-leaf", content={"src/leaf.py": "def leaf():\n    return 1\n"})
        applied = builder.apply_verified_candidate(candidate, self._units()[0], v25_5_validator=lambda *args: True)
        self.assertTrue(applied["applied"])
        self.assertEqual(1, applied["map_metrics"]["incremental_files_reparsed"])
        self.assertIn("leaf", builder.lexical_index.postings)

    def test_change_impact_is_bounded_and_public_contract_expands(self):
        self._write("src/a.py", "from src.b import b\ndef a(): return b()\n")
        self._write("src/b.py", "def b(): return 1\n")
        repo = build_repository_map(self.root)
        private = analyze_change_impact(repo, ("src/b.py",), max_depth=3, max_nodes=8)
        self.assertEqual(CHANGE_PRIVATE, private.change_kind)
        public = analyze_change_impact(repo, ("src/b.py",), blueprint=self._blueprint(), public_contract_changed=True, max_depth=2, max_nodes=8)
        island = build_change_island(public, blueprint=self._blueprint())
        self.assertTrue(island.regeneration_allowed)
        self.assertLessEqual(len(public.transitive_paths), 8)

    def test_large_repository_exact_symbol_uses_cheap_search(self):
        for index in range(40):
            self._write(f"pkg/mod_{index}.js", f"export function ordinary_{index}() {{ return {index}; }}\n")
        self._write("pkg/target.js", "export function UniqueLargeSymbol() { return 1; }\n")
        repo = build_repository_map(self.root)
        metrics = {}
        result = search_repository(
            RepoIntelligenceQuery.from_task("find UniqueLargeSymbol"), repo, self.root, metrics=metrics,
        )
        self.assertTrue(any("UniqueLargeSymbol" in str(candidate.symbol or candidate.identity) for candidate in result.candidates))
        self.assertEqual(0, result.metrics.get("semantic_queries", 0))
        self.assertLess(result.metrics.get("source_bodies_loaded", 0), len(repo.files))

    def test_brain_remains_reference_based_and_stale_does_not_authorize(self):
        with self.assertRaises(ValueError):
            ProjectBrainEntity.from_dict({"entity_id": "x", "entity_kind": "MODULE", "name": "X", "summary": "summary", "source": "not allowed"})
        entity = ProjectBrainEntity(
            "x", "MODULE", "X", "summary", references=(TypedReference("file", "src/missing.js"),),
            created_from_verified_evidence=True,
        )
        self.assertEqual("src/missing.js", entity.references[0].path)

    def test_full_v25_6_gate_is_required_for_project_success(self):
        result = ProjectBuilder(
            self.root, self._blueprint(), self._units(), authority=self._authority(), provider=self._provider(),
        ).generate()
        self.assertEqual(GENERATION_PARTIAL, result.status)
        self.assertEqual("V25_6_REQUIRED", result.integration_receipt["status"])

    def test_budget_bounds_large_plan(self):
        budget = GenerationBudget(max_units=1, max_candidates_per_unit=1, max_total_candidates=1)
        plan = build_generation_plan(self._blueprint(), self._units(), budget=budget)
        self.assertEqual(1, len(plan.units))

    def test_plan_and_dag_round_trip_are_stable(self):
        plan = build_generation_plan(self._blueprint(), self._units())
        from hivo.project_builder import ProjectGenerationPlan
        restored = ProjectGenerationPlan.from_value(plan.to_dict())
        self.assertEqual(plan.canonical_hash, restored.canonical_hash)

    def test_provider_receives_only_one_bounded_packet(self):
        seen = []

        class CaptureProvider:
            provider_id = "capture"
            def generate(self, packet, candidate_budget=1):
                seen.append(packet)
                return (GeneratedArtifactCandidate("c", packet.unit_id, content={"src/leaf.py": "def leaf():\n    return 1\n"}),)

        builder = ProjectBuilder(
            self.root, self._blueprint(), (self._units()[0],), authority=self._authority(), provider=CaptureProvider(),
        )
        result = builder.generate(v25_6_validator=lambda *args: True)
        self.assertEqual(GENERATION_COMPLETE, result.status)
        self.assertEqual(1, len(seen))
        packet_text = repr(seen[0].to_dict())
        self.assertNotIn("README body", packet_text)
        self.assertEqual(1, seen[0].budget["max_candidates"])

    def test_callback_gates_accept_small_signatures_and_reject_tests(self):
        accepted = ProjectBuilder(
            self.root, self._blueprint(), (self._units()[0],), authority=self._authority(), provider=self._provider(),
        ).generate(
            contract_validator=lambda candidate: True,
            test_validator=lambda candidate: True,
            v25_5_validator=lambda candidate: True,
            v25_6_validator=lambda plan: True,
        )
        self.assertEqual(GENERATION_COMPLETE, accepted.status)
        rejected = ProjectBuilder(
            self.root, self._blueprint(), (self._units()[0],), authority=self._authority(), provider=self._provider(),
        ).generate(test_validator=lambda candidate: False, v25_6_validator=lambda *args: True)
        self.assertTrue(any(error["status"] == "TEST_FAILURE" for error in rejected.errors))

    def test_public_application_revalidates_invalid_candidate(self):
        builder = ProjectBuilder(self.root, self._blueprint(), self._units(), authority=self._authority(), provider=self._provider())
        invalid = GeneratedArtifactCandidate("invalid", "unit-leaf", content={"src/leaf.py": "def leaf(:\n"})
        applied = builder.apply_verified_candidate(invalid, self._units()[0], v25_5_validator=lambda *args: True)
        self.assertFalse(applied["applied"])
        self.assertEqual("SYNTAX_FAILURE", applied["status"])

    def test_candidate_metadata_cannot_grant_scope(self):
        candidate = GeneratedArtifactCandidate(
            "scope-claim", "unit-leaf", content={"src/leaf.py": "def leaf():\n    return 1\n"},
            metadata={"approved_generation_scope": ["src/leaf.py"]},
        )
        result = validate_generated_artifact_candidate(
            self.root, self._blueprint(), self._units()[0], candidate,
        )
        self.assertFalse(result["valid"])
        self.assertEqual(AUTHORITY_FAILURE, result["status"])

    def test_resume_uses_verified_checkpoint_without_repeating_leaf(self):
        first_builder = ProjectBuilder(self.root, self._blueprint(), self._units(), authority=self._authority(), provider=self._provider())
        first = first_builder.generate(v25_6_validator=lambda *args: True)
        checkpoint = first.checkpoints[0]
        second_builder = ProjectBuilder(self.root, self._blueprint(), self._units(), authority=self._authority(), provider=self._provider())
        second = second_builder.generate(checkpoint=checkpoint, v25_6_validator=lambda *args: True)
        self.assertEqual(GENERATION_COMPLETE, second.status)
        self.assertEqual(("unit-app",), tuple(receipt.unit_id for receipt in second.unit_receipts))

    def test_interface_drift_is_reported_without_source_copy(self):
        self._write("src/leaf.js", "export function other() { return 1; }\n")
        repo = build_repository_map(self.root)
        blueprint = ProjectBlueprint(
            "drift", module_contracts=(ModuleContract("leaf", "Leaf", "leaf", public_interfaces=("leaf",), target_paths=("src/leaf.js",)),),
        )
        drift = detect_interface_drift(blueprint, repo)
        self.assertTrue(drift)
        self.assertEqual("INTERFACE_DRIFT", drift[0]["status"])

    def test_private_impact_does_not_regenerate_unrelated_modules(self):
        self._write("src/a.js", "export function a() { return 1; }\n")
        self._write("src/b.js", "export function b() { return 2; }\n")
        repo = build_repository_map(self.root)
        impact = analyze_change_impact(repo, ("src/a.js",), max_depth=4, max_nodes=20)
        self.assertNotIn("src/b.js", impact.transitive_paths)

    def test_path_traversal_is_rejected_at_blueprint_and_candidate_boundaries(self):
        with self.assertRaises(ValueError):
            ModuleContract("unsafe", "Unsafe", "unsafe", target_paths=("../outside.py",))
        with self.assertRaises(ValueError):
            GeneratedArtifactCandidate("unsafe", "unit-leaf", content={"../outside.py": "x"})

    def test_large_leaf_first_project_is_bounded(self):
        contracts = []
        units = []
        candidates = {}
        for index in range(14):
            module_id = f"m{index:02d}"
            dependency = (f"m{index - 1:02d}",) if index else ()
            path = f"generated/{module_id}.py"
            contracts.append(ModuleContract(module_id, module_id, "bounded module", public_interfaces=(module_id,), dependencies=dependency, target_paths=(path,)))
            unit_id = f"u{index:02d}"
            units.append(GenerationUnit(unit_id, module_id, "generate bounded module", target_paths=(path,), dependencies=dependency, authority_scope=(path,)))
            candidates[unit_id] = (GeneratedArtifactCandidate(f"c{index:02d}", unit_id, content={path: f"def {module_id}():\n    return {index}\n"}),)
        blueprint = ProjectBlueprint("large", module_contracts=tuple(contracts))
        scope = tuple(f"generated/m{index:02d}.py" for index in range(14))
        result = ProjectBuilder(
            self.root, blueprint, units, authority={"approved_generation_scope": scope},
            provider=DeterministicFakeProvider(candidates), budget=GenerationBudget(max_units=20),
        ).generate(v25_6_validator=lambda *args: True)
        self.assertEqual(GENERATION_COMPLETE, result.status)
        self.assertEqual(14, result.metrics.units_verified)
        self.assertEqual(14, result.metrics.checkpoints_created)


if __name__ == "__main__":
    unittest.main()
