import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo.target_locator import TargetLocator


def tool_call(name, args):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": name, "arguments": json.dumps(args)}}]}


class TargetLocatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.source = self.workspace / "index.html"
        self.source.write_text(
            "<style>\n.keys { display: flex; }\n</style>\n"
            "<script>\nfunction begin() {}\n"
            "window.addEventListener('keydown', event => {\n"
            "  const key = event.key.toLowerCase();\n"
            "  if (key === 'r') restartGame();\n"
            "});\nfunction restartGame() {}\n</script>\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_keyboard_requirement_ranks_behavior_over_css_decoy(self):
        locator = TargetLocator.build(self.workspace, "R key restart after game over", {
            "goal": "Handle keyboard restart after game over",
            "requirements": [{"text": "R key restarts the game"}],
            "allowed_inspection_paths": ["index.html"],
        })
        self.assertTrue(locator.candidates)
        top = locator.candidates[0]
        self.assertLessEqual(top["start_line"], 6)
        self.assertGreaterEqual(top["end_line"], 8)
        self.assertIn("keydown", top["matched_terms"])
        self.assertEqual(top["candidate_id"], "LOC-001")
        self.assertLessEqual(len(locator.candidates), 3)

    def test_only_approved_inspection_paths_are_searched(self):
        (self.workspace / "secret.js").write_text(
            "keydown key restartGame " * 40, encoding="utf-8")
        locator = TargetLocator.build(self.workspace, "keyboard restart", {
            "goal": "keyboard restart",
            "allowed_inspection_paths": ["index.html"],
        })
        self.assertTrue(all(item["path"] == "index.html" for item in locator.candidates))
        self.assertNotIn("secret.js", locator.packet())


class TargetLocatorControllerTests(unittest.TestCase):
    def setUp(self):
        self.saved = (mini.WORKSPACE, mini.RUN, mini.RUN_ID,
                      mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE)
        self.temp = tempfile.TemporaryDirectory()
        mini.WORKSPACE = Path(self.temp.name)
        mini.reset_run("experiment-5-controller")
        (mini.WORKSPACE / "index.html").write_text(
            "<script>\nwindow.addEventListener('keydown', event => {\n"
            "  const key = event.key.toLowerCase();\n"
            "  if (key === 'r') restartGame();\n"
            "});\n</script>\n", encoding="utf-8")
        mini.RUN["worker_progress_policy"] = "progress_constrained"
        mini.RUN["mutation_grounding_policy"] = "evidence_grounded"
        mini.RUN["target_locator_policy"] = "evidence_directed"
        mini.ACTIVE_TOOL_CONTRACT = {"task_id": "child", "goal": "Handle R key restart"}

    def tearDown(self):
        (mini.WORKSPACE, mini.RUN, mini.RUN_ID,
         mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE) = self.saved
        self.temp.cleanup()

    def test_candidate_read_supplies_grounded_source_to_real_edit_tool(self):
        responses = [
            tool_call("context_sufficiency_check", {
                "context_status": "sufficient", "reason": "contract and source are sufficient",
            }),
            tool_call("read_candidate_span", {"candidate_id": "LOC-001"}),
            tool_call("edit_file", {"path": "index.html",
                                    "old": "if (key === 'r') restartGame();",
                                    "new": "if (key === 'r') beginAgain();"}),
            tool_call("run_command", {"command": "echo verified"}),
            {"role": "assistant", "content": "completed", "tool_calls": []},
        ]
        observed = []

        def ask(messages, tools, **_kwargs):
            names = {item["function"]["name"] for item in tools}
            observed.append(names)
            self.assertIn("read_candidate_span", names)
            self.assertNotIn("read_file_range", names)
            self.assertIn("TARGET LOCATOR", str(messages))
            return responses[len(observed) - 1]

        anchor = {
            "root_goal": "R key restarts the game", "local_task": "Handle R key restart",
            "requirements": ["R key restart"],
            "allowed_inspection_paths": ["index.html"],
        }
        facts = [{
            "kind": "contract", "source_identity": "index.html:1",
            "excerpt": "Keyboard behavior is in index.html.",
            "claim_key": "keyboard.owner", "claim_value": "index.html",
        }]
        with patch.object(mini, "ask_ollama", side_effect=ask):
            result = mini.execute_agent_task(
                "Handle R key restart", {}, role="Builder", task_id="child",
                execution_contract={
                    "goal": "Handle R key restart",
                    "requirements": [{"text": "R key restarts the game"}],
                    "allowed_mutation_paths": ["index.html"],
                    "allowed_inspection_paths": ["index.html"],
                },
                context_sufficiency_enabled=True, context_anchor=anchor,
                initial_context_evidence=facts, max_steps=8,
            )
        self.assertEqual(result["target_locator"]["read_events"][0]["candidate_id"], "LOC-001")
        self.assertEqual(result["mutation_grounding"]["grounded_mutation_attempts"], 1)
        self.assertEqual(result["worker_progress"]["first_legal_mutation"]["tool_step"], 3)
        self.assertIn("beginAgain", (mini.WORKSPACE / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
