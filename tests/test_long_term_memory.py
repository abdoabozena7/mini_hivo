import json
import tempfile
import unittest
from pathlib import Path

from hivo.memory import MemoryStore


class LongTermMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.workspace = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_verified_notes_survive_restart_and_retrieve_by_relevance(self):
        first = MemoryStore(self.workspace)
        first.add_note(
            "Browser games need a deterministic state bridge for interaction verification.",
            kind="lesson",
            scope="web_game",
            verified=True,
            importance=0.9,
        )
        first.add_note(
            "Unrelated command line packaging detail.",
            kind="lesson",
            scope="cli",
            verified=True,
        )

        reopened = MemoryStore(self.workspace)
        notes = reopened.retrieve("verify browser game interaction bridge", max_items=2)

        self.assertTrue(notes)
        self.assertIn("deterministic state bridge", notes[0]["content"])
        self.assertEqual(reopened.db_path, self.workspace / ".hivo" / "memory.sqlite3")

    def test_unverified_information_is_not_injected_as_fact(self):
        store = MemoryStore(self.workspace)
        store.add_note("speculative fix that never passed", kind="attempt", verified=False)
        store.add_note("verified successful build command", kind="outcome", verified=True)

        context = store.context_for("successful build", max_items=5, max_chars=500)

        self.assertIn("verified successful build command", context)
        self.assertNotIn("speculative fix", context)

    def test_retrieval_is_bounded_without_loading_history_into_prompt(self):
        store = MemoryStore(self.workspace)
        for index in range(40):
            store.add_note(
                f"verified architecture observation {index} " + ("x" * 180),
                kind="lesson",
                verified=True,
            )

        context = store.context_for("architecture observation", max_items=20, max_chars=420)

        self.assertLessEqual(len(context), 420)
        self.assertLess(context.count("verified architecture observation"), 20)

    def test_run_and_task_ledger_survive_restart(self):
        store = MemoryStore(self.workspace)
        store.begin_run("run-1", "Build an API", {"requirements": ["health endpoint"]})
        store.upsert_task("run-1", "ROOT.S1", "Implement health endpoint", "running", stage_index=1)

        reopened = MemoryStore(self.workspace)
        snapshot = reopened.latest_resumable_run()

        self.assertEqual(snapshot["run_id"], "run-1")
        self.assertEqual(snapshot["goal"], "Build an API")
        self.assertEqual(snapshot["tasks"][0]["task_id"], "ROOT.S1")
        self.assertEqual(snapshot["tasks"][0]["status"], "running")
        context = reopened.resumable_context("continue the API health endpoint")
        self.assertIn("not proof of completion", context)
        self.assertIn("ROOT.S1", context)

    def test_legacy_json_is_imported_once(self):
        legacy = {
            "recent_files": ["index.html"],
            "operations": [
                {"time": "2026-08-27 12:00:00", "tool": "run_command",
                 "args": {"command": "python -m unittest"}, "result": "1 passed"}
            ],
            "last_error": None,
        }
        (self.workspace / ".agent_memory.json").write_text(json.dumps(legacy), encoding="utf-8")

        first = MemoryStore(self.workspace)
        self.assertEqual(first.event_count(), 1)
        second = MemoryStore(self.workspace)
        self.assertEqual(second.event_count(), 1)


if __name__ == "__main__":
    unittest.main()
