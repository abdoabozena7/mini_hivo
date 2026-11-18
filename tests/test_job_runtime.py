"""Controlled runtime checks: real disposable Git, fake Docker, no model."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from hivo import job_runtime as runtime


_PROJECT = Path(__file__).resolve().parents[1]
_IMAGE = "sha256:" + "1" * 64
_ORIGINAL = b'import sys\r\nprint("before")\r\n'
_CHANGED = b'import sys\r\nprint("after")\r\n'


def _outcome(status="candidate"):
    return {
        "status": status, "failure_code": None, "checkpoint": None, "decision_request": None,
        "evidence": {"root_verified": True},
        "usage": {"model_calls": 0, "tool_calls": 2, "elapsed_seconds": 0.1},
    }


class _FakeDaemon:
    def __init__(self):
        self.available = True
        self.image_available = True
        self.remove_available = True
        self.seccomp = True
        self.mismatch = False
        self.exit_after_attach = True
        self.calls = []
        self.containers = {}
        self.stage = {}
        self.launches = []
        self.removed = []
        self.block_worker = False
        self.on_worker_wait = None
        self.attached = threading.Event()
        self.outcome = _outcome()
        self.worker_snapshot = runtime._file_line("cli.py", 0o644, _CHANGED)

    def command(self, args):
        self.calls.append(args)
        if not self.available:
            return self.result(args, 1)
        if args[0] == "info":
            return self.result(args, data={
                "OSType": "linux", "Architecture": "x86_64", "MemTotal": 8 * 1024**3,
                "MemoryLimit": True, "SwapLimit": True, "PidsLimit": True, "CPUCfsQuota": True,
                "SecurityOptions": ["name=seccomp,profile=builtin"] if self.seccomp else [],
            })
        if args[:2] == ("image", "inspect"):
            return self.result(args, 0 if self.image_available else 1, {
                "Id": _IMAGE, "Os": "linux", "Architecture": "amd64", "Config": {"Env": ["LANG=C.UTF-8"]},
            })
        if args[0] == "create":
            return self.create(args)
        if args[:2] == ("container", "inspect"):
            target = args[-1]
            row = self.containers.get(target) or next(
                (record for record in self.containers.values() if record["Name"] == target), None,
            )
            return self.result(args, 0 if row else 1, row)
        if args[:3] == ("container", "rm", "--force"):
            if not self.remove_available or args[-1] not in self.containers:
                return self.result(args, 1)
            row = self.containers.pop(args[-1])
            self.removed.append((args[-1], row["State"]["Status"]))
            return self.result(args, data=(args[-1] + "\n").encode())
        raise AssertionError(f"unexpected fake request {args[0:2]}")

    def create(self, args):
        def option(flag):
            return args[args.index(flag) + 1]

        assert "--pull=never" in args
        assert "--network=none" in args and "--read-only" in args
        assert "readonly" in option("--mount").split(",")
        target = option("--workdir")
        assert target in {"/engine", "/project"}
        cid = uuid4().hex + uuid4().hex
        self.containers[cid] = {
            "Id": cid, "Image": args[args.index("-i") + 1], "Name": option("--name"),
            "Config": {
                "User": option("--user"), "WorkingDir": target, "Entrypoint": [option("--entrypoint")],
                "Cmd": list(args[args.index("-i") + 2:]), "Labels": {
                    option("--label").split("=")[0]: option("--label").split("=")[1],
                }, "OpenStdin": True, "Tty": False,
                "Env": [args[i + 1] for i, flag in enumerate(args) if flag == "--env"],
            },
            "State": {"Status": "created", "Pid": 0, "Running": False, "Restarting": False},
            "HostConfig": {
                "Runtime": "runc", "NetworkMode": "bridge" if self.mismatch else "none",
                "ReadonlyRootfs": True, "Privileged": False, "CapDrop": ["ALL"],
                "IpcMode": "private", "CgroupnsMode": "private", "PidMode": "", "UsernsMode": "",
                "SecurityOpt": ["no-new-privileges"], "RestartPolicy": {"Name": "no"},
                "LogConfig": {"Type": "none"}, "Memory": 512 * 1024**2, "MemorySwap": 512 * 1024**2,
                "NanoCpus": 1_000_000_000, "PidsLimit": 64, "ShmSize": 8 * 1024**2,
                "Tmpfs": {"/scratch": option("--tmpfs").split(":", 1)[1]}, "Ulimits": [
                    {"Name": "nofile", "Soft": 256, "Hard": 256},
                    {"Name": "fsize", "Soft": 4194304, "Hard": 4194304},
                ],
            },
            "Mounts": [{"Type": "bind", "Destination": target, "RW": False}],
        }
        return self.result(args, data=(cid + "\n").encode())

    @staticmethod
    def result(args, code=0, data=None):
        return subprocess.CompletedProcess(args, code, runtime._line(data) if isinstance(data, dict) else data or b"", b"")


class _DockerFakeRuntime(runtime.DockerJobRuntime):
    def __init__(self, root, engine_root, daemon, image=_IMAGE):
        super().__init__(root, image=image, engine_root=engine_root)
        self._docker = "fixture-docker"
        self.daemon = daemon

    def _command(self, args, deadline, cancelled, **_kwargs):
        runtime._check_clock(deadline, cancelled)
        return self.daemon.command(args)


class DockerJobRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="runtime-fixture-", dir=_PROJECT / ".runtime-proof")
        self.addCleanup(temporary.cleanup)
        self.fixture = Path(temporary.name)
        self.git = shutil.which("git")
        if self.git is None:
            self.fail("Git is required for the controlled staged revision test")
        self.repo = self.fixture / "registered"
        self.repo.mkdir()
        self.git_run("init", "--quiet")
        self.git_run("config", "core.autocrlf", "false")
        (self.repo / "cli.py").write_bytes(_ORIGINAL)
        self.git_run("add", "cli.py")
        self.git_run("commit", "--quiet", "-m", "authored runtime fixture")
        self.revision = self.git_run("rev-parse", "HEAD").strip().decode()
        (self.repo / "cli.py").write_bytes(b"DIRTY WORKTREE\n")
        (self.repo / "local-only.txt").write_bytes(b"NOT IN THE SNAPSHOT\n")
        self.engine = self.fixture / "engine"
        (self.engine / "hivo").mkdir(parents=True)
        (self.engine / "mini.py").write_bytes(b"# trusted controller fixture, not executed\n")
        for module in ("__init__", "job_worker", "job_runtime", "model_policy"):
            (self.engine / "hivo" / (module + ".py")).write_bytes(b"# not executed\n")
        self.root = self.fixture / "runtime"
        self.daemon = _FakeDaemon()
        self.runner = _DockerFakeRuntime(self.root, self.engine, self.daemon)
        self.job = {
            "attempt_id": uuid4().hex, "base_revision": self.revision, "prompt": "Preserve exact bytes.\n",
            "limits": {"max_model_calls": 4, "max_tool_calls": 8, "max_elapsed_seconds": 5},
        }
        real_child = runtime._Child
        daemon = self.daemon

        class FakeAttach:
            def __init__(self, argv, lines):
                self.cid = argv[-1]
                self.lines = lines
                self.receive_index = 0
                daemon.launches.append((self.cid, lines))
                if lines:
                    self.messages = [
                        runtime._line({"kind": "staged"}),
                        runtime._line({"kind": "outcome", "outcome": daemon.outcome}),
                        runtime._line({"kind": "snapshot"}),
                        daemon.worker_snapshot,
                        runtime._line({"kind": "snapshot_end"}),
                        None,
                    ]
                else:
                    command = daemon.containers[self.cid]["Config"]["Cmd"]
                    self.exit_code = 0 if command[-1] == "ok" else 2
                    self.messages = [b"after\n", None] if self.exit_code == 0 else [None]
                    self.stderr = b"" if self.exit_code == 0 else b"invalid input\n"
                daemon.containers[self.cid]["State"] = {
                    "Status": "running", "Pid": 567, "Running": True, "Restarting": False,
                }
                if lines:
                    daemon.attached.set()

            def send(self, data):
                if self.lines and daemon.stage.get(self.cid) is None:
                    daemon.stage[self.cid] = [runtime._json(line) for line in data.splitlines()]
                elif self.lines:
                    daemon.request = runtime._json(data)

            def receive(self, deadline, cancelled):
                if self.lines and self.receive_index == 1 and daemon.on_worker_wait is not None:
                    # The sandbox acknowledged staging and received the job; no outcome yet.
                    daemon.on_worker_wait()
                    runtime._check_clock(deadline, cancelled)
                while self.lines and daemon.block_worker:
                    runtime._check_clock(deadline, cancelled)
                    time.sleep(0.01)
                self.receive_index += 1
                return self.messages[self.receive_index - 1]

            def wait(self, _deadline, _cancelled):
                code = 0 if self.lines else self.exit_code
                if daemon.exit_after_attach:
                    daemon.containers[self.cid]["State"] = {
                        "Status": "exited", "Pid": 0, "Running": False, "Restarting": False, "ExitCode": code,
                    }
                return code

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                pass

        def child(argv, env, cwd, out_limit, err_limit, *, lines=False):
            if argv[0] != "fixture-docker":
                return real_child(argv, env, cwd, out_limit, err_limit, lines=lines)
            self.assertEqual(["start", "-a", "-i"], argv[-4:-1])
            return FakeAttach(argv, lines)

        process_patch = patch.object(runtime, "_Child", side_effect=child)
        process_patch.start()
        self.addCleanup(process_patch.stop)

    def git_run(self, *args):
        return subprocess.run(
            [self.git, "--no-pager", "-c", "user.name=Runtime Fixture", "-c", "user.email=fixture@example.invalid",
             "-c", "commit.gpgsign=false", "-C", str(self.repo), *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=5,
            env=runtime._host_environment() | {
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ALLOW_PROTOCOL": "",
            },
        ).stdout

    def no_finalize(self, *_args):
        self.fail("noncandidate or unconfirmed attempt called finalization")

    def run_job(self, finalize=None):
        return self.runner.run(self.job, self.repo, finalize or self.no_finalize)

    def start_job(self, finalize=None):
        results = []
        thread = threading.Thread(target=lambda: results.append(self.run_job(finalize)), daemon=True)
        thread.start()
        self.addCleanup(thread.join, 6)
        self.assertTrue(self.daemon.attached.wait(5))
        return thread, results

    def test_denies_missing_daemon_and_never_treats_unknown_id_as_stopped(self):
        self.daemon.available = False
        self.assertFalse(self.runner.stopped(self.job["attempt_id"]))
        result = self.run_job()
        self.assertEqual(("blocked", "docker_unavailable"), (result["status"], result["failure_code"]))
        self.assertEqual([("info", "--format", "{{json .}}")], self.daemon.calls)
        self.assertEqual([], self.daemon.launches)
        self.assertTrue(self.runner.stopped(self.job["attempt_id"]))

    def test_refuses_runtime_root_inside_registered_project_before_creating_any_files(self):
        shared_root = self.repo / "incorrect_runtime_root"
        runner = _DockerFakeRuntime(shared_root, self.engine, self.daemon)
        result = runner.run(self.job, self.repo, self.no_finalize)
        self.assertEqual(("blocked", "overlapping_project_and_runtime"), (result["status"], result["failure_code"]))
        self.assertFalse(shared_root.exists())
        self.assertEqual([], self.daemon.calls)

    def test_admission_checks_immutable_image_daemon_profile_and_container_config(self):
        for case in ("tag", "image_missing", "daemon_profile", "wrong_isolation"):
            with self.subTest(case=case):
                self.job["attempt_id"] = uuid4().hex
                self.runner.image = "python:latest" if case == "tag" else _IMAGE
                self.daemon.image_available = case != "image_missing"
                self.daemon.seccomp = case != "daemon_profile"
                self.daemon.mismatch = case == "wrong_isolation"
                self.daemon.calls.clear()
                expect = {
                    "tag": "immutable_image_required", "image_missing": "local_image_unavailable",
                    "daemon_profile": "isolation_profile_unavailable", "wrong_isolation": "container_profile_mismatch",
                }[case]
                result = self.run_job()
                self.assertEqual(("blocked", expect), (result["status"], result["failure_code"]))
                self.assertEqual([], self.daemon.launches)
                self.assertEqual({}, self.daemon.containers)
                if case == "tag":
                    self.assertEqual([], self.daemon.calls)

    def test_stages_exact_committed_bytes_and_finalizes_only_after_positive_worker_removal(self):
        index = (self.repo / ".git" / "index").read_bytes()
        hook_called = []

        def verify(base, candidate, outcome):
            self.assertEqual({}, self.daemon.containers)
            self.assertFalse(self.runner.stopped(self.job["attempt_id"]))
            self.assertEqual(["cli.py"], sorted(path.name for path in base.iterdir()))
            self.assertEqual(_ORIGINAL, (base / "cli.py").read_bytes())
            self.assertEqual(_CHANGED, (candidate / "cli.py").read_bytes())
            self.assertEqual("candidate", outcome["status"])
            hook_called.append(True)
            return {"diff": "verified by trusted callback"}

        result = self.run_job(verify)
        self.assertEqual("verified", result["status"], result)
        self.assertEqual({"diff": "verified by trusted callback"}, result["result"])
        self.assertEqual([True], hook_called)
        staged = next(iter(self.daemon.stage.values()))
        self.assertEqual(runtime._json(runtime._file_line("cli.py", 0o644, _ORIGINAL)), staged[0])
        self.assertEqual([{"kind": "stage_end"}], staged[1:])
        self.assertEqual(self.job["prompt"], self.daemon.request["job"]["prompt"])
        self.assertEqual("/scratch/project", self.daemon.request["workspace"])
        self.assertNotIn(str(self.repo), repr(self.daemon.calls))
        self.assertEqual(index, (self.repo / ".git" / "index").read_bytes())
        self.assertEqual(b"DIRTY WORKTREE\n", (self.repo / "cli.py").read_bytes())
        self.assertEqual(b"NOT IN THE SNAPSHOT\n", (self.repo / "local-only.txt").read_bytes())
        self.assertTrue(self.runner.stopped(self.job["attempt_id"]))
        self.assertFalse(self.runner._attempt(self.job["attempt_id"]).scratch.exists())

    def test_rejects_git_link_entry_before_container_creation(self):
        oid = self.git_run("rev-parse", "HEAD:cli.py").strip().decode()
        self.git_run("update-index", "--add", "--cacheinfo", f"120000,{oid},link.txt")
        self.git_run("commit", "--quiet", "-m", "synthetic Git link entry")
        self.job["base_revision"] = self.git_run("rev-parse", "HEAD").strip().decode()
        result = self.run_job()
        self.assertEqual(("blocked", "unsupported_project_blob"), (result["status"], result["failure_code"]))
        self.assertEqual([], self.daemon.launches)
        self.assertFalse(any(args[0] == "create" for args in self.daemon.calls))

    def test_untrusted_outcome_and_unsafely_named_snapshot_never_finalize(self):
        for label in ("forged status", "out-of-root name", "no exit proof"):
            with self.subTest(label=label):
                self.job["attempt_id"] = uuid4().hex
                self.daemon.outcome = _outcome("verified" if label == "forged status" else "candidate")
                path = "../outside.py" if label == "out-of-root name" else "cli.py"
                self.daemon.worker_snapshot = runtime._file_line(path, 0o644, _CHANGED)
                self.daemon.exit_after_attach = label != "no exit proof"
                result = self.run_job()
                self.assertEqual("failed", result["status"])
                self.assertNotIn("result", result)
                self.assertTrue(self.runner.stopped(self.job["attempt_id"]))
                self.assertEqual({}, self.daemon.containers)

    def test_prelaunch_tombstone_prevents_ever_starting_unknown_attempt(self):
        self.assertFalse(self.runner.cancel(self.job["attempt_id"]))
        self.assertFalse(self.runner.stopped(self.job["attempt_id"]))
        result = self.run_job()
        self.assertEqual("cancelled", result["status"])
        self.assertEqual([], self.daemon.calls)
        self.assertTrue(self.runner.stopped(self.job["attempt_id"]))

    def test_cancel_keeps_slot_fenced_until_active_attempt_and_finalizer_return(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def verify(_base, _candidate, _outcome):
            entered.set()
            self.assertTrue(release.wait(5))
            return {"should_not_publish": True}

        thread, results = self.start_job(verify)
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual({}, self.daemon.containers)
            restarted = _DockerFakeRuntime(self.root, self.engine, self.daemon)
            self.assertFalse(restarted.cancel(self.job["attempt_id"]))
            self.assertFalse(restarted.stopped(self.job["attempt_id"]))
        finally:
            release.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual("cancelled", results[0]["status"])
        self.assertNotIn("result", results[0])
        self.assertTrue(restarted.stopped(self.job["attempt_id"]))

    def test_cancel_running_worker_preserves_uncertain_state_until_restart_reconciliation(self):
        self.daemon.block_worker = True
        self.daemon.remove_available = False
        thread, results = self.start_job()
        self.assertFalse(self.runner.cancel(self.job["attempt_id"]))
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(("interrupted", "worker_stop_unconfirmed"),
                         (results[0]["status"], results[0]["failure_code"]))
        self.assertTrue(self.runner._attempt(self.job["attempt_id"]).scratch.exists())
        restarted = _DockerFakeRuntime(self.root, self.engine, self.daemon)
        self.daemon.available = False
        self.assertFalse(restarted.stopped(self.job["attempt_id"]))
        self.assertEqual(1, len(self.daemon.containers))
        self.daemon.available = self.daemon.remove_available = True
        self.assertTrue(restarted.stopped(self.job["attempt_id"]))
        self.assertFalse(restarted._attempt(self.job["attempt_id"]).scratch.exists())
        self.assertEqual({}, self.daemon.containers)

    def run_with_controlled_deadline(self, *, setup_seconds, worker_seconds=None):
        # Real Git staging is covered separately. Keep host scheduling and Git
        # latency from competing with this test's deliberate clock advances.
        started = 100.0
        clock = SimpleNamespace(now=started, monotonic=lambda: clock.now)
        steps = []
        self.job["limits"]["max_elapsed_seconds"] = 1.5

        def advance(phase, seconds):
            clock.now += seconds
            steps.append((phase, clock.now - started))

        def stage(_git, _repository, _revision, base, _deadline, _cancelled, _cwd):
            base.mkdir()
            (base / "cli.py").write_bytes(_ORIGINAL)
            advance("staged", setup_seconds)
            return runtime._file_line("cli.py", 0o644, _ORIGINAL)

        if worker_seconds is not None:
            self.daemon.on_worker_wait = lambda: advance("waiting_for_outcome", worker_seconds)
        finalize = Mock()
        with patch.object(runtime, "time", clock), patch.object(runtime, "_stage_repository", side_effect=stage):
            result = self.run_job(finalize)
        finalize.assert_not_called()
        return result, steps

    def test_watchdog_times_out_attachment_and_removes_container(self):
        result, steps = self.run_with_controlled_deadline(setup_seconds=1.0, worker_seconds=0.5)
        diagnostic = f"steps={steps!r}, launches={self.daemon.launches!r}, outcome={result!r}"
        self.assertEqual([("staged", 1.0), ("waiting_for_outcome", 1.5)], steps, diagnostic)
        self.assertTrue(self.daemon.attached.is_set(), diagnostic)
        self.assertEqual(self.job, self.daemon.request["job"])
        self.assertEqual(("timed_out", "attempt_deadline"), (result["status"], result["failure_code"]), diagnostic)
        self.assertEqual(1.5, result["usage"]["elapsed_seconds"])
        (cid, worker), = self.daemon.launches
        self.assertTrue(worker)
        self.assertEqual([(cid, "running")], self.daemon.removed, diagnostic)
        self.assertEqual({}, self.daemon.containers)
        self.assertFalse(self.runner._attempt(self.job["attempt_id"]).scratch.exists())
        self.assertTrue(self.runner.stopped(self.job["attempt_id"]))

    def test_watchdog_counts_setup_in_attempt_deadline_and_does_not_launch(self):
        result, steps = self.run_with_controlled_deadline(setup_seconds=1.5)
        diagnostic = f"steps={steps!r}, commands={[args[0] for args in self.daemon.calls]!r}, outcome={result!r}"
        self.assertEqual([("staged", 1.5)], steps, diagnostic)
        self.assertEqual(("timed_out", "attempt_deadline"), (result["status"], result["failure_code"]), diagnostic)
        self.assertEqual({"model_calls": 0, "tool_calls": 0, "elapsed_seconds": 1.5}, result["usage"])
        self.assertFalse(self.daemon.attached.is_set(), diagnostic)
        self.assertFalse(any(args[0] == "create" for args in self.daemon.calls), diagnostic)
        self.assertEqual({}, self.daemon.containers)
        self.assertFalse(self.runner._attempt(self.job["attempt_id"]).scratch.exists())
        self.assertTrue(self.runner.stopped(self.job["attempt_id"]))

    def test_oracle_has_separate_ids_exact_capture_and_readonly_disposable_scope(self):
        with self.assertRaisesRegex(ValueError, "active trusted finalizer"):
            self.runner.check(self.repo, ["python", "-B", "cli.py", "ok"])

        def verify(base, candidate, _outcome):
            frozen = base.parent / "independent" / "frozen"
            shutil.copytree(candidate, frozen)
            for path, argv in (
                (frozen, ["python", "-B", "-c", "print(7)"]),
                (self.repo, ["python", "-B", "cli.py", "ok"]),
                (candidate, ["python", "-B", "cli.py", "ok"]),
            ):
                with self.assertRaises(ValueError):
                    self.runner.check(path, argv)
            success = self.runner.check(frozen, ["python", "-B", "cli.py", "ok"])
            invalid = self.runner.check(frozen, ["python", "-B", "cli.py", "--invalid"])
            self.assertEqual({"exit_code": 0, "stdout": b"after\n", "stderr": b""}, success)
            self.assertEqual({"exit_code": 2, "stdout": b"", "stderr": b"invalid input\n"}, invalid)
            self.assertEqual(_CHANGED, (frozen / "cli.py").read_bytes())
            return {"checked_both_inputs": True}

        result = self.run_job(verify)
        self.assertEqual("verified", result["status"], result)
        self.assertEqual(3, len({cid for cid, _kind in self.daemon.launches}))
        self.assertEqual([True, False, False], [kind for _cid, kind in self.daemon.launches])
        self.assertTrue(all("--network=none" in args and "--read-only" in args
                            for args in self.daemon.calls if args[0] == "create"))
        self.assertEqual({}, self.daemon.containers)

    def test_oracle_failed_cleanup_is_not_downgraded_to_safe_verification_failure(self):
        def verify(base, candidate, _outcome):
            frozen = base.parent / "frozen"
            shutil.copytree(candidate, frozen)
            self.daemon.remove_available = False
            with self.assertRaisesRegex(ValueError, "oracle stop unconfirmed"):
                self.runner.check(frozen, ["python", "-B", "cli.py", "ok"])
            return {"fake_verifier_attempted_to_hide_error": True}

        result = self.run_job(verify)
        self.assertEqual(("interrupted", "worker_stop_unconfirmed"), (result["status"], result["failure_code"]))
        self.assertNotIn("result", result)
        self.assertFalse(self.runner.stopped(self.job["attempt_id"]))
        self.daemon.remove_available = True
        self.assertTrue(self.runner.stopped(self.job["attempt_id"]))


class RuntimeBoundaryTests(unittest.TestCase):
    def test_isolated_python_command_preserves_authored_cli_sibling_imports(self):
        # Authored, fixed fixture only: this validates the interpreter invocation,
        # not Docker isolation, and never executes worker output on the host.
        with tempfile.TemporaryDirectory(prefix="oracle-launcher-", dir=_PROJECT / ".runtime-proof") as temp:
            fixture = Path(temp)
            (fixture / "messages.py").write_bytes(b"SUCCESS = b'SHIPPED\\n'\n")
            cli = fixture / "cli.py"
            cli.write_bytes(
                b"import sys\nfrom messages import SUCCESS\n"
                b"assert sys.flags.isolated and sys.flags.dont_write_bytecode\n"
                b"if sys.argv[1:] != ['ok']:\n"
                b"    sys.stderr.buffer.write(b'invalid input\\n')\n    raise SystemExit(2)\n"
                b"sys.stdout.buffer.write(SUCCESS)\n"
            )
            for arg, expected in (
                ("ok", (0, b"SHIPPED\n", b"")),
                ("--invalid", (2, b"", b"invalid input\n")),
            ):
                result = runtime._capture(
                    [sys.executable, *runtime._oracle_command(str(cli), [arg])], runtime._host_environment(),
                    _PROJECT, time.monotonic() + 5, lambda: False,
                )
                self.assertEqual(expected, (result.returncode, result.stdout, result.stderr))
            self.assertEqual(["cli.py", "messages.py"], sorted(path.name for path in fixture.iterdir()))

    def test_provider_allowlist_and_call_budget_are_enforced_before_network_io(self):
        bridge = runtime._Bridge(1, time.monotonic() + 4, lambda: False)
        payload = {"model": runtime.GEMMA_MODEL, "messages": [{"role": "user", "content": "fixture"}]}
        tags = {"kind": "provider", "op": "get", "path": "/api/tags", "timeout": 1, "payload": None}
        chat = dict(tags, op="post", path="/api/chat", payload=payload)
        catalog = runtime._line({"models": [
            {"name": runtime.GEMMA_MODEL, "digest": runtime._GEMMA_DIGEST},
            {"name": "unrelated-local-model", "digest": "not-exposed"},
        ]}).decode()
        with patch.object(runtime, "_local_http", side_effect=[(200, catalog), (200, '{"message":"fixture"}')]) as http:
            for denied in (
                dict(tags, path="http://127.0.0.1:42/api/tags"),
                dict(chat, path="/api/pull"),
                dict(chat, path="/api/chat?model=other"),
                dict(chat, payload=dict(payload, model="other")),
                dict(chat, payload=dict(payload, stream=True)),
                dict(chat, payload=dict(payload, options={"num_predict": -1})),
            ):
                self.assertEqual("provider_request_denied", bridge.handle(denied)["error"])
            http.assert_not_called()
            listing = bridge.handle(tags)["text"]
            self.assertNotIn("unrelated", listing)
            self.assertEqual(200, bridge.handle(chat)["status_code"])
            self.assertEqual("provider_call_budget_exhausted", bridge.handle(chat)["error"])
            self.assertEqual([("GET", "/api/tags"), ("POST", "/api/chat")],
                             [call.args[:2] for call in http.call_args_list])
            outgoing = runtime._json(http.call_args.args[2])
            self.assertEqual(runtime.GEMMA_MODEL, outgoing["model"])
            self.assertIs(False, outgoing["stream"])
            self.assertEqual(1, bridge.calls)

    def test_unpinned_catalog_prevents_model_dispatch(self):
        bridge = runtime._Bridge(1, time.monotonic() + 4, lambda: False)
        response = runtime._line({"models": [{"name": runtime.GEMMA_MODEL, "digest": "wrong"}]}).decode()
        with patch.object(runtime, "_local_http", return_value=(200, response)) as http:
            result = bridge.handle({
                "kind": "provider", "op": "post", "path": "/api/show",
                "timeout": 2, "payload": {"model": runtime.GEMMA_MODEL},
            })
        self.assertEqual("pinned_local_model_unavailable", result["error"])
        self.assertEqual(("GET", "/api/tags"), http.call_args.args[:2])
        self.assertEqual(1, http.call_count)
        self.assertEqual(0, bridge.calls)

    def test_process_limits_stdout_stderr_and_time_without_docker(self):
        cases = (
            ("import sys; sys.stdout.buffer.write(b'x' * 8192)", 4, "process_output_limit"),
            ("import sys; sys.stderr.buffer.write(b'x' * 8192)", 4, "process_output_limit"),
            ("import time; time.sleep(5)", 0.15, "attempt_deadline"),
        )
        for program, seconds, expected in cases:
            with self.subTest(code=expected, fixture=program):
                with self.assertRaisesRegex(runtime._Failure, expected):
                    runtime._capture(
                        [sys.executable, "-I", "-B", "-c", program], runtime._host_environment(), _PROJECT,
                        time.monotonic() + seconds, lambda: False, limit=1024,
                    )


if __name__ == "__main__":
    unittest.main()
