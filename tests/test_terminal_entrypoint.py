import builtins
from contextlib import contextmanager, ExitStack, redirect_stdout
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import mini
from hivo.memory import MemoryStore


class TerminalEntrypointTests(unittest.TestCase):
    def setUp(self):
        names = (
            "WORKSPACE", "MEMORY_STORE", "RUN", "TASKS", "RUN_ID", "MODEL_POLICY",
            "ACTIVE_TRANSACTION", "LAST_COMMITTED_TRANSACTION", "ACTIVE_CONTRACT",
            "ACTIVE_TOOL_CONTRACT", "ACTIVE_CONTEXT_SUFFICIENCY_GATE",
            "ACTIVE_PROJECT_WORLD_MODEL", "ACTIVE_IMPACT_CONTRACT",
            "ACTIVE_IMPACT_REQUIRED", "ACTIVE_TERMINAL", "HOST_PREFLIGHT_RESULT",
        )
        saved = {name: getattr(mini, name) for name in names}
        self.addCleanup(lambda: [setattr(mini, name, value) for name, value in saved.items()])
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.first, self.second = self.root / "first", self.root / "second"
        self.first.mkdir()
        self.second.mkdir()
        mini.WORKSPACE = self.first
        mini.ACTIVE_TRANSACTION = None
        mini.ACTIVE_TERMINAL = None
        mini.RUN = {}

    def drive_main(self, runner, *, engine=None, preflight=None, sessions=False):
        args = SimpleNamespace(
            mode="auto", model=None, prompt_file=None, workspace=str(self.first),
            self_test=False, install_browser=False, no_bootstrap=True,
            plain=False, verbose=False, resume=None, sessions=sessions,
        )

        class Terminal:
            def __init__(self, store, run_request, create_workspace, **kwargs):
                self.store, self.run_request = store, run_request

            def run(self, initial):
                runner(self.run_request, initial, self.store)

            detail_print = staticmethod(builtins.print)
            progress = staticmethod(lambda *args, **kwargs: None)

        output = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(patch.dict("os.environ", {"HIVO_SESSION_HOME": str(self.root / "state")}))
            stack.enter_context(patch.object(mini, "parse_args", return_value=args))
            stack.enter_context(patch.object(mini, "ensure_dependencies", return_value=True))
            stack.enter_context(patch.object(mini.sys.stdin, "isatty", return_value=True))
            stack.enter_context(patch.object(mini.sys.stdout, "isatty", return_value=True))
            stack.enter_context(patch("hivo.terminal_ui.TerminalApp", Terminal))
            host = stack.enter_context(patch.object(
                mini, "run_host_preflight", side_effect=preflight,
                return_value={"passed": True, "report": {}},
            ))
            stack.enter_context(patch.object(mini, "format_host_preflight_report", return_value="preflight details"))
            model = stack.enter_context(patch.object(mini, "select_local_ollama_model"))
            run = stack.enter_context(patch.object(
                mini, "run_auto_request", side_effect=engine,
                return_value=({"status": "done", "summary": "done"}, {}),
            ))
            mini.main()
        return host, model, run, output.getvalue()

    def test_workspace_selection_discards_previous_authority_and_working_brain(self):
        mini.RUN = {"_working_brain_store": MemoryStore(self.first)}
        mini.RUN_ID = "previous-run"
        mini.ACTIVE_CONTRACT = {"old": "authority"}
        mini.ACTIVE_TOOL_CONTRACT = {"old": "tool-scope"}
        mini.ACTIVE_IMPACT_CONTRACT = {"old": "impact"}
        mini.ACTIVE_IMPACT_REQUIRED = True
        mini.ACTIVE_PROJECT_WORLD_MODEL = object()

        memory = mini._session_memory(self.second)

        self.assertEqual(Path(memory["memory_db"]), self.second / ".hivo" / "memory.sqlite3")
        self.assertEqual(mini.get_memory_store().workspace, self.second)
        self.assertEqual(mini.RUN, {})
        self.assertEqual(mini.RUN_ID, "")
        self.assertIsNone(mini.ACTIVE_CONTRACT)
        self.assertIsNone(mini.ACTIVE_TOOL_CONTRACT)
        self.assertIsNone(mini.ACTIVE_PROJECT_WORLD_MODEL)
        self.assertIsNone(mini.ACTIVE_IMPACT_CONTRACT)
        self.assertFalse(mini.ACTIVE_IMPACT_REQUIRED)

    def test_an_active_transaction_cannot_be_switched_to_another_workspace(self):
        mini.begin_transaction("ROOT")
        with self.assertRaisesRegex(RuntimeError, "transaction is active"):
            mini._session_memory(self.second)
        self.assertEqual(mini.WORKSPACE, self.first)
        mini.rollback_transaction()

    def test_cancelled_engine_callback_rolls_back_and_restores_print_routing(self):
        def engine(*args, **kwargs):
            mini.begin_transaction("ROOT")
            mini.write_file("draft.txt", "not committed", role="System")
            raise KeyboardInterrupt

        def runner(callback, session, store):
            self.assertIsNone(mini.ACTIVE_TERMINAL)
            with self.assertRaises(KeyboardInterrupt):
                callback("Create a draft", session)
            self.assertIsNone(mini.ACTIVE_TRANSACTION)
            self.assertIsNone(mini.ACTIVE_TERMINAL)
            self.assertNotIn("print", vars(mini))
            self.assertFalse((self.first / "draft.txt").exists())

        host, _, run, _ = self.drive_main(runner, engine=engine)
        host.assert_called_once()
        run.assert_called_once()

    def test_preflight_is_lazy_workspace_specific_and_memory_does_not_leak(self):
        observed = []

        def engine(text, memory, **kwargs):
            observed.append((text, memory["workspace"]))
            return {"status": "done", "summary": text}, memory

        def runner(callback, session, store):
            self.assertEqual(observed, [])
            self.assertIsNone(mini.ACTIVE_TERMINAL)
            callback("first request", session)
            callback("second request", session)
            callback("other workspace", store.create(self.second, "Other"))

        host, model, run, _ = self.drive_main(runner, engine=engine)
        self.assertEqual(host.call_count, 2)
        self.assertEqual(model.call_count, 3)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(observed, [
            ("first request", str(self.first)), ("second request", str(self.first)),
            ("other workspace", str(self.second)),
        ])

    def test_failed_preflight_cannot_reach_the_engine(self):
        def runner(callback, session, store):
            with self.assertRaisesRegex(mini.ProviderError, "HOST_PREFLIGHT_FAILED"):
                callback("Do not execute", session)

        host, model, run, _ = self.drive_main(
            runner, preflight=lambda *args: {
                "passed": False, "report": {"failure_reason": "OLLAMA_UNAVAILABLE"},
            },
        )
        host.assert_called_once()
        model.assert_not_called()
        run.assert_not_called()
        self.assertIsNone(mini.ACTIVE_TERMINAL)
        self.assertFalse(mini.HOST_PREFLIGHT_RESULT["passed"])

    def test_listing_sessions_never_qualifies_or_calls_the_model(self):
        host, model, run, output = self.drive_main(
            lambda *args: self.fail("session listing opened the input loop"), sessions=True,
        )
        host.assert_not_called()
        model.assert_not_called()
        run.assert_not_called()
        self.assertIn("session", output.casefold())

    def test_native_decisions_suspend_redraw_and_nested_answers_stay_answers(self):
        pauses = []

        @contextmanager
        def interaction():
            pauses.append("paused")
            try:
                yield
            finally:
                pauses.append("resumed")

        terminal = SimpleNamespace(
            interaction=interaction, detail_print=lambda *args, **kwargs: None,
            read_prompt=lambda label: "/switch is just an answer",
        )
        with mini._terminal_engine_output(terminal):
            selected = mini.select_clarification_option(
                {"options": ["Keep current behavior"], "recommended_option": "Keep current behavior"},
                key_sequence=["enter"], terminal_available=True,
            )
            self.assertEqual(selected, 0)
            self.assertEqual(mini.read_user_prompt("Other> "), "/switch is just an answer")
        self.assertEqual(pauses, ["paused", "resumed"])
        self.assertIsNone(mini.ACTIVE_TERMINAL)

    def test_native_decisions_include_actual_question_and_approval_scope(self):
        mini._load_optional_imports()
        question = {
            "question": "Should proof.txt end with a newline?",
            "reason": "Exact byte verification depends on this choice.",
            "options": ["Without newline", "With newline"],
        }
        plan = {
            "approved_change_nodes": [{
                "current_owner": "proof.txt", "goal": "Create only proof.txt.",
                "mutation_required": True, "preservation_constraints": ["Keep every other file."],
            }],
            "tests_to_update_or_add": [{"contract": ["Verify exact bytes."]}],
        }
        with patch.object(mini, "_show_terminal_decision", return_value=0) as dialog:
            mini.select_clarification_option(question, terminal_available=True, output_fn=lambda *args: None)
            self.assertIn(question["question"], dialog.call_args.args[1])
            self.assertIn(question["reason"], dialog.call_args.args[1])
            mini.select_plan_approval_option(plan, terminal_available=True, output_fn=lambda *args: None)
            context = dialog.call_args.args[1]
            self.assertIn("Create only proof.txt.", context)
            self.assertIn("Keep every other file.", context)
            self.assertIn("Verify exact bytes.", context)


if __name__ == "__main__":
    unittest.main()
