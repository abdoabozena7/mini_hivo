"""Headless acceptance on an authored CLI; these tests do not run a model."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch

from hivo.job_result import snapshot_digest
from hivo.job_service import JobService
from hivo.job_store import JobStore


OLD = b'def success_message():\n    return "READY"\n'
NEW = b'def success_message():\n    return "SHIPPED"\n'
CLI = (
    b"import sys\n"
    b"from messages import success_message\n"
    b'if sys.argv[1:] != ["ok"]:\n'
    b'    print("invalid input", file=sys.stderr)\n'
    b"    raise SystemExit(2)\n"
    b"print(success_message())\n"
)
PROMPT = (
    "Update messages.py so running python cli.py ok prints exactly SHIPPED followed by a newline. "
    "Keep the existing invalid input behavior and do not change cli.py."
)
PLAN_HASH = hashlib.sha256(b"change only messages.py").hexdigest()


def _git(repo, *args):
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    return subprocess.run(
        ["git", "--no-pager", "-C", str(repo), *args], env=env, check=True,
        capture_output=True, timeout=10,
    ).stdout


def _fixture_project(path, files=None):
    files = {"messages.py": OLD, "cli.py": CLI} if files is None else files
    path.mkdir()
    for name, content in files.items():
        (path / name).write_bytes(content)
    _git(path, "init", "--template=")
    _git(path, "config", "core.autocrlf", "false")
    _git(path, "add", "--", *files)
    tree = _git(path, "write-tree").decode().strip()
    return _git(
        path, "-c", "user.name=Acceptance fixture", "-c", "user.email=fixture@example.invalid",
        "commit-tree", tree, "-m", "Trusted headless CLI fixture",
    ).decode().strip()


def _trusted_cli_checker(_job, workspace):
    # Execute only the exact authored sources; any other candidate is refused here.
    if (workspace / "cli.py").read_bytes() != CLI or (workspace / "messages.py").read_bytes() != NEW:
        return [{"check_id": "known-fixture", "passed": False}]
    invocation = [sys.executable, "-B", "-E", "-s", "cli.py"]
    valid = subprocess.run([*invocation, "ok"], cwd=workspace, capture_output=True, timeout=10)
    invalid = subprocess.run([*invocation, "wrong"], cwd=workspace, capture_output=True, timeout=10)
    return [
        {"check_id": "new-stdout", "passed": valid.returncode == 0 and valid.stdout.replace(b"\r\n", b"\n") == b"SHIPPED\n"},
        {"check_id": "preserved-rejection", "passed": invalid.returncode == 2 and not invalid.stdout
         and invalid.stderr.replace(b"\r\n", b"\n") == b"invalid input\n"},
    ]


def _outcome(status, **extra):
    return {
        "status": status, "failure_code": None, "checkpoint": None, "decision_request": None,
        "evidence": None, "usage": {"model_calls": 1, "tool_calls": 1, "elapsed_seconds": 0.1},
        **extra,
    }


class _ScriptedRuntime:
    """Trusted fixture driver in place of a Docker worker and model."""

    def __init__(self):
        self.started = {project: Event() for project in ("alpha", "beta")}
        self.release = Event()
        self.pause = False
        self.fail_provider = False
        self.wrong_candidate = False
        self.needs_clarification = False
        self.pause_candidate = False
        self.finalizing = Event()
        self.received = []

    def run(self, job, repository, finalize):
        self.received.append((job["project_id"], job["attempt_id"]))
        self.started[job["project_id"]].set()
        if self.pause and not self.release.wait(10):
            raise RuntimeError("fixture worker release did not arrive")
        if self.fail_provider:
            return _outcome("blocked", failure_code="PROVIDER_UNAVAILABLE")
        decision = job["decision"] or {}
        if self.needs_clarification and not decision:
            return _outcome(
                "waiting_clarification",
                decision_request={
                    "decision_id": "question-" + job["job_id"], "kind": "clarification",
                    "questions": [{"question_id": "success-text", "question": "What text should success print?"}],
                },
                checkpoint={"question_shown": "success-text", "internal_trace": "not public"},
            )
        if decision.get("kind") == "answer":
            if decision.get("answers") != {"success-text": "SHIPPED"}:
                return _outcome("failed", failure_code="unexpected_fixture_answer")
        if decision.get("kind") != "approve":
            with tempfile.TemporaryDirectory() as temp:
                base = Path(temp)
                self.materialize(job, repository, base)
                base_digest = snapshot_digest(base)
            return _outcome(
                "waiting_approval",
                decision_request={
                    "decision_id": "review-" + job["job_id"], "kind": "approval",
                    "plan_hash": PLAN_HASH, "plan_summary": "Change only messages.py",
                },
                checkpoint={"plan_hash": PLAN_HASH, "base_sha256": base_digest,
                            "allowed_paths": ["messages.py"], "internal_trace": "not public"},
            )
        with tempfile.TemporaryDirectory() as temp:
            base, work = Path(temp) / "base", Path(temp) / "candidate"
            base.mkdir()
            self.materialize(job, repository, base)
            shutil.copytree(base, work)
            (work / "messages.py").write_bytes(OLD.replace(b"READY", b"WRONG") if self.wrong_candidate else NEW)
            candidate = _outcome(
                "candidate",
                evidence={
                    "job_id": job["job_id"], "attempt_id": job["attempt_id"],
                    "root_verified": True, "base_revision": job["base_revision"],
                    "plan_hash": PLAN_HASH, "allowed_paths": ["messages.py"],
                    "workspace_sha256": snapshot_digest(work),
                },
            )
            try:
                result = finalize(base, work, candidate)
            except ValueError:
                return _outcome("failed", failure_code="candidate_verification_failed")
            self.finalizing.set()
            if self.pause_candidate and not self.release.wait(10):
                raise RuntimeError("fixture finalization release did not arrive")
            return {**candidate, "status": "verified", "result": result}

    @staticmethod
    def materialize(job, repository, base):
        for name in ("messages.py", "cli.py"):
            (base / name).write_bytes(_git(repository, "show", f"{job['base_revision']}:{name}"))

    @staticmethod
    def stopped(_attempt_id):
        return False

    @staticmethod
    def cancel(_attempt_id):
        return False


class HeadlessJobIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp)
        self.projects = {name: self.root / name for name in ("alpha", "beta")}
        self.bases = {name: _fixture_project(repo) for name, repo in self.projects.items()}
        self.database = self.root / "jobs.sqlite3"
        self.runtime = _ScriptedRuntime()
        self.service = self.new_service()

    def new_service(self):
        return JobService(JobStore(self.database), self.runtime, self.projects, _trusted_cli_checker,
                          authorize_decision=lambda _project, actor: actor == "operator")

    def submit(self, project="alpha", key="request"):
        row = self.service.submit(project, base_revision=self.bases[project], prompt=PROMPT, idempotency_key=key)
        return row["job_id"]

    def approve(self, job_id, *, plan_hash=PLAN_HASH):
        request = self.service.status(job_id)["decision_request"]
        return self.service.approve(
            job_id, decision_id=request["decision_id"], plan_hash=plan_hash, actor_id="operator",
        )

    def assert_origin_unchanged(self):
        for project in self.projects.values():
            self.assertEqual((project / "messages.py").read_bytes(), OLD)
            self.assertEqual((project / "cli.py").read_bytes(), CLI)

    def test_patch_only_journey_survives_restart_and_preserves_old_behavior(self):
        job_id = self.submit()
        self.assertEqual(self.submit(), job_id)
        self.service.run_next()
        self.assertEqual(self.service.status(job_id)["status"], "waiting_approval")
        self.assertIsNone(self.service.result(job_id))
        with self.assertRaises(ValueError):
            self.approve(job_id, plan_hash=hashlib.sha256(b"wrong plan").hexdigest())
        self.service = self.new_service()
        self.approve(job_id)
        self.service.run_next()
        self.assertEqual(self.service.status(job_id)["status"], "verified")
        result = self.service.result(job_id)
        self.assertEqual(result["base_revision"], self.bases["alpha"])
        self.assertEqual(result["changed_paths"], ["messages.py"])
        self.assertEqual({row["check_id"] for row in result["checks"]},
                         {"new-stdout", "preserved-rejection"})
        self.assertTrue(all(row["passed"] for row in result["checks"]))
        patch = self.root / "verified.patch"
        patch.write_bytes(result["diff"].encode("utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            verification_copy = Path(temp)
            for name in ("cli.py", "messages.py"):
                (verification_copy / name).write_bytes(_git(self.projects["alpha"], "show", f"{self.bases['alpha']}:{name}"))
            _git(verification_copy, "apply", "--", str(patch))
            self.assertEqual((verification_copy / "messages.py").read_bytes(), NEW)
            self.assertTrue(all(row["passed"] for row in _trusted_cli_checker({}, verification_copy)))
        self.assert_origin_unchanged()

    def test_false_worker_success_never_publishes_a_patch(self):
        job_id = self.submit()
        self.service.run_next()
        self.approve(job_id)
        self.runtime.wrong_candidate = True
        self.service.run_next()
        self.assertIn(self.service.status(job_id)["status"], {"blocked", "failed"})
        self.assertIsNone(self.service.result(job_id))
        self.assert_origin_unchanged()

    def test_two_projects_overlap_but_same_project_stays_queued(self):
        alpha, beta, later = self.submit(), self.submit("beta"), self.submit(key="second")
        self.runtime.pause = True
        workers = [Thread(target=self.service.run_next) for _ in range(2)]
        for worker in workers:
            worker.start()
        try:
            self.assertTrue(all(started.wait(5) for started in self.runtime.started.values()))
            self.assertEqual(self.service.status(alpha)["status"], "running")
            self.assertEqual(self.service.status(beta)["status"], "running")
            self.assertEqual(self.service.status(later)["status"], "queued")
            self.assertIsNone(self.service.run_next())
        finally:
            self.runtime.release.set()
            for worker in workers:
                worker.join(10)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(self.service.status(alpha)["status"], "waiting_approval")
        self.assertEqual(self.service.status(beta)["status"], "waiting_approval")
        self.assert_origin_unchanged()

    def test_provider_failure_has_no_patch_or_root_success(self):
        job_id = self.submit()
        self.runtime.fail_provider = True
        self.service.run_next()
        state = self.service.status(job_id)
        self.assertEqual((state["status"], state["failure_code"]), ("blocked", "PROVIDER_UNAVAILABLE"))
        self.assertIsNone(self.service.result(job_id))
        self.assert_origin_unchanged()

    def test_inflight_cancel_fences_even_a_valid_late_candidate(self):
        job_id = self.submit()
        self.service.run_next()
        self.approve(job_id)
        self.runtime.pause_candidate = True
        worker = Thread(target=self.service.run_next)
        worker.start()
        try:
            self.assertTrue(self.runtime.finalizing.wait(5))
            self.assertEqual(self.service.cancel(job_id)["status"], "cancelling")
            self.assertIsNone(self.service.result(job_id))
        finally:
            self.runtime.release.set()
            worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.service.status(job_id)["status"], "cancelled")
        self.assertIsNone(self.service.result(job_id))
        self.assert_origin_unchanged()

    def test_exact_saved_answer_advances_without_running_during_wait(self):
        self.runtime.needs_clarification = True
        job_id = self.submit()
        self.service.run_next()
        waiting = self.service.status(job_id)
        self.assertEqual(waiting["status"], "waiting_clarification")
        request = waiting["decision_request"]
        self.assertEqual(len(self.runtime.received), 1)
        self.assertIsNone(self.service.run_next())
        self.service = self.new_service()
        with self.assertRaises((PermissionError, ValueError)):
            self.service.answer(job_id, decision_id=request["decision_id"],
                                answers={"success-text": "SHIPPED"}, actor_id="untrusted")
        with self.assertRaises(ValueError):
            self.service.answer(job_id, decision_id="stale",
                                answers={"success-text": "SHIPPED"}, actor_id="operator")
        self.service.answer(job_id, decision_id=request["decision_id"],
                            answers={"success-text": "SHIPPED"}, actor_id="operator")
        self.service.run_next()
        self.assertEqual(self.service.status(job_id)["status"], "waiting_approval")
        self.approve(job_id)
        self.service.run_next()
        self.assertEqual(self.service.status(job_id)["status"], "verified")
        self.assert_origin_unchanged()

    def test_real_controller_under_scripted_provider_delivers_checked_patch(self):
        import mini
        from hivo.job_worker import run_attempt
        from test_job_worker import BASE, PROMPT as WORKER_PROMPT, FixtureProvider

        repository = self.root / "controller"
        revision = _fixture_project(repository, BASE)
        expected = BASE["greeting.py"].replace(b"HELLO", b"WELCOME")
        real_run = subprocess.run
        attempts = []

        def guarded_run(args, **kwargs):
            root = Path(kwargs["cwd"])
            self.assertTrue(root.is_relative_to(self.root) and root != repository)
            self.assertEqual(args[1:], ["test_cli.py"])
            for name in ("test_cli.py", "cli.py"):
                self.assertEqual((root / name).read_bytes(), BASE[name])
            return real_run([sys.executable, "-B", "test_cli.py"], **kwargs)

        def independent_checker(_job, workspace):
            self.assertEqual((workspace / "cli.py").read_bytes(), BASE["cli.py"])
            self.assertEqual((workspace / "greeting.py").read_bytes().replace(b"\r\n", b"\n"), expected)
            checks = []
            for value, code, stdout in (("valid", 0, "WELCOME\n"), ("invalid", 2, "")):
                completed = real_run(
                    [sys.executable, "-B", "-E", "-s", "-c",
                     f"from cli import main; raise SystemExit(main({value!r}))"],
                    cwd=workspace, capture_output=True, timeout=10, text=True,
                )
                checks.append({"check_id": value, "passed": (completed.returncode, completed.stdout) == (code, stdout)})
            return checks

        class FixtureEngineRuntime(_ScriptedRuntime):
            def run(driver, job, origin, finalize):
                with tempfile.TemporaryDirectory(dir=self.root) as scratch:
                    base, work = Path(scratch) / "base", Path(scratch) / "candidate"
                    base.mkdir()
                    for name in BASE:
                        (base / name).write_bytes(_git(origin, "show", f"{job['base_revision']}:{name}"))
                    shutil.copytree(base, work)
                    provider = FixtureProvider(execute=(job["decision"] or {}).get("kind") == "approve")
                    with patch.object(mini.subprocess, "run", side_effect=guarded_run):
                        outcome = run_attempt(job, work, transport=provider)
                    attempts.append((job["attempt_id"], outcome["status"], len(provider.calls)))
                    if outcome["status"] != "candidate":
                        return outcome
                    result = finalize(base, work, outcome)
                    return {**outcome, "status": "verified", "result": result}

        runtime = FixtureEngineRuntime()

        def service():
            return JobService(JobStore(self.database), runtime, {"controller": repository}, independent_checker,
                              authorize_decision=lambda project, actor: (project, actor) == ("controller", "operator"))

        jobs = service()
        job_id = jobs.submit("controller", base_revision=revision, prompt=WORKER_PROMPT,
                             idempotency_key="actual-controller")["job_id"]
        waiting = jobs.run_next()
        self.assertEqual(waiting["status"], "waiting_approval", waiting)
        self.assertIsNone(jobs.result(job_id))
        request = waiting["decision_request"]
        jobs = service()
        jobs.approve(job_id, decision_id=request["decision_id"], plan_hash=request["plan_hash"], actor_id="operator")
        terminal = jobs.run_next()
        self.assertEqual(terminal["status"], "verified", terminal)
        self.assertEqual(jobs.result(job_id)["changed_paths"], ["greeting.py"])
        self.assertEqual(jobs.result(job_id)["checks"], [{"check_id": "valid", "passed": True},
                                                        {"check_id": "invalid", "passed": True}])
        self.assertEqual([status for _, status, _ in attempts], ["waiting_approval", "candidate"])
        self.assertNotEqual(attempts[0][0], attempts[1][0])
        for name, content in BASE.items():
            self.assertEqual((repository / name).read_bytes(), content)


@unittest.skipUnless(os.environ.get("HIVO_HEADLESS_TEST_IMAGE"),
                     "a pre-provisioned trusted Linux Docker image is required for live acceptance")
class HeadlessJobLiveAcceptanceTests(unittest.TestCase):
    def test_existing_repo_approval_and_independently_verified_patch(self):
        from hivo.job_runtime import DockerJobRuntime

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repository = root / "subject"
            base = _fixture_project(repository)
            runtime = DockerJobRuntime(root / "attempts", image=os.environ["HIVO_HEADLESS_TEST_IMAGE"],
                                       engine_root=Path(__file__).resolve().parents[1])

            def checker(_job, workspace):
                good = runtime.check(workspace, ["python", "-B", "cli.py", "ok"], timeout=10)
                bad = runtime.check(workspace, ["python", "-B", "cli.py", "wrong"], timeout=10)
                return [
                    {"check_id": "new-stdout", "passed": good["exit_code"] == 0 and good["stdout"] == b"SHIPPED\n"},
                    {"check_id": "preserved-rejection", "passed": bad["exit_code"] == 2 and not bad["stdout"]
                     and bad["stderr"] == b"invalid input\n"},
                ]

            def service():
                return JobService(JobStore(root / "queue.sqlite3"), runtime, {"fixture": repository}, checker,
                                  authorize_decision=lambda project, actor: (project, actor) == ("fixture", "qa-operator"))

            jobs = service()
            job_id = jobs.submit(
                "fixture", base_revision=base, prompt=PROMPT, idempotency_key="live-acceptance",
                limits={"max_model_calls": 48, "max_tool_calls": 48, "max_elapsed_seconds": 240, "max_attempts": 3},
            )["job_id"]
            state = jobs.run_next()
            self.assertEqual(state["status"], "waiting_approval", state)
            self.assertEqual((repository / "messages.py").read_bytes(), OLD)
            self.assertIsNone(jobs.result(job_id))
            request = state["decision_request"]
            jobs = service()
            jobs.approve(job_id, decision_id=request["decision_id"], plan_hash=request["plan_hash"],
                         actor_id="qa-operator")
            state = jobs.run_next()
            self.assertEqual(state["status"], "verified", state)
            result = jobs.result(job_id)
            self.assertEqual(result["changed_paths"], ["messages.py"])
            self.assertTrue(all(row["passed"] for row in result["checks"]))
            self.assertEqual((repository / "messages.py").read_bytes(), OLD)
            self.assertEqual((repository / "cli.py").read_bytes(), CLI)


if __name__ == "__main__":
    unittest.main()
