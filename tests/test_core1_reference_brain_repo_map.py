import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import mini
from hivo.memory import MemoryStore
from hivo.project_brain_refs import (
    ENTITY_KINDS,
    ProjectBrainEntity,
    TypedReference,
    canonical_hash,
    new_core1_metrics,
    query_project_brain,
    validate_project_brain_entity,
)
from hivo.reference_resolution import (
    AMBIGUOUS,
    INVALID_REFERENCE,
    RESOLVED_BUT_CHANGED,
    RESOLVED_CURRENT,
    STALE_REFERENCE,
    TARGET_MISSING,
    EvidenceResolutionRequest,
    ProjectReferenceResolver,
    request_project_evidence,
)
from hivo.repository_map import (
    RepositoryMap,
    build_repository_map,
    incremental_reindex,
    query_repository_map,
)


class Core1ReferenceBrainRepoMapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hivo_core1_")
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src" / "helper.js").write_text(
            "export function helper(value) { return value; }\n", encoding="utf-8",
        )
        (self.root / "src" / "status_view.js").write_text(
            """import { helper } from './helper.js';
export const STATUS_KEY = 'status';
export function renderStatus(controller) {
  return helper(controller.isPaused() ? 'Paused' : 'Running');
}
export function renderPauseIndicator(controller) {
  return controller.isPaused() ? 'Paused' : '';
}
module.exports = { renderStatus, renderPauseIndicator };
""",
            encoding="utf-8",
        )
        (self.root / "tests" / "status_view.test.js").write_text(
            "import { renderStatus } from '../src/status_view.js';\ntest('status', () => renderStatus);\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_typed_reference_canonical_and_safe(self):
        reference = TypedReference("symbol", "src\\status_view.js", "renderStatus", "a" * 64, "rev-1")
        self.assertIn("symbol://src/status_view.js?", reference.canonical_uri)
        self.assertTrue(reference.canonical_uri.endswith("#renderStatus"))
        self.assertEqual(TypedReference.from_uri(reference.canonical_uri), reference)
        self.assertEqual(
            TypedReference("symbol", "src/status_view.js", "renderStatus").canonical_uri,
            "symbol://src/status_view.js#renderStatus",
        )
        with self.assertRaises(ValueError):
            TypedReference("file", "../outside.js")
        with self.assertRaises(ValueError):
            TypedReference.from_uri("file:///outside.js")

    def test_brain_entity_v2_is_canonical_and_verified_only(self):
        entity = ProjectBrainEntity(
            entity_id="status-view", entity_kind="MODULE", name="StatusView",
            summary="Renders pause status and indicator.",
            contracts=("PauseController remains the state owner.",),
            invariants=("Running and paused labels remain stable.",),
            references=(TypedReference("symbol", "src/status_view.js", "renderStatus"),),
            verified_subject_identity="subject-1", verified_revision_identity="rev-1",
            verified_source_hashes={"src/status_view.js": "a" * 64},
            created_from_verified_evidence=True,
        )
        restored = ProjectBrainEntity.from_dict(entity.to_dict())
        self.assertEqual(entity.canonical_hash, restored.canonical_hash)
        self.assertEqual(set(ENTITY_KINDS), set((
            "MODULE", "FILE", "SYMBOL", "SERVICE", "INTERFACE", "DATA_MODEL",
            "TEST_AREA", "ARCHITECTURE_DECISION", "CONTRACT",
        )))
        self.assertTrue(validate_project_brain_entity(entity)["valid"])
        speculative = ProjectBrainEntity(
            entity_id="speculative", entity_kind="CONTRACT", name="Speculative",
            summary="unverified", created_from_verified_evidence=False,
        )
        self.assertEqual(validate_project_brain_entity(speculative)["status"], "UNVERIFIED_BRAIN_ENTITY")
        with self.assertRaises(ValueError):
            ProjectBrainEntity.from_dict({
                "entity_id": "copy", "entity_kind": "FILE", "name": "Copy",
                "summary": "bad", "body": "not allowed",
            })

    def test_old_brain_record_remains_readable_and_durable_entity_is_separate(self):
        legacy = {
            "record_id": "legacy-1", "durability_class": "STATE_BOUND_VERIFIED",
            "subject_state_hash": "subject-1", "status": "ACTIVE",
            "fact": {"category": "CONTRACT", "field": "pause_owner", "fact": "controller owns pause"},
        }
        entity = ProjectBrainEntity.from_legacy_record(legacy)
        self.assertEqual(entity.entity_id, "legacy-1")
        self.assertTrue(entity.created_from_verified_evidence)
        store = MemoryStore(self.root)
        self.assertEqual(store.project_brain_snapshot()["records"], [])
        result = store.commit_verified_project_brain_entity(
            ProjectBrainEntity(
                entity_id="status-view", entity_kind="MODULE", name="StatusView",
                summary="verified status module", verified_subject_identity="subject-1",
                verified_revision_identity="rev-1", created_from_verified_evidence=True,
            ),
            project_id="core1",
        )
        self.assertEqual(result["status"], "PROMOTED")
        self.assertEqual(store.project_brain_snapshot()["records"], [])
        self.assertEqual(len(store.reference_brain_snapshot("core1")["entities"]), 1)
        rejected = store.commit_verified_project_brain_entity(speculative_entity())
        self.assertEqual(rejected["status"], "UNVERIFIED_BRAIN_ENTITY")

    def test_verified_reference_entity_survives_restart_without_touching_legacy_facts(self):
        store = MemoryStore(self.root)
        entity = verified_entity()
        self.assertEqual(
            store.commit_verified_project_brain_entity(entity, project_id="restart")["status"],
            "PROMOTED",
        )
        reopened = MemoryStore(self.root)
        snapshot = reopened.reference_brain_snapshot("restart")
        self.assertEqual(snapshot["entities"][0]["entity_id"], entity.entity_id)
        self.assertEqual(reopened.project_brain_snapshot()["records"], [])

    def test_brain_query_is_summary_only_and_metrics_are_deterministic(self):
        entity = verified_entity()
        metrics = new_core1_metrics()
        rows = query_project_brain([entity], "pause indicator", metrics=metrics)
        self.assertEqual(rows[0]["entity_id"], entity.entity_id)
        self.assertNotIn("source_body", rows[0])
        self.assertEqual(metrics["brain_entities_examined"], 1)
        self.assertEqual(query_project_brain([entity], "pause indicator"), rows)

    def test_cold_index_is_deterministic_and_indexes_js_structure(self):
        first_metrics = new_core1_metrics()
        first = build_repository_map(self.root, metrics=first_metrics)
        second = build_repository_map(self.root)
        self.assertEqual(first.logical_hash, second.logical_hash)
        self.assertEqual(first_metrics["cold_index_files_scanned"], 3)
        self.assertIn("src/status_view.js", first.files)
        self.assertTrue(any("renderStatus" in symbol_id for symbol_id in first.symbols))
        self.assertIn("renderStatus", first.files["src/status_view.js"]["exports"])
        self.assertEqual(first.files["src/status_view.js"]["imports"][0]["resolved_path"], "src/helper.js")
        self.assertTrue(any(edge["kind"] == "depends_on" for edge in first.edges))
        serialized = json.dumps(first.to_dict(), sort_keys=True)
        self.assertNotIn("return helper", serialized)
        self.assertNotIn("source_body", serialized)

    def test_incremental_single_file_update_and_deletion_remove_stale_symbols(self):
        repository_map = build_repository_map(self.root)
        before_hash = repository_map.files["src/status_view.js"]["content_hash"]
        (self.root / "src" / "status_view.js").write_text(
            "export function renderStatus(controller) { return controller; }\n",
            encoding="utf-8",
        )
        metrics = new_core1_metrics()
        updated = incremental_reindex(
            repository_map, self.root, changed_paths=["src/status_view.js"], metrics=metrics,
        )
        self.assertNotEqual(before_hash, updated.files["src/status_view.js"]["content_hash"])
        self.assertEqual(metrics["incremental_files_reparsed"], 1)
        self.assertNotIn("renderPauseIndicator", " ".join(updated.files["src/status_view.js"]["top_level_symbols"]))
        (self.root / "src" / "helper.js").unlink()
        deleted = incremental_reindex(updated, self.root, deleted_paths=["src/helper.js"], metrics=metrics)
        self.assertNotIn("src/helper.js", deleted.files)
        self.assertFalse(any(edge["source"] == "src/helper.js" or edge["target"] == "src/helper.js" for edge in deleted.edges))
        self.assertIn("src/helper.js", deleted.invalidated_references)

    def test_conservative_move_updates_only_when_hash_identity_is_exact(self):
        repository_map = build_repository_map(self.root)
        old = self.root / "src" / "helper.js"
        new = self.root / "src" / "renamed_helper.js"
        old.rename(new)
        moved = incremental_reindex(repository_map, self.root, moved_paths=[("src/helper.js", "src/renamed_helper.js")])
        self.assertNotIn("src/helper.js", moved.files)
        self.assertIn("src/renamed_helper.js", moved.files)
        self.assertTrue(any(row.get("path") == "src/renamed_helper.js" for row in moved.symbols.values()))

    def test_repository_map_query_returns_metadata_only(self):
        repository_map = build_repository_map(self.root)
        rows = query_repository_map(repository_map, "renderStatus")
        self.assertTrue(rows)
        self.assertTrue(any(row["kind"] == "symbol" for row in rows))
        self.assertNotIn("source_body", rows[0])

    def test_resolver_supports_file_symbol_test_and_lazy_levels(self):
        repository_map = build_repository_map(self.root)
        metrics = new_core1_metrics()
        resolver = ProjectReferenceResolver(repository_map, self.root, metrics=metrics)
        file_result = resolver.resolve("file://src/status_view.js")
        self.assertEqual(file_result.state, RESOLVED_CURRENT)
        self.assertNotIn("source_body", file_result.evidence)
        symbol = resolver.resolve(
            "symbol://src/status_view.js#renderStatus",
            EvidenceResolutionRequest("symbol://src/status_view.js#renderStatus", requested_level=2),
        )
        self.assertEqual(symbol.state, RESOLVED_CURRENT)
        self.assertIn("signature", symbol.evidence["symbol"])
        self.assertNotIn("source_body", symbol.evidence)
        detailed = request_project_evidence(
            "symbol://src/status_view.js#renderStatus", repository_map, self.root, level=3,
            metrics=metrics,
        )
        self.assertEqual(detailed.state, RESOLVED_CURRENT)
        self.assertIn("return helper", detailed.source_body)
        self.assertEqual(metrics["source_bodies_loaded"], 1)
        test_result = resolver.resolve("test://tests/status_view.test.js")
        self.assertEqual(test_result.state, RESOLVED_CURRENT)
        self.assertEqual(metrics["full_file_reads_requested"], 0)

    def test_full_file_level_is_explicit_and_bounded(self):
        repository_map = build_repository_map(self.root)
        metrics = new_core1_metrics()
        result = request_project_evidence(
            "file://src/status_view.js", repository_map, self.root, level=5, metrics=metrics,
        )
        self.assertEqual(result.state, RESOLVED_CURRENT)
        self.assertIn("renderPauseIndicator", result.evidence["full_file"])
        self.assertEqual(metrics["full_file_reads_requested"], 1)

    def test_duplicate_source_body_is_suppressed(self):
        repository_map = build_repository_map(self.root)
        metrics = new_core1_metrics()
        resolver = ProjectReferenceResolver(repository_map, self.root, metrics=metrics)
        first = resolver.resolve("symbol://src/status_view.js#renderStatus", EvidenceResolutionRequest("symbol://src/status_view.js#renderStatus", 3))
        second = resolver.resolve("symbol://src/status_view.js#renderStatus", EvidenceResolutionRequest("symbol://src/status_view.js#renderStatus", 3))
        self.assertIsNotNone(first.source_body)
        self.assertIsNone(second.source_body)
        self.assertTrue(second.duplicate_source_body_suppressed)
        self.assertEqual(metrics["duplicate_source_bodies_suppressed"], 1)

    def test_ambiguity_missing_invalid_and_changed_states_are_explicit(self):
        (self.root / "src" / "other.js").write_text(
            "export function renderStatus(controller) { return controller; }\n", encoding="utf-8",
        )
        repository_map = build_repository_map(self.root)
        resolver = ProjectReferenceResolver(repository_map, self.root)
        self.assertEqual(resolver.resolve("symbol://#renderStatus").state, AMBIGUOUS)
        self.assertEqual(resolver.resolve("file://src/missing.js").state, TARGET_MISSING)
        self.assertEqual(resolver.resolve("not-a-reference").state, INVALID_REFERENCE)
        old_hash = repository_map.files["src/status_view.js"]["content_hash"]
        changed = resolver.resolve(TypedReference("file", "src/status_view.js", anchor_hash="0" * 64))
        self.assertEqual(changed.state, RESOLVED_BUT_CHANGED)
        entity = verified_entity(
            anchor_hash=repository_map.symbols["src/status_view.js::function::renderStatus"]["anchor_hash"],
            source_hash=old_hash,
        )
        (self.root / "src" / "status_view.js").write_text(
            "export function renderStatus(controller) { return 'changed'; }\n", encoding="utf-8",
        )
        current_map = incremental_reindex(repository_map, self.root, changed_paths=["src/status_view.js"])
        stale = ProjectReferenceResolver(current_map, self.root, brain_entities=[entity]).resolve(
            entity.references[0], brain_entity=entity,
        )
        self.assertEqual(stale.state, STALE_REFERENCE)
        self.assertTrue(stale.current_repository_wins)
        self.assertIn("repository_file", stale.evidence)

    def test_brain_and_repo_are_separate_and_current_source_wins_without_writes(self):
        entity = verified_entity()
        before = tree_digest(self.root)
        repository_map = build_repository_map(self.root)
        result = ProjectReferenceResolver(repository_map, self.root, brain_entities=[entity]).resolve(
            entity.references[0], brain_entity=entity,
        )
        self.assertEqual(result.state, RESOLVED_CURRENT)
        self.assertEqual(tree_digest(self.root), before)
        self.assertNotIn("authorize", json.dumps(repository_map.to_dict()).casefold())

    def test_large_synthetic_repo_reparses_small_changed_set(self):
        large = self.root / "large"
        large.mkdir()
        for index in range(40):
            (large / f"module_{index}.js").write_text(
                f"export const VALUE_{index} = {index};\n", encoding="utf-8",
            )
        cold_metrics = new_core1_metrics()
        repository_map = build_repository_map(self.root, metrics=cold_metrics)
        (large / "module_17.js").write_text(
            "export const VALUE_17 = 1700;\n", encoding="utf-8",
        )
        incremental_metrics = new_core1_metrics()
        updated = incremental_reindex(
            repository_map, self.root, changed_paths=["large/module_17.js"], metrics=incremental_metrics,
        )
        self.assertGreaterEqual(cold_metrics["cold_index_files_scanned"], 43)
        self.assertEqual(incremental_metrics["incremental_files_reparsed"], 1)
        self.assertLess(incremental_metrics["incremental_files_reparsed"], cold_metrics["cold_index_files_scanned"])
        self.assertNotEqual(repository_map.logical_hash, updated.logical_hash)

    def test_memory_rejects_unverified_or_private_reference_entities(self):
        store = MemoryStore(self.root)
        self.assertEqual(store.commit_verified_project_brain_entity(speculative_entity())["status"], "UNVERIFIED_BRAIN_ENTITY")
        private = verified_entity()
        private = ProjectBrainEntity(
            **{**private.to_dict(), "contracts": ["chain_of_thought must not persist"]},
        )
        self.assertEqual(store.commit_verified_project_brain_entity(private)["status"], "BRAIN_PRIVATE_PROVENANCE_REJECTED")

    def test_mini_integration_api_is_explicit_and_does_not_change_authority(self):
        repository_map = build_repository_map(self.root)
        entity = verified_entity()
        metrics = new_core1_metrics()
        self.assertEqual(mini.query_project_brain("pause", entities=[entity], metrics=metrics)[0]["entity_id"], entity.entity_id)
        self.assertTrue(mini.query_repository_map("renderStatus", repository_map=repository_map))
        resolved = mini.resolve_project_reference(
            entity.references[0], repository_map=repository_map, project_root=self.root,
            brain_entity=entity, metrics=metrics,
        )
        self.assertEqual(resolved.state, RESOLVED_CURRENT)
        self.assertFalse(hasattr(resolved, "authorize_mutation"))

    def test_path_safety_rejects_escape_and_symlink_escape(self):
        repository_map = build_repository_map(self.root)
        resolver = ProjectReferenceResolver(repository_map, self.root)
        self.assertEqual(resolver.resolve("file://../secret.js").state, INVALID_REFERENCE)
        outside = Path(self.temp.name).parent / "core1_outside.js"
        outside.write_text("export const secret = true;\n", encoding="utf-8")
        link = self.root / "src" / "outside.js"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            outside.unlink(missing_ok=True)
            return
        try:
            self.assertNotIn("src/outside.js", build_repository_map(self.root).files)
        finally:
            outside.unlink(missing_ok=True)


def verified_entity(anchor_hash=None, source_hash=None):
    return ProjectBrainEntity(
        entity_id="status-view", entity_kind="MODULE", name="StatusView",
        summary="Renders current pause status and indicator.",
        contracts=("PauseController owns pause state.",),
        invariants=("Running status is preserved.",),
        references=(TypedReference("symbol", "src/status_view.js", "renderStatus", anchor_hash=anchor_hash),),
        verified_subject_identity="subject-1", verified_revision_identity="rev-1",
        verified_source_hashes={"src/status_view.js": source_hash} if source_hash else {},
        created_from_verified_evidence=True,
    )


def speculative_entity():
    return ProjectBrainEntity(
        entity_id="speculative", entity_kind="CONTRACT", name="Speculative",
        summary="unverified hypothesis", created_from_verified_evidence=False,
    )


def tree_digest(root):
    rows = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or ".hivo" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{relative}\0{digest}\0{path.stat().st_size}")
    return canonical_hash(rows)


if __name__ == "__main__":
    unittest.main()
