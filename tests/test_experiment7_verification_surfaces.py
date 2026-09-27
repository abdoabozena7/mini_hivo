import unittest
from types import SimpleNamespace

from hivo import verification_environment as env
from hivo import verification_surfaces as surfaces


class _Keyboard:
    def __init__(self, page):
        self.page = page

    def press(self, key):
        self.page.pressed.append(key)
        self.page.after_key = True


class _Page:
    def __init__(self, *, terminal=True):
        self.terminal = terminal
        self.after_key = False
        self.pressed = []
        self.keyboard = _Keyboard(self)

    def evaluate(self, script):
        if "Object.getOwnPropertyNames(window)" in script:
            return {"candidates": [], "dom": {"canvasCount": 1, "controls": [], "liveRegions": 1}}
        return {"terminal": self.terminal and not self.after_key,
                "score": 0 if self.after_key else 3,
                "visibleMarkerCount": 1}

    def wait_for_timeout(self, _milliseconds):
        pass


class _InstrumentedPage(_Page):
    def evaluate(self, script, argument=None):
        if "Object.getOwnPropertyNames(window)" in script:
            return {"candidates": [], "actionFunctions": ["restartApp"],
                    "dom": {"canvasCount": 1, "controls": [], "liveRegions": 1}}
        if "const original = window[name]" in script:
            self.probe_installed = True
            return True
        if "const probe = window[token]" in script:
            self.probe_installed = False
            return 1 if self.after_key else 0
        return {"terminal": self.terminal and not self.after_key,
                "score": None, "visibleMarkerCount": 1}


class VerificationSurfaceTests(unittest.TestCase):
    def test_key_is_extracted_from_requirement_not_hardcoded(self):
        self.assertEqual(surfaces.requested_key("Press R key to restart"), "r")
        self.assertEqual(surfaces.requested_key("The P-key pauses the game"), "p")
        self.assertIsNone(surfaces.requested_key("Restart using the button"))

    def test_dom_route_requires_visible_terminal_and_observable_reset(self):
        profile = SimpleNamespace(required_interactions=("restart_resets_state",))
        page = _Page()
        surface, checks = surfaces.run_game_checks(page, profile, "R key restarts after game over")
        self.assertEqual(surface["surface_type"], "observable_browser")
        self.assertTrue(surface["all_required_executed"])
        self.assertEqual(page.pressed, ["r"])
        self.assertEqual([(item["name"], item["passed"]) for item in checks],
                         [("restart_resets_state", True)])

    def test_absent_terminal_precondition_cannot_pass_from_key_dispatch(self):
        profile = SimpleNamespace(required_interactions=("restart_resets_state",))
        page = _Page(terminal=False)
        surface, checks = surfaces.run_game_checks(page, profile, "R key restarts after game over")
        self.assertEqual(surface["surface_type"], "unavailable")
        self.assertFalse(checks)
        self.assertEqual(page.pressed, [])

    def test_temporary_instrumentation_is_removed_after_observing_real_input(self):
        profile = SimpleNamespace(required_interactions=("restart_resets_state",))
        page = _InstrumentedPage()
        surface, checks = surfaces.run_game_checks(page, profile, "R key restarts after game over")
        self.assertEqual(surface["surface_type"], "temporary_instrumentation")
        self.assertTrue(checks[0]["passed"])
        self.assertEqual(checks[0]["call_count"], 1)
        self.assertEqual(page.pressed, ["r"])
        self.assertFalse(page.probe_installed)

    def test_unavailable_surface_does_not_route_to_repair_without_real_failure(self):
        browser = {"passed": False, "environment_error": False,
                   "verification_surface_unavailable": True,
                   "interaction_checks": [],
                   "failures": [{"code": "verification_surface_unavailable"}]}
        self.assertEqual(env.classify_browser_result(browser), env.VERIFIER_UNAVAILABLE)
        browser["interaction_checks"] = [{"name": "restart_resets_state",
                                          "executed": True, "passed": False}]
        self.assertEqual(env.classify_browser_result(browser), env.TEST_FAILED)


if __name__ == "__main__":
    unittest.main()
