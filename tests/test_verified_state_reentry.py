import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import mini
from hivo.integration_gate import canonical_hash, fingerprint_dependency_paths
from hivo.memory import MemoryStore
from hivo.promotion import DURABLE_VERIFIED, STATE_BOUND_VERIFIED
from hivo.project_understanding import DIRECT_OBSERVATION, REPOSITORY_EVIDENCE
from hivo.reentry import (
    ACTIVE,
    AUTHORITY_IMPLEMENTATION_DRIFT,
    CONFLICTED,
    CURRENT_DURABLE_AUTHORITY,
    CURRENT_VERIFIED,
    FRESH_TASK_BRAIN_TYPE,
    NEW_REQUIREMENT_VS_CURRENT_ARCHITECTURE,
    REENTRY_MEMORY_UNAVAILABLE,
    REENTRY_PROJECT_ID_MISMATCH,
    REENTRY_READY,
    STALE_VERIFIED,
    SUPERSEDED,
    build_reentry_context,
    build_fresh_task_brain,
    reconcile_verified_project_brain,
    run_verified_state_reentry,
    run_verified_state_reentry_self_test,
    validate_fresh_task_brain,
    validate_reentry_context,
)


class VerifiedStateReentryTests(unittest.TestCase):
    """Deterministic V23 tests over a production-shaped V22 Brain snapshot."""

    FROZEN_FIXTURE_HASHES = {
        "src/input.js": "3534ebd784e405a9fcc32cba0fec67a56f16731bc8036a0b7fc7ff07d8d77b9b",
        "src/pause_controller.js": "94bf565534236a4dce68e2b0b865a3d52415a221f4e77046558a7facd5e473aa",
        "src/status_view.js": "0f9684c6e0ed12e3cbf6c0e6d94a35c8c84f9bbb1017ff495897baae71321852",
        "tests/input.test.js": "aef72c63ee7e569c3e59a7d8280875e8ad77e696e23d6a1d95e80252254b6d46",
        "tests/status_view.test.js": "928d633bb6c62279fac80eaa1396b5cf28863efeb6545811216adc19f3555015",
        "tests/pause_flow.integration.test.js": "260ec9920c77b7ddf5e61d53878439bdd5aa1fa845778e636043524deff93099",
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hivo_v23_reentry_")
        self.root = Path(self.temp.name)
        self.project_id = "pause-project"
        self.files = {
            "src/input.js": """const { PauseController } = require('./pause_controller');

const MOVEMENTS = Object.freeze({
  ArrowUp: Object.freeze({ x: 0, y: -1 }),
  ArrowDown: Object.freeze({ x: 0, y: 1 }),
  ArrowLeft: Object.freeze({ x: -1, y: 0 }),
  ArrowRight: Object.freeze({ x: 1, y: 0 }),
});

function normalizeInput(event) {
  return typeof event === 'string' ? event : event && event.key;
}

function handleInput(event, pauseController, position) {
  if (!(pauseController instanceof PauseController)) {
    throw new TypeError('a PauseController is required');
  }
  const key = normalizeInput(event);
  const current = { x: position.x, y: position.y };
  if (key === 'Escape') {
    return { type: 'pause', paused: pauseController.togglePause() };
  }
  const delta = MOVEMENTS[key];
  if (!delta) {
    return { type: 'noop', position: current };
  }
  return {
    type: 'move',
    direction: key,
    position: { x: current.x + delta.x, y: current.y + delta.y },
  };
}

module.exports = { handleInput, normalizeInput };
""",
            "src/pause_controller.js": """class PauseController {
  constructor() {
    this.paused = false;
  }

  togglePause() {
    this.paused = !this.paused;
    return this.paused;
  }

  isPaused() {
    return this.paused;
  }
}

module.exports = { PauseController };
""",
            "src/status_view.js": """const { PauseController } = require('./pause_controller');

function renderStatus(pauseController) {
  if (!(pauseController instanceof PauseController)) {
    throw new TypeError('a PauseController is required');
  }
  return pauseController.isPaused() ? 'Paused' : 'Running';
}

module.exports = { renderStatus };
""",
            "tests/input.test.js": """const assert = require('assert/strict');
const { PauseController } = require('../src/pause_controller');
const { handleInput } = require('../src/input');

const pauseController = new PauseController();
const initialPosition = { x: 0, y: 0 };

const movement = handleInput({ key: 'ArrowRight' }, pauseController, initialPosition);
assert.deepEqual(movement, {
  type: 'move', direction: 'ArrowRight', position: { x: 1, y: 0 },
});
assert.deepEqual(initialPosition, { x: 0, y: 0 });
assert.equal(pauseController.isPaused(), false);

const firstEscape = handleInput({ key: 'Escape' }, pauseController, initialPosition);
assert.deepEqual(firstEscape, { type: 'pause', paused: true });
assert.equal(pauseController.isPaused(), true);

const secondEscape = handleInput({ key: 'Escape' }, pauseController, initialPosition);
assert.deepEqual(secondEscape, { type: 'pause', paused: false });
assert.equal(pauseController.isPaused(), false);

console.log('Child A input verification passed');
""",
            "tests/status_view.test.js": """const assert = require('assert/strict');
const { PauseController } = require('../src/pause_controller');
const { renderStatus } = require('../src/status_view');

const pauseController = new PauseController();
assert.equal(renderStatus(pauseController), 'Running');
assert.equal(pauseController.isPaused(), false);

pauseController.togglePause();
assert.equal(renderStatus(pauseController), 'Paused');
assert.equal(pauseController.isPaused(), true);

pauseController.togglePause();
assert.equal(renderStatus(pauseController), 'Running');
assert.equal(pauseController.isPaused(), false);

console.log('Child B status-view verification passed');
""",
            "tests/pause_flow.integration.test.js": """const assert = require('assert/strict');
const { PauseController } = require('../src/pause_controller');
const { handleInput } = require('../src/input');
const { renderStatus } = require('../src/status_view');

const pauseController = new PauseController();
let position = { x: 0, y: 0 };

assert.equal(renderStatus(pauseController), 'Running');

const paused = handleInput({ key: 'Escape' }, pauseController, position);
assert.deepEqual(paused, { type: 'pause', paused: true });
assert.equal(renderStatus(pauseController), 'Paused');

const resumed = handleInput({ key: 'Escape' }, pauseController, position);
assert.deepEqual(resumed, { type: 'pause', paused: false });
assert.equal(renderStatus(pauseController), 'Running');

const moved = handleInput({ key: 'ArrowRight' }, pauseController, position);
position = moved.position;
assert.deepEqual(moved, {
  type: 'move', direction: 'ArrowRight', position: { x: 1, y: 0 },
});
assert.equal(pauseController.isPaused(), false);
assert.equal(renderStatus(pauseController), 'Running');

console.log('Parent pause-flow integration verification passed');
""",
        }
        for relative, content in self.files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            # Preserve the frozen Stage 5B LF bytes so the fixture hashes are
            # byte-for-byte identical on Windows as well as POSIX hosts.
            path.write_bytes(content.encode("utf-8"))
        self.assertEqual(
            {
                relative: hashlib.sha256((self.root / relative).read_bytes()).hexdigest()
                for relative in self.files
            },
            self.FROZEN_FIXTURE_HASHES,
        )
        self.dependencies = list(self.files)
        self.subject = fingerprint_dependency_paths(self.root, self.dependencies)
        self.store = MemoryStore(self.root)
        self._seed_production_shaped_brain()
        self.brain_hash_before = self.store.project_brain_hash(self.project_id)

    def tearDown(self):
        self.temp.cleanup()

    def _fact(
        self,
        text,
        category,
        field,
        *,
        durability=DURABLE_VERIFIED,
        authority="USER/REQUIREMENT",
        authority_source="approved_requirement_field",
        path=None,
        symbol=None,
        requirement_id=None,
        kind=None,
        result=None,
        conflict_key=None,
    ):
        fact = {
            "category": category,
            "field": field,
            "fact": text,
            "authority": authority,
            "authority_source": authority_source,
            "source": "approved_requirement_contract" if authority == "USER/REQUIREMENT" else "verified_parent_integration_evidence",
            "verified": True,
            "approved": True,
            "evidence_refs": ["parent:" + ("a" * 64), "verified-parent-receipt.json"],
            "dependency_paths": list(self.dependencies),
            "subject_state_hash": self.subject["hash"],
            "durability_class": durability,
        }
        if path:
            fact["path"] = path
        if symbol:
            fact["symbol"] = symbol
        if requirement_id:
            fact["requirement_id"] = requirement_id
        if kind:
            fact["kind"] = kind
        if result:
            fact["result"] = result
        fact["conflict_key"] = conflict_key or f"{category}:{field}:{text.casefold()}"
        fact["semantic_hash"] = canonical_hash({
            "category": fact["category"], "field": fact["field"], "fact": fact["fact"],
            "authority": fact["authority"], "conflict_key": fact["conflict_key"],
        })
        fact["fact_hash"] = canonical_hash({key: value for key, value in fact.items() if key != "fact_hash"})
        return fact

    def _record(self, fact, record_id, *, status=ACTIVE, supersedes=None, project_id=None):
        return {
            "record_id": record_id,
            "project_id": project_id or self.project_id,
            "fact_hash": fact["fact_hash"],
            "semantic_hash": fact["semantic_hash"],
            "conflict_key": fact["conflict_key"],
            "fact": fact,
            "durability_class": fact["durability_class"],
            "subject_state_hash": fact["subject_state_hash"],
            "status": status,
            "supersedes": list(supersedes or []),
            "superseded_by": None,
            "provenance": {
                "source": "deterministic_verified_parent_receipt",
                "model_calls": 0,
                "raw_worker_transcript_included": False,
                "authority_escalation": False,
                "cross_project_memory": False,
                "strategy_learning": False,
                "auto_reverification": False,
            },
        }

    def _seed_production_shaped_brain(self):
        facts = [
            self._fact("PauseController remains the sole pause-state owner.", "verified_facts", "state_ownership", requirement_id="REQ-002", path="src/pause_controller.js"),
            self._fact("Escape flows through the existing pause interface.", "verified_facts", "verified_facts", requirement_id="REQ-001", path="src/input.js"),
            self._fact("Movement behavior remains intact.", "verified_preservations", "verified_preservations", requirement_id="REQ-003", path="src/input.js"),
            self._fact("StatusView reflects PauseController running and paused state.", "verified_preservations", "status_behavior", requirement_id="REQ-003", path="src/status_view.js"),
            self._fact("PauseController.togglePause()", "verified_interfaces", "interfaces_to_reuse", requirement_id="REQ-001", path="src/pause_controller.js", symbol="PauseController.togglePause()"),
            self._fact("PauseController.togglePause() is the existing pause transition interface.", "verified_interfaces", "verified_interfaces", requirement_id="REQ-001", path="src/pause_controller.js", symbol="PauseController.togglePause()"),
            self._fact("Do not modify src/pause_controller.js.", "verified_prohibitions", "do_not_touch", requirement_id="REQ-002", path="src/pause_controller.js"),
            self._fact("PauseController remains the sole pause-state owner.", "verified_prohibitions", "prohibition_constraints", requirement_id="REQ-002", path="src/pause_controller.js"),
            self._fact("src/pause_controller.js", "verified_prohibitions", "global_do_not_touch", requirement_id="REQ-002", path="src/pause_controller.js"),
            self._fact("Preserve movement behavior and pause-state ownership.", "verified_preservations", "preservation_constraints", requirement_id="REQ-003", path="src/input.js"),
            self._fact("Required integration verification passed on tests/pause_flow.integration.test.js", "verified_tests", "integration_test_evidence", durability=STATE_BOUND_VERIFIED, authority="VERIFIED/EVIDENCE", authority_source="verified_parent_verification_receipt", path="tests/pause_flow.integration.test.js", kind="VERIFIED_INTEGRATION_FACT", result="PASS", conflict_key="integration:INTEGRATION_TEST:tests/pause_flow.integration.test.js"),
            self._fact("Pause behavior remains covered by the parent integration route.", "verified_facts", "integration_coverage", requirement_id="REQ-003", path="tests/pause_flow.integration.test.js"),
        ]
        categories = {
            "verified_facts": [], "verified_interfaces": [], "verified_preservations": [],
            "verified_prohibitions": [], "verified_tests": [],
        }
        for index, fact in enumerate(facts, 1):
            categories[fact["category"]].append(fact)
        candidate = {
            "schema_version": "V22.5C",
            "artifact_type": "PromotionCandidate",
            "candidate_id": "",
            "project_id": self.project_id,
            "parent_id": "PARENT",
            "source": {
                "parent_verification_hash": "a" * 64,
                "parent_contract_hash": "b" * 64,
                "plan_hash": "c" * 64,
                "child_receipt_hashes": ["d" * 64, "e" * 64],
                "authority_preserved": True,
                "approved_authority_change": False,
            },
            "subject_state_hash": self.subject["hash"],
            "subject_state_paths": self.dependencies,
            "artifact_refs": ["parent_verification_receipt.json"],
            **categories,
            "supersedes": [],
            "provenance": {
                "source": "deterministic_verified_parent_receipt",
                "model_calls": 0,
                "raw_worker_transcript_included": False,
                "authority_escalation": False,
                "cross_project_memory": False,
                "strategy_learning": False,
                "auto_reverification": False,
            },
        }
        candidate["fact_count"] = sum(len(values) for values in categories.values())
        candidate["candidate_hash"] = canonical_hash({
            key: value for key, value in candidate.items() if key not in {"candidate_hash", "candidate_id"}
        })
        candidate["candidate_id"] = f"candidate-{candidate['candidate_hash'][:24]}"
        committed = self.store.commit_verified_promotion(candidate)
        self.assertEqual(committed["promotion_status"], "PROMOTED")

    def _run(self, task_goal="Continue pause behavior.", **kwargs):
        return run_verified_state_reentry(
            self.store, self.project_id, kwargs.pop("new_task_id", "V23-TASK"), task_goal,
            workspace=self.root, **kwargs,
        )

    def _classification(self, result, record_id):
        return next(
            item for item in result["reentry_context"]["record_classifications"]
            if item.get("record_id") == record_id
        )

    def _integration_record_id(self):
        records = self.store.project_brain_snapshot(self.project_id, include_inactive=True)["records"]
        return next(item["record_id"] for item in records if item["fact"].get("field") == "integration_test_evidence")

    def test_fresh_reentry_keeps_state_bound_fact_current_and_is_read_only(self):
        before = self.store.project_brain_hash(self.project_id)
        result = self._run(previous_task_id="NO-OLD-POINTER")
        self.assertEqual(result["status"], REENTRY_READY)
        self.assertTrue(validate_reentry_context(result["reentry_context"])["valid"])
        self.assertTrue(validate_fresh_task_brain(result["task_brain"])["valid"])
        integration_id = self._integration_record_id()
        self.assertEqual(self._classification(result, integration_id)["classification"], CURRENT_VERIFIED)
        self.assertIn(integration_id, {item["record_id"] for item in result["task_brain"]["current_verified_facts"]})
        self.assertEqual(result["metrics"]["project_brain_records_considered"], 12)
        self.assertEqual(result["metrics"]["project_brain_records_stale"], 0)
        self.assertEqual(result["metrics"]["reentry_model_calls"], 0)
        self.assertEqual(result["verification_calls"], 0)
        self.assertFalse(result["execution_started"])
        self.assertFalse(result["project_brain_mutated"])
        self.assertEqual(before, self.store.project_brain_hash(self.project_id))

    def test_relevant_dependency_change_makes_state_bound_fact_stale_without_reverification(self):
        integration_id = self._integration_record_id()
        target = self.root / "src" / "input.js"
        target.write_text(target.read_text(encoding="utf-8") + "// changed relevant dependency\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result["status"], REENTRY_READY)
        classification = self._classification(result, integration_id)
        self.assertEqual(classification["classification"], STALE_VERIFIED)
        self.assertFalse(classification["accepted_as_current"])
        warning = next(item for item in result["task_brain"]["stale_verified_facts"] if item["record_id"] == integration_id)
        self.assertTrue(warning["previously_verified"])
        self.assertNotIn(integration_id, {item["record_id"] for item in result["task_brain"]["current_verified_facts"]})
        self.assertEqual(result["verification_calls"], 0)
        self.assertEqual(result["metrics"]["automatic_reverification_attempts"], 0)
        self.assertIn("src/input.js", classification["freshness"]["changed_dependency_paths"])

    def test_unrelated_file_change_does_not_stale_state_bound_fact(self):
        (self.root / "README.tmp").write_text("unrelated fixture change\n", encoding="utf-8")
        result = self._run()
        integration_id = self._integration_record_id()
        self.assertEqual(self._classification(result, integration_id)["classification"], CURRENT_VERIFIED)
        self.assertEqual(result["metrics"]["project_brain_records_stale"], 0)

    def test_durable_authority_remains_current_across_source_change(self):
        target = self.root / "src" / "input.js"
        target.write_text(target.read_text(encoding="utf-8") + "// implementation changed\n", encoding="utf-8")
        result = self._run()
        owner = next(
            item for item in self.store.project_brain_snapshot(self.project_id)["records"]
            if item["fact"].get("field") == "state_ownership"
        )
        self.assertEqual(self._classification(result, owner["record_id"])["classification"], CURRENT_DURABLE_AUTHORITY)
        self.assertEqual(self._classification(result, self._integration_record_id())["classification"], STALE_VERIFIED)

    def test_explicit_superseding_record_is_history_only(self):
        snapshot = self.store.project_brain_snapshot(self.project_id, include_inactive=True)
        old = next(item for item in snapshot["records"] if item["fact"].get("field") == "state_ownership")
        new_fact = self._fact(
            "PauseController remains the designated pause-state owner.", "verified_facts", "state_ownership",
            requirement_id="REQ-002", path="src/pause_controller.js", conflict_key=old["conflict_key"],
        )
        new = self._record(new_fact, "verified-new-owner", supersedes=[old["record_id"], old["fact_hash"]])
        old_copy = copy.deepcopy(old)
        old_copy["status"] = "SUPERSEDED"
        snapshot["records"] = [old_copy, new] + [item for item in snapshot["records"] if item["record_id"] not in {old["record_id"]}]
        context = build_reentry_context(
            self.project_id, "SUPERSEDE", snapshot, self.root,
            task_goal="Continue pause behavior.", current_repository_evidence=[],
        )
        self.assertTrue(context["ready"])
        self.assertEqual(next(item for item in context["record_classifications"] if item["record_id"] == old["record_id"])["classification"], SUPERSEDED)
        self.assertNotIn(old["record_id"], {item["record_id"] for item in context["current_verified_facts"]})
        self.assertIn("verified-new-owner", {item["record_id"] for item in context["current_verified_facts"]})

    def test_unlinked_contradictory_active_authority_fails_closed(self):
        snapshot = self.store.project_brain_snapshot(self.project_id, include_inactive=True)
        old = next(item for item in snapshot["records"] if item["fact"].get("field") == "state_ownership")
        conflicting_fact = self._fact(
            "StatusView is the sole pause-state owner.", "verified_facts", "state_ownership",
            requirement_id="REQ-CONFLICT", path="src/status_view.js",
            conflict_key=old["conflict_key"],
        )
        conflicting = self._record(conflicting_fact, "verified-unlinked-conflict")
        snapshot["records"].append(conflicting)
        context = build_reentry_context(
            self.project_id, "AUTH-CONFLICT", snapshot, self.root,
            task_goal="Continue pause behavior.", current_repository_evidence=[],
        )
        classifications = {
            item["record_id"]: item["classification"]
            for item in context["record_classifications"]
        }
        self.assertEqual(classifications[old["record_id"]], CONFLICTED)
        self.assertEqual(classifications[conflicting["record_id"]], CONFLICTED)
        current_ids = {item["record_id"] for item in context["current_verified_facts"]}
        self.assertNotIn(old["record_id"], current_ids)
        self.assertNotIn(conflicting["record_id"], current_ids)
        self.assertTrue(any(
            item.get("kind") == "CONTRADICTORY_ACTIVE_AUTHORITY"
            for item in context["conflicts"]
        ))

    def test_new_user_requirement_has_precedence_and_conflict_is_explicit(self):
        before = self.store.project_brain_hash(self.project_id)
        result = self._run("Move pause-state ownership away from PauseController.")
        self.assertEqual(result["status"], REENTRY_READY)
        self.assertTrue(any(
            item.get("kind") == NEW_REQUIREMENT_VS_CURRENT_ARCHITECTURE
            for item in result["reentry_context"]["conflicts"]
        ))
        self.assertIn(
            "Move pause-state ownership away from PauseController.",
            [item["text"] for item in result["reentry_context"]["new_requirements"]],
        )
        self.assertTrue(any(
            "PauseController remains the sole pause-state owner" in item["fact"].get("fact", "")
            for item in result["task_brain"]["current_verified_facts"]
        ))
        self.assertEqual(before, self.store.project_brain_hash(self.project_id))

    def test_authority_repository_drift_is_recorded_without_rewriting_authority(self):
        status_path = self.root / "src" / "status_view.js"
        status_path.write_text(
            "class StatusView { // StatusView owns pause state.\n  render() {}\n}\n",
            encoding="utf-8",
        )
        digest = hashlib.sha256(status_path.read_bytes()).hexdigest()
        observation = {
            "evidence_id": "REPO-001",
            "category": "CURRENT_STATE_OWNER",
            "path": "src/status_view.js",
            "symbol": "StatusView",
            "fact": "StatusView owns pause state.",
            "source_kind": "SOURCE",
            "evidence_type": DIRECT_OBSERVATION,
            "provenance": REPOSITORY_EVIDENCE,
            "line_start": 1,
            "line_end": 2,
            "file_sha256": digest,
            "support": "class StatusView owns pause state.",
        }
        before = self.store.project_brain_hash(self.project_id)
        result = self._run(current_repository_evidence=[observation])
        self.assertEqual(result["status"], REENTRY_READY)
        self.assertTrue(any(
            item.get("kind") == AUTHORITY_IMPLEMENTATION_DRIFT
            for item in result["reentry_context"]["conflicts"]
        ))
        self.assertTrue(all(
            item.get("provenance") == REPOSITORY_EVIDENCE
            for item in result["reentry_context"]["current_repository_evidence"]
        ))
        self.assertEqual(before, self.store.project_brain_hash(self.project_id))

    def test_tampered_and_invalid_authority_records_are_not_consumed(self):
        snapshot = self.store.project_brain_snapshot(self.project_id, include_inactive=True)
        tampered = copy.deepcopy(snapshot["records"][0])
        tampered["fact"]["fact"] = "Tampered authority claim"
        invalid_authority = copy.deepcopy(snapshot["records"][1])
        invalid_authority["fact"]["authority_source"] = "worker-advice"
        for record in (tampered, invalid_authority):
            record["fact"]["fact_hash"] = canonical_hash({key: value for key, value in record["fact"].items() if key != "fact_hash"})
            record["fact_hash"] = record["fact"]["fact_hash"]
        context = build_reentry_context(
            self.project_id, "TAMPER", {"project_id": self.project_id, "records": [tampered, invalid_authority]}, self.root,
            task_goal="Continue pause behavior.", current_repository_evidence=[],
        )
        self.assertTrue(context["ready"])
        self.assertTrue(all(item.get("classification") == CONFLICTED for item in context["record_classifications"]))
        self.assertEqual(context["current_verified_facts"], [])

    def test_cross_project_identity_fails_closed(self):
        snapshot = self.store.project_brain_snapshot(self.project_id, include_inactive=True)
        result = build_reentry_context(
            "other-project", "CROSS", snapshot, self.root,
            task_goal="Continue pause behavior.", current_repository_evidence=[],
        )
        self.assertEqual(result["status"], REENTRY_PROJECT_ID_MISMATCH)
        self.assertFalse(result["ready"])

    def test_memory_read_failure_is_explicit_not_empty_state(self):
        class BrokenStore:
            workspace = self.root

            def project_brain_snapshot(self, *_args, **_kwargs):
                raise OSError("simulated Project Brain read failure")

        result = run_verified_state_reentry(BrokenStore(), self.project_id, "BROKEN", "Continue pause behavior.")
        self.assertEqual(result["status"], REENTRY_MEMORY_UNAVAILABLE)
        self.assertFalse(result["ready"])
        self.assertIn("read failed", result["errors"][0])

    def test_repository_read_failure_is_not_converted_to_empty_current_state(self):
        result = self._run(
            current_repository_evidence={
                "status": "REPOSITORY_EVIDENCE_UNAVAILABLE",
                "available": False,
                "error": "simulated repository read failure",
                "evidence": [],
            }
        )
        self.assertEqual(result["status"], "REENTRY_REPOSITORY_UNAVAILABLE")
        self.assertFalse(result["ready"])
        self.assertIn("simulated repository read failure", result["reentry_context"]["error"][0])

    def test_empty_project_brain_does_not_fabricate_verified_state(self):
        with tempfile.TemporaryDirectory(prefix="hivo_v23_empty_") as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "only.js").write_text("export const current = true;\n", encoding="utf-8")
            store = MemoryStore(root)
            result = run_verified_state_reentry(
                store, "empty-project", "EMPTY-TASK", "Inspect the current project.", workspace=root,
            )
        self.assertEqual(result["status"], REENTRY_READY)
        self.assertEqual(result["metrics"]["project_brain_records_considered"], 0)
        self.assertEqual(result["task_brain"]["current_verified_facts"], [])

    def test_reentry_and_task_brain_hashes_are_deterministic_and_sensitive(self):
        first = self._run(new_task_id="HASH-TASK", current_repository_evidence=[])
        second = self._run(new_task_id="HASH-TASK", current_repository_evidence=[])
        self.assertEqual(first["reentry_context"]["reentry_hash"], second["reentry_context"]["reentry_hash"])
        self.assertEqual(first["task_brain"]["task_brain_hash"], second["task_brain"]["task_brain_hash"])
        changed_requirement = self._run(
            "Continue status-view pause behavior.", new_task_id="HASH-TASK", current_repository_evidence=[],
        )
        self.assertNotEqual(first["reentry_context"]["reentry_hash"], changed_requirement["reentry_context"]["reentry_hash"])
        target = self.root / "src" / "input.js"
        target.write_text(target.read_text(encoding="utf-8") + "// hash-sensitive change\n", encoding="utf-8")
        changed_repo = self._run(new_task_id="HASH-TASK", current_repository_evidence=[])
        self.assertNotEqual(first["reentry_context"]["reentry_hash"], changed_repo["reentry_context"]["reentry_hash"])

    def test_large_project_brain_stays_bounded_without_dumping_into_task_brain(self):
        snapshot = self.store.project_brain_snapshot(self.project_id, include_inactive=True)
        records = []
        for index in range(256):
            record = copy.deepcopy(snapshot["records"][index % len(snapshot["records"])])
            record["record_id"] = f"large-{index:03d}"
            record["fact"]["fact"] += f" variant {index}"
            record["fact"]["conflict_key"] = f"large:{index}"
            record["fact"]["semantic_hash"] = canonical_hash({
                key: record["fact"].get(key)
                for key in ("category", "field", "fact", "authority", "conflict_key")
            })
            record["fact"]["fact_hash"] = canonical_hash({
                key: value for key, value in record["fact"].items() if key != "fact_hash"
            })
            record["fact_hash"] = record["fact"]["fact_hash"]
            record["semantic_hash"] = record["fact"]["semantic_hash"]
            record["conflict_key"] = record["fact"]["conflict_key"]
            records.append(record)
        context = build_reentry_context(
            self.project_id, "LARGE-TASK", {"project_id": self.project_id, "records": records},
            self.root, task_goal="Continue pause behavior.", current_repository_evidence=[],
        )
        brain = build_fresh_task_brain(context, task_goal="Continue pause behavior.")
        self.assertTrue(context["ready"])
        self.assertLessEqual(len(json.dumps(context, separators=(",", ":"))), 40_000)
        self.assertEqual(context["record_classification_count"], 256)
        self.assertTrue(context["record_classifications_truncated"])
        self.assertEqual(brain["artifact_type"], FRESH_TASK_BRAIN_TYPE)
        self.assertLessEqual(len(json.dumps(brain, separators=(",", ":"))), 10_000)
        self.assertTrue(validate_fresh_task_brain(brain)["valid"])

    def test_task_brain_is_fresh_bounded_and_excludes_private_material(self):
        pointer = {
            "schema_version": "V22.5C",
            "task_id": "OLD-TASK",
            "terminal_state": "VERIFIED_AND_PROMOTED",
            "promotion_hash": "a" * 64,
            "parent_verification_hash": "b" * 64,
            "subject_state_hash": self.subject["hash"],
            "artifact_refs": ["parent_verification_receipt.json"],
            "project_brain_record_ids": [self._integration_record_id()],
            "completion_hash": "c" * 64,
        }
        result = self._run(previous_task_completion=pointer)
        brain = result["task_brain"]
        self.assertEqual(brain["artifact_type"], FRESH_TASK_BRAIN_TYPE)
        self.assertEqual(brain["task_id"], "V23-TASK")
        self.assertFalse(brain["provenance"]["old_task_brain_reused"])
        self.assertFalse(brain["provenance"]["private_execution_material_loaded"])
        self.assertLessEqual(len(json.dumps(brain, separators=(",", ":"))), 10_000)
        serialized = json.dumps(brain, ensure_ascii=False).casefold()
        for marker in ("worker transcript", "missioncompiler", "decomposer output", "falsifier prose", "strategy output"):
            self.assertNotIn(marker, serialized)
        self.assertIn("OLD-TASK", json.dumps(brain["continuation_provenance"]))

    def test_model_calls_zero_and_stage6a_architecture_self_test_passes(self):
        result = self._run(current_repository_evidence=[])
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["metrics"]["freshness_model_calls"], 0)
        self.assertEqual(result["metrics"]["relevance_model_calls"], 0)
        self.assertEqual(result["metrics"]["task_brain_bootstrap_model_calls"], 0)
        self.assertEqual(result["verification_calls"], 0)
        self.assertTrue(all(value == 0 for value in result["model_call_accounting"].values()))
        self.assertEqual(result["next_stage"], "STOP_AFTER_FRESH_TASK_BRAIN")
        self.assertTrue(run_verified_state_reentry_self_test()["passed"])

    def test_mini_explicit_wrapper_updates_only_reentry_metrics(self):
        saved_workspace, saved_run = mini.WORKSPACE, mini.RUN
        try:
            mini.WORKSPACE = self.root
            mini.RUN = mini.new_metrics("recursive")
            result = mini.run_verified_state_reentry(
                self.project_id, "MINI-TASK", "Continue pause behavior.",
                store=self.store, workspace=self.root, current_repository_evidence=[],
            )
            self.assertEqual(result["status"], REENTRY_READY)
            self.assertEqual(mini.RUN["reentry_model_calls"], 0)
            self.assertEqual(mini.RUN["task_brain_bootstraps"], 1)
            self.assertEqual(mini.RUN["automatic_reverification_attempts"], 0)
        finally:
            mini.WORKSPACE, mini.RUN = saved_workspace, saved_run


if __name__ == "__main__":
    unittest.main()
