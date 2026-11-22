import unittest

from hivo.playbooks import classify_project, playbook_context
from hivo.quality_rubric import (
    BROWSER_CANVAS_QUALITY_JS,
    detect_quality_domain,
    detect_threejs_or_3d,
    diagnose_browser_failures,
    quality_rubric_context,
)
from hivo.verification import (
    GAME_BRIDGE_NAME,
    evaluate_web_snapshot,
    infer_web_profile,
)


class ThreeJsQualityRubricTests(unittest.TestCase):
    def test_detect_threejs_or_3d_positive_and_negative_cases(self):
        for positive in (
            "Build a Three.js solar system explorer",
            "Create a threejs interactive viewer",
            "Render a WebGL particle tunnel",
            "Build a 3D scene with lighting",
            "Build a 3D game with obstacles",
            "Add OrbitControls camera navigation",
            {"goal": "Create interactive visualizer", "requirements": [{"requirement_id": "R1", "text": "Use WebGL2"}]},
        ):
            with self.subTest(case=positive):
                self.assertTrue(detect_threejs_or_3d(positive))

        for negative in (
            None,
            "",
            "Create a REST API service with health endpoint",
            "Build a command line CSV converter",
            "Build a Pomodoro focus timer",
            {
                "goal": "Pause the countdown timer",
                "execution_contract_hash": "ce528e3d39cd",
                "requirements": [{"requirement_id": "REQ-3d", "text": "Preserve Start and Reset"}],
            },
        ):
            with self.subTest(case=negative):
                self.assertFalse(detect_threejs_or_3d(negative))

    def test_quality_rubric_context_stays_under_budget_across_all_domains(self):
        cases = (
            ("threejs_3d", {"goal": "Build a Three.js 3D solar system simulator"}, ""),
            ("web_game", {"goal": "Build a 2D retro arcade game on HTML5 canvas"}, ""),
            ("web_app", {"goal": "Build a browser focus timer web app"}, ""),
            ("cli", {"goal": "Create a command line log analyzer"}, ""),
            ("api", {"goal": "Create a FastAPI REST API"}, ""),
            ("general", {"goal": "Implement a string utility helper"}, ""),
        )
        for expected_domain, contract, task_goal in cases:
            with self.subTest(domain=expected_domain):
                self.assertEqual(detect_quality_domain(contract, task_goal), expected_domain)
                rubric = quality_rubric_context(contract, task_goal)
                self.assertIn("FINISHING & QUALITY CONTRACT", rubric)
                self.assertIn(expected_domain, rubric)
                self.assertLess(len(rubric), 1300)

    def test_threejs_rubric_contains_critical_weak_model_guardrails(self):
        rubric = quality_rubric_context(None, "Build a 3D Three.js hovercraft game")
        required_fragments = (
            '<script type="importmap">',
            '<script type="module">',
            "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
            "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/",
            "BoxGeometry",
            "SphereGeometry",
            "BufferGeometry",
            "*BufferGeometry",
            "AmbientLight",
            "DirectionalLight",
            "renderer.setSize(window.innerWidth, window.innerHeight)",
            "html, body { margin: 0; height: 100%; overflow: hidden; }",
            "window.AGENT_GAME",
            "getState()",
            "move(direction)",
            "forceCollect()",
            "forceCollision()",
            "forceWin()",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, rubric)

    def test_diagnose_browser_failures_translates_root_causes_into_repair_hints(self):
        bare_three = diagnose_browser_failures({
            "page_errors": [
                'TypeError: Failed to resolve module specifier "three". '
                'Relative references must start with either "/", "./", or "../".'
            ],
        })
        self.assertTrue(any('<script type="importmap">' in hint and "three@0.160.0" in hint for hint in bare_three))

        legacy_geom = diagnose_browser_failures({
            "console_errors": ["Uncaught TypeError: THREE.BoxBufferGeometry is not a constructor"],
        })
        self.assertTrue(any("THREE.BoxGeometry" in hint for hint in legacy_geom))

        removed_geom = diagnose_browser_failures({
            "page_errors": ["TypeError: THREE.Geometry is not a constructor"],
        })
        self.assertTrue(any("THREE.BufferGeometry" in hint for hint in removed_geom))

        zero_canvas = diagnose_browser_failures({
            "failures": [{"code": "zero_size_canvas", "evidence": "0x0px"}],
            "runtime_state": {"canvasCount": 1, "canvasMetrics": {"count": 1, "maxWidth": 0, "maxHeight": 0}},
        })
        self.assertTrue(any(
            "renderer.setSize(window.innerWidth, window.innerHeight)" in hint and "height: 100%" in hint
            for hint in zero_canvas
        ))

        missing_bridge = diagnose_browser_failures({
            "failures": [{"code": "missing_game_bridge", "evidence": "window.AGENT_GAME unavailable"}],
        })
        self.assertTrue(any("window.AGENT_GAME" in hint and "getState" in hint for hint in missing_bridge))

        failed_move = diagnose_browser_failures({
            "interaction_checks": [{"name": "keyboard_movement", "passed": False}],
        })
        self.assertTrue(any(
            "move(direction)" in hint and "ArrowUp" in hint and "getState().position" in hint
            for hint in failed_move
        ))

        self.assertEqual(diagnose_browser_failures({"passed": True, "failures": []}), [])

    def test_evaluate_web_snapshot_preserves_synthetic_snapshots_and_flags_zero_canvas(self):
        profile = infer_web_profile("Build a 3D Three.js arena game", {})

        def make_snapshot(runtime_state):
            return {
                "title": "3D Arena",
                "text": "Score: 0 | Controls: WASD / Arrows",
                "console_errors": [],
                "page_errors": [],
                "network_errors": [],
                "runtime_state": runtime_state,
                "interaction_checks": [
                    {"name": name, "passed": True}
                    for name in profile.required_interactions
                ],
            }

        synthetic_no_metrics = evaluate_web_snapshot(
            make_snapshot({
                "canvasCount": 1,
                "gameBridge": {"name": GAME_BRIDGE_NAME, "state": {"status": "playing"}},
            }),
            profile,
        )
        self.assertTrue(synthetic_no_metrics["passed"])
        self.assertEqual(synthetic_no_metrics["failures"], [])
        self.assertNotIn("repair_hints", synthetic_no_metrics)

        broken_zero = evaluate_web_snapshot(
            make_snapshot({
                "canvasCount": 1,
                "canvasMetrics": {"count": 1, "maxWidth": 0, "maxHeight": 0, "visibleCount": 0},
                "gameBridge": {"name": GAME_BRIDGE_NAME, "state": {"status": "playing"}},
            }),
            profile,
        )
        self.assertFalse(broken_zero["passed"])
        self.assertTrue(any(
            item["code"] == "zero_size_canvas" and "0x0px" in item["evidence"]
            for item in broken_zero["failures"]
        ))
        self.assertTrue(broken_zero.get("repair_hints"))
        self.assertTrue(any("renderer.setSize" in hint for hint in broken_zero["repair_hints"]))

        healthy_canvas = evaluate_web_snapshot(
            make_snapshot({
                "canvasCount": 1,
                "canvasMetrics": {"count": 1, "maxWidth": 800, "maxHeight": 600, "visibleCount": 1},
                "gameBridge": {"name": GAME_BRIDGE_NAME, "state": {"status": "playing"}},
            }),
            profile,
        )
        self.assertTrue(healthy_canvas["passed"])
        self.assertEqual(healthy_canvas["failures"], [])

        web_profile = infer_web_profile("Build a static company landing page", {})
        self.assertFalse(web_profile.require_canvas)
        non_canvas_page = evaluate_web_snapshot({
            "title": "Landing Page",
            "text": "Welcome to our studio",
            "console_errors": [],
            "page_errors": [],
            "network_errors": [],
            "runtime_state": {
                "canvasCount": 1,
                "canvasMetrics": {"count": 1, "maxWidth": 0, "maxHeight": 0, "visibleCount": 0},
            },
            "interaction_checks": [],
        }, web_profile)
        self.assertTrue(non_canvas_page["passed"])

    def test_playbooks_classify_3d_simulators_without_breaking_api_cli_docs(self):
        self.assertEqual(classify_project({"goal": "Build a solar system orbit simulator"}), "web_game")
        self.assertEqual(classify_project({"goal": "Create an interactive 3D scene"}), "web_game")
        self.assertEqual(classify_project({"goal": "Build an arcade space shooter on canvas"}), "web_game")
        self.assertEqual(classify_project({"goal": "Create a FastAPI endpoint for solar telemetry"}), "api")
        self.assertEqual(classify_project({"goal": "Create a CLI orbit simulator with argparse"}), "cli")
        self.assertEqual(classify_project({"goal": "Fix a typo in README documentation"}), "documentation")
        self.assertIn("importmap", playbook_context({"goal": "Build a Three.js game"}))


