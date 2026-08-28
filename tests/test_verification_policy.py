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

    def test_timer_profile_requires_observable_behavior_not_just_clean_console(self):
        from hivo.verification import evaluate_web_snapshot, infer_web_profile, interaction_expectations

        contract = {
            "requirements": [
                "Start, Pause, and Reset controls",
                "configurable focus and break durations with sensible validation",
                "automatic focus/break phases and completed sessions",
                "persist settings in localStorage",
                "responsive keyboard-accessible UI with reduced-motion support",
            ],
        }
        profile = infer_web_profile("Build a focus timer", contract)
        required = {
            "timer_start_changes_visible_time",
            "timer_pause_freezes_visible_time",
            "timer_reset_restores_visible_time",
            "timer_phase_switches_and_counts_session",
            "timer_duration_configuration",
            "settings_persistence",
            "keyboard_activation",
            "responsive_no_overflow",
            "reduced_motion",
        }
        self.assertEqual(profile.kind, "timer")
        self.assertTrue(required <= set(profile.required_interactions))
        expectations = " ".join(interaction_expectations(profile))
        self.assertIn("Completed Sessions: 0", expectations)
        self.assertIn("current-session ordinal", expectations)

        result = evaluate_web_snapshot({
            "title": "Focus Timer",
            "text": "Focus Timer 00:00 Start Pause Reset",
            "console_errors": [],
            "page_errors": [],
            "network_errors": [],
            "runtime_state": {"canvasCount": 0},
            "interaction_checks": [
                {"name": name, "passed": name != "timer_start_changes_visible_time"}
                for name in required
            ],
        }, profile)
        self.assertFalse(result["passed"])
        self.assertTrue(any(
            failure["code"] == "failed_interaction"
            and "timer_start_changes_visible_time" in failure["evidence"]
            for failure in result["failures"]
        ))


if __name__ == "__main__":
    unittest.main()
