import copy
import unittest

from hivo.verification import infer_web_profile


class FieldScopedProfileTests(unittest.TestCase):
    def test_hash_fragment_cannot_turn_timer_into_game(self):
        contract = {
            "goal": "Pause the countdown timer without resetting its visible time",
            "requirements": [{"requirement_id": "REQ-3d", "text": "Preserve Start and Reset"}],
            "allowed_mutation_paths": ["timer.html"],
            "execution_contract_hash": "ce528e3d39cd",
        }
        self.assertEqual(infer_web_profile(contract["goal"], contract).kind, "game")
        profile = infer_web_profile(contract["goal"], contract,
                                    classification_policy="field_scoped")
        self.assertEqual(profile.kind, "timer")
        self.assertFalse(profile.require_canvas)
        self.assertEqual(profile.required_interactions[:3], (
            "timer_start_changes_visible_time", "timer_pause_freezes_visible_time",
            "timer_reset_restores_visible_time"))

    def test_arbitrary_authority_metadata_cannot_change_profile(self):
        base = {"goal": "Pause the countdown timer", "integration_test_target": "timer.html"}
        expected = infer_web_profile(base["goal"], base, classification_policy="field_scoped")
        for metadata in (
            {"execution_contract_hash": "3d-game-webgl"},
            {"plan_hash": "3d", "receipt_digest": "game"},
            {"requirement_id": "game", "provenance": {"text": "3D game"}},
            {"nested": {"ids": ["game"], "hash": "3d"}},
        ):
            contract = copy.deepcopy(base) | metadata
            self.assertEqual(infer_web_profile(base["goal"], contract,
                                                classification_policy="field_scoped"), expected)

    def test_semantic_requirements_and_paths_are_used(self):
        self.assertEqual(infer_web_profile("", {"requirements": [{
            "requirement_id": "REQ-001", "text": "Build a 3D game"
        }]}, classification_policy="field_scoped").kind, "game")
        self.assertEqual(infer_web_profile("Fix behavior", {
            "allowed_mutation_paths": ["focus_timer.html"]
        }, classification_policy="field_scoped").kind, "timer")

    def test_game_remains_game_despite_timer_metadata(self):
        contract = {
            "goal": "Fix keyboard movement in the arena game",
            "requirements": ["Preserve touch controls"],
            "contract_hash": "countdown-timer",
            "provenance": {"notes": "pomodoro"},
        }
        profile = infer_web_profile(contract["goal"], contract,
                                    classification_policy="field_scoped")
        self.assertEqual(profile.kind, "game")
        self.assertTrue(profile.require_canvas)
        self.assertIn("keyboard_movement", profile.required_interactions)

    def test_generic_web_and_default_policy(self):
        contract = {"goal": "Fix the submit button", "contract_hash": "game-3d"}
        self.assertEqual(infer_web_profile(contract["goal"], contract,
                                            classification_policy="field_scoped").kind, "web")
        self.assertEqual(infer_web_profile(contract["goal"], contract).kind, "game")


if __name__ == "__main__":
    unittest.main()
