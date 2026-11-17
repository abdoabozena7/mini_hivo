import io
import shutil
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console

from hivo.sessions import SessionStore
from hivo.terminal_ui import TerminalApp, list_sessions


class TerminalUITests(unittest.TestCase):
    def setUp(self):
        project = Path(__file__).resolve().parents[1]
        self.root = project / ".runtime-proof" / f"terminal-ui-test-{uuid4().hex}"
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root)
        self.workspace = self.root / "project-1"
        self.workspace.mkdir()
        self.store = SessionStore(self.root / "state")
        self.session = self.store.create(self.workspace, "First")
        self.output = io.StringIO()
        self.console = Console(
            file=self.output, width=60, color_system=None, force_terminal=False,
        )
        self.engine = Mock(return_value={
            "status": "done", "summary": "Created greeting.txt.",
            "run_id": "run-one", "changed_files": ["greeting.txt"],
        })
        self.created = []

        def create_workspace():
            path = self.root / f"project-{len(self.created) + 2}"
            path.mkdir()
            self.created.append(path)
            return path

        self.create_workspace = Mock(side_effect=create_workspace)
        self.app = TerminalApp(
            self.store, self.engine, self.create_workspace, console=self.console,
        )

    def run_script(self, values, *, app=None, session=None):
        app = app or self.app
        reader = Mock()
        reader.prompt.side_effect = [*values, EOFError()]
        with patch.object(app, "_input_session", return_value=reader):
            app.run(session or self.session)

    def keyboard(self, text, action):
        with create_pipe_input() as pipe:
            def make_prompt(*args, **kwargs):
                return PromptSession(
                    *args, input=pipe, output=DummyOutput(), **kwargs,
                )

            # A bad binding must fail the assertions, not leave unittest waiting.
            timeout = threading.Timer(5, pipe.close)
            timeout.start()
            try:
                with patch("hivo.terminal_ui.PromptSession", side_effect=make_prompt):
                    pipe.send_text(text)
                    return action()
            finally:
                timeout.cancel()
                timeout.join()

    def test_quiet_narrow_result_keeps_complete_utf8_diagnostics(self):
        diagnostic = "OLLAMA SHAPE " + ("تفاصيل [bold]literal[/bold] " * 120)
        summary = "Created greeting.txt. " + "Long result detail. " * 50

        def request(prompt, session):
            self.app.detail_print(diagnostic)
            self.app.detail_print("RUN METRICS", {"tokens": 1234})
            self.app.progress("Planning", role="brain", task="ROOT")
            self.app.progress("Writing greeting.txt", action="write", tool="write_file")
            return {"status": "done", "summary": summary, "run_id": "real-id"}

        self.engine.side_effect = request
        self.run_script(["اكتب greeting.txt", "/quit"])
        visible = self.output.getvalue()
        self.assertIn("Hivo", visible)
        self.assertIn("/help", visible)
        self.assertIn("Completed", visible)
        self.assertNotIn("OLLAMA SHAPE", visible)
        self.assertNotIn("RUN METRICS", visible)
        self.assertNotIn("Planning", visible)
        self.assertLessEqual(len([line for line in visible.splitlines() if line.strip()]), 20)
        turn = SessionStore(self.store.state_dir).history(self.session.id)[-1]
        self.assertEqual((turn.status, turn.run_id), ("completed", "real-id"))
        raw = turn.log_path.read_bytes()
        log = raw.decode("utf-8")
        self.assertIn(diagnostic, log)
        self.assertIn(summary, log)
        self.assertIn("اكتب greeting.txt", log)
        self.assertIn('"tool": "write_file"', log)
        self.assertIn(str(turn.log_path), visible.replace("\n", "").replace(" ", ""))

    def test_verbose_and_custom_stream_obey_print_arguments_and_log_all(self):
        destination = io.StringIO()
        self.app.verbose = True

        def request(prompt, session):
            self.app.detail_print("one", "two", sep="|", end="")
            self.app.detail_print("next", end="\n")
            self.app.detail_print("ملف", "value", sep=":", file=destination, flush=True)
            with self.assertRaises(TypeError):
                self.app.detail_print("bad", sep=123)
            return {"status": "completed", "summary": "Ready."}

        self.engine.side_effect = request
        self.run_script(["go", "/quit"])
        self.assertIn("one|twonext", self.output.getvalue())
        self.assertEqual(destination.getvalue(), "ملف:value\n")
        log = self.store.history(self.session.id)[-1].log_path.read_text(encoding="utf-8")
        self.assertIn("one|twonext\n", log)
        self.assertIn("ملف:value\n", log)

    def test_model_markup_and_controls_are_literal_in_output_and_logs(self):
        hostile = "[bold]literal[/bold]\x1b[2J\x07\r\u202e"

        def request(prompt, session):
            self.app.detail_print("[ERROR] " + hostile)
            return {"status": "blocked", "summary": hostile}

        self.engine.side_effect = request
        self.run_script(["safe request", "/quit"])
        turn = self.store.history(self.session.id)[-1]
        for text in (self.output.getvalue(), turn.log_path.read_text(encoding="utf-8")):
            self.assertIn("[bold]literal[/bold]", text)
            self.assertIn("\\x1b[2J", text)
            self.assertIn("\\x07", text)
            self.assertIn("\\x0d", text)
            self.assertIn("\\u202e", text)
            self.assertNotIn("\x1b", text)
            self.assertNotIn("\x07", text)
            self.assertNotIn("\u202e", text)
        self.assertEqual(turn.status, "blocked")

    def test_warning_is_concise_but_full_text_remains_logged(self):
        warning = "[WARN] storage warning " + ("detail " * 150)

        def request(prompt, session):
            self.app.detail_print(warning)
            self.app.detail_print("ordinary hidden detail")
            return {"status": "completed", "summary": "Done with warning."}

        self.engine.side_effect = request
        self.run_script(["go", "/quit"])
        visible = self.output.getvalue()
        self.assertIn("[WARN]", visible)
        self.assertNotIn("ordinary hidden detail", visible)
        self.assertNotIn(warning, visible)
        self.assertIn(
            warning,
            self.store.history(self.session.id)[-1].log_path.read_text(encoding="utf-8"),
        )

    def test_unexpected_failure_logs_traceback_and_next_request_works(self):
        self.engine.side_effect = [
            RuntimeError("provider disconnected"),
            {"status": "completed", "summary": "Recovered."},
        ]
        self.run_script(["first", "retry", "/quit"])
        turns = self.store.history(self.session.id)
        self.assertEqual([turn.status for turn in turns], ["failed", "completed"])
        self.assertIn("provider disconnected", self.output.getvalue())
        log = turns[0].log_path.read_text(encoding="utf-8")
        self.assertIn("Traceback (most recent call last)", log)
        self.assertIn("RuntimeError: provider disconnected", log)
        self.assertFalse(self.app._running)

    def test_cancelled_request_is_not_done_and_following_input_is_usable(self):
        self.engine.side_effect = [
            KeyboardInterrupt(),
            {"status": "done", "summary": "Second finished."},
        ]
        self.run_script(["cancel this", "then this", "/quit"])
        turns = self.store.history(self.session.id)
        self.assertEqual([turn.status for turn in turns], ["cancelled", "completed"])
        self.assertIsNotNone(turns[0].finished_at)
        self.assertIn("Cancelled by user.", turns[0].log_path.read_text(encoding="utf-8"))
        self.assertIn("Cancelled", self.output.getvalue())
        self.assertEqual(self.engine.call_count, 2)

    def test_eof_during_nested_input_cancels_and_quits_safely(self):
        self.engine.side_effect = EOFError()
        self.run_script(["question", EOFError()])
        self.assertEqual(self.store.history(self.session.id)[0].status, "cancelled")
        self.assertIn("Input closed", self.output.getvalue())
        self.assertIn("Goodbye.", self.output.getvalue())

    def test_invalid_engine_result_never_claims_completion(self):
        self.engine.side_effect = [None, {"status": "running", "summary": "not terminal"}]
        self.run_script(["one", "two", "/quit"])
        turns = self.store.history(self.session.id)
        self.assertEqual([turn.status for turn in turns], ["failed", "failed"])
        self.assertNotIn("Completed", self.output.getvalue())
        self.assertIn("invalid status", turns[1].log_path.read_text(encoding="utf-8"))

    def test_real_engine_attention_states_preserve_the_original_summary_and_code(self):
        cases = [
            ("clarification_required", "blocked"), ("needs_clarification", "blocked"),
            ("plan_approval_required", "blocked"), ("plan_rejected", "blocked"),
            ("too_broad", "failed"), ("budget_exhausted", "blocked"),
        ]
        self.engine.side_effect = [
            {"status": status, "summary": f"Original reason: {status}"}
            for status, _ in cases
        ]
        self.run_script([*(status for status, _ in cases), "/quit"])
        turns = self.store.history(self.session.id)
        self.assertEqual([turn.status for turn in turns], [expected for _, expected in cases])
        for turn, (status, _) in zip(turns, cases):
            self.assertEqual(turn.summary, f"Original reason: {status}")
            self.assertIn(f'"status": "{status}"', turn.log_path.read_text(encoding="utf-8"))
        self.assertNotIn("invalid status", self.output.getvalue())
        self.assertNotIn("Completed", self.output.getvalue())

    def test_reopening_immediately_shows_unfinished_work_without_replaying(self):
        self.store.start_turn(self.session.id, "unfinished old request")
        self.run_script(["/quit"])
        self.engine.assert_not_called()
        self.assertIn("unfinished: unfinished old request", self.output.getvalue())
        self.assertIn("Not replayed.", self.output.getvalue())
        self.assertEqual(self.store.history(self.session.id)[-1].status, "running")

    def test_startup_history_error_is_explicit_and_prevents_execution(self):
        with patch.object(self.store, "history", side_effect=OSError("cannot read catalogue")):
            self.run_script(["must not execute", "/quit"])
        self.engine.assert_not_called()
        visible = " ".join(self.output.getvalue().split())
        self.assertIn("cannot restore session history", visible)
        self.assertIn("cannot read catalogue", visible)

    def test_preflight_block_and_callback_exit_remain_truthful_and_recoverable(self):
        self.engine.side_effect = [
            {"status": "blocked", "summary": "Approval required; no changes made."},
            SystemExit("provider setup failed"),
            {"status": "completed", "summary": "Ready again."},
        ]
        self.run_script(["blocked task", "bad setup", "retry", "/quit"])
        turns = self.store.history(self.session.id)
        self.assertEqual(
            [turn.status for turn in turns], ["blocked", "failed", "completed"],
        )
        self.assertIn("Approval required", self.output.getvalue())
        self.assertIn("provider setup failed", self.output.getvalue())
        self.assertIn(
            "SystemExit: provider setup failed",
            turns[1].log_path.read_text(encoding="utf-8"),
        )

    def test_invalid_commands_and_references_never_call_engine(self):
        self.store.create(self.workspace, "Duplicate")
        self.store.create(self.workspace, "duplicate")
        self.run_script([
            "/unknown", "/switch missing", "/resume duplicate", "/switch",
            "/rename", "/quit unexpected", "/help", "/quit",
        ])
        self.engine.assert_not_called()
        self.create_workspace.assert_not_called()
        self.assertEqual(self.app._session.id, self.session.id)
        visible = self.output.getvalue()
        for expected in ("Unknown command", "Unknown session", "Ambiguous", "Usage:", "Ctrl+R"):
            self.assertIn(expected, visible)

    def test_session_commands_persist_history_and_logs_without_replay(self):
        self.run_script([
            "/logs", "/new Other", "/rename Renamed", "other task",
            f"/switch {self.session.id}", "/sessions", "/quit",
        ])
        other = self.store.resolve("renamed")
        self.assertEqual(other.workspace, self.created[0])
        self.assertEqual(self.engine.call_args.args[1].id, other.id)
        self.assertEqual(self.engine.call_count, 1)
        reloaded = SessionStore(self.store.state_dir)
        output = io.StringIO()
        app = TerminalApp(
            reloaded, self.engine, self.create_workspace,
            console=Console(file=output, width=60, color_system=None),
        )
        self.run_script(["/history", "/logs", "/quit"], app=app, session=other)
        self.assertEqual(self.engine.call_count, 1)
        self.assertIn("completed: other task", output.getvalue())
        self.assertIn("Created greeting.txt.", output.getvalue())
        self.assertIn("No request logs yet", self.output.getvalue())

    def test_missing_workspace_switch_preserves_current_session(self):
        missing = self.root / "removed"
        missing.mkdir()
        other = self.store.create(missing, "Removed")
        missing.rmdir()
        self.run_script([f"/switch {other.id}", "still here", "/quit"])
        self.assertEqual(self.engine.call_args.args[1].id, self.session.id)
        self.assertIn("Cannot switch", self.output.getvalue())

    def test_resume_preserves_unfinished_turn_without_executing_it(self):
        unfinished = self.store.start_turn(self.session.id, "interrupted old task")
        self.run_script([f"/resume {self.session.id}", "/history", "/logs", "/quit"])
        self.engine.assert_not_called()
        self.assertEqual(self.store.history(self.session.id)[-1].status, "running")
        self.assertIn("unfinished: interrupted old task", self.output.getvalue())
        self.assertIn("Not replayed.", self.output.getvalue())
        self.assertTrue(unfinished.log_path.exists())

    def test_busy_request_rejects_reentrant_submission_and_switch(self):
        other = self.store.create(self.workspace, "Other")

        def request(prompt, session):
            self.app._handle_command(f"/switch {other.id}")
            self.app._execute_request("must not run")
            with self.assertRaises(RuntimeError):
                self.app.run(other)
            self.assertEqual(self.app._session.id, session.id)
            return {"status": "completed", "summary": "Only request."}

        self.engine.side_effect = request
        self.run_script(["go", "/quit"])
        self.assertEqual(self.engine.call_count, 1)
        self.assertEqual(len(self.store.history(self.session.id)), 1)
        self.assertEqual(self.store.history(other.id), [])
        self.assertIn("already running", self.output.getvalue())

    def test_storage_failure_before_start_never_calls_engine(self):
        with patch.object(self.store, "start_turn", side_effect=OSError("disk full")):
            self.run_script(["do not run", "/quit"])
        self.engine.assert_not_called()
        self.assertIn("Storage error", self.output.getvalue())
        self.assertIn("disk full", self.output.getvalue())
        self.assertEqual(self.store.history(self.session.id), [])

    def test_unavailable_log_blocks_engine_and_records_failure(self):
        original_open = Path.open

        def open_path(path, mode="r", *args, **kwargs):
            if mode == "a" and path.suffix == ".log":
                raise OSError("log denied")
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", new=open_path):
            self.run_script(["do not run", "/quit"])
        self.engine.assert_not_called()
        self.assertEqual(self.store.history(self.session.id)[-1].status, "failed")
        self.assertIn("request not run", self.output.getvalue())

    def test_failed_history_save_is_explicit_and_never_implicitly_done(self):
        with patch.object(self.store, "finish_turn", side_effect=OSError("database read-only")):
            self.run_script(["request", "/quit"])
        turn = self.store.history(self.session.id)[-1]
        self.assertEqual(turn.status, "running")
        visible = self.output.getvalue()
        self.assertIn("request status could not be saved", visible)
        self.assertIn("History remains unfinished", visible)
        self.assertIn("database read-only", turn.log_path.read_text(encoding="utf-8"))

    def test_mid_request_log_failure_is_visible_and_cannot_record_success(self):
        def request(prompt, session):
            self.app._log.close()
            self.app.detail_print("cannot be saved")
            return {"status": "completed", "summary": "Must not claim this."}

        self.engine.side_effect = request
        self.run_script(["go", "/quit"])
        self.assertEqual(self.store.history(self.session.id)[0].status, "failed")
        self.assertIn("diagnostic log incomplete", self.output.getvalue())
        self.assertNotIn("Completed", self.output.getvalue())

    def test_nested_interactions_pause_activity_and_show_native_questions(self):
        output = io.StringIO()
        console = Console(
            file=output, width=60, color_system=None,
            force_terminal=True, force_interactive=True,
        )
        self.app.console = console
        status = Mock()

        def request(prompt, session):
            self.assertTrue(self.app._status_started)
            with self.app.interaction():
                self.assertFalse(self.app._status_started)
                self.app.detail_print("Choose [one] or [two]:")
                with self.assertRaisesRegex(ValueError, "dialog"):
                    with self.app.interaction():
                        self.app.progress("Waiting for your answer")
                        raise ValueError("dialog")
                self.assertFalse(self.app._status_started)
            self.assertTrue(self.app._status_started)
            return {"status": "completed", "summary": "Answered."}

        self.engine.side_effect = request
        with patch.object(console, "status", return_value=status):
            self.run_script(["go", "/quit"])
        self.assertIn("Choose [one] or [two]:", output.getvalue())
        self.assertEqual(status.start.call_count, 2)
        self.assertEqual(status.stop.call_count, 2)
        self.assertFalse(self.app._engine_active)
        self.assertEqual(self.app._interaction_depth, 0)
        self.assertFalse(self.app._status_started)

    def test_activity_stops_before_result_rendering_and_history_storage(self):
        console = Console(
            file=self.output, width=60, color_system=None,
            force_terminal=True, force_interactive=True,
        )
        self.app.console = console
        status = Mock()
        original_log = self.app._try_log
        original_finish = self.store.finish_turn
        observed = []

        def log(text):
            if text.startswith("\nEngine result:"):
                observed.append("result")
                self.assertFalse(self.app._engine_active)
                self.assertFalse(self.app._status_started)
            return original_log(text)

        def finish(*args, **kwargs):
            observed.append("storage")
            self.assertFalse(self.app._engine_active)
            self.assertFalse(self.app._status_started)
            return original_finish(*args, **kwargs)

        def request(prompt, session):
            self.assertTrue(self.app._engine_active)
            self.assertTrue(self.app._status_started)
            return {"status": "completed", "summary": "Finished."}

        self.engine.side_effect = request
        with (
            patch.object(console, "status", return_value=status),
            patch.object(self.app, "_try_log", side_effect=log),
            patch.object(self.store, "finish_turn", side_effect=finish),
        ):
            self.run_script(["go", "/quit"])
        self.assertEqual(observed, ["result", "storage"])
        self.assertEqual(status.start.call_count, 1)
        self.assertEqual(status.stop.call_count, 1)

    def test_real_keyboard_shortcuts_picker_and_multiline_submission(self):
        text = "\x0e\x12\x1b[B\rfirst\x1b\rsecond\r/quit\r"
        self.keyboard(text, lambda: self.app.run(self.session))
        self.assertEqual(len(self.created), 1)
        self.assertEqual(self.engine.call_count, 1)
        self.assertEqual(self.engine.call_args.args[0], "first\nsecond")
        self.assertEqual(self.engine.call_args.args[1].id, self.session.id)
        self.assertIn("Up/Down select", self.output.getvalue())

    def test_real_nested_prompt_keeps_slash_answer_literal_and_logs_it(self):
        answers = []

        def request(prompt, session):
            answer = self.keyboard(
                "/switch not-a-command\x1b\ryes\r",
                lambda: self.app.read_prompt("Which [target]? "),
            )
            answers.append(answer)
            return {"status": "completed", "summary": "Clarified."}

        self.engine.side_effect = request
        self.run_script(["go", "/quit"])
        self.assertEqual(answers, ["/switch not-a-command\nyes"])
        self.assertEqual(self.app._session.id, self.session.id)
        log = self.store.history(self.session.id)[0].log_path.read_text(encoding="utf-8")
        self.assertIn("Question: Which [target]?", log)
        self.assertIn("Answer: /switch not-a-command\nyes", log)

    def test_real_picker_escape_and_idle_ctrl_c_do_not_execute(self):
        self.app._session = self.session
        selected = self.keyboard("\x1b", self.app._choose_session)
        self.assertIsNone(selected)
        self.run_script([KeyboardInterrupt(), "/quit"])
        self.engine.assert_not_called()
        self.assertIn("Session selection cancelled", self.output.getvalue())
        self.assertIn("Input cleared.", self.output.getvalue())

    def test_standalone_session_list_is_compact_literal_and_has_empty_state(self):
        empty = SessionStore(self.root / "empty")
        list_sessions(empty, console=self.console)
        named = self.store.rename(self.session.id, "[bold]First[/bold]")
        list_sessions(self.store, console=self.console)
        visible = self.output.getvalue()
        self.assertIn("No sessions yet", visible)
        self.assertIn(named.id[:8], visible)
        self.assertIn("[bold]First[/bold]", visible)
        self.assertIn(named.last_active_at[:10], visible)
        self.engine.assert_not_called()


if __name__ == "__main__":
    unittest.main()
