"""Controlled lifecycle checks: real SQLite, independent callers, no runtime."""

import json
import subprocess
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from hivo.job_store import JobStore


ROOT = Path(__file__).resolve().parents[1]
REVISION = "a" * 40
PLAN_HASH = "b" * 64


def spec(project="alpha", key="request", *, limits=None):
    return {
        "project_id": project,
        "base_revision": REVISION,
        "prompt": "  Keep invalid input rejected.\nغير رسالة النجاح فقط.\r\n",
        "idempotency_key": key,
        "limits": limits,
    }


def usage(model=0, tool=0, elapsed=0):
    return {"model_calls": model, "tool_calls": tool, "elapsed_seconds": elapsed}


def approval(decision_id="plan-1", **changes):
    return {
        "decision_id": decision_id,
        "kind": "approve",
        "actor_id": "operator",
        "plan_hash": PLAN_HASH,
        **changes,
    }


def waiting(decision_id="plan-1", *, consumed=None):
    return {
        "status": "waiting_approval",
        "checkpoint": {
            "base_sha256": "e" * 64,
            "allowed_paths": ["main.py"],
            "private": {"plan": ["immutable step"], "local_metadata": "not an event"},
        },
        "decision_request": {
            "decision_id": decision_id,
            "kind": "approval",
            "plan_hash": PLAN_HASH,
            "plan_summary": "Change only the successful message.",
        },
        "usage": usage() if consumed is None else consumed,
    }


