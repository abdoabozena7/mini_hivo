import unittest

from hivo.browser_checks import _clock, _run_duration_configuration


class BrowserProbeTests(unittest.TestCase):
    def test_clock_probe_accepts_nested_split_visible_time(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed")

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as exc:
                self.skipTest(f"Playwright Chromium is unavailable: {exc}")
            try:
                page = browser.new_page()
                page.set_content(
                    '<div id="clock" style="font-size:48px">'
                    '<span>25</span>\n<span>:00</span></div>'
                )

                clock = _clock(page)

                self.assertIsNotNone(clock)
                self.assertEqual(clock["text"], "25:00")
                self.assertEqual(clock["seconds"], 1500)
            finally:
                browser.close()

    def test_duration_probe_applies_value_and_checks_positive_minimum(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed")

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as exc:
                self.skipTest(f"Playwright Chromium is unavailable: {exc}")
            try:
                page = browser.new_page()
                page.clock.install()
                page.set_content("""
                    <label>Focus Time (Minutes)
                        <input id="focus" type="number" min="1" max="60" value="25">
                    </label>
                    <label>Break Time (Minutes)
                        <input id="break" type="number" min="1" max="30" value="5">
                    </label>
                    <div id="clock">25:00</div>
                    <button id="save">Save Settings</button>
                    <script>
                        document.getElementById('save').addEventListener('click', () => {
                            document.getElementById('clock').textContent =
                                String(Number(document.getElementById('focus').value)).padStart(2, '0') + ':00';
                        });
                    </script>
                """)

                check = _run_duration_configuration(page)

                self.assertTrue(check["passed"], check)
                self.assertEqual(check["expected_seconds"], 60)
                self.assertTrue(check["below_minimum_is_invalid"])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
