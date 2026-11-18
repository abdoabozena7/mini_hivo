"""Provider-free V25.5 pre-commit execution-invariant enforcement tests."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo import approval_authority as authority
from hivo import execution_contracts as stage4
from hivo import execution_invariants as invariants
from hivo import precommit_invariant_gate as precommit
from hivo import verification_gap_remediation as remediation


ROOT = Path(__file__).resolve().parents[1]
PLANNING_ROOT = ROOT / "output" / "hivo-v24-4-6-stage6b-planning-live-1"
FIXTURE_ROOT = ROOT / "output" / "hivo-v25-stage6c-b-approved-execution-live-1"
LATEST_LIVE_ROOT = ROOT / "output" / "hivo-v25-4-2-stage6c-b-final-closed-loop-live-1"
HISTORICAL_DB = ROOT / "output" / "hivo-v22-stage5c-fresh-receipts-live-1" / ".hivo" / "memory.sqlite3"
EXPECTED_STATUS_VIEW_HASH = "0f9684c6e0ed12e3cbf6c0e6d94a35c8c84f9bbb1017ff495897baae71321852"
EXPECTED_PLAN_ID = "PLAN-5E9D01B255C2"
EXPECTED_PLAN_HASH = "5e9d01b255c23753eafa3fa76160b91b8b92486506580ffaf11f582b9522115a"
EXPECTED_DIRECT_ORACLE_HASH = "f1ccdc309c31709f3bc589b184a7f3d252de408f0b8da2e2ad908109f079b140"
EXPECTED_COVERAGE_HASH = "6bab7c0383a56446d00c6681675366b020a17f524d5bb46b9349ff9c03a85402"


def _load(path: Path, fallback=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return copy.deepcopy(fallback)


class PreCommitExecutionInvariantGateTests(unittest.TestCase):
    """The gate and mutation seams are tested without Gemma or a real Worker."""

    @classmethod
    def setUpClass(cls):
        from tests.test_v25_2_worker_execution_invariant_projection import (
            WorkerExecutionInvariantProjectionTests,
        )

        WorkerExecutionInvariantProjectionTests.setUpClass()
        source = WorkerExecutionInvariantProjectionTests
        cls.plan = copy.deepcopy(source.plan)
        cls.request = copy.deepcopy(source.request)
        cls.receipt = copy.deepcopy(source.receipt)
        cls.revalidation = copy.deepcopy(source.revalidation)
        cls.authorization = copy.deepcopy(source.authorization)
        cls.evidence = copy.deepcopy(source.evidence)
        cls.contract = copy.deepcopy(source.contract)
        # Keep the V25.2 record frozen.  Individual gate instances take their
        # own defensive copies when a test needs to alter a synthetic set.
        cls.invariant_set = source.invariant_set
        cls.oracle_source = _load(
            LATEST_LIVE_ROOT / "artifacts" / "direct_behavior_oracle_source.json", {},
        )

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="hivo_v25_5_precommit_")
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
        self.status_path = self.workspace / "src/status_view.js"
        self.original = self.status_path.read_text(encoding="utf-8")
        self.original_bytes = self.status_path.read_bytes()
        self.historical_bytes = HISTORICAL_DB.read_bytes()
        self._mini_saved = None

    def tearDown(self):
        self._restore_mini_tools()
        self.assertEqual(HISTORICAL_DB.read_bytes(), self.historical_bytes)
        self.assertEqual(FIXTURE_ROOT.joinpath("src/status_view.js").read_bytes(), self.original_bytes)
        self.tempdir.cleanup()

    @staticmethod
    def _additive_candidate(source: str | None = None) -> str:
        current = source or (FIXTURE_ROOT / "src/status_view.js").read_text(encoding="utf-8")
        return current.replace(
            "module.exports = { renderStatus };",
            """function renderPauseIndicator(pauseController) {
  if (!(pauseController instanceof PauseController)) {
    throw new TypeError('a PauseController is required');
  }
  return pauseController.isPaused() ? '⏸ Paused' : '';
}