def verified(**changes):
    # This fixture plays the trusted publisher; store tests do not verify patches.
    return {
        "status": "verified",
        "usage": usage(1, 2, 0.5),
        "result": {
            "diff": "trusted patch bytes",
            "base_revision": REVISION,
            "changed_paths": ["main.py"],
            "workspace_sha256": "c" * 64,
            "patch_sha256": "d" * 64,
            "checks": [{"check_id": "original_invalid_input", "passed": True}],
        },
        **changes,
    }


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / ".runtime-proof"
        scratch.mkdir(exist_ok=True)
        directory = TemporaryDirectory(prefix="lifecycle-check-", dir=scratch)
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "jobs.sqlite3"
        self.store = JobStore(self.db)
        self.other = JobStore(self.db)

    def finish(self, claim, outcome, *, store=None):
        return (self.store if store is None else store).finish(
            claim["job_id"], claim["attempt_id"], outcome
        )

    def run_child(self, program, *args):
        return subprocess.run(
            [sys.executable, "-B", "-c", program, str(self.db), *args],
            cwd=ROOT, capture_output=True, encoding="utf-8", timeout=15, check=False,
        )

    def approve_job(self, limits=None):
        job = self.store.submit(spec(limits=limits))
        self.finish(self.other.claim(), waiting(consumed=usage(2, 3, 5)))
        self.other.decide(job["job_id"], approval())
        return self.store.claim()

    def statuses(self, job_id):
        events = self.other.events(job_id)
        self.assertTrue(all(set(event) == {"seq", "status"} for event in events), events)
        seq = [event["seq"] for event in events]
        self.assertEqual(seq, sorted(set(seq)))
        return [event["status"] for event in events]

    def test_submit_race_preserves_exact_payload_and_one_event_per_project_key(self):
        ready = threading.Barrier(2)

        def submit(store):
            ready.wait(timeout=10)
            return store.submit(spec())

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(submit, self.store)
            second = pool.submit(submit, self.other)
            job = first.result(timeout=15)
            self.assertEqual(second.result(timeout=15), job)
        job_id = job["job_id"]
        self.assertEqual(self.other.get(job_id)["prompt"], spec()["prompt"])
        self.assertEqual(self.statuses(job_id), ["queued"])
        self.assertNotEqual(self.store.submit(spec("beta"))["job_id"], job_id)
        for changed in (
            {"prompt": spec()["prompt"].strip()},
            {"base_revision": "e" * 40},
            {"limits": {"max_attempts": 2}},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.other.submit({**spec(), **changed})
        for bad in ({"max_model_calls": True}, {"max_elapsed_seconds": float("inf")},
                    {"max_attempts": 10**9}, {"max_tool_calls": 0}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.other.submit(spec(key="invalid", limits=bad))
        self.assertEqual(self.statuses(job_id), ["queued"])
        with self.assertRaises(KeyError):
            self.store.events("missing")

    def test_atomic_claims_admit_two_projects_and_never_overlap_one_project(self):
        alpha = self.store.submit(spec("alpha", "first"))
        queued_alpha = self.store.submit(spec("alpha", "second"))
        beta = self.store.submit(spec("beta"))
        gamma = self.store.submit(spec("gamma"))
        ready = threading.Barrier(5)

        def claim():
            store = JobStore(self.db)
            ready.wait(timeout=10)
            return store.claim()

        with ThreadPoolExecutor(max_workers=5) as pool:
            claims = [job for job in pool.map(lambda _: claim(), range(5)) if job is not None]
        self.assertEqual(len(claims), 2)
        running = {job["job_id"]: job for job in claims}
        self.assertEqual(running.keys(), {alpha["job_id"], beta["job_id"]})
        self.assertEqual(len({job["attempt_id"] for job in claims}), 2)
        self.assertEqual(self.other.get(queued_alpha["job_id"])["status"], "queued")
        self.assertEqual(self.other.get(gamma["job_id"])["status"], "queued")
        self.finish(running[beta["job_id"]], {"status": "failed", "usage": usage()})
        gamma_claim = self.other.claim()
        self.assertEqual(gamma_claim["job_id"], gamma["job_id"])
        self.finish(gamma_claim, {"status": "failed", "usage": usage()})
        self.assertIsNone(self.other.claim(), "alpha cannot overlap even with a free slot")
        self.finish(running[alpha["job_id"]], {"status": "failed", "usage": usage()})
        self.assertEqual(self.other.claim()["job_id"], queued_alpha["job_id"])

    def test_exact_decisions_and_budget_survive_process_restart_to_publication(self):
        job_id = self.store.submit(spec())["job_id"]
        first = self.store.claim()
        clarification = {
            "status": "waiting_clarification",
            "checkpoint": {"private": {"source": REVISION}},
            "decision_request": {
                "decision_id": "question-1",
                "kind": "clarification",
                "questions": [{"question_id": "message", "question": "Which message?"}],
            },
            "usage": usage(2, 3, 7.5),
        }
        paused = self.finish(first, clarification)
        self.assertEqual(paused["status"], "waiting_clarification")
        self.assertEqual(self.other.active_attempts(), [])
        self.assertIsNone(self.other.claim(), "waiting does not dispatch without a bound decision")
        paused["checkpoint"]["private"].clear()
        self.assertEqual(self.other.get(job_id)["checkpoint"], clarification["checkpoint"])
        answer = {
            "decision_id": "question-1", "kind": "answer", "actor_id": "operator",
            "answers": {"message": "  Ready to continue.  "},
        }
        for bad in ({}, {"message": " "}, {"message": "yes", "extra": "no"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.other.decide(job_id, dict(answer, answers=bad))
        self.assertEqual(self.other.decide(job_id, answer)["status"], "queued")
        self.assertEqual(self.store.decide(job_id, answer)["status"], "queued")
        with self.assertRaises(ValueError):
            self.other.decide(job_id, dict(answer, actor_id="different-operator"))
        second = self.other.claim()
        self.assertEqual(second["decision"], answer)
        self.assertEqual(second["checkpoint"], clarification["checkpoint"])
        self.assertEqual(second["decision_request"], clarification["decision_request"])
        self.assertEqual(second["limits"], {
            "max_model_calls": 16, "max_tool_calls": 22, "max_elapsed_seconds": 112.5, "max_attempts": 3,
        })
        with self.assertRaises(ValueError):
            self.finish(second, waiting(decision_id="question-1"))
        planned = waiting(consumed=usage(4, 5, 20))
        malformed = planned | {"decision_request": dict(planned["decision_request"], plan_summary=None)}
        with self.assertRaises(ValueError):
            self.finish(second, malformed)
        self.assertEqual(self.finish(second, planned)["status"], "waiting_approval")
        self.assertEqual(self.other.active_attempts(), [])
        for bad in (approval("question-1"), approval(plan_hash="wrong-plan"), answer | {"decision_id": "plan-1"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.other.decide(job_id, bad)
        restarted = self.run_child(
            "import json, sys\n"
            "from hivo.job_store import JobStore\n"
            "store = JobStore(sys.argv[1])\n"
            "print(json.dumps(store.decide(sys.argv[2], json.loads(sys.argv[3]))))\n",
            job_id, json.dumps(approval()),
        )
        self.assertEqual(restarted.returncode, 0, restarted.stderr)
        self.assertEqual(json.loads(restarted.stdout)["decision"], approval())
        third = self.store.claim()
        self.assertEqual(third["checkpoint"], planned["checkpoint"])
        self.assertEqual(third["decision_request"], planned["decision_request"])
        self.assertEqual(third["decision"], approval())
        self.assertEqual(third["limits"], {
            "max_model_calls": 12, "max_tool_calls": 17, "max_elapsed_seconds": 92.5, "max_attempts": 2,
        })
        self.assertEqual(self.other.get(job_id)["limits"]["max_elapsed_seconds"], 120)
        self.assertEqual(len({item["attempt_id"] for item in (first, second, third)}), 3)
        with self.assertRaises(ValueError):
            self.finish(first, verified())
        with self.assertRaises(ValueError):
            self.finish(third, waiting(decision_id="different-plan"))
        with self.assertRaises(ValueError):
            self.finish(third, verified(status="candidate"))
        with self.assertRaises(ValueError):
            self.finish(third, verified(result={"base_revision": "f" * 40}))
        self.assertIsNone(self.other.get(job_id)["result"])
        expected = verified()
        published = self.finish(third, expected)
        self.assertEqual(published["result"], expected["result"])
        published["result"]["changed_paths"].clear()
        self.assertEqual(self.other.decide(job_id, approval())["result"], expected["result"])
        self.assertEqual(self.other.decide(job_id, answer)["status"], "verified")
        self.assertEqual(self.statuses(job_id), [
            "queued", "running", "waiting_clarification", "queued", "running",
            "waiting_approval", "queued", "running", "verified",
        ])
        events = self.other.events(job_id)
        self.assertEqual(self.other.events(job_id, after=events[-2]["seq"]), events[-1:])

    def test_rejection_binds_the_plan_and_never_queues_work(self):
        job = self.store.submit(spec())
        job_id = job["job_id"]
        self.finish(self.store.claim(), waiting())
        rejection = approval(kind="reject")
        with self.assertRaises(ValueError):
            self.other.decide(job_id, rejection | {"plan_hash": "different"})
        rejected = self.other.decide(job_id, rejection)
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(self.store.decide(job_id, rejection), rejected)
        with self.assertRaises(ValueError):
            self.store.decide(job_id, approval())
        with self.assertRaises(ValueError):
            self.other.retry(job_id)
        self.assertIsNone(self.other.claim())
        self.assertEqual(self.statuses(job_id), ["queued", "running", "waiting_approval", "rejected"])

    def test_conflicting_decisions_race_but_only_one_binds(self):
        job_id = self.store.submit(spec())["job_id"]
        self.finish(self.store.claim(), waiting())
        ready = threading.Barrier(2)

        def decide(store, decision):
            ready.wait(timeout=10)
            try:
                return store.decide(job_id, decision)
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            trials = (
                pool.submit(decide, self.store, approval()),
                pool.submit(decide, self.other, approval(kind="reject")),
            )
            accepted = [job for trial in trials if (job := trial.result(timeout=15)) is not None]
        self.assertEqual(len(accepted), 1)
        winner = accepted[0]
        self.assertEqual(self.other.decide(job_id, winner["decision"]), winner)
        self.assertEqual(self.statuses(job_id), ["queued", "running", "waiting_approval", winner["status"]])

    def test_cancellation_wins_against_ready_finalization_without_releasing_slot_early(self):
        claim = self.approve_job()
        job_id = claim["job_id"]
        next_job = self.store.submit(spec(key="same-project"))
        entered_finalizer = threading.Event()
        release_finalizer = threading.Event()

        def finalizer():
            result = verified()
            entered_finalizer.set()
            if not release_finalizer.wait(timeout=10):
                raise TimeoutError("test did not release finalizer")
            return self.finish(claim, result)

        with ThreadPoolExecutor(max_workers=1) as pool:
            finalizing = pool.submit(finalizer)
            try:
                self.assertTrue(entered_finalizer.wait(timeout=10))
                cancelling = self.other.cancel(job_id)
                self.assertEqual(cancelling["status"], "cancelling")
                self.assertEqual(self.other.cancel(job_id), cancelling)
                self.assertEqual(self.other.recover(["not-the-attempt"]), [])
                self.assertIsNone(self.other.claim())
                self.assertEqual(self.other.active_attempts(), [{
                    "job_id": job_id, "attempt_id": claim["attempt_id"], "status": "cancelling",
                }])
            finally:
                release_finalizer.set()
            stopped = finalizing.result(timeout=10)
        self.assertEqual(stopped["status"], "cancelled")
        self.assertIsNone(stopped["result"])
        self.assertEqual(self.other.claim()["job_id"], next_job["job_id"])
        with self.assertRaises(ValueError):
            self.finish(claim, verified())
        self.assertEqual(self.statuses(job_id)[-2:], ["cancelling", "cancelled"])

    def test_cancelled_unknown_stop_needs_exact_positive_proof_and_fences_old_result(self):
        claim = self.approve_job()
        job_id, attempt_id = claim["job_id"], claim["attempt_id"]
        self.other.cancel(job_id)
        self.finish(claim, {"status": "interrupted", "failure_code": "backend_unavailable"})
        restarted = JobStore(self.db)
        self.assertEqual(restarted.get(job_id)["status"], "cancelling")
        self.assertEqual(restarted.recover([]), [])
        self.assertEqual(restarted.active_attempts()[0]["attempt_id"], attempt_id)
        stopped, = restarted.recover([attempt_id])
        self.assertEqual(stopped["status"], "cancelled")
        self.assertEqual(restarted.recover([attempt_id]), [])
        self.assertIsNone(stopped["result"])
        with self.assertRaises(ValueError):
            self.finish(claim, verified())

    def test_interrupted_retry_requires_death_and_preserves_measured_usage(self):
        first = self.store.submit(spec())
        claim = self.store.claim()
        interrupted = {"status": "interrupted", "failure_code": "stop_unconfirmed", "usage": usage(4, 6, 8)}
        self.assertEqual(self.finish(claim, interrupted)["status"], "interrupted")
        restart = JobStore(self.db)
        self.assertEqual(restart.recover([]), [])
        self.assertEqual(restart.active_attempts()[0]["status"], "interrupted")
        with self.assertRaises(ValueError):
            restart.retry(first["job_id"])
        with self.assertRaises(ValueError):
            self.finish(claim, {"status": "failed", "usage": usage()})
        self.assertEqual(restart.recover([claim["attempt_id"]])[0]["status"], "interrupted")
        self.assertEqual(restart.active_attempts(), [])
        self.assertEqual(restart.retry(first["job_id"])["status"], "queued")
        retry = restart.claim()
        self.assertNotEqual(retry["attempt_id"], claim["attempt_id"])
        self.assertEqual(retry["limits"], {
            "max_model_calls": 14, "max_tool_calls": 19, "max_elapsed_seconds": 112, "max_attempts": 3,
        })
        with self.assertRaises(ValueError):
            self.finish(claim, {"status": "failed", "usage": usage()})
        self.assertEqual(self.other.get(first["job_id"])["status"], "running")

    def test_crash_without_usage_spends_allowance_instead_of_granting_a_reset(self):
        claim = self.approve_job()
        job_id = claim["job_id"]
        restart = JobStore(self.db)
        self.assertEqual(restart.recover([]), [])
        self.assertEqual(restart.get(job_id)["status"], "running")
        with self.assertRaises(ValueError):
            restart.retry(job_id)
        stopped, = restart.recover([claim["attempt_id"]])
        self.assertEqual(stopped["status"], "interrupted")
        self.assertEqual(restart.active_attempts(), [])
        with self.assertRaisesRegex(ValueError, "remaining retry budget"):
            restart.retry(job_id)
        with self.assertRaises(ValueError):
            self.finish(claim, verified())

    def test_crash_during_claim_never_commits_partial_state_or_event(self):
        job_id = self.store.submit(spec())["job_id"]
        crashed = self.run_child(
            "import os, sys\n"
            "from hivo.job_store import JobStore\n"
            "store = JobStore(sys.argv[1])\n"
            "record = store._record\n"
            "def crash_before_commit(*args):\n"
            "    record(*args)\n"
            "    os._exit(73)\n"
            "store._record = crash_before_commit\n"
            "store.claim()\n",
        )
        self.assertEqual(crashed.returncode, 73, crashed.stderr)
        restart = JobStore(self.db)
        self.assertEqual(restart.get(job_id)["status"], "queued")
        self.assertEqual(self.statuses(job_id), ["queued"])
        self.assertEqual(restart.active_attempts(), [])
        restarted_claim = restart.claim()
        self.assertEqual(restarted_claim["limits"]["max_attempts"], 4)
        self.assertEqual(self.statuses(job_id), ["queued", "running"])

    def test_failed_and_blocked_retries_keep_plan_and_respect_attempt_budget(self):
        claim = self.approve_job({"max_attempts": 3})
        job_id = claim["job_id"]
        failed = self.finish(claim, {
            "status": "failed", "failure_code": "provider_down", "usage": usage(2, 1, 7),
            "checkpoint": {"private": "do not replace the approved checkpoint"},
        })
        self.assertEqual(failed["failure_code"], "provider_down")
        self.assertIsNone(failed["result"])
        restarted = JobStore(self.db)
        self.assertEqual(restarted.retry(job_id)["status"], "queued")
        retry = restarted.claim()
        self.assertEqual(retry["checkpoint"], claim["checkpoint"])
        self.assertEqual(retry["decision_request"], claim["decision_request"])
        self.assertEqual(retry["decision"], claim["decision"])
        self.assertEqual(retry["limits"], {
            "max_model_calls": 14, "max_tool_calls": 21, "max_elapsed_seconds": 108, "max_attempts": 1,
        })
        self.assertEqual(self.finish(retry, {"status": "blocked", "usage": usage()})["status"], "blocked")
        with self.assertRaisesRegex(ValueError, "remaining retry budget"):
            self.store.retry(job_id)
        self.assertIsNone(restarted.claim())

    def test_malformed_usage_cannot_release_slot_and_over_budget_cannot_publish(self):
        claim = self.approve_job()
        job_id = claim["job_id"]
        events = self.other.events(job_id)
        for bad in (None, usage(True), usage(-1), usage(elapsed=float("nan")), {"model_calls": 1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.finish(claim, verified(usage=bad))
        self.assertEqual(self.other.events(job_id), events)
        self.assertEqual(self.other.active_attempts()[0]["attempt_id"], claim["attempt_id"])
        expired = self.finish(claim, verified(usage=usage(elapsed=116)))
        self.assertEqual(expired["status"], "timed_out")
        self.assertEqual(expired["failure_code"], "budget_exhausted")
        self.assertIsNone(expired["result"])
        self.assertEqual(self.other.active_attempts(), [])

    def test_waiting_job_can_be_cancelled_without_runtime_stop(self):
        job_id = self.store.submit(spec())["job_id"]
        claim = self.store.claim()
        self.finish(claim, waiting())
        cancelled = self.other.cancel(job_id)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(self.store.cancel(job_id), cancelled)
        self.assertEqual(self.other.active_attempts(), [])
        with self.assertRaises(ValueError):
            self.other.decide(job_id, approval())
        with self.assertRaises(ValueError):
            self.finish(claim, verified())


if __name__ == "__main__":
    unittest.main()
