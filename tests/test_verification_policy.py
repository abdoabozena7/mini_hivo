import hashlib
import inspect
import re
import unittest
from pathlib import Path

import mini
from hivo.verification import GAME_BRIDGE_EXPRESSION, GAME_BRIDGE_NAME
from hivo.verification import evaluate_web_snapshot, infer_web_profile


class VerificationPolicyTests(unittest.TestCase):
    @staticmethod
    def benchmark_prompt():
        return Path(__file__).resolve().parents[1] / "output" / "gemma-only-rescue-recursive-v9-hard-prompt.txt"

    @staticmethod
    def game_snapshot(runtime_state, profile):
        return {
            "title": "Arena Game",
            "text": "Playable arena game",
            "console_errors": [],
            "page_errors": [],
            "network_errors": [],
            "runtime_state": runtime_state,
            "interaction_checks": [
                {"name": name, "passed": True}
                for name in profile.required_interactions
            ],
        }

    def test_frozen_prompt_uses_exact_bridge_identifier(self):
        prompt = self.benchmark_prompt()
        self.assertEqual(
            hashlib.sha256(prompt.read_bytes()).hexdigest(),
            "dc118c0ca846d92fed3681f679df33466056101330c38363cc5965fd3e7815d5",
        )
        raw = prompt.read_text(encoding="utf-8")
        bridge_line = next(line for line in raw.splitlines() if "debug/testing bridge" in line)
        self.assertEqual(re.search(r"window\.[A-Za-z_$][A-Za-z0-9_$]*", bridge_line).group(0), "window.AGENT_GAME")

    def test_source_ledger_preserves_exact_benchmark_bridge(self):
        raw = self.benchmark_prompt().read_text(encoding="utf-8")
        ledger = mini.extract_source_requirement_ledger(raw, use_model=False)
        bridge = next(item for item in mini.ledger_requirements(ledger) if "debug/testing bridge" in item["text"])
        self.assertEqual(bridge["explicit_items"][0], "window.AGENT_GAME")
        self.assertEqual(bridge["explicit_items"][0], GAME_BRIDGE_EXPRESSION)
        self.assertEqual(bridge["source_segments"], [4])

    def test_active_game_verifier_uses_one_exact_bridge_expression(self):
        source = inspect.getsource(mini.browser_snapshot)
        self.assertEqual(GAME_BRIDGE_NAME, "AGENT_GAME")
        self.assertEqual(GAME_BRIDGE_EXPRESSION, "window.AGENT_GAME")
        self.assertIn("window.AGENT_GAME with getState()", mini.SYSTEM_PROMPT)
        self.assertNotIn("window.__AGENT_GAME__", mini.SYSTEM_PROMPT)
        self.assertIn("const bridge = {GAME_BRIDGE_EXPRESSION} || null;", source)
        self.assertIn("bridge_expr = GAME_BRIDGE_EXPRESSION", source)
        self.assertNotIn("window.__AGENT_GAME__", source)
        self.assertNotIn("window.__HOPLINE__", source)

    def test_exact_bridge_snapshot_passes_and_legacy_only_bridge_fails(self):
        profile = infer_web_profile("Build a browser game", {})
        exact = evaluate_web_snapshot(self.game_snapshot({
            "canvasCount": 1,
            "gameBridge": {"name": GAME_BRIDGE_NAME, "state": {"status": "playing"}},
        }, profile), profile)
        self.assertTrue(exact["passed"])
        self.assertFalse(any(item["code"] == "missing_game_bridge" for item in exact["failures"]))

        legacy_only = evaluate_web_snapshot(self.game_snapshot({
            "canvasCount": 1,
            "gameBridge": None,
            "debugState": None,
            "legacyBridge": {"name": "__AGENT_GAME__"},
        }, profile), profile)
        self.assertFalse(legacy_only["passed"])
        self.assertTrue(any(item["code"] == "missing_game_bridge" for item in legacy_only["failures"]))
        self.assertIn("window.AGENT_GAME", legacy_only["failures"][-1]["evidence"])

    def test_all_game_bridge_method_references_use_the_same_expression(self):
        source = inspect.getsource(mini.browser_snapshot)
        self.assertIn("const game={bridge_expr}", source)
        self.assertIn("({bridge_expr}).getState()", source)
        for method in ("start", "restart", "move", "forceCollision", "forceCollect", "forceWin"):
            self.assertIn(method, source)
        self.assertIn("typeof ({bridge_expr}).forceCollect", source)
        self.assertIn("typeof ({bridge_expr}).forceCollision", source)
        self.assertIn("typeof ({bridge_expr}).restart", source)
        self.assertIn("typeof ({bridge_expr}).forceWin", source)

    def test_source_code_rendered_as_body_is_not_a_passing_game(self):
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
        from hivo.verification import interaction_expectations

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
