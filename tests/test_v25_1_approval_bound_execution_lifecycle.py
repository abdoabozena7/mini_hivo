"""Provider-free V25.1 approval-bound execution lifecycle tests."""

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
from hivo import approval_bound_execution as stage6cb
from hivo import execution_contracts as stage4
from hivo import integration_gate
from hivo.memory import MemoryStore


ROOT = Path(__file__).resolve().parents[1]
PLANNING_ROOT = ROOT / "output" / "hivo-v24-4-6-stage6b-planning-live-1"
FIXTURE_ROOT = ROOT / "output" / "hivo-v25-stage6c-b-approved-execution-live-1"
HISTORICAL_DB = ROOT / "output" / "hivo-v22-stage5c-fresh-receipts-live-1" / ".hivo" / "memory.sqlite3"
EXPECTED_BRAIN_HASH = "8eac670a83eeddb30528ebd3ad5032dabc6f6d1a3fb97b65b4600964b1b434bb"


def _load(root: Path, name: str, fallback=None):
    try:
        with (root / name).open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return copy.deepcopy(fallback)


class ApprovalBoundExecutionLifecycleTests(unittest.TestCase):
    """The Worker seam and verifier are deterministic; no provider is used."""

    @classmethod
    def setUpClass(cls):
        cls.plan = _load(PLANNING_ROOT, "final_plan.json", {})
        cls.context = _load(PLANNING_ROOT, "verified_planning_context.json", {})
        cls.freshness = _load(PLANNING_ROOT, "planning_context_freshness.json", {})
        cls.plan_validation = _load(PLANNING_ROOT, "plan_validation.json", {})
        cls.contractability = _load(PLANNING_ROOT, "stage4_contractability_audit.json", {})
        cls.reconciliation = _load(
            PLANNING_ROOT, "challenger_reconciliation.json",
            cls.plan.get("challenger_reconciliation", {}),
        )
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
            "planning_context_freshness": cls.freshness,
            "plan_validation": cls.plan_validation,
            "stage4_contractability_audit": cls.contractability,
            "challenger_reconciliation": cls.reconciliation,
            "terminal_state": authority.PLAN_APPROVAL_REQUIRED,
            "source_repository_fingerprint": cls.context.get("source_repository_fingerprint", {}),
        }
        cls.request = authority.create_plan_approval_request(cls.plan, cls.state)
        cls.event = authority.make_test_explicit_user_approval_event(cls.request)
        cls.receipt = authority.record_plan_approval(cls.request, cls.event)
        cls.revalidation = authority.pre_execution_approval_revalidation(
            cls.receipt, cls.plan, cls.state, request=cls.request,
        )
        cls.authorization = authority.create_approved_execution_authorization(
            cls.receipt, cls.revalidation, request=cls.request,
        )
        cls.compiled = authority.compile_approval_bound_execution_contracts(
            cls.plan, cls.receipt, cls.revalidation, cls.authorization,
            request=cls.request, requirements=cls.plan.get("requirements", []),
        )
        cls.fixture_status_view = (FIXTURE_ROOT / "src/status_view.js").read_text(encoding="utf-8")

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="hivo_v25_1_execution_")
        root = Path(self.tempdir.name)
        self.workspace = root / "execution"
        self.workspace.mkdir()
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

    def _run(self, worker, *, state=None, authorization=None, verification_runner=None):
        with patch.object(mini, "ask_ollama", side_effect=AssertionError("provider must not be called")):
            return mini.run_approval_bound_execution_lifecycle(
                plan=copy.deepcopy(self.plan),
                request=copy.deepcopy(self.request),
                receipt=copy.deepcopy(self.receipt),
                revalidation=copy.deepcopy(self.revalidation),
                authorization=copy.deepcopy(authorization or self.authorization),
                memory={},
                workspace=self.workspace,
                working_brain_store=self.working_store,
                current_state=copy.deepcopy(state or self.state),
                worker_callback=worker,
                verification_runner=verification_runner,
            )

    @staticmethod
    def _approved_edit(execute_tool=None, **_kwargs):
        old = "module.exports = { renderStatus };"
        new = """function renderPauseIndicator(pauseController) {
  if (!(pauseController instanceof PauseController)) {
    throw new TypeError('a PauseController is required');
  }
  return pauseController.isPaused() ? '⏸ Paused' : '▶ Running';
}

module.exports = { renderStatus, renderPauseIndicator };"""
        result = execute_tool(
            "edit_file",
            {
                "path": "src/status_view.js", "old": old, "new": new,
                "expected_replacements": 1,
            },
        )
        return {
            "status": "done", "summary": "approved status indicator edit applied",
            "tool_evidence": [{
                "tool": "edit_file", "target": "src/status_view.js",
                "result": str(result),
            }],
        }

    def test_positive_execution_reaches_promotion_and_reentry(self):
        result, _memory = self._run(self._approved_edit)
        self.assertEqual(result.get("status"), "done")
        self.assertEqual(result.get("terminal_state"), mini.APPROVED_EXECUTION_VERIFIED_AND_PROMOTED)
        self.assertEqual(result.get("post_promotion_terminal_state"), mini.POST_PROMOTION_REENTRY_READY)
        self.assertEqual((result.get("post_promotion_reentry") or {}).get("status"), "REENTRY_READY")
        self.assertTrue((result.get("post_promotion_reentry") or {}).get("ready"))
        self.assertEqual(mini.RUN.get("approved_worker_calls"), 1)
        self.assertEqual(mini.RUN.get("approval_bound_executions_started"), 1)
        self.assertEqual(mini.RUN.get("model_calls"), 0)
        self.assertIn("PROMOTED", {
            result.get("promotion_status"), "ALREADY_PROMOTED",
        })
        self.assertTrue((self.workspace / "src/status_view.js").read_text(encoding="utf-8").find("renderPauseIndicator") >= 0)
        self.assertEqual((FIXTURE_ROOT / "src/status_view.js").read_text(encoding="utf-8"), self.fixture_status_view)
        self.assertNotEqual(self.working_store.project_brain_hash(self.context.get("project_id")), EXPECTED_BRAIN_HASH)
        self.assertEqual(HISTORICAL_DB.read_bytes(), self.historical_bytes)
        candidate = (result.get("promotion") or {}).get("candidate") or {}
        self.assertEqual((candidate.get("provenance") or {}).get("model_calls"), 0)
        self.assertFalse((candidate.get("provenance") or {}).get("raw_worker_transcript_included"))

    def test_unauthorized_and_dnt_mutations_fail_closed_without_promotion(self):
        def unauthorized(**kwargs):
            target = Path(kwargs["workspace"]) / "src/input.js"
            target.write_text(target.read_text(encoding="utf-8") + "\n// unauthorized\n", encoding="utf-8")
            return {"status": "done", "summary": "direct write", "tool_evidence": []}

        result, _ = self._run(unauthorized)
        self.assertEqual(result.get("terminal_state"), mini.UNAUTHORIZED_MUTATION)
        self.assertNotIn(result.get("promotion_status"), {"PROMOTED", "ALREADY_PROMOTED"})

        # The first fail-closed attempt is intentionally not rolled back.  A
        # fresh disposable execution root models the next independent attempt.
        self.tearDown()
        self.setUp()

        def dnt(**kwargs):
            target = Path(kwargs["workspace"]) / "src/pause_controller.js"
            target.write_text(target.read_text(encoding="utf-8") + "\n// dnt\n", encoding="utf-8")
            return {"status": "done", "summary": "direct write", "tool_evidence": []}

        result, _ = self._run(dnt)
        self.assertEqual(result.get("terminal_state"), mini.DNT_VIOLATION)
        self.assertNotIn(result.get("promotion_status"), {"PROMOTED", "ALREADY_PROMOTED"})

    def test_noop_and_verification_failure_stop_before_stage5c(self):
        def noop(**_kwargs):
            return {"status": "done", "summary": "nothing changed", "tool_evidence": []}

        result, _ = self._run(noop)
        self.assertEqual(result.get("terminal_state"), mini.WORKER_NO_APPROVED_MUTATION)
        child = (result.get("contract_results") or [{}])[0]
        self.assertEqual(mini.TASKS.get("EXEC-001", {}).get("status"), "failed")
        self.assertEqual(mini.RUN.get("verified_execution_promotions"), 0)
        self.assertEqual(child.get("status"), "failed")

        def broken(execute_tool=None, **_kwargs):
            result = execute_tool(
                "edit_file",
                {
                    "path": "src/status_view.js",
                    "old": "return pauseController.isPaused() ? 'Paused' : 'Running';",
                    "new": "return pauseController.isPaused() ? 'BROKEN' : 'BROKEN';",
                    "expected_replacements": 1,
                },
            )
            return {"status": "done", "summary": "broken edit", "tool_evidence": [{"tool": "edit_file", "target": "src/status_view.js", "result": str(result)}]}

        result, _ = self._run(broken)
        self.assertEqual(mini.TASKS.get("EXEC-001", {}).get("status"), "failed")
        self.assertEqual(mini.RUN.get("verified_execution_promotions"), 0)
        self.assertEqual(result.get("terminal_state"), mini.VERIFICATION_FAILED)

    def test_stale_subject_and_brain_are_revalidated_before_callback(self):
        self.workspace.joinpath("src/status_view.js").write_text(
            self.workspace.joinpath("src/status_view.js").read_text(encoding="utf-8") + "\n// drift\n",
            encoding="utf-8",
        )
        calls = []

        def worker(**_kwargs):
            calls.append(True)
            return self._approved_edit(**_kwargs)

        result, _ = self._run(worker)
        self.assertEqual(result.get("terminal_state"), authority.REAPPROVAL_REQUIRED)
        self.assertEqual(calls, [])

        stale_brain = copy.deepcopy(self.state)
        stale_brain["brain_hash"] = "stale-brain"
        calls = []
        result, _ = self._run(worker, state=stale_brain)
        self.assertEqual(result.get("terminal_state"), authority.REAPPROVAL_REQUIRED)
        self.assertEqual(calls, [])

    def test_contract_authorization_and_interface_drift_fail_last_moment_audit(self):
        contract = copy.deepcopy(self.compiled["contracts"][0])
        contract["allowed_mutation_paths"] = ["src/input.js"]
        contract["contract_hash"] = stage4.deterministic_hash(stage4._without(contract, "contract_hash"))
        audit = stage6cb.last_moment_authorization_audit(
            authorization=self.authorization, receipt=self.receipt,
            revalidation=self.revalidation, request=self.request,
            plan=self.plan, current_state=self.state,
            contracts=[contract], graph=self.compiled["graph"], contract=contract,
            workspace=self.workspace, store=self.working_store,
            project_id=self.context.get("project_id"),
        )
        self.assertFalse(audit.get("allowed"))
        self.assertEqual(audit.get("status"), stage6cb.WORKER_AUTHORIZATION_INVALID)

        tampered_authorization = copy.deepcopy(self.authorization)
        tampered_authorization["authorization_hash"] = "tampered"
        result, _ = self._run(self._approved_edit, authorization=tampered_authorization)
        self.assertEqual(result.get("status"), "blocked")
        self.assertEqual(result.get("worker_calls"), 0)

        interface_contract = copy.deepcopy(self.compiled["contracts"][0])
        interface_contract["interfaces_to_reuse"] = ["Other.togglePause"]
        interface_contract["contract_hash"] = stage4.deterministic_hash(
            stage4._without(interface_contract, "contract_hash")
        )
        interface_audit = stage6cb.last_moment_authorization_audit(
            authorization=self.authorization, receipt=self.receipt,
            revalidation=self.revalidation, request=self.request,
            plan=self.plan, current_state=self.state,
            contracts=[interface_contract], graph=self.compiled["graph"],
            contract=interface_contract, workspace=self.workspace,
            store=self.working_store, project_id=self.context.get("project_id"),
        )
        self.assertFalse(interface_audit.get("allowed"))

    def test_missing_authorization_and_missing_working_brain_block_without_worker(self):
        with patch.object(mini, "ask_ollama", side_effect=AssertionError("provider must not be called")):
            missing, _ = mini.run_approval_bound_execution_lifecycle(
                plan=copy.deepcopy(self.plan), request=copy.deepcopy(self.request),
                receipt=copy.deepcopy(self.receipt),
                revalidation=copy.deepcopy(self.revalidation), authorization=None,
                memory={}, workspace=self.workspace,
                working_brain_store=self.working_store,
                current_state=copy.deepcopy(self.state), worker_callback=self._approved_edit,
            )
            no_brain, _ = mini.run_approval_bound_execution_lifecycle(
                plan=copy.deepcopy(self.plan), request=copy.deepcopy(self.request),
                receipt=copy.deepcopy(self.receipt),
                revalidation=copy.deepcopy(self.revalidation),
                authorization=copy.deepcopy(self.authorization), memory={},
                workspace=self.workspace, working_brain_store=None,
                current_state=copy.deepcopy(self.state), worker_callback=self._approved_edit,
            )
        self.assertEqual(missing.get("terminal_state"), mini.WORKER_AUTHORIZATION_INVALID)
        self.assertEqual(no_brain.get("terminal_state"), mini.WORKER_AUTHORIZATION_INVALID)

    def test_worker_context_is_bounded_and_authoritative(self):
        captured = {}

        def worker(execute_tool=None, worker_context=None, **_kwargs):
            captured["context"] = worker_context
            return self._approved_edit(execute_tool=execute_tool)

        result, _ = self._run(worker)
        self.assertEqual(result.get("status"), "done")
        context = captured.get("context", "")
        self.assertLessEqual(len(context), mini.MAX_WORKER_MISSION_CHARS)
        self.assertIn("EXEC-001", context)
        self.assertIn("src/status_view.js", context)
        self.assertNotIn("full_project_brain", context)
        self.assertNotIn("raw Challenger", context)
        self.assertNotIn("approval conversation", context.casefold())

    def test_created_and_deleted_unapproved_files_are_mutations(self):
        def create_file(**kwargs):
            Path(kwargs["workspace"], "src", "not-approved.js").write_text(
                "module.exports = {};\n", encoding="utf-8",
            )
            return {"status": "done", "summary": "created file", "tool_evidence": []}

        result, _ = self._run(create_file)
        self.assertEqual(result.get("terminal_state"), mini.UNAUTHORIZED_MUTATION)

        # This is a separate attempt because the lifecycle intentionally does
        # not add rollback or mutation recovery.
        self.tearDown()
        self.setUp()

        def delete_file(**kwargs):
            Path(kwargs["workspace"], "src", "input.js").unlink()
            return {"status": "done", "summary": "deleted file", "tool_evidence": []}

        result, _ = self._run(delete_file)
        self.assertEqual(result.get("terminal_state"), mini.UNAUTHORIZED_MUTATION)

    def test_execution_start_receipt_is_hashed_over_authority_and_pre_state(self):
        contract = self.compiled["contracts"][0]
        subject = integration_gate.fingerprint_dependency_paths(
            self.workspace,
            sorted(set(contract["allowed_inspection_paths"] + contract["allowed_mutation_paths"] + contract["global_do_not_touch"])),
        )
        start = stage6cb.create_execution_start_receipt(
            self.authorization, self.receipt, self.plan, contract,
            pre_subject_hash=subject["hash"], pre_brain_hash=EXPECTED_BRAIN_HASH,
            workspace=self.workspace,
        )
        self.assertTrue(stage6cb.validate_execution_start_receipt(start)["valid"])
        self.assertEqual(start["authorization_hash"], self.authorization["authorization_hash"])
        self.assertEqual(start["approval_receipt_hash"], self.receipt["receipt_hash"])
        self.assertEqual(start["execution_contract_hash"], contract["contract_hash"])
        self.assertEqual(start["pre_worker_subject_hash"], subject["hash"])
        changed_auth = copy.deepcopy(self.authorization)
        changed_auth["authorization_hash"] = "changed-auth"
        changed = stage6cb.create_execution_start_receipt(
            changed_auth, self.receipt, self.plan, contract,
            pre_subject_hash=subject["hash"], pre_brain_hash=EXPECTED_BRAIN_HASH,
            workspace=self.workspace,
        )
        changed_contract = copy.deepcopy(contract)
        changed_contract["contract_hash"] = "changed-contract"
        changed_contract_receipt = stage6cb.create_execution_start_receipt(
            self.authorization, self.receipt, self.plan, changed_contract,
            pre_subject_hash=subject["hash"], pre_brain_hash=EXPECTED_BRAIN_HASH,
            workspace=self.workspace,
        )
        changed_subject = stage6cb.create_execution_start_receipt(
            self.authorization, self.receipt, self.plan, contract,
            pre_subject_hash="changed-subject", pre_brain_hash=EXPECTED_BRAIN_HASH,
            workspace=self.workspace,
        )
        self.assertNotEqual(start["receipt_hash"], changed["receipt_hash"])
        self.assertNotEqual(start["receipt_hash"], changed_contract_receipt["receipt_hash"])
        self.assertNotEqual(start["receipt_hash"], changed_subject["receipt_hash"])

    def test_worker_self_report_is_not_verification(self):
        def approved_without_verification(**kwargs):
            # The callback claims success but does not change the subject.
            return {"status": "done", "summary": "tests passed", "tool_evidence": [{
                "tool": "run_command", "target": "tests/status_view.test.js",
                "result": "[exit_code=0] claimed pass",
            }]}

        result, _ = self._run(approved_without_verification)
        self.assertEqual(result.get("terminal_state"), mini.WORKER_NO_APPROVED_MUTATION)
        self.assertEqual(mini.RUN.get("verified_execution_promotions"), 0)

    def test_verifier_claim_without_actual_evidence_cannot_pass(self):
        result, _ = self._run(
            self._approved_edit,
            verification_runner=lambda **_kwargs: {"passed": True},
        )
        self.assertEqual(result.get("terminal_state"), mini.VERIFICATION_FAILED)
        self.assertEqual(mini.RUN.get("verified_execution_promotions"), 0)

    def test_execution_does_not_rerun_planner_challenger_or_reviser(self):
        calls = []

        def forbidden(*_args, **_kwargs):
            calls.append(True)
            raise AssertionError("planning roles must not run during execution")

        with patch.object(mini, "decide_task_fit", side_effect=forbidden), \
                patch.object(mini, "decompose_task", side_effect=forbidden):
            result, _ = self._run(self._approved_edit)
        self.assertEqual(result.get("status"), "done")
        self.assertEqual(calls, [])
        self.assertEqual(mini.RUN.get("impact_planner_calls"), 0)
        self.assertEqual(mini.RUN.get("impact_challenger_calls"), 0)
        self.assertEqual(mini.RUN.get("impact_plan_revision_calls"), 0)

    def test_stage6c_b_architecture_self_test_is_provider_free(self):
        self.assertTrue(mini.run_stage6c_b_self_test()["passed"])


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
