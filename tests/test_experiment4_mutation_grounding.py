import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo.mutation_grounding import MutationGrounding, MUTATION_TARGET_UNRESOLVED


def tool_call(name, arguments):
    return {
        "role": "assistant", "content": "",
        "tool_calls": [{"function": {"name": name, "arguments": json.dumps(arguments)}}],
    }


def range_result(path, first, last):
    lines = path.read_text(encoding="utf-8").splitlines()
    return f"[lines {first}-{last} of {len(lines)}]\n" + "\n".join(
        f"{number}: {line}" for number, line in enumerate(
            lines[first - 1:last], start=first)
    )


class MutationGroundingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.path = self.workspace / "index.html"
        self.path.write_text('a\nif (event.key === "r") restart();\nz\n', encoding="utf-8")
        self.grounding = MutationGrounding(
            self.workspace, ("index.html",), policy="evidence_grounded")

    def tearDown(self):
        self.temp.cleanup()

    def test_stale_replace_requires_bounded_refresh_then_exact_retry(self):
        self.grounding.observe_read("read_file", {"path": "index.html"},
                                    self.path.read_text(encoding="utf-8"), self.path)
        stale = self.grounding.before_mutation("edit_file", {
            "path": "index.html", "old": "if (event.key === 'r') restart();", "new": "changed",
        }, self.path, tool_step=2)
        self.assertFalse(stale["allowed"])
        self.assertIn("REPLACE_NOT_FOUND", stale["result"])
        self.grounding.observe_read("read_file_range", {
            "path": "index.html", "start_line": 2, "end_line": 2,
        }, range_result(self.path, 2, 2), self.path)
        corrected = self.grounding.before_mutation("edit_file", {
            "path": "index.html", "old": 'if (event.key === "r") restart();',
            "new": "changed",
        }, self.path, tool_step=4)
        self.assertTrue(corrected["allowed"])
        self.assertTrue(corrected["attempt"]["grounded"])
        self.assertEqual(corrected["attempt"]["source_lines"], [2, 2])

    def test_second_stale_replace_terminates_without_file_change(self):
        original = self.path.read_bytes()
        self.grounding.observe_read("read_file", {"path": "index.html"},
                                    self.path.read_text(encoding="utf-8"), self.path)
        self.grounding.before_mutation("edit_file", {
            "path": "index.html", "old": "imagined", "new": "changed",
        }, self.path, tool_step=2)
        self.grounding.observe_read("read_file_range", {
            "path": "index.html", "start_line": 2, "end_line": 2,
        }, range_result(self.path, 2, 2), self.path)
        decision = self.grounding.before_mutation("edit_file", {
            "path": "index.html", "old": "still imagined", "new": "changed",
        }, self.path, tool_step=4)
        self.assertFalse(decision["allowed"])
        self.assertEqual(self.grounding.terminal_reason, MUTATION_TARGET_UNRESOLVED)
        self.assertEqual(self.path.read_bytes(), original)

    def test_file_change_invalidates_old_anchor(self):
        self.grounding.observe_read("read_file", {"path": "index.html"},
                                    self.path.read_text(encoding="utf-8"), self.path)
        self.path.write_text("different", encoding="utf-8")
        decision = self.grounding.before_mutation("edit_file", {
            "path": "index.html", "old": "different", "new": "changed",
        }, self.path, tool_step=2)
        self.assertFalse(decision["allowed"])
        self.assertIn("MUTATION_ANCHOR_REQUIRED", decision["result"])

    def test_retry_cannot_use_old_full_read_outside_refreshed_span(self):
        self.grounding.observe_read("read_file", {"path": "index.html"},
                                    self.path.read_text(encoding="utf-8"), self.path)
        self.grounding.before_mutation("edit_file", {
            "path": "index.html", "old": "imagined", "new": "changed",
        }, self.path, tool_step=2)
        self.grounding.observe_read("read_file_range", {
            "path": "index.html", "start_line": 1, "end_line": 1,
        }, range_result(self.path, 1, 1), self.path)
        decision = self.grounding.before_mutation("edit_file", {
            "path": "index.html", "old": 'if (event.key === "r") restart();',
            "new": "changed",
        }, self.path, tool_step=4)
        self.assertFalse(decision["allowed"])
        self.assertEqual(self.grounding.terminal_reason, MUTATION_TARGET_UNRESOLVED)

    def test_unseen_read_result_does_not_create_anchor(self):
        self.grounding.observe_read("read_file", {"path": "index.html"},
                                    "different content", self.path)
        decision = self.grounding.before_mutation("edit_file", {
            "path": "index.html", "old": 'if (event.key === "r") restart();',
            "new": "changed",
        }, self.path, tool_step=2)
        self.assertFalse(decision["allowed"])
        self.assertIn("MUTATION_ANCHOR_REQUIRED", decision["result"])

    def test_multiple_replacements_need_full_file_observation(self):
        self.path.write_text("match\nmatch\n", encoding="utf-8")
        self.grounding.observe_read("read_file_range", {
            "path": "index.html", "start_line": 1, "end_line": 1,
        }, range_result(self.path, 1, 1), self.path)
        decision = self.grounding.before_mutation("edit_file", {
            "path": "index.html", "old": "match", "new": "changed",
            "expected_replacements": 2,
        }, self.path, tool_step=2)
        self.assertFalse(decision["allowed"])
        self.assertIn("MUTATION_ANCHOR_REQUIRED", decision["result"])


