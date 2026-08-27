import unittest

from hivo.playbooks import build_execution_stages, classify_project, playbook_context


class PlaybookTests(unittest.TestCase):
    def test_project_type_is_general_and_not_game_specific(self):
        game = {"goal": "Build a responsive 3D browser game", "requirements": ["collision"]}
        api = {"goal": "Create a REST API service", "requirements": ["health endpoint", "tests"]}
        cli = {"goal": "Create a command line utility", "requirements": ["flags"]}

        self.assertEqual(classify_project(game), "web_game")
        self.assertEqual(classify_project(api), "api")
        self.assertEqual(classify_project(cli), "cli")

    def test_complex_contract_is_split_into_bounded_vertical_stages(self):
        contract = {
            "goal": "Build a browser game",
            "requirements": ["movement", "collision", "score", "responsive controls", "restart"],
            "constraints": ["single local app"],
            "success_criteria": ["all mechanics are executable"],
        }

        stages = build_execution_stages(contract, max_stages=4)
        joined = " ".join(stage["goal"] for stage in stages)

        self.assertGreaterEqual(len(stages), 2)
        self.assertLessEqual(len(stages), 4)
        self.assertEqual([stage["index"] for stage in stages], list(range(1, len(stages) + 1)))
        for requirement in contract["requirements"]:
            self.assertIn(requirement, joined)

    def test_small_task_stays_one_stage_and_playbook_is_compact(self):
        contract = {"goal": "Fix a typo in README", "requirements": ["correct one typo"],
                    "constraints": [], "success_criteria": ["text is correct"]}

        stages = build_execution_stages(contract)
        context = playbook_context(contract)

        self.assertEqual(len(stages), 1)
        self.assertLess(len(context), 3000)
        self.assertIn("PROJECT PROFILE", context)


if __name__ == "__main__":
    unittest.main()
