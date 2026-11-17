import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from hivo.sessions import SessionStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TerminalSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix=".terminal-sessions-test-", dir=PROJECT_ROOT
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.other_workspace = self.root / "other-workspace"
        self.workspace.mkdir()
        self.other_workspace.mkdir()
        self.store = SessionStore(self.root / "private-state")

    def test_catalogue_and_truthful_turns_survive_new_process(self):
        marker = self.workspace / "user-owned.txt"
        marker.write_bytes(b"not permission to execute or overwrite\n")
        first = self.store.create(self.workspace, "Original")
        second = self.store.create(self.other_workspace, "Second")
        prompt = "اكتب الملف\nwithout losing the original prompt"
        running = self.store.start_turn(first.id, prompt)
        log_bytes = "تفاصيل request\ncomplete local diagnostics\n".encode("utf-8")
        running.log_path.write_bytes(log_bytes)
        completed = self.store.finish_turn(
            running.id, status="completed", summary="تم\nliteral [summary]", run_id="run-42"
        )
        unfinished = self.store.start_turn(first.id, "Interrupted before any result")
        self.store.rename(first.id, "Saved جلسة")
        self.store.select(first.id)

        script = """
import json
import sys
from dataclasses import asdict
from pathlib import Path
from hivo.sessions import SessionStore

store = SessionStore(Path(sys.argv[1]))
session = store.resolve("SAVED جلسة")
observed = {
    "session": asdict(session),
    "turns": [asdict(turn) for turn in store.history(session.id)],
    "recent": store.list()[0].id,
    "engine_loaded": "mini" in sys.modules,
}
store.rename(session.id, "Renamed after restart")
store.select(sys.argv[2])
print(json.dumps(observed, default=str, ensure_ascii=False))
"""
        child = subprocess.run(
            [
                sys.executable, "-X", "utf8", "-B", "-c", script,
                str(self.store.state_dir), second.id,
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        observed = json.loads(child.stdout)
        self.assertEqual(observed["session"]["id"], first.id)
        self.assertEqual(observed["session"]["name"], "Saved جلسة")
        self.assertEqual(observed["session"]["workspace"], str(self.workspace.resolve()))
        self.assertEqual(observed["recent"], first.id)
        self.assertFalse(observed["engine_loaded"])
        self.assertEqual(
            [turn["status"] for turn in observed["turns"]], ["completed", "running"]
        )
        self.assertEqual(observed["turns"][0]["prompt"], prompt)
        self.assertEqual(observed["turns"][0]["summary"], "تم\nliteral [summary]")
        self.assertEqual(observed["turns"][0]["run_id"], "run-42")
        self.assertEqual(observed["turns"][0]["log_path"], str(completed.log_path))
        self.assertEqual(observed["turns"][0]["finished_at"], completed.finished_at)
        self.assertIsNone(observed["turns"][1]["finished_at"])

        reopened = SessionStore(self.store.state_dir)
        self.assertEqual(reopened.get(first.id).name, "Renamed after restart")
        self.assertEqual(reopened.get(first.id).workspace, first.workspace)
        self.assertEqual(reopened.list()[0].id, second.id)
        self.assertEqual(reopened.history(first.id), [completed, unfinished])
        self.assertEqual(completed.log_path.read_bytes(), log_bytes)
        reopened.start_turn(first.id, "A fresh request, not an automatic replay")
        self.assertEqual(reopened.history(first.id)[1], unfinished)
        self.assertEqual(list(self.workspace.iterdir()), [marker])
        self.assertEqual(marker.read_bytes(), b"not permission to execute or overwrite\n")
        self.assertEqual(list(self.other_workspace.iterdir()), [])

    def test_resolution_rejects_ambiguous_names_prefixes_and_cross_matches(self):
        ids = [
            UUID("abc00000-0000-0000-0000-000000000001"),
            UUID("abc11111-0000-0000-0000-000000000002"),
            UUID("def00000-0000-0000-0000-000000000003"),
        ]
        with patch("hivo.sessions.uuid4", side_effect=ids):
            first = self.store.create(self.workspace, "Straße")
            second = self.store.create(self.other_workspace, "Twin")
            third = self.store.create(self.workspace, "tWiN")
        self.assertEqual(self.store.resolve(first.id).id, first.id)
        self.assertEqual(self.store.resolve("STRASSE").id, first.id)
        self.assertEqual(self.store.resolve("abc0").id, first.id)
        before = self.store.list()
        for reference in ("abc", "TWIN"):
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                self.store.resolve(reference)
        self.assertEqual(self.store.list(), before)

        self.store.rename(first.id, second.id[:8])
        with self.assertRaises(ValueError):
            self.store.resolve(second.id[:8])
        self.store.rename(third.id, first.id)
        self.assertEqual(self.store.resolve(first.id).id, first.id)

    def test_names_and_workspaces_validate_without_creating_workspaces(self):
        original = self.store.create(self.workspace, "  Readable جلسة  ")
        self.assertEqual(original.name, "Readable جلسة")
        invalid_names = ("", " \t ", "bad\nname", "\x1b[31mred", "nul\0name", "n" * 10000, 3)
        for name in invalid_names:
            with self.subTest(name=repr(name)[:60]):
                with self.assertRaises(ValueError):
                    self.store.create(self.workspace, name)
                with self.assertRaises(ValueError):
                    self.store.rename(original.id, name)
        missing = self.root / "must-not-be-created"
        with self.assertRaises(FileNotFoundError):
            self.store.create(missing)
        self.assertFalse(missing.exists())
        not_directory = self.root / "a-file"
        not_directory.write_bytes(b"user file")
        with self.assertRaises(NotADirectoryError):
            self.store.create(not_directory)
        self.assertEqual(self.store.list(), [original])
        self.assertEqual(not_directory.read_bytes(), b"user file")
        default = self.store.create(self.other_workspace)
        self.assertEqual(default.workspace, self.other_workspace.resolve())
        self.assertTrue(default.name.strip())

    def test_unknown_references_fail_without_changing_recency(self):
        self.store.create(self.workspace, "Existing")
        before = self.store.list()
        calls = [
            lambda: self.store.get("unknown"),
            lambda: self.store.resolve("unknown"),
            lambda: self.store.resolve(""),
            lambda: self.store.select("unknown"),
            lambda: self.store.rename("unknown", "New"),
            lambda: self.store.start_turn("unknown", "Do not execute"),
            lambda: self.store.history("unknown"),
            lambda: self.store.finish_turn("unknown", status="failed", summary="No turn"),
        ]
        for index, call in enumerate(calls):
            with self.subTest(operation=index), self.assertRaises(KeyError):
                call()
        self.assertEqual(self.store.list(), before)
        self.assertFalse((self.store.state_dir / "logs").exists())

    def test_select_rejects_removed_or_replaced_workspace_without_recreation(self):
        first = self.store.create(self.workspace, "First")
        second = self.store.create(self.other_workspace, "Second")
        self.store.select(second.id)
        before = self.store.list()
        self.workspace.rmdir()
        with self.assertRaises(FileNotFoundError):
            self.store.select(first.id)
        self.assertFalse(self.workspace.exists())
        self.assertEqual(self.store.list(), before)
        self.workspace.write_bytes(b"not a workspace directory")
        with self.assertRaises(NotADirectoryError):
            self.store.select(first.id)
        self.assertEqual(self.store.list(), before)
        self.assertEqual(self.workspace.read_bytes(), b"not a workspace directory")
        self.workspace.unlink()
        self.workspace.mkdir()
        selected = self.store.select(first.id)
        reopened = SessionStore(self.store.state_dir)
        self.assertEqual(reopened.list()[0], selected)
        self.assertEqual(selected.workspace, first.workspace)

    def test_finish_is_explicit_and_cannot_rewrite_terminal_status(self):
        session = self.store.create(self.workspace)
        for status in ("completed", "failed", "cancelled", "blocked"):
            with self.subTest(status=status):
                started = self.store.start_turn(session.id, f"Request ending {status}")
                finished = self.store.finish_turn(
                    started.id, status=status, summary=f"Actual {status}", run_id="real-run"
                )
                self.assertEqual(finished.status, status)
                self.assertIsNotNone(finished.finished_at)
                self.assertGreaterEqual(finished.finished_at, finished.started_at)
                with self.assertRaises(ValueError):
                    self.store.finish_turn(
                        finished.id, status="completed", summary="Cannot rewrite history"
                    )
                self.assertEqual(self.store.history(session.id)[-1], finished)

        running = self.store.start_turn(session.id, "Still running")
        for status in ("running", "", "invented-success", None):
            with self.subTest(invalid_status=status), self.assertRaises(ValueError):
                self.store.finish_turn(running.id, status=status, summary="No result")
        with self.assertRaises(ValueError):
            self.store.finish_turn(running.id, status="failed", summary=None)
        with self.assertRaises(ValueError):
            self.store.finish_turn(running.id, status="failed", summary="", run_id=None)
        self.assertEqual(SessionStore(self.store.state_dir).history(session.id)[-1], running)
        for prompt in ("", " \n ", None):
            with self.subTest(prompt=prompt), self.assertRaises(ValueError):
                self.store.start_turn(session.id, prompt)

    def test_history_returns_latest_bounded_turns_in_creation_order(self):
        session = self.store.create(self.workspace)
        other = self.store.create(self.other_workspace)
        with patch("hivo.sessions._now", return_value="2026-11-17T13:00:00.000000+00:00"):
            for index in range(23):
                self.store.start_turn(session.id, f"Request {index}")
            self.store.start_turn(other.id, "Must not leak into another session")
        reopened = SessionStore(self.store.state_dir)
        self.assertEqual(
            [turn.prompt for turn in reopened.history(session.id, limit=2)],
            ["Request 21", "Request 22"],
        )
        self.assertEqual(
            [turn.prompt for turn in reopened.history(session.id)],
            [f"Request {index}" for index in range(3, 23)],
        )
        self.assertEqual(len(reopened.history(session.id, limit=100)), 23)
        for limit in (0, -1, 101, True, 1.5, "2", None):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                reopened.history(session.id, limit=limit)

    def test_log_paths_use_opaque_ids_not_display_names(self):
        session = self.store.create(self.workspace, "../../outside [markup]")
        first = self.store.start_turn(session.id, "First")
        second = self.store.start_turn(session.id, "Second")
        self.store.rename(session.id, "Different name")
        self.assertNotEqual(first.log_path, second.log_path)
        for turn in (first, second):
            self.assertEqual(
                turn.log_path, self.store.state_dir / "logs" / session.id / f"{turn.id}.log"
            )
            self.assertTrue(turn.log_path.is_file())
            self.assertEqual(turn.log_path.read_bytes(), b"")
        self.assertEqual(SessionStore(self.store.state_dir).history(session.id), [first, second])
        self.assertFalse((self.root / "outside [markup]").exists())

    def test_log_storage_failure_is_explicit_and_does_not_record_a_turn(self):
        session = self.store.create(self.workspace)
        (self.store.state_dir / "logs").write_bytes(b"blocks log directories")
        with self.assertRaises(OSError):
            self.store.start_turn(session.id, "Must not run without a durable log")
        self.assertEqual(self.store.history(session.id), [])
        self.assertEqual(self.store.get(session.id), session)

    def test_transaction_failures_roll_back_turn_and_session_updates(self):
        session = self.store.create(self.workspace)
        trigger = """
            CREATE TRIGGER reject_activity BEFORE UPDATE ON sessions
            BEGIN SELECT RAISE(ABORT, 'storage rejected update'); END
        """
        with closing(sqlite3.connect(self.store.db_path)) as connection:
            connection.execute(trigger)
            connection.commit()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "storage rejected update"):
            self.store.start_turn(session.id, "Insert must roll back")
        self.assertEqual(self.store.history(session.id), [])
        self.assertEqual(self.store.get(session.id), session)
        self.assertEqual(list((self.store.state_dir / "logs").rglob("*.log")), [])

        with closing(sqlite3.connect(self.store.db_path)) as connection:
            connection.execute("DROP TRIGGER reject_activity")
            connection.commit()
        running = self.store.start_turn(session.id, "Finish must roll back")
        before = self.store.get(session.id)
        with closing(sqlite3.connect(self.store.db_path)) as connection:
            connection.execute(trigger)
            connection.commit()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "storage rejected update"):
            self.store.finish_turn(running.id, status="completed", summary="Not committed")
        reopened = SessionStore(self.store.state_dir)
        self.assertEqual(reopened.history(session.id), [running])
        self.assertEqual(reopened.get(session.id), before)
        self.assertTrue(running.log_path.is_file())

    def test_invalid_state_directory_and_corrupt_database_fail_explicitly(self):
        not_directory = self.root / "state-is-a-file"
        not_directory.write_bytes(b"preserve me")
        with self.assertRaises(OSError):
            SessionStore(not_directory)
        self.assertEqual(not_directory.read_bytes(), b"preserve me")
        self.store.db_path.write_bytes(b"not a SQLite catalogue")
        with self.assertRaises(sqlite3.DatabaseError):
            SessionStore(self.store.state_dir)


if __name__ == "__main__":
    unittest.main()