class BrowserCanvasQualityPlaywrightTests(unittest.TestCase):
    def _launch_browser(self, playwright):
        try:
            return playwright.chromium.launch(headless=True)
        except Exception as exc:
            self.skipTest(f"Playwright Chromium is unavailable: {exc}")

    def test_broken_zero_size_canvas_and_working_webgl_canvas_in_chromium(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed")

        profile = infer_web_profile("Build a 3D WebGL scene with keyboard movement", {})

        with sync_playwright() as playwright:
            browser = self._launch_browser(playwright)
            try:
                broken_page = browser.new_page(viewport={"width": 1024, "height": 768})
                broken_page.set_content("""
                    <!doctype html>
                    <html>
                    <head><title>Broken 3D Scene</title></head>
                    <body style="margin:0; height:0;">
                        <canvas id="broken" width="0" height="0" style="width:100%; height:100%; display:block;"></canvas>
                    </body>
                    </html>
                """)
                broken_metrics = broken_page.evaluate(BROWSER_CANVAS_QUALITY_JS)
                self.assertEqual(broken_metrics["count"], 1)
                self.assertEqual(broken_metrics["maxWidth"], 0)
                self.assertEqual(broken_metrics["maxHeight"], 0)
                self.assertEqual(broken_metrics["visibleCount"], 0)
                self.assertFalse(broken_metrics["hasImportMap"])

                broken_eval = evaluate_web_snapshot({
                    "title": broken_page.title(),
                    "text": "Broken 3D Scene",
                    "console_errors": [],
                    "page_errors": [],
                    "network_errors": [],
                    "runtime_state": {
                        "canvasCount": broken_metrics["count"],
                        "canvasMetrics": broken_metrics,
                        "gameBridge": {"name": GAME_BRIDGE_NAME, "state": {"status": "playing"}},
                    },
                    "interaction_checks": [{"name": "keyboard_movement", "passed": True}],
                }, profile)
                self.assertFalse(broken_eval["passed"])
                self.assertTrue(any(f["code"] == "zero_size_canvas" for f in broken_eval["failures"]))
                self.assertTrue(broken_eval.get("repair_hints"))

                working_page = browser.new_page(viewport={"width": 1024, "height": 768})
                working_page.set_content("""
                    <!doctype html>
                    <html>
                    <head>
                        <title>Orbital WebGL Simulator</title>
                        <script type="importmap">
                        {
                            "imports": {
                                "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
                                "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
                            }
                        }
                        </script>
                        <style>
                            html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; background: #050816; }
                            #scene { display: block; width: 100vw; height: 100vh; }
                            #hud { position: fixed; top: 12px; left: 12px; color: #f8fafc; z-index: 10; }
                        </style>
                    </head>
                    <body>
                        <div id="hud" role="status" aria-live="polite">
                            <h1>Orbital WebGL Simulator</h1>
                            <div id="score">Score: 0</div>
                            <button id="start-btn" type="button">Start</button>
                            <button id="reset-btn" type="button">Reset</button>
                        </div>
                        <canvas id="scene" width="1024" height="768"></canvas>
                        <script>
                            const canvas = document.getElementById('scene');
                            const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
                            if (gl) {
                                gl.viewport(0, 0, canvas.width, canvas.height);
                                gl.clearColor(0.08, 0.16, 0.36, 1.0);
                                gl.clear(gl.COLOR_BUFFER_BIT);
                            } else {
                                const ctx = canvas.getContext('2d');
                                if (ctx) {
                                    ctx.fillStyle = '#14295c';
                                    ctx.fillRect(0, 0, canvas.width, canvas.height);
                                }
                            }
                            const state = { status: 'ready', score: 0, position: { x: 0, y: 0, z: 0 }, tick: 0 };
                            window.AGENT_GAME = {
                                getState: () => JSON.parse(JSON.stringify(state)),
                                start: () => { state.status = 'playing'; },
                                restart: () => { state.status = 'playing'; state.score = 0; state.position = { x: 0, y: 0, z: 0 }; },
                                move: (dir) => {
                                    if (dir === 'up') state.position.z -= 1;
                                    state.tick += 1;
                                },
                            };
                        </script>
                    </body>
                    </html>
                """)
                working_metrics = working_page.evaluate(BROWSER_CANVAS_QUALITY_JS)
                self.assertEqual(working_metrics["count"], 1)
                self.assertEqual(working_metrics["maxWidth"], 1024)
                self.assertEqual(working_metrics["maxHeight"], 768)
                self.assertEqual(working_metrics["visibleCount"], 1)
                self.assertTrue(working_metrics["hasImportMap"])
                self.assertGreaterEqual(working_metrics["hudElementCount"], 2)
                self.assertEqual(working_metrics["interactiveControlCount"], 2)

                working_page.evaluate("() => { window.AGENT_GAME.start(); window.AGENT_GAME.move('up'); }")
                bridge_state = working_page.evaluate("() => window.AGENT_GAME.getState()")
                self.assertEqual(bridge_state["status"], "playing")
                self.assertEqual(bridge_state["position"]["z"], -1)

                working_eval = evaluate_web_snapshot({
                    "title": working_page.title(),
                    "text": working_page.locator("body").inner_text(),
                    "console_errors": [],
                    "page_errors": [],
                    "network_errors": [],
                    "runtime_state": {
                        "canvasCount": working_metrics["count"],
                        "canvasMetrics": working_metrics,
                        "gameBridge": {"name": GAME_BRIDGE_NAME, "state": bridge_state},
                    },
                    "interaction_checks": [{"name": "keyboard_movement", "passed": True}],
                }, profile)
                self.assertTrue(working_eval["passed"], working_eval)
                self.assertEqual(working_eval["failures"], [])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
