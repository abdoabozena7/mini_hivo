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

    def test_new_no_build_web_app_gets_clean_file_boundary_guidance(self):
        contract = {
            "goal": "Build a browser focus timer with a local HTML entry point",
            "requirements": ["working controls"],
            "constraints": ["no build step"],
        }

        context = playbook_context(contract)

        self.assertIn("markup, styles, and behavior in separate small local files", context)

    def test_six_requirements_use_one_weak_model_pass_each(self):
        contract = {
            "goal": "Build a focus timer",
            "requirements": [f"requirement {index}" for index in range(1, 7)],
            "constraints": [],
            "success_criteria": ["verified"],
        }

        stages = build_execution_stages(contract)

        self.assertEqual(len(stages), 6)
        self.assertEqual([len(stage["requirements"]) for stage in stages], [1, 1, 1, 1, 1, 1])
        self.assertEqual(
            [item for stage in stages for item in stage["requirements"]],
            contract["requirements"],
        )


if __name__ == "__main__":
    unittest.main()
