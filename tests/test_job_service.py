"""Callable API contract checks; no subprocess, Docker, or provider."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import Mock, patch

from hivo.job_service import JobService


REVISION = "a" * 40
PLAN = "b" * 64
LIMITS = {"max_model_calls": 18, "max_tool_calls": 25, "max_elapsed_seconds": 120, "max_attempts": 4}
USAGE = {"model_calls": 2, "tool_calls": 3, "elapsed_seconds": 4}
APPROVAL = {
    "decision_id": "plan-1",
    "kind": "approval",
    "plan_summary": "Change only the successful message.",
    "plan_hash": PLAN,
}
CANDIDATE = {"status": "candidate", "usage": USAGE, "evidence": {"plan_hash": PLAN}}
DIFF = "--- a/toy.py\n+++ b/toy.py\n@@ -1 +1 @@\n-print('old')\n+print('new')\n"
RECEIPT = {
    "base_revision": REVISION,
    "diff": DIFF,
    "changed_paths": ["toy.py"],
    "patch_sha256": sha256(DIFF.encode()).hexdigest(),
    "workspace_sha256": "c" * 64,
    "checks": [{"check_id": "valid-and-invalid-input", "passed": True}],
}


def fixture_job(job_id="job-1", project_id="toy", **overrides):
    return {
        "job_id": job_id,
        "project_id": project_id,
        "base_revision": REVISION,
        "prompt": "private prompt",
        "idempotency_key": "private key",
        "attempt_id": None,
        "status": "queued",
        "decision_request": None,
        "decision": None,
        "checkpoint": {"private": "do not project"},
        "limits": dict(LIMITS),
        "failure_code": None,
        "result": None,
        **overrides,
    }


class JobServiceTests(unittest.TestCase):
    def setUp(self):
        self.store = Mock(spec=["submit", "get", "events", "claim", "decide", "cancel", "retry",
                                "active_attempts", "recover", "finish"])
        self.runtime = Mock(spec=["run", "cancel", "stopped"])
        self.fixture_root = Path(__file__).resolve().parents[1] / ".runtime-proof"
        self.projects = {"toy": self.fixture_root / "registered", "other": self.fixture_root / "other"}
        self.base, self.work, self.frozen = [
            self.fixture_root / part for part in ("base", "work", "frozen")
        ]
        self.authorize = Mock(side_effect=lambda project, actor: (project, actor) == ("toy", "operator"))
        self.checker = Mock(return_value=deepcopy(RECEIPT["checks"]))
        self.service = JobService(self.store, self.runtime, self.projects, self.checker,
                                  authorize_decision=self.authorize)
        self.rows = {"job-1": fixture_job()}
        self.store.get.side_effect = lambda job_id: deepcopy(self.rows[job_id])
        self.store.finish.side_effect = self.finish
        self.store.recover.return_value = []

    def finish(self, job_id, attempt_id, outcome):
        row = self.rows[job_id]
        if row["attempt_id"] != attempt_id or row["status"] not in {"running", "cancelling"}:
            raise ValueError("stale attempt")
        status = outcome["status"]
        row["status"] = "cancelled" if row["status"] == "cancelling" and status != "interrupted" else status
        row["result"] = outcome.get("result") if row["status"] == "verified" else None
        row["failure_code"] = outcome.get("failure_code")
        return deepcopy(row)

    def claim(self, *, approved=True):
        self.rows["job-1"] = fixture_job(
            status="running",
            attempt_id="attempt-1",
            decision_request=deepcopy(APPROVAL) if approved else None,
            decision={"decision_id": "plan-1", "kind": "approve", "plan_hash": PLAN,
                      "actor_id": "operator", "answers": {}} if approved else None,
        )
        self.store.claim.return_value = deepcopy(self.rows["job-1"])

    def checked_receipt(self, job, base, work, candidate, checker):
        self.assertEqual((job["job_id"], job["attempt_id"]), ("job-1", "attempt-1"))
        self.assertEqual((base, work), (self.base, self.work))
        self.assertEqual(job["decision"]["plan_hash"], candidate["evidence"]["plan_hash"])
        self.assertEqual(job["base_revision"], REVISION)
        checks = [{**item, "private_trace": str(self.frozen)} for item in checker(job, self.frozen)]
        return {**RECEIPT, "checks": checks, "private_path": str(self.frozen)}

    def stopped_runtime(self, job, repository, finalize):
        self.assertEqual(repository, self.projects[job["project_id"]])
        try:
            receipt = finalize(self.base, self.work, deepcopy(CANDIDATE))
        except ValueError as exc:
            self.assertEqual(str(exc), "candidate verification failed")
            return {"status": "failed", "failure_code": "candidate_verification_failed", "usage": USAGE}
        return {**CANDIDATE, "status": "verified", "result": receipt}

    def test_registry_rejects_duplicate_repository_paths(self):
        repository = self.projects["toy"]
        lexical = repository.parent / "missing-directory" / ".." / repository.name
        aliases = [("lexical", repository, lexical)]
        project_root = self.fixture_root.parent
        if project_root.drive.endswith(":"):
            aliases.append(("verbatim", project_root, Path("\\\\?\\" + str(project_root))))
        for kind, original, alias in aliases:
            with self.subTest(alias=kind), self.assertRaisesRegex(ValueError, "duplicate repository path"):
                JobService(self.store, self.runtime, {"toy": original, "alias": alias}, self.checker,
                           authorize_decision=self.authorize)

    def test_submit_preserves_the_request_and_only_projects_registered_metadata(self):
        prompt = "\n Only change the successful message.\n"
        self.store.submit.return_value = fixture_job(
            checkpoint={"host_path": str(self.projects["toy"])}, result=RECEIPT
        )
        spec = dict(base_revision=REVISION, prompt=prompt, idempotency_key="retry-key", limits=LIMITS)

        first = self.service.submit("toy", **spec)
        self.assertEqual(first, self.service.submit("toy", **spec))
        self.assertEqual(
            set(first), {"job_id", "project_id", "base_revision", "status", "limits",
                         "decision_request", "failure_code"},
        )
        self.assertEqual(first["status"], "queued")
        self.assertIsNone(self.service.result(first["job_id"]))
        self.assertEqual(self.store.submit.call_count, 2)
        for call in self.store.submit.call_args_list:
            self.assertEqual(call.args[0], {"project_id": "toy", **spec})
        with self.assertRaises(KeyError):
            self.service.submit("unregistered", **spec)
        for revision in ["HEAD", REVISION[:12], "-" + REVISION[1:]]:
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                self.service.submit("toy", **{**spec, "base_revision": revision})
        self.assertEqual(self.store.submit.call_count, 2)
        self.runtime.run.assert_not_called()

    def test_typed_status_and_event_cursor_do_not_leak_private_data(self):
        request = {
            "kind": "clarification",
            "decision_id": "q-1",
            "questions": [{"question_id": "message", "question": "Which message?",
                           "private": str(self.fixture_root)}],
            "checkpoint": "host only",
        }
        self.rows["job-1"].update(status="waiting_clarification", decision_request=request)
        self.store.events.return_value = [{"seq": 7, "status": "waiting_clarification", "private": request}]

        view = self.service.status("job-1")
        self.assertEqual(view["decision_request"], {
            "kind": "clarification", "decision_id": "q-1",
            "questions": [{"question_id": "message", "question": "Which message?"}],
        })
        view["decision_request"]["questions"].clear()
        self.assertEqual(len(self.service.status("job-1")["decision_request"]["questions"]), 1)
        self.assertEqual(self.service.events("job-1", after=6), [{"seq": 7, "status": "waiting_clarification"}])
        self.store.events.assert_called_once_with("job-1", after=6)
        with self.assertRaises(ValueError):
            self.service.events("job-1", after=True)

    def test_answers_require_an_explicit_project_actor_allow(self):
        self.rows["job-1"].update(status="waiting_clarification")
        self.store.decide.return_value = fixture_job()
        for policy_result in [False, "allow", RuntimeError("private auth failure")]:
            with self.subTest(policy_result=policy_result):
                self.authorize.side_effect = policy_result if isinstance(policy_result, Exception) else None
                self.authorize.return_value = policy_result
                with self.assertRaisesRegex(PermissionError, "^actor not authorized for this project$"):
                    self.service.answer("job-1", decision_id="q-1", answers={"message": " OK "}, actor_id="operator")
        self.store.decide.assert_not_called()

        self.authorize.side_effect = lambda project, actor: (project, actor) == ("toy", "operator")
        for invalid in ["x" * 701, "a\0b"]:
            with self.assertRaises(ValueError):
                self.service.answer("job-1", decision_id="q-1", answers={"message": invalid}, actor_id="operator")
        self.store.decide.assert_not_called()
        answers = {"message": " OK "}
        self.assertEqual(self.service.answer(
            "job-1", decision_id="q-1", answers=answers, actor_id="operator",
        )["status"], "queued")
        answers.clear()
        self.authorize.assert_called_with("toy", "operator")
        self.store.decide.assert_called_once_with("job-1", {
            "decision_id": "q-1", "kind": "answer", "actor_id": "operator", "answers": {"message": " OK "},
        })

    def test_approval_decisions_preserve_binding_and_delegate_atomic_fencing(self):
        self.rows["job-1"].update(status="waiting_approval", decision_request=APPROVAL)
        self.rows["job-2"] = fixture_job("job-2", status="waiting_approval", decision_request=APPROVAL)
        self.store.decide.side_effect = [
            ValueError("stale plan hash"), fixture_job(), fixture_job(),
            ValueError("decision already bound"), fixture_job("job-2", status="rejected"),
        ]
        with self.assertRaises(PermissionError):
            self.service.reject("job-1", decision_id="plan-1", plan_hash=PLAN, actor_id="stranger")
        self.store.decide.assert_not_called()
        with self.assertRaisesRegex(ValueError, "stale plan hash"):
            self.service.approve("job-1", decision_id="plan-1", plan_hash="wrong", actor_id="operator")
        self.assertEqual(self.service.approve(
            "job-1", decision_id="plan-1", plan_hash=PLAN, actor_id="operator",
        )["status"], "queued")
        self.rows["job-1"]["status"] = "queued"
        self.assertEqual(self.service.approve(
            "job-1", decision_id="plan-1", plan_hash=PLAN, actor_id="operator",
        )["status"], "queued")
        self.assertEqual(self.store.decide.call_args_list[1], self.store.decide.call_args_list[2])
        with self.assertRaisesRegex(ValueError, "decision already bound"):
            self.service.reject("job-1", decision_id="plan-1", plan_hash=PLAN, actor_id="operator")
        self.assertEqual(self.service.reject(
            "job-2", decision_id="plan-1", plan_hash=PLAN, actor_id="operator",
        )["status"], "rejected")
        self.store.decide.assert_called_with("job-2", {
            "decision_id": "plan-1", "kind": "reject", "actor_id": "operator", "answers": {}, "plan_hash": PLAN,
        })

    def test_run_next_uses_only_the_host_finalized_result_and_projects_a_detached_patch(self):
        self.claim()
        self.runtime.run.side_effect = self.stopped_runtime
        self.assertIsNone(self.service.result("job-1"))
        with patch("hivo.job_service._verify_candidate", side_effect=self.checked_receipt) as verify:
            self.assertEqual(self.service.run_next()["status"], "verified")
        verify.assert_called_once()
        self.checker.assert_called_once()
        self.assertEqual(self.checker.call_args.args[1], self.frozen)
        self.assertEqual(self.store.finish.call_args.args[2]["usage"], USAGE)
        result = self.service.result("job-1")
        self.assertEqual(result, RECEIPT)
        result["changed_paths"].clear()
        result["checks"][0]["passed"] = False
        self.assertEqual(self.service.result("job-1"), RECEIPT)
        self.assertIsNone(self.service.status("job-1")["decision_request"])

    def test_forged_unfinalized_tampered_and_unapproved_reports_never_publish(self):
        def altered(job, repository, finalize):
            report = self.stopped_runtime(job, repository, finalize)
            report["result"]["diff"] += "forged\n"
            return report

        cases = [
            ("forged", True, lambda *_: {**CANDIDATE, "status": "verified", "result": RECEIPT}, 0),
            ("candidate-only", True, lambda *_: CANDIDATE, 0),
            ("tampered", True, altered, 1),
            ("not-approved", False, self.stopped_runtime, 0),
        ]
        for name, approved, report, calls in cases:
            with self.subTest(name=name):
                self.claim(approved=approved)
                self.runtime.run.side_effect = report
                with patch("hivo.job_service._verify_candidate", side_effect=self.checked_receipt) as verify:
                    stopped = self.service.run_next()
                self.assertEqual(verify.call_count, calls)
                self.assertEqual(stopped["status"], "failed")
                self.assertEqual(stopped["failure_code"], "candidate_verification_failed")
                self.assertNotIn("result", self.store.finish.call_args.args[2])
                self.assertIsNone(self.service.result("job-1"))

    def test_failed_oracle_diagnostics_are_redacted_and_no_patch_is_stored(self):
        self.claim()
        self.runtime.run.side_effect = self.stopped_runtime
        with patch("hivo.job_service._verify_candidate", side_effect=ValueError(str(self.frozen))):
            result = self.service.run_next()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_code"], "candidate_verification_failed")
        self.assertIsNone(self.service.result("job-1"))

    def test_retry_is_explicit_and_never_uses_result_from_a_failed_report(self):
        self.claim()
        self.runtime.run.return_value = {
            "status": "failed", "failure_code": "provider_unavailable", "usage": USAGE, "result": RECEIPT,
        }
        self.store.retry.return_value = fixture_job()
        self.assertEqual(self.service.run_next()["failure_code"], "provider_unavailable")
        self.assertNotIn("result", self.store.finish.call_args.args[2])
        self.assertIsNone(self.service.result("job-1"))
        self.store.retry.assert_not_called()
        self.assertEqual(self.service.retry("job-1")["status"], "queued")
        self.store.retry.assert_called_once_with("job-1")

    def test_cancel_during_oracle_keeps_slot_until_finalization_drains(self):
        self.claim()
        entered, release = Event(), Event()

        def delayed_receipt(*args):
            entered.set()
            self.assertTrue(release.wait(5), "oracle was not released")
            return self.checked_receipt(*args)

        def cancelling(job_id):
            self.rows[job_id]["status"] = "cancelling"
            return self.store.get(job_id)

        self.store.cancel.side_effect = cancelling
        self.store.active_attempts.return_value = [{"job_id": "job-1", "attempt_id": "attempt-1",
                                                  "status": "cancelling"}]
        self.runtime.cancel.return_value = True
        self.runtime.run.side_effect = self.stopped_runtime
        with patch("hivo.job_service._verify_candidate", side_effect=delayed_receipt):
            with ThreadPoolExecutor(max_workers=1) as pool:
                running = pool.submit(self.service.run_next)
                try:
                    self.assertTrue(entered.wait(5), "oracle did not start")
                    self.assertEqual(self.service.cancel("job-1")["status"], "cancelling")
                    self.runtime.cancel.assert_called_once_with("attempt-1")
                    self.store.recover.assert_not_called()
                    self.assertEqual(self.service.recover(), [])
                    self.store.recover.assert_called_once_with([])
                    self.runtime.stopped.assert_not_called()
                    self.assertIsNone(self.service.result("job-1"))
                finally:
                    release.set()
                self.assertEqual(running.result(timeout=5)["status"], "cancelled")
        self.assertNotIn("result", self.store.finish.call_args.args[2])
        self.assertIsNone(self.service.result("job-1"))

    def test_runtime_exception_and_restart_reconciliation_do_not_assume_worker_death(self):
        self.claim()
        self.runtime.run.side_effect = RuntimeError(str(self.fixture_root))
        self.assertEqual(self.service.run_next()["status"], "interrupted")
        self.assertEqual(self.store.finish.call_args.args[2], {
            "status": "interrupted", "failure_code": "runtime_error",
        })
        self.store.active_attempts.return_value = [
            {"job_id": "job-1", "attempt_id": "attempt-1", "status": "interrupted"},
            {"job_id": "job-2", "attempt_id": "attempt-2", "status": "cancelling"},
        ]
        self.runtime.stopped.side_effect = [RuntimeError("daemon unavailable"), True]
        self.store.recover.return_value = [fixture_job("job-2", status="cancelled")]

        self.assertEqual([job["job_id"] for job in self.service.recover()], ["job-2"])
        self.store.recover.assert_called_once_with(["attempt-2"])
        self.assertEqual(self.service.status("job-1")["status"], "interrupted")

    def test_run_next_does_not_serialize_different_projects(self):
        self.rows = {
            "job-1": fixture_job("job-1", "toy", attempt_id="attempt-1", status="running"),
            "job-2": fixture_job("job-2", "other", attempt_id="attempt-2", status="running"),
        }
        self.store.claim.side_effect = [deepcopy(row) for row in self.rows.values()] + [None]
        rendezvous = Barrier(2)

        def overlap(job, repository, _finalize):
            self.assertEqual(repository, self.projects[job["project_id"]])
            rendezvous.wait(timeout=5)
            return {"status": "failed", "failure_code": "provider_unavailable", "usage": USAGE}

        self.runtime.run.side_effect = overlap
        with ThreadPoolExecutor(max_workers=2) as pool:
            runs = [pool.submit(self.service.run_next) for _ in range(2)]
            self.assertEqual({run.result(timeout=10)["status"] for run in runs}, {"failed"})
        self.assertEqual(self.runtime.run.call_count, 2)
        self.assertIsNone(self.service.run_next())


if __name__ == "__main__":
    unittest.main()
