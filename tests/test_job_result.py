import copy
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from hivo.job_result import snapshot_digest, verify_candidate
from hivo.job_runtime import _oracle_command


_PROJECT = Path(__file__).resolve().parents[1]
_PLAN = "a" * 64
_MESSAGES = b"""import sys

def write_success(message):
    sys.stdout.buffer.write(message.encode("utf-8") + b"\\n")
"""
_BASE_CLI = b"""import sys
from messages import write_success

if sys.argv[1:] != ["valid"]:
    sys.stderr.buffer.write(b"invalid input\\n")
    raise SystemExit(2)
write_success("old message")
"""
_ACCEPTED_CLI = _BASE_CLI.replace(b"old message", b"new message")
_MISLEADING_CLI = _BASE_CLI.replace(b"old message", b"PASS")
_BROKEN_INVALID_CLI = _ACCEPTED_CLI.replace(b"raise SystemExit(2)", b"raise SystemExit(0)")
_AUTHORED = {_BASE_CLI, _ACCEPTED_CLI, _MISLEADING_CLI, _BROKEN_INVALID_CLI}
_PASS = [{"check_id": "test-inventory", "passed": True}]


def _process_env():
    return {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR"}}


def _run_cli(root, argument):
    result = subprocess.run(
        [sys.executable, *_oracle_command(str(root / "cli.py"), [argument])],
        cwd=root, env=_process_env(), capture_output=True, timeout=10,
    )
    return result.returncode, result.stdout, result.stderr


def _cli_oracle(_job, root):
    # This fixture runs only known, checked-in test source, never model output.
    # Expected behavior lives here, not in files generated or edited by a job.
    if (
        sorted(p.name for p in root.iterdir()) != ["cli.py", "messages.py"]
        or (root / "cli.py").read_bytes() not in _AUTHORED
        or (root / "messages.py").read_bytes() != _MESSAGES
    ):
        return [{"check_id": "authored-fixture", "passed": False}]
    return [
        {"check_id": "success-message", "passed": _run_cli(root, "valid") == (0, b"new message\n", b"")},
        {"check_id": "invalid-input", "passed": _run_cli(root, "invalid") == (2, b"", b"invalid input\n")},
    ]


class JobResultTests(unittest.TestCase):
    def setUp(self):
        state = _PROJECT / ".runtime-proof"
        state.mkdir(exist_ok=True)
        scratch = tempfile.TemporaryDirectory(prefix="test-job-result-", dir=state)
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name) / "scratch"
        self.base, self.work = self.scratch / "base", self.scratch / "candidate"
        self.base.mkdir(parents=True)
        self.work.mkdir()
        (self.base / "cli.py").write_bytes(_BASE_CLI)
        (self.work / "cli.py").write_bytes(_ACCEPTED_CLI)
        for root in (self.base, self.work):
            (root / "messages.py").write_bytes(_MESSAGES)

    def _git(self, root, *args, data=b""):
        env = _process_env()
        env.update(
            GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
            GIT_CEILING_DIRECTORIES=str(self.scratch.parent),
            GIT_AUTHOR_DATE="2026-11-18 00:00:00 +0000",
            GIT_COMMITTER_DATE="2026-11-18 00:00:00 +0000",
        )
        return subprocess.run(
            ["git", "--no-pager", "-c", "core.autocrlf=false", *args],
            cwd=root, env=env, input=data, capture_output=True, check=True, timeout=10,
        ).stdout

    def _evidence(self, allowed=("cli.py",), revision="b" * 40):
        job = {
            "job_id": "fixture-job", "attempt_id": "current-attempt", "base_revision": revision,
            "checkpoint": {"base_sha256": snapshot_digest(self.base), "allowed_paths": list(allowed)},
            "decision_request": {
                "kind": "approval", "decision_id": "fixture-approval", "plan_hash": _PLAN,
                "plan_summary": "Change the successful message without changing invalid input.",
            },
            "decision": {
                "kind": "approve", "decision_id": "fixture-approval", "plan_hash": _PLAN, "actor_id": "operator",
            },
        }
        outcome = {"status": "candidate", "evidence": {
            "root_verified": True,
            "job_id": job["job_id"], "attempt_id": job["attempt_id"], "base_revision": revision,
            "plan_hash": _PLAN, "allowed_paths": list(allowed), "workspace_sha256": snapshot_digest(self.work),
        }}
        return job, outcome

    def test_authored_cli_patch_and_consumer_preserve_original_and_invalid_input(self):
        origin = self.scratch.parent / "registered-source"
        origin.mkdir()
        self._git(origin, "init", "--quiet", "--template=", "--object-format=sha1")
        (origin / "cli.py").write_bytes(_BASE_CLI)
        (origin / "messages.py").write_bytes(_MESSAGES)
        self._git(origin, "add", "--", "cli.py", "messages.py")
        tree = self._git(origin, "write-tree").decode("ascii").strip()
        revision = self._git(
            origin, "-c", "user.name=Evidence Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgSign=false", "commit-tree", tree, "-m", "Authored CLI fixture", "-m",
            "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>",
        ).decode("ascii").strip()
        for path, authored in {"cli.py": _BASE_CLI, "messages.py": _MESSAGES}.items():
            approved_blob = self._git(origin, "cat-file", "blob", f"{revision}:{path}")
            self.assertEqual(approved_blob, authored)
            (self.base / path).write_bytes(approved_blob)
        self.assertEqual(_run_cli(self.base, "valid"), (0, b"old message\n", b""))
        self.assertEqual(_run_cli(self.base, "invalid"), (2, b"", b"invalid input\n"))

        (self.work / ".hivo").mkdir()
        (self.work / ".hivo" / "claimed-proof").write_bytes(b"PASS")
        job, outcome = self._evidence(revision=revision)
        checked_paths = []

        def oracle(safely_detached_job, materialized):
            checked_paths.append(materialized)
            relative = materialized.relative_to(self.work.parent)
            self.assertNotIn(relative.parts[0], {"base", "candidate", "engine"})
            self.assertEqual(materialized, materialized.resolve(strict=True))
            return _cli_oracle(safely_detached_job, materialized)

        result = verify_candidate(job, self.base, self.work, outcome, oracle)
        delivered = result["diff"].encode("utf-8")
        self.assertEqual(result["base_revision"], revision)
        self.assertEqual(result["changed_paths"], ["cli.py"])
        self.assertEqual(result["patch_sha256"], hashlib.sha256(delivered).hexdigest())
        self.assertEqual(result["checks"], [
            {"check_id": "success-message", "passed": True},
            {"check_id": "invalid-input", "passed": True},
        ])
        self.assertEqual(len(checked_paths), 1)
        self.assertFalse(checked_paths[0].exists())

        consumer = self.scratch.parent / "patch-consumer"
        consumer.mkdir()
        for path in ("cli.py", "messages.py"):
            (consumer / path).write_bytes(self._git(origin, "cat-file", "blob", f"{revision}:{path}"))
        self._git(consumer, "apply", "-", data=delivered)
        self.assertEqual(snapshot_digest(consumer), result["workspace_sha256"])
        self.assertTrue(all(check["passed"] for check in _cli_oracle(job, consumer)))
        self.assertEqual((origin / "cli.py").read_bytes(), _BASE_CLI)
        self.assertEqual((origin / "messages.py").read_bytes(), _MESSAGES)
        self.assertEqual((self.base / "cli.py").read_bytes(), _BASE_CLI)

    def test_wrong_behavior_fails_despite_root_verified_and_printed_pass(self):
        for authored in (_MISLEADING_CLI, _BROKEN_INVALID_CLI):
            with self.subTest(authored=authored):
                (self.work / "cli.py").write_bytes(authored)
                job, outcome = self._evidence()
                with self.assertRaisesRegex(ValueError, "independent behavior checks failed"):
                    verify_candidate(job, self.base, self.work, outcome, _cli_oracle)

    def test_oracle_does_not_execute_unrecognized_candidate(self):
        (self.work / "cli.py").write_bytes(b"# Not an authored fixture variant\n")
        job, outcome = self._evidence()
        with patch(f"{__name__}._run_cli") as execute:
            with self.assertRaisesRegex(ValueError, "independent behavior checks failed"):
                verify_candidate(job, self.base, self.work, outcome, _cli_oracle)
            execute.assert_not_called()

    def test_roundtrip_text_add_delete_and_exact_line_endings(self):
        (self.base / "removed").write_bytes(b"no final newline")
        (self.base / "has space.txt").write_bytes(b"before\r\nlast")
        (self.work / "has space.txt").write_bytes("caf\u00e9\r\nlast\r\n".encode("utf-8"))
        (self.work / "new").mkdir()
        (self.work / "new" / "\u00e9.txt").touch()
        allowed = ("removed", "cli.py", "new/\u00e9.txt", "has space.txt")
        job, outcome = self._evidence(allowed)
        outcome["evidence"]["allowed_paths"].reverse()
        expected = {
            "cli.py": _ACCEPTED_CLI,
            "messages.py": _MESSAGES,
            "has space.txt": "caf\u00e9\r\nlast\r\n".encode("utf-8"),
            "new/\u00e9.txt": b"",
        }

        def check(_job, replay):
            actual = {p.relative_to(replay).as_posix(): p.read_bytes() for p in replay.rglob("*") if p.is_file()}
            return [{"check_id": "exact-tree", "passed": actual == expected}]

        result = verify_candidate(job, self.base, self.work, outcome, check)
        self.assertEqual(result["changed_paths"], sorted(allowed))

    def test_exact_delivered_patch_is_replayed_before_oracle(self):
        job, outcome = self._evidence()
        good = verify_candidate(job, self.base, self.work, outcome, _cli_oracle)["diff"].encode("utf-8")
        altered = good.replace(b"new message", b"different but applicable")
        self.assertNotEqual(altered, good)
        checker = Mock(return_value=_PASS)
        with patch("hivo.job_result._render_patch", return_value=altered):
            with self.assertRaisesRegex(ValueError, "did not reproduce the candidate"):
                verify_candidate(job, self.base, self.work, outcome, checker)
        checker.assert_not_called()

    def test_stale_or_misattributed_evidence_never_calls_oracle(self):
        job, outcome = self._evidence()
        checker = Mock(return_value=_PASS)
        for field, value in {
            "job_id": "other-job", "attempt_id": "retired-attempt", "base_revision": "e" * 40,
            "plan_hash": "e" * 64, "root_verified": "PASS", "workspace_sha256": "e" * 64,
            "allowed_paths": ["cli.py", "unapproved.txt"],
        }.items():
            with self.subTest(field=field):
                altered = copy.deepcopy(outcome)
                altered["evidence"][field] = value
                with self.assertRaises(ValueError):
                    verify_candidate(job, self.base, self.work, altered, checker)
        with self.assertRaisesRegex(ValueError, "missing candidate"):
            verify_candidate(job, self.base, self.work, {"status": "verified"}, checker)
        with self.assertRaisesRegex(ValueError, "approved plan"):
            verify_candidate({**job, "decision": {**job["decision"], "decision_id": "old"}}, self.base,
                             self.work, outcome, checker)
        (self.base / "cli.py").write_bytes(b"not the approved base")
        with self.assertRaisesRegex(ValueError, "base snapshot is stale"):
            verify_candidate(job, self.base, self.work, outcome, checker)
        checker.assert_not_called()

    def test_scope_and_nontext_changes_stop_before_oracle(self):
        checker = Mock(return_value=_PASS)
        # A broad ".agent_*" exclusion would silently miss this extra file.
        extra = self.work / ".agent_user_config"
        extra.touch()
        job, outcome = self._evidence()
        with self.assertRaisesRegex(ValueError, "outside the approved path scope"):
            verify_candidate(job, self.base, self.work, outcome, checker)
        extra.unlink()
        for invalid_path in ("../cli.py", r"C:\cli.py", "cli.py.", ".hivo/cache", ".git/config"):
            with self.subTest(path=invalid_path):
                job, outcome = self._evidence(("cli.py", invalid_path))
                with self.assertRaises(ValueError):
                    verify_candidate(job, self.base, self.work, outcome, checker)
        for data in (_BASE_CLI, b"binary\0", b"not UTF-8: \xff"):
            (self.work / "cli.py").write_bytes(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                job, outcome = self._evidence()
                verify_candidate(job, self.base, self.work, outcome, checker)
        checker.assert_not_called()

    def test_oracle_requires_explicit_passing_boolean_receipts_and_no_writes(self):
        job, outcome = self._evidence()
        for receipt in (
            "PASS", [], [{"check_id": "valid", "passed": 1}],
            [{"check_id": "valid", "passed": False}], _PASS + _PASS,
        ):
            with self.subTest(receipt=receipt), self.assertRaisesRegex(ValueError, "behavior checks"):
                verify_candidate(job, self.base, self.work, outcome, lambda *_: receipt)

        def mutate(_job, replay):
            (replay / "cli.py").write_bytes(_MISLEADING_CLI)
            return _PASS

        with self.assertRaisesRegex(ValueError, "snapshot changed during verification"):
            verify_candidate(job, self.base, self.work, outcome, mutate)
        self.assertEqual((self.work / "cli.py").read_bytes(), _ACCEPTED_CLI)

    def test_digest_binds_path_and_bytes_and_rejects_hardlinks(self):
        original_digest = snapshot_digest(self.work)
        runtime = self.work / ".agent_runs"
        runtime.mkdir()
        (runtime / "state.json").write_bytes(b"private state")
        self.assertEqual(snapshot_digest(self.work), original_digest)
        original_file = self.work / "cli.py"
        renamed = original_file.rename(self.work / "renamed.py")
        self.assertNotEqual(snapshot_digest(self.work), original_digest)
        renamed.rename(original_file)
        original_file.write_bytes(_ACCEPTED_CLI + b"\n")
        self.assertNotEqual(snapshot_digest(self.work), original_digest)
        os.link(original_file, self.work / "alias.py")
        with self.assertRaisesRegex(ValueError, "links and special"):
            snapshot_digest(self.work)


if __name__ == "__main__":
    unittest.main()