class MutationGroundingControllerTests(unittest.TestCase):
    def setUp(self):
        self.saved = (mini.WORKSPACE, mini.RUN, mini.RUN_ID,
                      mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE)
        self.temp = tempfile.TemporaryDirectory()
        mini.WORKSPACE = Path(self.temp.name)
        mini.reset_run("experiment-4-controller")
        (mini.WORKSPACE / "index.html").write_text(
            'a\nif (event.key === "r") restart();\nz\n', encoding="utf-8")
        mini.RUN["worker_progress_policy"] = "progress_constrained"
        mini.RUN["mutation_grounding_policy"] = "evidence_grounded"
        mini.ACTIVE_TOOL_CONTRACT = {"task_id": "child", "goal": "Change index.html"}

    def tearDown(self):
        (mini.WORKSPACE, mini.RUN, mini.RUN_ID,
         mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE) = self.saved
        self.temp.cleanup()

    def _run(self, responses):
        actual_edit_calls = []

        def run_tool(name, args, role="Builder"):
            if name == "context_sufficiency_check":
                return mini._context_sufficiency_tool(args, role=role, task_id="child")
            if name == "read_file":
                return mini.read_file(args["path"])
            if name == "read_file_range":
                return mini.read_file_range(args["path"], args["start_line"], args["end_line"])
            if name == "edit_file":
                actual_edit_calls.append(args)
                path = mini.WORKSPACE / args["path"]
                source = path.read_text(encoding="utf-8")
                if args["old"] not in source:
                    return "error: expected 1 exact replacement(s), found 0; file was not changed"
                path.write_text(source.replace(args["old"], args["new"]), encoding="utf-8")
                return "edited file"
            return "ok"

        anchor = {
            "root_goal": "Change index.html", "local_task": "Change index.html",
            "requirements": ["The page contains the new content"],
            "allowed_inspection_paths": ["index.html"],
        }
        facts = [{
            "kind": "contract", "source_identity": "index.html:1",
            "excerpt": "The page contains old content.",
            "claim_key": "page.content", "claim_value": "old",
        }]
        with patch.object(mini, "ask_ollama", side_effect=responses), \
                patch.object(mini, "run_tool", side_effect=run_tool):
            result = mini.execute_agent_task(
                "Change index.html", {}, role="Builder", task_id="child",
                execution_contract={
                    "allowed_mutation_paths": ["index.html"],
                    "allowed_inspection_paths": ["index.html"],
                },
                context_sufficiency_enabled=True, context_anchor=anchor,
                initial_context_evidence=facts, max_steps=10,
            )
        return result, actual_edit_calls

    def test_exact_refresh_commits_a_legal_edit(self):
        responses = [
            tool_call("read_file", {"path": "index.html"}),
            tool_call("context_sufficiency_check", {
                "context_status": "sufficient", "reason": "source observed",
            }),
            tool_call("edit_file", {"path": "index.html",
                                    "old": "if (event.key === 'r') restart();", "new": "changed"}),
            tool_call("read_file_range", {"path": "index.html", "start_line": 2, "end_line": 2}),
            tool_call("edit_file", {"path": "index.html",
                                    "old": 'if (event.key === "r") restart();', "new": "changed"}),
            tool_call("run_command", {"command": "echo verified"}),
            {"role": "assistant", "content": "completed", "tool_calls": []},
        ]
        result, calls = self._run(responses)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(result["failure_type"])
        self.assertEqual(result["mutation_grounding"]["mutation_attempts"], 2)
        self.assertEqual(result["mutation_grounding"]["grounded_mutation_attempts"], 1)
        self.assertEqual(result["mutation_grounding"]["first_applied_mutation_step"], 5)
        self.assertEqual(result["worker_progress"]["first_legal_mutation"]["tool_step"], 5)
        self.assertIn("changed", (mini.WORKSPACE / "index.html").read_text(encoding="utf-8"))

    def test_second_unanchored_attempt_returns_specific_blocker(self):
        responses = [
            tool_call("read_file", {"path": "index.html"}),
            tool_call("context_sufficiency_check", {
                "context_status": "sufficient", "reason": "source observed",
            }),
            tool_call("edit_file", {"path": "index.html", "old": "imagined", "new": "changed"}),
            tool_call("read_file_range", {"path": "index.html", "start_line": 2, "end_line": 2}),
            tool_call("edit_file", {"path": "index.html", "old": "still imagined", "new": "changed"}),
        ]
        result, calls = self._run(responses)
        self.assertEqual(result["failure_type"], MUTATION_TARGET_UNRESOLVED)
        self.assertEqual(calls, [])
        self.assertIn('if (event.key === "r")',
                      (mini.WORKSPACE / "index.html").read_text(encoding="utf-8"))

    def test_real_file_tool_applies_exact_observed_edit(self):
        responses = [
            tool_call("read_file", {"path": "index.html"}),
            tool_call("context_sufficiency_check", {
                "context_status": "sufficient", "reason": "source observed",
            }),
            tool_call("edit_file", {"path": "index.html",
                                    "old": 'if (event.key === "r") restart();',
                                    "new": 'if (event.key === "r") startAgain();'}),
            tool_call("run_command", {"command": "echo verified"}),
            {"role": "assistant", "content": "completed", "tool_calls": []},
        ]
        anchor = {
            "root_goal": "Change index.html", "local_task": "Change index.html",
            "requirements": ["The page contains the new content"],
            "allowed_inspection_paths": ["index.html"],
        }
        facts = [{
            "kind": "contract", "source_identity": "index.html:1",
            "excerpt": "The page contains old content.",
            "claim_key": "page.content", "claim_value": "old",
        }]
        with patch.object(mini, "ask_ollama", side_effect=responses):
            result = mini.execute_agent_task(
                "Change index.html", {}, role="Builder", task_id="child",
                execution_contract={
                    "allowed_mutation_paths": ["index.html"],
                    "allowed_inspection_paths": ["index.html"],
                },
                context_sufficiency_enabled=True, context_anchor=anchor,
                initial_context_evidence=facts, max_steps=8,
            )
        self.assertEqual(result["mutation_grounding"]["grounded_mutation_attempts"], 1)
        self.assertEqual(result["mutation_grounding"]["applied_mutation_attempts"], 1)
        self.assertEqual(result["worker_progress"]["first_legal_mutation"]["tool_step"], 3)
        self.assertIn("startAgain", (mini.WORKSPACE / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
