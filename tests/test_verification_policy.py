import unittest


class VerificationPolicyTests(unittest.TestCase):
    def test_source_code_rendered_as_body_is_not_a_passing_game(self):
        from hivo.verification import evaluate_web_snapshot, infer_web_profile

        profile = infer_web_profile(
            "Build a 3D hovercraft game with keyboard and touch controls, collisions, "
            "energy collection, best score, restart, and a win state",
            {},
        )
        result = evaluate_web_snapshot({
            "title": "",
            "text": "// Global Constants and Setup (Placeholder/Assumed Context)\nconst ROAD_WIDTH = 20;",
            "console_errors": [],
            "page_errors": [],
            "network_errors": [],
            "runtime_state": {"canvasCount": 0, "gameBridge": None},
            "interaction_checks": [],
        }, profile)

        self.assertFalse(result["passed"])
        codes = {failure["code"] for failure in result["failures"]}
        self.assertTrue({"missing_title", "missing_canvas", "source_dump", "missing_game_bridge"} <= codes)

    def test_game_profile_requires_contract_specific_interactions(self):
        from hivo.verification import infer_web_profile

        profile = infer_web_profile(
            "A game that collects energy, avoids collision barriers, supports touch, "
            "persists best score, restarts, and can be won",
            {},
        )
        self.assertTrue({
            "keyboard_movement", "collision_game_over", "collection_updates_state",
            "restart_resets_state", "goal_win_state", "score_persistence", "touch_control",
        } <= set(profile.required_interactions))


if __name__ == "__main__":
    unittest.main()