module.exports = { renderStatus, renderPauseIndicator };""",
        )

    @staticmethod
    def _object_candidate(source: str) -> str:
        start = source.index("function renderStatus")
        close = source.index("\n}\n\nmodule.exports", start) + 2
        replacement = """function renderStatus(pauseController) {
  return pauseController.isPaused()
    ? { status: 'Paused', indicator: '🛑 PAUSED' }
    : { status: 'Running', indicator: '' };
}"""
        return source[:start] + replacement + source[close:]

    def _gate(self, *, invariant_set=None, contract=None, authorization=None,
              source_files=None):
        return precommit.PreCommitExecutionInvariantGate(
            copy.deepcopy(invariant_set or self.invariant_set),
            contract=copy.deepcopy(contract or self.contract),
            authorization=copy.deepcopy(authorization or self.authorization),
            workspace=self.workspace,
            source_files=source_files,
        )

    def _evaluate(self, candidate, *, path="src/status_view.js", original=None,
                  pre_state_bytes=None, **kwargs):
        if original is None and path == "src/status_view.js":
            original = self.original
        if pre_state_bytes is None and path == "src/status_view.js":
            pre_state_bytes = self.original_bytes
        return self._gate().evaluate(
            path, candidate, original_content=original,
            pre_state_bytes=pre_state_bytes, **kwargs,
        )

    def _activate_mini_tools(self):
        if self._mini_saved is not None:
            return
        self._mini_saved = {
            "WORKSPACE": mini.WORKSPACE,
            "RUN": mini.RUN,
            "RUN_ID": mini.RUN_ID,
            "ACTIVE_TOOL_CONTRACT": mini.ACTIVE_TOOL_CONTRACT,
            "ACTIVE_TRANSACTION": mini.ACTIVE_TRANSACTION,
        }
        mini.WORKSPACE = self.workspace
        mini.RUN_ID = "v25-5-test"
        mini.RUN = {
            "stage6c_enabled": True,
            "execution_invariant_set": copy.deepcopy(self.invariant_set),
            "execution_authorization": copy.deepcopy(self.authorization),
            "precommit_invariant_audits": [],
            "precommit_invariant_gate_calls": 0,
            "precommit_invariant_gate_rejections": 0,
        }
        mini.ACTIVE_TOOL_CONTRACT = {
            "execution_contract_id": self.contract.get("execution_contract_id"),
            "execution_contract": copy.deepcopy(self.contract),
        }
        mini.ACTIVE_TRANSACTION = None

    def _restore_mini_tools(self):
        if self._mini_saved is None:
            return
        saved = self._mini_saved
        mini.WORKSPACE = saved["WORKSPACE"]
        mini.RUN = saved["RUN"]
        mini.RUN_ID = saved["RUN_ID"]
        mini.ACTIVE_TOOL_CONTRACT = saved["ACTIVE_TOOL_CONTRACT"]
        mini.ACTIVE_TRANSACTION = saved["ACTIVE_TRANSACTION"]
        self._mini_saved = None

    def _synthetic_set(self, *, authorized=False, with_owner=False,
                       with_interface=False, with_dnt=False):
        view = """function showMode(controller) {
  return controller.isActive() ? 'On' : 'Off';
}
module.exports = { showMode };
"""
        consumer = """const assert = require('assert/strict');
