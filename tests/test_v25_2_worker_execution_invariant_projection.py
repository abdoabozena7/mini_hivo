"""Provider-free V25.2 deterministic Worker-invariant projection tests."""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo import approval_authority as authority
from hivo import execution_contracts as stage4
from hivo import execution_invariants as invariants
from hivo.memory import MemoryStore


ROOT = Path(__file__).resolve().parents[1]
PLANNING_ROOT = ROOT / "output" / "hivo-v24-4-6-stage6b-planning-live-1"
FIXTURE_ROOT = ROOT / "output" / "hivo-v25-stage6c-b-approved-execution-live-1"
FAILED_LIVE_ROOT = ROOT / "output" / "hivo-v25-1-stage6c-b-approved-execution-live-2"
HISTORICAL_DB = ROOT / "output" / "hivo-v22-stage5c-fresh-receipts-live-1" / ".hivo" / "memory.sqlite3"
EXPECTED_BRAIN_HASH = "8eac670a83eeddb30528ebd3ad5032dabc6f6d1a3fb97b65b4600964b1b434bb"


def _load(path: Path, fallback=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return copy.deepcopy(fallback)


class WorkerExecutionInvariantProjectionTests(unittest.TestCase):
    """All Worker behavior is injected; no provider is reachable."""

    @classmethod
    def setUpClass(cls):
        cls.plan = _load(PLANNING_ROOT / "final_plan.json", {})
        cls.context = _load(PLANNING_ROOT / "verified_planning_context.json", {})
        cls.brain = authority.read_only_project_brain_identity(
            HISTORICAL_DB, cls.context.get("project_id"),
        )
        cls.state = {
            "task_id": cls.context.get("task_id"),
            "project_id": cls.context.get("project_id"),
            "planning_mode": cls.context.get("planning_mode"),
            "verified_planning_context": cls.context,
            "planning_context_hash": cls.context.get("planning_context_hash"),
            "brain_hash": cls.brain["logical_hash"],
            "subject_aggregate_hash": (cls.context.get("source_repository_fingerprint") or {}).get("hash"),
            "upstream_bindings": cls.plan.get("upstream_bindings", {}),
            "requirements": cls.plan.get("requirements", []),
            "coverage": cls.plan.get("coverage", []),
            "planning_context_freshness": _load(PLANNING_ROOT / "planning_context_freshness.json", {}),
            "plan_validation": _load(PLANNING_ROOT / "plan_validation.json", {}),
            "stage4_contractability_audit": _load(PLANNING_ROOT / "stage4_contractability_audit.json", {}),
            "challenger_reconciliation": _load(
                PLANNING_ROOT / "challenger_reconciliation.json",
                cls.plan.get("challenger_reconciliation", {}),
            ),
            "terminal_state": authority.PLAN_APPROVAL_REQUIRED,
            "source_repository_fingerprint": cls.context.get("source_repository_fingerprint", {}),
        }
        cls.evidence = _load(PLANNING_ROOT / "current_surface_evidence.json", {}).get(
            "repository_evidence", [],
        )
        cls.request = authority.create_plan_approval_request(cls.plan, cls.state)
        cls.receipt = authority.record_plan_approval(
            cls.request, authority.make_test_explicit_user_approval_event(cls.request),
        )
        cls.revalidation = authority.pre_execution_approval_revalidation(
            cls.receipt, cls.plan, cls.state, request=cls.request,
        )
        cls.old_authorization = authority.create_approved_execution_authorization(
            cls.receipt, cls.revalidation, request=cls.request,
        )
        cls.old_compiled = authority.compile_approval_bound_execution_contracts(
            cls.plan, cls.receipt, cls.revalidation, cls.old_authorization,
            request=cls.request, requirements=cls.plan.get("requirements", []),
            repository_evidence=cls.evidence,
        )
        cls.old_contract = next(
            item for item in cls.old_compiled["contracts"]
            if item.get("responsibility_type") == stage4.MUTATION
        )
        cls.invariant_set = invariants.build_execution_invariant_set(
            execution_contract=cls.old_contract,
            approved_plan=cls.plan,
            source_root=FIXTURE_ROOT,
            repository_evidence=cls.evidence,
        )
        cls.authorization = authority.create_approved_execution_authorization(
            cls.receipt, cls.revalidation, request=cls.request,
            execution_invariant_set=cls.invariant_set,
            stage4_graph=cls.old_compiled["graph"],
        )
        cls.compiled = authority.compile_approval_bound_execution_contracts(
            cls.plan, cls.receipt, cls.revalidation, cls.authorization,
            request=cls.request, requirements=cls.plan.get("requirements", []),
            repository_evidence=cls.evidence,
            execution_invariant_set=cls.invariant_set,
            execution_invariant_source_root=FIXTURE_ROOT,
        )
        cls.contract = next(
            item for item in cls.compiled["contracts"]
            if item.get("responsibility_type") == stage4.MUTATION
        )

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="hivo_v25_2_invariants_")
        root = Path(self.tempdir.name)
        self.workspace = root / "execution"
        for relative in (
            "src/input.js", "src/pause_controller.js", "src/status_view.js",
            "tests/input.test.js", "tests/pause_flow.integration.test.js",
            "tests/status_view.test.js",
        ):
            target = self.workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(FIXTURE_ROOT / relative, target)
        self.working_root = root / "working_brain"
        (self.working_root / ".hivo").mkdir(parents=True)
        shutil.copy2(HISTORICAL_DB, self.working_root / ".hivo" / "memory.sqlite3")
        self.working_store = MemoryStore(self.working_root)
        self.historical_bytes = HISTORICAL_DB.read_bytes()

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def _additive_callback(execute_tool=None, **_kwargs):
        old = "module.exports = { renderStatus };"
        new = """function renderPauseIndicator(pauseController) {
  if (!(pauseController instanceof PauseController)) {
    throw new TypeError('a PauseController is required');
  }
  return pauseController.isPaused() ? '⏸ Paused' : '▶ Running';
}

module.exports = { renderStatus, renderPauseIndicator };"""
        result = execute_tool(
            "edit_file", {"path": "src/status_view.js", "old": old,
                           "new": new, "expected_replacements": 1},
        )
        return {
            "status": "done", "summary": "additive indicator edit applied",
            "tool_evidence": [{"tool": "edit_file", "target": "src/status_view.js", "result": result}],
        }

    @staticmethod
    def _object_return_callback(execute_tool=None, **_kwargs):
        old = "module.exports = { renderStatus };"
        new = """function renderStatus(pauseController) {
  if (!(pauseController instanceof PauseController)) {
    throw new TypeError('a PauseController is required');
  }
  if (pauseController.isPaused()) {
    return { status: 'Paused', indicator: '🛑 PAUSED' };
  }
  return { status: 'Running', indicator: '' };
}

module.exports = { renderStatus };"""
        result = execute_tool(
            "edit_file", {"path": "src/status_view.js", "old": old,
                           "new": new, "expected_replacements": 1},
        )
        return {
            "status": "done", "summary": "object return mutation applied",
            "tool_evidence": [{"tool": "edit_file", "target": "src/status_view.js", "result": result}],
        }

    def _run(self, worker, *, authorization=None, invariant_set=None):
        with patch.object(mini, "ask_ollama", side_effect=AssertionError("provider must not be called")):
            return mini.run_approval_bound_execution_lifecycle(
                plan=copy.deepcopy(self.plan), request=copy.deepcopy(self.request),
                receipt=copy.deepcopy(self.receipt),
                revalidation=copy.deepcopy(self.revalidation),
                authorization=copy.deepcopy(authorization or self.authorization),
                memory={}, workspace=self.workspace,
                working_brain_store=self.working_store,
                current_state=copy.deepcopy(self.state), worker_callback=worker,
                execution_invariant_set=copy.deepcopy(invariant_set or self.invariant_set),
                repository_evidence=copy.deepcopy(self.evidence),
            )

    def test_fixture_invariants_are_structurally_derived_and_immutable(self):
        self.assertEqual(self.invariant_set["status"], invariants.VALID)
        self.assertEqual(self.invariant_set["model_calls"], 0)
        self.assertTrue(self.invariant_set["invariant_set_hash"])
        by_type = {item["type"]: item for item in self.invariant_set["invariants"]}
        self.assertEqual(by_type[invariants.FUNCTION_SIGNATURE]["signature"], "renderStatus(pauseController)")
        self.assertEqual(by_type[invariants.RETURN_SHAPE]["return_shape"], "primitive string")
        self.assertEqual(set(by_type[invariants.EXACT_EXISTING_OUTPUT]["output_literals"]), {"Running", "Paused"})
        self.assertEqual(
            {item["path"] for item in by_type[invariants.CONSUMER_EXPECTATION]["consumers"]},
            {"tests/status_view.test.js", "tests/pause_flow.integration.test.js"},
        )
        self.assertEqual(by_type[invariants.INTERFACE_COMPATIBILITY]["classification"], invariants.PRESERVE)
        self.assertEqual(by_type[invariants.INTERFACE_COMPATIBILITY]["change_authorization"], invariants.CHANGE_NOT_AUTHORIZED)
        with self.assertRaises(TypeError):
            self.invariant_set["status"] = "tampered"
        self.assertEqual(
            self.invariant_set["invariant_set_hash"],
            invariants.canonical_invariant_set_hash(self.invariant_set),
        )

    def test_evidence_refs_hashes_locations_and_symbol_validation(self):
        checked = invariants.validate_execution_invariant_set(
            self.invariant_set, execution_contract=self.contract,
            source_root=FIXTURE_ROOT, require_current_subject=True,
        )
        self.assertTrue(checked["valid"], checked["errors"])
        refs = [ref for item in self.invariant_set["invariants"] for ref in item["evidence_refs"]]
        self.assertTrue(refs)
        self.assertTrue(all(ref.get("evidence_id") and ref.get("file_sha256") for ref in refs))
        self.assertTrue(all(ref.get("path") for ref in refs))
        self.assertTrue(any(ref.get("location", {}).get("line_start") == 3 for ref in refs))

    def test_projection_explicitly_separates_semantic_authority_and_scope(self):
        projection = invariants.build_worker_execution_invariant_projection(
            self.invariant_set, self.contract, max_chars=4200,
        )
        rendered = invariants.render_worker_execution_invariant_projection(projection, max_chars=4200)
        self.assertLessEqual(len(rendered), 4200)
        self.assertIn("CURRENT EXECUTION INVARIANTS", rendered)
        self.assertIn("primitive string", rendered)
        self.assertIn('"Paused"', rendered)
        self.assertIn('"Running"', rendered)
        self.assertIn("tests/status_view.test.js", rendered)
        self.assertIn("additively", rendered)
        self.assertEqual(projection["mandatory_drops"], 0)
        self.assertEqual(projection["provider_facing_hash"], invariants.canonical_hash(rendered))
        self.assertEqual(projection["execution_invariant_set_hash"], self.invariant_set["invariant_set_hash"])
        self.assertEqual(projection["model_calls"], 0)
        self.assertEqual(projection["worker_calls"], 0)
        self.assertEqual(
            invariants.validate_worker_execution_invariant_projection(
                projection, self.invariant_set, self.contract,
            )["valid"], True,
        )

    def test_stage4_and_authorization_bind_invariant_hash_without_changing_receipt(self):
        self.assertTrue(authority.validate_plan_approval_receipt(self.receipt, self.request)["valid"])
        self.assertEqual(self.receipt["receipt_hash"], self.request.get("binding", {}).get("receipt_hash", self.receipt["receipt_hash"]))
        self.assertEqual(self.authorization["execution_invariant_set_hash"], self.invariant_set["invariant_set_hash"])
        self.assertTrue(all(
            item.get("execution_invariant_set_hash") == self.invariant_set["invariant_set_hash"]
            for item in self.compiled["contracts"]
        ))
        self.assertNotEqual(
            self.contract["contract_hash"], self.old_contract["contract_hash"],
        )
        tampered = copy.deepcopy(self.authorization)
        tampered["execution_invariant_set_hash"] = "0" * 64
        self.assertFalse(authority.validate_approved_execution_authorization(tampered)["valid"])

    def test_exact_failed_live_packet_is_read_only_replay_baseline(self):
        audit = _load(FAILED_LIVE_ROOT / "artifacts" / "worker_packet_audit.json", {})
        old_packet = next(iter((audit.get("projections") or {}).values()), {})
        self.assertEqual(audit.get("worker_context_rendered_chars"), 2535)
        self.assertIn("VERIFIED REPOSITORY FACTS", old_packet.get("rendered_worker_context", ""))
        self.assertIn("- (none)", old_packet.get("rendered_worker_context", ""))
        self.assertNotIn("primitive string", old_packet.get("rendered_worker_context", ""))
        self.assertEqual(audit.get("worker_context_projection_failures"), 0)

    def test_new_packet_has_field_level_semantic_delta_and_identity(self):
        mission = stage4.hydrate_worker_mission(
            self.contract,
            {"objective": self.contract["goal"], "implementation_steps": ["Apply approved responsibility only"]},
            [],
        )
        projection = stage4.build_worker_context_projection(
            mission, self.contract, [], max_chars=mini.MAX_WORKER_MISSION_CHARS,
        )
        packet = stage4.render_worker_context_projection(
            projection, max_chars=mini.MAX_WORKER_MISSION_CHARS,
        )
        self.assertLessEqual(len(packet), mini.MAX_WORKER_MISSION_CHARS)
        self.assertEqual(projection["projection_audit"]["authority_items_dropped"], 0)
        self.assertIn("primitive string", packet)
        self.assertIn("Existing compatible outputs", packet)
        self.assertIn("Existing consumers depend", packet)
        self.assertIn("additively", packet)
        self.assertEqual(
            projection["execution_invariant_projection"]["projection_hash"],
            invariants.canonical_hash(
                invariants._without(projection["execution_invariant_projection"], "projection_hash")
            ),
        )
        self.assertEqual(
            projection["execution_invariant_projection"]["invariant_ids"],
            projection["execution_invariant_ids"],
        )

    def test_positive_injected_worker_preserves_legacy_contract_and_passes_real_verification(self):
        before = {
            relative: (self.workspace / relative).read_bytes()
            for relative in (
                "src/input.js", "src/pause_controller.js", "src/status_view.js",
                "tests/input.test.js", "tests/pause_flow.integration.test.js",
                "tests/status_view.test.js",
            )
        }
        result, _ = self._run(self._additive_callback)
        self.assertEqual(result.get("status"), "done", result)
        self.assertIn("renderPauseIndicator", (self.workspace / "src/status_view.js").read_text(encoding="utf-8"))
        self.assertNotEqual(before["src/status_view.js"], (self.workspace / "src/status_view.js").read_bytes())
        for relative, content in before.items():
            if relative != "src/status_view.js":
                self.assertEqual(content, (self.workspace / relative).read_bytes(), relative)
        self.assertEqual(before["src/pause_controller.js"], (self.workspace / "src/pause_controller.js").read_bytes())
        self.assertEqual(result.get("worker_calls"), 1)
        self.assertEqual(mini.RUN.get("model_calls"), 0)

    def test_adversarial_object_return_is_explicitly_forbidden_but_not_guaranteed(self):
        captured = {}

        def worker(worker_context=None, **kwargs):
            captured["context"] = worker_context
            return self._object_return_callback(**kwargs)

        result, _ = self._run(worker)
        self.assertNotEqual(result.get("status"), "done")
        self.assertIn("does not authorize replacing its return shape", captured.get("context", ""))
        self.assertIn("primitive string", captured.get("context", ""))
        self.assertEqual(result.get("terminal_state"), mini.VERIFICATION_FAILED)
        self.assertEqual(mini.RUN.get("verified_execution_promotions"), 0)

    def test_unauthorized_worker_tool_cannot_expand_scope(self):
        def unapproved(execute_tool=None, **_kwargs):
            result = execute_tool("read_file", {"path": "src/input.js"})
            return {"status": "done", "summary": "read only", "tool_evidence": [result]}

        result, _ = self._run(unapproved)
        self.assertEqual(result.get("terminal_state"), mini.WORKER_NO_APPROVED_MUTATION)

    def test_alternate_symbol_and_consumer_are_structural(self):
        source = """function showMode(controller) {
  return controller.isActive() ? 'On' : 'Off';
}
module.exports = { showMode };
"""
        consumer = """const assert = require('assert/strict');
const { showMode } = require('../src/view');
const controller = {};
assert.equal(showMode(controller), 'Off');
assert.equal(showMode(controller), 'On');
"""
        evidence = [
            {"evidence_id": "ALT-SOURCE", "path": "src/view.js", "symbol": "showMode", "source_kind": "SOURCE"},
            {"evidence_id": "ALT-TEST", "path": "tests/view.test.js", "symbol": "showMode", "source_kind": "TEST"},
        ]
        contract = {
            "allowed_mutation_paths": ["src/view.js"],
            "allowed_inspection_paths": ["src/view.js", "tests/view.test.js"],
            "repository_evidence_ids": ["ALT-SOURCE", "ALT-TEST"],
            "global_do_not_touch": [], "interfaces_to_reuse": [],
        }
        result = invariants.build_execution_invariant_set(
            contract, source_root=None,
            source_files={"src/view.js": source, "tests/view.test.js": consumer},
            repository_evidence=evidence,
            approved_plan={"requirements": ["add an additional marker while preserving existing output"]},
        )
        self.assertEqual(result["status"], invariants.VALID, result)
        self.assertEqual(
            next(item for item in result["invariants"] if item["type"] == invariants.FUNCTION_SIGNATURE)["signature"],
            "showMode(controller)",
        )
        self.assertEqual(
            set(next(item for item in result["invariants"] if item["type"] == invariants.EXACT_EXISTING_OUTPUT)["output_literals"]),
            {"On", "Off"},
        )

    def test_duplicate_evidence_is_fanned_into_one_semantic_invariant(self):
        source = "function showMode(controller) { return controller.isActive() ? 'On' : 'Off'; }"
        consumer = "const assert = require('assert/strict'); assert.equal(showMode({}), 'Off');"
        evidence = [
            {"evidence_id": "D-SOURCE-A", "path": "src/view.js", "symbol": "showMode", "source_kind": "SOURCE"},
            {"evidence_id": "D-SOURCE-B", "path": "src/view.js", "symbol": "showMode", "source_kind": "SOURCE"},
            {"evidence_id": "D-TEST", "path": "tests/view.test.js", "symbol": "showMode", "source_kind": "TEST"},
        ]
        contract = {
            "allowed_mutation_paths": ["src/view.js"],
            "allowed_inspection_paths": ["tests/view.test.js"],
            "global_do_not_touch": [], "interfaces_to_reuse": [],
        }
        result = invariants.build_execution_invariant_set(
            contract, source_files={"src/view.js": source, "tests/view.test.js": consumer},
            repository_evidence=evidence,
        )
        signature = next(item for item in result["invariants"] if item["type"] == invariants.FUNCTION_SIGNATURE)
        self.assertEqual(len(signature["evidence_refs"]), 2)
        self.assertEqual(sum(item["type"] == invariants.FUNCTION_SIGNATURE for item in result["invariants"]), 1)

    def test_unrelated_same_literal_is_not_consumer_evidence(self):
        source = "function showMode(controller) { return controller.isActive() ? 'On' : 'Off'; }"
        unrelated = "const assert = require('assert/strict'); assert.equal(other(), 'Off');"
        evidence = [
            {"evidence_id": "U-SOURCE", "path": "src/view.js", "symbol": "showMode", "source_kind": "SOURCE"},
            {"evidence_id": "U-TEST", "path": "tests/other.test.js", "symbol": "other", "source_kind": "TEST"},
        ]
        contract = {"allowed_mutation_paths": ["src/view.js"], "allowed_inspection_paths": ["tests/other.test.js"], "repository_evidence_ids": ["U-SOURCE", "U-TEST"], "global_do_not_touch": [], "interfaces_to_reuse": []}
        result = invariants.build_execution_invariant_set(
            contract, source_files={"src/view.js": source, "tests/other.test.js": unrelated}, repository_evidence=evidence,
        )
        self.assertEqual(result["status"], invariants.UNSUPPORTED)
        self.assertEqual(result["code"], invariants.EXECUTION_INVARIANT_UNSUPPORTED)

    def test_authorized_interface_change_does_not_create_false_preservation_block(self):
        source = "function showMode(controller) { return controller.isActive() ? 'On' : 'Off'; }"
        consumer = "const assert = require('assert/strict'); assert.equal(showMode({}), 'Off');"
        evidence = [
            {"evidence_id": "C-SOURCE", "path": "src/view.js", "symbol": "showMode", "source_kind": "SOURCE"},
            {"evidence_id": "C-TEST", "path": "tests/view.test.js", "symbol": "showMode", "source_kind": "TEST"},
        ]
        contract = {"allowed_mutation_paths": ["src/view.js"], "allowed_inspection_paths": ["tests/view.test.js"], "repository_evidence_ids": ["C-SOURCE", "C-TEST"], "global_do_not_touch": [], "interfaces_to_reuse": []}
        plan = {"authorized_interface_changes": [{"symbol": "showMode", "path": "src/view.js", "authorized": True}], "requirements": ["change the return shape"]}
        result = invariants.build_execution_invariant_set(
            contract, approved_plan=plan,
            source_files={"src/view.js": source, "tests/view.test.js": consumer}, repository_evidence=evidence,
        )
        self.assertEqual(result["status"], invariants.VALID)
        self.assertTrue(all(
            item["classification"] == invariants.CHANGE_AUTHORIZED
            for item in result["invariants"]
            if item["type"] in {invariants.RETURN_SHAPE, invariants.INTERFACE_COMPATIBILITY}
        ))

    def test_conflict_and_ambiguous_source_fail_closed(self):
        conflict_source = "function showMode(controller) { return controller.isActive() ? 'On' : 'Off'; }"
        conflict_test = "const assert = require('assert/strict'); assert.equal(showMode({}), 'Stopped');"
        evidence = [
            {"evidence_id": "X-SOURCE", "path": "src/view.js", "symbol": "showMode", "source_kind": "SOURCE"},
            {"evidence_id": "X-TEST", "path": "tests/view.test.js", "symbol": "showMode", "source_kind": "TEST"},
        ]
        contract = {"allowed_mutation_paths": ["src/view.js"], "allowed_inspection_paths": ["tests/view.test.js"], "repository_evidence_ids": ["X-SOURCE", "X-TEST"], "global_do_not_touch": [], "interfaces_to_reuse": []}
        conflict = invariants.build_execution_invariant_set(
            contract, source_files={"src/view.js": conflict_source, "tests/view.test.js": conflict_test}, repository_evidence=evidence,
        )
        self.assertEqual(conflict["code"], invariants.EXECUTION_INVARIANT_EVIDENCE_CONFLICT)
        ambiguous_source = "function showMode(controller) { if (controller.isActive()) return 'On'; return { value: 'Off' }; }"
        ambiguous = invariants.build_execution_invariant_set(
            contract, source_files={"src/view.js": ambiguous_source, "tests/view.test.js": "assert.equal(showMode({}), 'On');"}, repository_evidence=evidence,
        )
        self.assertEqual(ambiguous["status"], invariants.UNSUPPORTED)
        self.assertEqual(ambiguous["code"], invariants.EXECUTION_INVARIANT_UNSUPPORTED)

    def test_stale_hash_blocks_current_subject_without_regeneration(self):
        with tempfile.TemporaryDirectory(prefix="hivo_v25_2_stale_") as tmp:
            temp_root = Path(tmp)
            for relative in ("src/status_view.js", "src/pause_controller.js", "tests/pause_flow.integration.test.js", "tests/status_view.test.js"):
                target = temp_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(FIXTURE_ROOT / relative, target)
            (temp_root / "src/status_view.js").write_text(
                (temp_root / "src/status_view.js").read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            checked = invariants.validate_execution_invariant_set(
                self.invariant_set, execution_contract=self.contract,
                source_root=temp_root, require_current_subject=True,
            )
            self.assertFalse(checked["valid"])
            self.assertEqual(checked["code"], invariants.REAPPROVAL_REQUIRED)
            self.assertEqual(self.invariant_set["invariant_set_hash"], invariants.canonical_invariant_set_hash(self.invariant_set))

    def test_stale_subject_blocks_before_injected_worker(self):
        (self.workspace / "src/status_view.js").write_text(
            (self.workspace / "src/status_view.js").read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        called = []

        def worker(**_kwargs):
            called.append(True)
            return {"status": "done"}

        result, _ = self._run(worker)
        self.assertFalse(called)
        self.assertEqual(result.get("worker_calls"), 0)
        self.assertIn(result.get("terminal_state"), {invariants.REAPPROVAL_REQUIRED, mini.WORKER_AUTHORIZATION_INVALID})

    def test_scope_dnt_and_owner_authority_are_not_expanded(self):
        authority_data = self.invariant_set["authority"]
        self.assertEqual(authority_data["mutation_paths"], ["src/status_view.js"])
        self.assertEqual(authority_data["dnt_paths"], ["src/pause_controller.js"])
        self.assertEqual(authority_data["new_owner_symbols"], [])
        tampered = copy.deepcopy(self.invariant_set)
        tampered["authority"]["mutation_paths"].append("src/input.js")
        tampered["invariant_set_hash"] = invariants.canonical_invariant_set_hash(tampered)
        self.assertFalse(invariants.validate_execution_invariant_set(tampered, execution_contract=self.contract)["valid"])

    def test_injected_worker_cannot_edit_outside_approved_scope(self):
        def unapproved(execute_tool=None, **_kwargs):
            denied = execute_tool(
                "edit_file",
                {"path": "src/input.js", "old": "function", "new": "function", "expected_replacements": 1},
            )
            return {"status": "done", "tool_evidence": [denied]}

        before = (self.workspace / "src/input.js").read_bytes()
        result, _ = self._run(unapproved)
        self.assertEqual(before, (self.workspace / "src/input.js").read_bytes())
        self.assertEqual(result.get("terminal_state"), mini.WORKER_NO_APPROVED_MUTATION)

    def test_budget_overflow_is_mandatory_and_pre_provider(self):
        with self.assertRaises(invariants.ExecutionInvariantError) as raised:
            invariants.build_worker_execution_invariant_projection(
                self.invariant_set, self.contract, max_chars=10,
            )
        self.assertEqual(raised.exception.code, invariants.EXECUTION_INVARIANT_CONTEXT_OVERFLOW)
        self.assertEqual(self.invariant_set["model_calls"], 0)

    def test_production_extractor_has_no_fixture_literals(self):
        production = (ROOT / "hivo" / "execution_invariants.py").read_text(encoding="utf-8")
        for literal in ("renderStatus", "status_view.js", "Running", "Paused"):
            self.assertNotIn(literal, production)

    def test_model_and_worker_accounting_stays_zero_until_injected_fixture(self):
        self.assertEqual(self.invariant_set["model_calls"], 0)
        self.assertEqual(self.invariant_set["worker_calls"], 0)
        self.assertEqual(self.authorization.get("model_calls", 0), 0)
        self.assertEqual(self.authorization.get("worker_calls", 0), 0)


if __name__ == "__main__":
    unittest.main()