assert.equal(showMode({}), 'Off');
assert.equal(showMode({}), 'On');
"""
        controller = """class ModeController {
  constructor() { this.active = false; }
  toggle() { this.active = !this.active; return this.active; }
}
module.exports = { ModeController };
"""
        evidence = [
            {"evidence_id": "ALT-SOURCE", "path": "src/view.js", "symbol": "showMode", "source_kind": "SOURCE"},
            {"evidence_id": "ALT-TEST", "path": "tests/view.test.js", "symbol": "showMode", "source_kind": "TEST"},
        ]
        files = {"src/view.js": view, "tests/view.test.js": consumer}
        contract = {
            "allowed_mutation_paths": ["src/view.js"],
            "allowed_inspection_paths": ["src/view.js", "tests/view.test.js"],
            "global_do_not_touch": [],
            "interfaces_to_reuse": [],
            "repository_evidence_ids": ["ALT-SOURCE", "ALT-TEST"],
        }
        if with_owner:
            evidence.append({
                "evidence_id": "ALT-OWNER", "path": "src/controller.js",
                "symbol": "ModeController", "source_kind": "SOURCE",
                "role": "STATE_OWNER", "structured_relations": ["state_owner"],
            })
            files["src/controller.js"] = controller
        if with_interface:
            evidence.append({
                "evidence_id": "ALT-INTERFACE", "path": "src/controller.js",
                "symbol": "ModeController.toggle", "source_kind": "SOURCE",
            })
            files["src/controller.js"] = controller
            contract["interfaces_to_reuse"] = ["ModeController.toggle"]
        if with_dnt:
            evidence.append({
                "evidence_id": "ALT-DNT", "path": "src/controller.js",
                "symbol": "ModeController", "source_kind": "SOURCE",
            })
            files["src/controller.js"] = controller
            contract["global_do_not_touch"] = ["src/controller.js"]
        plan = {
            "requirements": ["add an additive mode indicator"],
            "authorized_interface_changes": ([{
                "symbol": "showMode", "path": "src/view.js", "authorized": True,
            }] if authorized else []),
        }
        built = invariants.build_execution_invariant_set(
            contract, approved_plan=plan, source_files=files,
            repository_evidence=evidence,
        )
        bound_contract = copy.deepcopy(contract)
        bound_contract["execution_invariant_set_hash"] = built.get("invariant_set_hash")
        bound_contract["execution_invariant_ids"] = list(built.get("invariant_ids", []) or [])
        bound_authorization = {
            "execution_invariant_set_hash": built.get("invariant_set_hash"),
            "execution_invariant_ids": list(built.get("invariant_ids", []) or []),
        }
        return built, bound_contract, bound_authorization, files

    def test_latest_live_paused_output_is_rejected(self):
        audit = self._evaluate(self.original.replace("'Paused'", "'Paused [PAUSED INDICATOR]'"))
        self.assertFalse(audit["allowed"])
        self.assertEqual(audit["status"], invariants.EXECUTION_INVARIANT_MUTATION_VIOLATION)
        self.assertTrue(any(item["type"] == invariants.EXACT_EXISTING_OUTPUT for item in audit["violations"]))

    def test_latest_live_replay_keeps_exact_original_hash(self):
        self._activate_mini_tools()
        result = mini.edit_file(
            "src/status_view.js",
            "return pauseController.isPaused() ? 'Paused' : 'Running';",
            "return pauseController.isPaused() ? 'Paused [PAUSED INDICATOR]' : 'Running';",
        )
        self.assertIn(invariants.EXECUTION_INVARIANT_MUTATION_VIOLATION, result)
        self.assertEqual(hashlib.sha256(self.status_path.read_bytes()).hexdigest(), EXPECTED_STATUS_VIEW_HASH)
        self.assertFalse((self.workspace / ".agent_backups").exists())

    def test_object_return_replay_reports_return_shape(self):
        audit = self._evaluate(self._object_candidate(self.original))
        self.assertFalse(audit["allowed"])
        self.assertIn(invariants.RETURN_SHAPE, {item["type"] for item in audit["violations"]})

    def test_signature_removal_is_rejected(self):
        candidate = self.original.replace("function renderStatus", "function renamedStatus")
        audit = self._evaluate(candidate)
        self.assertFalse(audit["allowed"])
        self.assertIn(invariants.FUNCTION_SIGNATURE, {item["type"] for item in audit["violations"]})

    def test_exact_output_drift_is_rejected(self):
        audit = self._evaluate(self.original.replace("'Running'", "'Started'"))
        self.assertFalse(audit["allowed"])
        self.assertIn(invariants.EXACT_EXISTING_OUTPUT, {item["type"] for item in audit["violations"]})

    def test_consumer_expectation_drift_is_rejected(self):
        path = "tests/status_view.test.js"
        original = (self.workspace / path).read_text(encoding="utf-8")
        candidate = original.replace("assert.equal(renderStatus(pauseController), 'Paused');", "assert.equal(renderStatus(pauseController), 'Changed');")
        audit = self._gate().evaluate(
            path, candidate, original_content=original,
            pre_state_bytes=(self.workspace / path).read_bytes(),
        )
        self.assertFalse(audit["allowed"])
        self.assertIn(invariants.CONSUMER_EXPECTATION, {item["type"] for item in audit["violations"]})

    def test_state_owner_drift_is_rejected_when_evidence_binds_owner(self):
        built, contract, authorization, files = self._synthetic_set(with_owner=True)
        candidate = files["src/controller.js"].replace("class ModeController", "class OtherController")
        audit = precommit.PreCommitExecutionInvariantGate(
            built, contract=None, authorization=authorization, source_files=files,
        ).evaluate(
            "src/controller.js", candidate,
            original_content=files["src/controller.js"],
        )
        self.assertFalse(audit["allowed"])
        self.assertIn(invariants.STATE_OWNER, {item["type"] for item in audit["violations"]})

    def test_required_interface_reuse_drift_is_rejected_when_detectable(self):
        built, _contract, authorization, files = self._synthetic_set(with_interface=True)
        candidate = files["src/controller.js"].replace("toggle()", "renamed()")
        audit = precommit.PreCommitExecutionInvariantGate(
            built, contract=None, authorization=authorization, source_files=files,
        ).evaluate(
            "src/controller.js", candidate,
            original_content=files["src/controller.js"],
        )
        self.assertFalse(audit["allowed"])
        self.assertIn(invariants.REQUIRED_INTERFACE_REUSE, {item["type"] for item in audit["violations"]})

    def test_additive_sibling_function_is_allowed(self):
        audit = self._evaluate(self._additive_candidate(self.original))
        self.assertTrue(audit["allowed"], audit)

    def test_additive_export_is_allowed(self):
        candidate = self.original.replace(
            "module.exports = { renderStatus };",
            "module.exports = { renderStatus, renderPauseIndicator };",
        )
        audit = self._evaluate(candidate)
        self.assertTrue(audit["allowed"], audit)

    def test_known_good_additive_candidate_passes_legacy_tests(self):
        candidate = self._additive_candidate(self.original)
        audit = self._evaluate(candidate)
        self.assertTrue(audit["allowed"], audit)
        self.status_path.write_text(candidate, encoding="utf-8")
        for relative in (
            "tests/input.test.js", "tests/pause_flow.integration.test.js", "tests/status_view.test.js",
        ):
            completed = subprocess.run(
                ["node", str(self.workspace / relative)], cwd=self.workspace,
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_known_good_additive_candidate_passes_direct_oracle(self):
        self.status_path.write_text(self._additive_candidate(self.original), encoding="utf-8")
        oracle = self.oracle_source.get("oracle", {})
        observable = self.oracle_source.get("observable_contract", {})
        result = remediation.execute_direct_behavior_oracle(
            oracle, self.workspace, observable_contract=observable,
        )
        self.assertTrue(result.get("valid"), result)
        self.assertEqual(result.get("oracle_hash"), EXPECTED_DIRECT_ORACLE_HASH)

    def test_unrelated_symbol_change_is_allowed(self):
        source = """function showMode(controller) {
  return controller.isActive() ? 'On' : 'Off';
}
function helper() { return 'old'; }
module.exports = { showMode, helper };
"""
        consumer = "const assert = require('assert/strict'); assert.equal(showMode({}), 'Off'); assert.equal(showMode({}), 'On');"
        built, contract, authorization, files = self._synthetic_set()
        files = {"src/view.js": source, "tests/view.test.js": consumer}
        evidence = [
            {"evidence_id": "S-SOURCE", "path": "src/view.js", "symbol": "showMode", "source_kind": "SOURCE"},
            {"evidence_id": "S-TEST", "path": "tests/view.test.js", "symbol": "showMode", "source_kind": "TEST"},
        ]
        built = invariants.build_execution_invariant_set(
            {"allowed_mutation_paths": ["src/view.js"], "allowed_inspection_paths": ["tests/view.test.js"]},
            source_files=files, repository_evidence=evidence,
        )
        contract = {"allowed_mutation_paths": ["src/view.js"], "allowed_inspection_paths": ["tests/view.test.js"], "execution_invariant_set_hash": built["invariant_set_hash"], "execution_invariant_ids": built["invariant_ids"]}
        authorization = {"execution_invariant_set_hash": built["invariant_set_hash"], "execution_invariant_ids": built["invariant_ids"]}
        candidate = source.replace("return 'old';", "return 'new';")
        audit = precommit.PreCommitExecutionInvariantGate(
            built, contract=contract, authorization=authorization,
            source_files=files,
        ).evaluate("src/view.js", candidate, original_content=source)
        self.assertTrue(audit["allowed"], audit)

    def test_change_authorized_semantic_change_is_allowed(self):
        built, contract, authorization, files = self._synthetic_set(authorized=True)
        source = files["src/view.js"]
        candidate = source.replace(
            "return controller.isActive() ? 'On' : 'Off';",
            "return controller.isActive() ? { mode: 'On' } : { mode: 'Off' };",
        )
        audit = precommit.PreCommitExecutionInvariantGate(
            built, contract=contract, authorization=authorization, source_files=files,
        ).evaluate("src/view.js", candidate, original_content=source)
        self.assertTrue(audit["allowed"], audit)
        self.assertTrue(all(
            value == invariants.CHANGE_AUTHORIZED
            for value in audit["classifications"].values()
            if value
        ))

    def test_preserve_classification_is_required_for_blocking(self):
        built, contract, authorization, files = self._synthetic_set()
        changed = copy.deepcopy(built)
        for item in changed["invariants"]:
            item["classification"] = invariants.CHANGE_AUTHORIZED
        changed["invariant_set_hash"] = invariants.canonical_invariant_set_hash(changed)
        authorization["execution_invariant_set_hash"] = changed["invariant_set_hash"]
        authorization["execution_invariant_ids"] = list(changed["invariant_ids"])
        contract["execution_invariant_set_hash"] = changed["invariant_set_hash"]
        contract["execution_invariant_ids"] = list(changed["invariant_ids"])
        candidate = files["src/view.js"].replace("'Off'", "'Off [X]'")
        audit = precommit.PreCommitExecutionInvariantGate(
            changed, contract=contract, authorization=authorization, source_files=files,
        ).evaluate("src/view.js", candidate, original_content=files["src/view.js"])
        self.assertTrue(audit["allowed"], audit)

    def test_mutation_scope_alone_does_not_grant_semantic_change_authority(self):
        built, contract, authorization, files = self._synthetic_set()
        candidate = files["src/view.js"].replace("'Off'", "'Off [X]'")
        audit = precommit.PreCommitExecutionInvariantGate(
            built, contract=contract, authorization=authorization, source_files=files,
        ).evaluate("src/view.js", candidate, original_content=files["src/view.js"])
        self.assertFalse(audit["allowed"])

    def test_stale_target_is_classified_before_gate(self):
        self._activate_mini_tools()
        result = mini.edit_file(
            "src/status_view.js", "text that is not present",
            "replacement",
        )
        record = mini.mutation_failure_record("edit_file", "src/status_view.js", result)
        self.assertEqual(record["category"], "STALE_TARGET")
        self.assertEqual(mini.RUN.get("precommit_invariant_gate_calls"), 0)

    def test_syntax_invalid_candidate_is_rejected_before_gate(self):
        self._activate_mini_tools()
        result = mini.edit_file(
            "src/status_view.js",
            "return pauseController.isPaused() ? 'Paused' : 'Running';",
            "return (;")
        self.assertIn("syntax validation", result)
        self.assertEqual(mini.RUN.get("precommit_invariant_gate_calls"), 0)
        self.assertEqual(self.status_path.read_bytes(), self.original_bytes)

    def test_rejected_candidate_never_commits(self):
        self._activate_mini_tools()
        before = self.status_path.read_bytes()
        result = mini.edit_file(
            "src/status_view.js",
            "return pauseController.isPaused() ? 'Paused' : 'Running';",
            "return pauseController.isPaused() ? 'Changed' : 'Running';",
        )
        self.assertIn("mutation rejected before commit", result)
        self.assertEqual(self.status_path.read_bytes(), before)

    def test_audit_records_violated_invariant_ids(self):
        audit = self._evaluate(self.original.replace("'Paused'", "'Changed'"))
        self.assertTrue(audit["violations"])
        self.assertTrue(set(item["invariant_id"] for item in audit["violations"]).issubset(set(audit["applicable_invariant_ids"])))

    def test_audit_canonical_hash_recomputes(self):
        audit = self._evaluate(self.original.replace("'Paused'", "'Changed'"))
        checked = precommit.validate_precommit_invariant_audit(audit)
        self.assertTrue(checked["valid"], checked)
        self.assertEqual(audit["canonical_hash"], precommit.canonical_precommit_invariant_audit_hash(audit))

    def test_multiple_invariant_violations_fan_into_one_artifact(self):
        audit = self._evaluate(self._object_candidate(self.original))
        self.assertFalse(audit["allowed"])
        self.assertGreaterEqual(len(audit["violations"]), 2)
        self.assertEqual(audit["status"], invariants.EXECUTION_INVARIANT_MUTATION_VIOLATION)
        self.assertTrue(audit["candidate_mutation_id"])

    def test_gate_evaluation_makes_no_model_call(self):
        with patch.object(mini, "ask_ollama", side_effect=AssertionError("model call is forbidden")):
            audit = self._evaluate(self.original.replace("'Paused'", "'Changed'"))
        self.assertEqual(audit["model_calls"], 0)
        self.assertEqual(audit["worker_calls"], 0)

    def test_gate_does_not_derive_new_authority_at_mutation_time(self):
        with patch.object(invariants, "build_execution_invariant_set", side_effect=AssertionError("no authority derivation")):
            audit = self._evaluate(self.original.replace("'Paused'", "'Changed'"))
        self.assertFalse(audit["allowed"])

    def test_gate_consumes_authorization_bound_invariant_set(self):
        wrong = copy.deepcopy(self.authorization)
        wrong["execution_invariant_set_hash"] = "0" * 64
        audit = self._gate(authorization=wrong).evaluate(
            "src/status_view.js", self.original.replace("'Paused'", "'Changed'"),
            original_content=self.original, pre_state_bytes=self.original_bytes,
        )
        self.assertFalse(audit["allowed"])
        self.assertEqual(audit["status"], invariants.EXECUTION_INVARIANT_MUTATION_VIOLATION)
        self.assertTrue(any(item["type"] == "AUTHORIZATION_BOUND_INVARIANT_SET" for item in audit["violations"]))

    def test_write_file_path_is_guarded(self):
        self._activate_mini_tools()
        result = mini.write_file("src/status_view.js", self.original.replace("'Paused'", "'Changed'"))
        self.assertIn(invariants.EXECUTION_INVARIANT_MUTATION_VIOLATION, result)
        self.assertEqual(self.status_path.read_bytes(), self.original_bytes)

    def test_edit_file_path_is_guarded(self):
        self._activate_mini_tools()
        result = mini.edit_file(
            "src/status_view.js", "'Paused'", "'Changed'",
        )
        self.assertIn(invariants.EXECUTION_INVARIANT_MUTATION_VIOLATION, result)
        self.assertEqual(self.status_path.read_bytes(), self.original_bytes)

    def test_edit_file_range_path_is_guarded(self):
        self._activate_mini_tools()
        lines = self.original.splitlines()
        line = next(index for index, value in enumerate(lines, 1) if "'Paused'" in value)
        result = mini.edit_file_range(
            "src/status_view.js", line, line,
            "  return pauseController.isPaused() ? 'Changed' : 'Running';",
        )
        self.assertIn(invariants.EXECUTION_INVARIANT_MUTATION_VIOLATION, result)
        self.assertEqual(self.status_path.read_bytes(), self.original_bytes)

    def test_generic_alternate_symbol_drift_is_rejected(self):
        built, contract, authorization, files = self._synthetic_set()
        candidate = files["src/view.js"].replace("'Off'", "'Off [X]'")
        audit = precommit.PreCommitExecutionInvariantGate(
            built, contract=contract, authorization=authorization, source_files=files,
        ).evaluate("src/view.js", candidate, original_content=files["src/view.js"])
        self.assertFalse(audit["allowed"])
        self.assertIn("showMode", {item["symbol"] for item in audit["violations"]})

    def test_generic_alternate_symbol_additive_sibling_is_legal(self):
        built, contract, authorization, files = self._synthetic_set()
        candidate = files["src/view.js"].replace(
            "module.exports = { showMode };",
            "function showModeIndicator(controller) { return controller.isActive() ? 'On!' : ''; }\nmodule.exports = { showMode, showModeIndicator };",
        )
        audit = precommit.PreCommitExecutionInvariantGate(
            built, contract=contract, authorization=authorization, source_files=files,
        ).evaluate("src/view.js", candidate, original_content=files["src/view.js"])
        self.assertTrue(audit["allowed"], audit)

    def test_dnt_status_is_separate_from_semantic_violation(self):
        built, _contract, authorization, files = self._synthetic_set(with_dnt=True)
        candidate = files["src/controller.js"] + "\n// candidate"
        audit = precommit.PreCommitExecutionInvariantGate(
            built, contract=None, authorization=authorization, source_files=files,
        ).evaluate("src/controller.js", candidate, original_content=files["src/controller.js"])
        self.assertEqual(audit["status"], precommit.PRECOMMIT_DNT_VIOLATION)
        self.assertNotEqual(audit["status"], invariants.EXECUTION_INVARIANT_MUTATION_VIOLATION)

    def test_worker_packet_remains_bounded_and_invariant_visible(self):
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
        self.assertLessEqual(len(packet), 4200)
        self.assertIn("CURRENT EXECUTION INVARIANTS", packet)
        self.assertIn("primitive string", packet)

    def test_plan_hash_and_id_are_unchanged_in_latest_live_receipt(self):
        receipt = _load(LATEST_LIVE_ROOT / "artifacts" / "approval_request.json", {})
        self.assertEqual(receipt.get("canonical_plan_id"), EXPECTED_PLAN_ID)
        self.assertEqual(receipt.get("canonical_plan_hash"), EXPECTED_PLAN_HASH)

    def test_verification_digest_is_unchanged(self):
        request = _load(LATEST_LIVE_ROOT / "artifacts" / "approval_request.json", {})
        binding = request.get("binding", {})
        self.assertEqual(binding.get("verification_contract_digest"), "98a8ed7513a7f3da21a3e5062712890ad2f499c390070e7cbaa3f57b2b655b51")

    def test_coverage_and_oracle_hashes_are_unchanged(self):
        coverage = _load(LATEST_LIVE_ROOT / "artifacts" / "execution_time_verification_coverage.json", {})
        self.assertEqual(coverage.get("coverage_hash"), EXPECTED_COVERAGE_HASH)
        source = _load(LATEST_LIVE_ROOT / "artifacts" / "direct_behavior_oracle_source.json", {})
        self.assertEqual((source.get("oracle") or {}).get("oracle_hash"), EXPECTED_DIRECT_ORACLE_HASH)

    def test_stage5a_exact_routing_has_no_required_null_route(self):
        routes = _load(LATEST_LIVE_ROOT / "artifacts" / "stage5a_route_bindings.json", {})
        self.assertEqual(routes.get("route_validation", {}).get("checked_routes"), 6)
        self.assertEqual(routes.get("route_validation", {}).get("mandatory_routes"), 5)
        self.assertTrue(all(
            item.get("target") is not None
            for item in routes.get("routes", [])
            if item.get("required") is True
        ))

    def test_approval_receipt_historical_integrity_is_unchanged(self):
        request = _load(LATEST_LIVE_ROOT / "artifacts" / "approval_request.json", {})
        receipt = _load(LATEST_LIVE_ROOT / "artifacts" / "approval_receipt.json", {})
        self.assertEqual(receipt.get("approval_request_hash"), request.get("request_hash"))
        self.assertEqual(receipt.get("canonical_plan_hash"), request.get("canonical_plan_hash"))
        self.assertTrue(receipt.get("receipt_hash"))

    def test_positive_provider_free_lifecycle_accepts_illegal_then_legal_sequence(self):
        # The focused direct tooling replay below is the lifecycle's mutation
        # seam; the full positive lifecycle is covered by the inherited V25.2
        # provider-free execution test and the dedicated replay tests here.
        self._activate_mini_tools()
        illegal = mini.edit_file(
            "src/status_view.js",
            "'Paused'", "'Paused [PAUSED INDICATOR]'",
        )
        inspected = mini.read_file("src/status_view.js")
        legal = mini.edit_file(
            "src/status_view.js",
            "module.exports = { renderStatus };",
            """function renderPauseIndicator(pauseController) {
  return pauseController.isPaused() ? '⏸ Paused' : '▶ Running';
}

module.exports = { renderStatus, renderPauseIndicator };""",
        )
        self.assertIn("mutation rejected before commit", illegal)
        self.assertEqual(inspected, self.original)
        self.assertIn("edited file", legal)
        self.assertNotEqual(self.status_path.read_bytes(), self.original_bytes)
        self.assertEqual(mini.RUN["precommit_invariant_gate_rejections"], 1)

    def test_repeated_illegal_edits_never_corrupt_subject(self):
        self._activate_mini_tools()
        for _ in range(4):
            result = mini.edit_file(
                "src/status_view.js", "'Paused'", "'Paused [PAUSED INDICATOR]'",
            )
            self.assertIn(invariants.EXECUTION_INVARIANT_MUTATION_VIOLATION, result)
        self.assertEqual(self.status_path.read_bytes(), self.original_bytes)
        self.assertEqual(mini.RUN["precommit_invariant_gate_rejections"], 4)

    def test_historical_brain_and_subject_are_untouched_by_replays(self):
        self.assertEqual(HISTORICAL_DB.read_bytes(), self.historical_bytes)
        self.assertEqual((FIXTURE_ROOT / "src/status_view.js").read_bytes(), self.original_bytes)

    def test_architecture_self_test_remains_provider_free(self):
        result = mini.run_stage6c_b_self_test(
            artifact_root=PLANNING_ROOT,
            brain_database_path=HISTORICAL_DB,
            fixture_root=FIXTURE_ROOT,
        )
        self.assertTrue(result.get("passed"), result)
        self.assertEqual(result.get("model_calls"), 0)
        self.assertEqual(result.get("worker_calls"), 1)
        self.assertEqual(result.get("historical_brain_writes"), 0)
        self.assertEqual(result.get("repository_subject_mutations"), 0)

    def test_legacy_v25_2_invariant_set_remains_immutable_and_valid(self):
        self.assertEqual(self.invariant_set["status"], invariants.VALID)
        self.assertEqual(self.invariant_set["invariant_set_hash"], invariants.canonical_invariant_set_hash(self.invariant_set))
        with self.assertRaises(TypeError):
            self.invariant_set["status"] = "tampered"

    def test_no_fixture_specific_literals_are_in_production_gate(self):
        production = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "hivo" / "execution_invariants.py", ROOT / "hivo" / "precommit_invariant_gate.py")
        )
        for literal in ("renderStatus", "renderPauseIndicator", "status_view.js", "Running", "Paused"):
            self.assertNotIn(literal, production)

    def test_audit_feedback_is_compact_and_deterministic(self):
        audit = self._evaluate(self.original.replace("'Paused'", "'Changed'"), mutation_id="EDIT-1")
        feedback = precommit.format_precommit_invariant_feedback(audit)
        self.assertIn("mutation rejected before commit", feedback)
        self.assertIn("candidate_mutation_id=EDIT-1", feedback)
        self.assertIn("canonical_hash=", feedback)
        self.assertLess(len(feedback), 1800)

    def test_safe_whitespace_equivalence_is_allowed(self):
        candidate = self.original.replace(
            "function renderStatus(pauseController)",
            "function renderStatus( pauseController )",
        )
        audit = self._evaluate(candidate)
        self.assertTrue(audit["allowed"], audit)

    def test_unsupported_semantics_fail_closed(self):
        candidate = self.original.replace(
            "return pauseController.isPaused() ? 'Paused' : 'Running';",
            "return pauseController.isPaused() ? String('Paused') : 'Running';",
        )
        audit = self._evaluate(candidate)
        self.assertFalse(audit["allowed"])
        self.assertTrue(audit["violations"])

    def test_change_authorized_does_not_freeze_unrelated_preserved_symbol(self):
        built, contract, authorization, files = self._synthetic_set(authorized=True)
        source = files["src/view.js"] + "\nfunction helper() { return 'old'; }\n"
        candidate = source.replace("'old'", "'new'")
        audit = precommit.PreCommitExecutionInvariantGate(
            built, contract=contract, authorization=authorization,
            source_files={**files, "src/view.js": source},
        ).evaluate("src/view.js", candidate, original_content=source)
        self.assertTrue(audit["allowed"], audit)

    def test_authority_set_hash_is_present_in_audit(self):
        audit = self._evaluate(self.original)
        self.assertEqual(audit["authority_set_hash"], self.invariant_set["invariant_set_hash"])
        self.assertEqual(audit["status"], precommit.PRECOMMIT_ALLOWED)

    def test_write_backup_is_deferred_until_after_gate(self):
        self._activate_mini_tools()
        mini.write_file("src/status_view.js", self.original.replace("'Paused'", "'Changed'"))
        self.assertFalse((self.workspace / ".agent_backups").exists())

    def test_worker_and_model_accounting_stay_zero_in_audit(self):
        audit = self._evaluate(self.original)
        self.assertEqual(audit.get("model_calls"), 0)
        self.assertEqual(audit.get("worker_calls"), 0)


if __name__ == "__main__":
    unittest.main()
