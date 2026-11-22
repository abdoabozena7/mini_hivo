"""End-to-end controlled functional & real-Playwright tests for AGISS (R_UPDATE_009).

Exercises the complete Mini Hivo recursive multi-file pipeline (`run_recursive_request`)
with:
1. Disjoint Child File Ownership & Producer -> Consumer DAG Scheduling (`assume_guarantee.py`)
2. Zero-Model AST / HTML / ES-Module Sibling Interface Certificates & Live ACI Counterexamples
3. Role-Conditioned & Stagnation-Adaptive `min_p` Decoding Schedule (`hyperparams.py`)
4. Real Headless Chromium WebGL Pre-Start Luminance-Variance (`initialFrameBlank == False`)
   and HUD Bounding-Box Anti-Overlap (`hudOverlapCount == 0`) Verification Oracles
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini


class AgissMultifileAndVisualE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            name: getattr(mini, name)
            for name in (
                "WORKSPACE",
                "MODEL",
                "MODEL_POLICY",
                "RUN",
                "TASKS",
                "RUN_ID",
                "MEMORY_STORE",
                "ACTIVE_TRANSACTION",
                "LAST_COMMITTED_TRANSACTION",
                "ACTIVE_CONTRACT",
                "ACTIVE_TOOL_CONTRACT",
                "ACTIVE_CONTEXT_SUFFICIENCY_GATE",
                "ACTIVE_PROJECT_WORLD_MODEL",
                "ACTIVE_IMPACT_CONTRACT",
                "ACTIVE_IMPACT_REQUIRED",
                "ACTIVE_RUN_BUDGET",
                "FORCE_CPU_FOR_RUN",
            )
        }
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        mini._load_optional_imports()
        mini.WORKSPACE = Path(self.temp.name) / "workspace"
        mini.WORKSPACE.mkdir(parents=True, exist_ok=True)
        mini.MEMORY_STORE = None
        mini.FORCE_CPU_FOR_RUN = False
        mini.reset_run("recursive")

    def tearDown(self) -> None:
        if mini.ACTIVE_TRANSACTION is not None:
            try:
                mini.rollback_transaction()
            except Exception:
                mini.ACTIVE_TRANSACTION = None
        if mini.MEMORY_STORE is not None:
            try:
                mini.MEMORY_STORE.close()
            except Exception:
                pass
        for name, val in self._saved.items():
            setattr(mini, name, val)
        self.temp.cleanup()

    @staticmethod
    def _tool_msg(name: str, arguments: dict) -> dict:
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
        }

    @staticmethod
    def _done_msg(text: str = "Completed.") -> dict:
        return {"role": "assistant", "content": text, "tool_calls": []}

    def test_multifile_python_recursive_agiss_disjoint_ownership_sibling_contracts_and_adaptive_decoding(self) -> None:
        prompt = (
            "Create `metrics.py`, `cli.py`, and `test_metrics.py` for a Swarm Telemetry Analyzer in Python 3:\n"
            "1. `metrics.py`: implement `summarize_latencies(values: list[float]) -> dict` returning "
            "`{\"count\": len(values), \"min\": min_val, \"max\": max_val, \"mean\": round(mean_val, 2)}` "
            "and raising `ValueError(\"values must not be empty\")` on empty input.\n"
            "2. `cli.py`: accept `--values` comma-separated numbers, call `summarize_latencies`, print canonical JSON.\n"
            "3. `test_metrics.py`: unittest suite verifying `metrics.py` and `cli.py`."
        )
        contract = {
            "goal": prompt,
            "original_goal": prompt,
            "requirements": [
                "Create `metrics.py` implementing `summarize_latencies(values: list[float]) -> dict`.",
                "Create `cli.py` accepting `--values` and calling `summarize_latencies`.",
                "Create `test_metrics.py` with unittest tests for `metrics.py` and `cli.py`.",
            ],
            "constraints": ["Python 3 stdlib only"],
            "success_criteria": ["All unit tests in `test_metrics.py` pass with exit code 0."],
        }

        recorded_options: list[tuple[str, dict]] = []
        child_prompts: dict[str, str] = {}

        metrics_src = (
            "def summarize_latencies(values: list[float]) -> dict:\n"
            "    if not values:\n"
            "        raise ValueError('values must not be empty')\n"
            "    nums = [float(v) for v in values]\n"
            "    return {\n"
            "        'count': len(nums),\n"
            "        'min': min(nums),\n"
            "        'max': max(nums),\n"
            "        'mean': round(sum(nums) / len(nums), 2),\n"
            "    }\n"
        )
        cli_bad_import_src = (
            "import argparse, json, sys\n"
            "from metrics import compute_average\n"
            "print('bad')\n"
        )
        cli_good_src = (
            "import argparse\n"
            "import json\n"
            "import sys\n"
            "from metrics import summarize_latencies\n\n"
            "def main() -> int:\n"
            "    parser = argparse.ArgumentParser()\n"
            "    parser.add_argument('--values', required=True)\n"
            "    args = parser.parse_args()\n"
            "    try:\n"
            "        raw = [p.strip() for p in args.values.split(',') if p.strip()]\n"
            "        vals = [float(x) for x in raw]\n"
            "        res = summarize_latencies(vals)\n"
            "    except ValueError as exc:\n"
            "        print(str(exc), file=sys.stderr)\n"
            "        return 2\n"
            "    print(json.dumps(res, sort_keys=True))\n"
            "    return 0\n\n"
            "if __name__ == '__main__':\n"
            "    sys.exit(main())\n"
        )
        test_src = (
            "import subprocess\n"
            "import sys\n"
            "import unittest\n"
            "from metrics import summarize_latencies\n\n"
            "class TelemetryTests(unittest.TestCase):\n"
            "    def test_summary(self):\n"
            "        self.assertEqual(\n"
            "            summarize_latencies([10, 20, 30]),\n"
            "            {'count': 3, 'min': 10.0, 'max': 30.0, 'mean': 20.0},\n"
            "        )\n\n"
            "    def test_empty_raises(self):\n"
            "        with self.assertRaises(ValueError):\n"
            "            summarize_latencies([])\n\n"
            "    def test_cli_valid_and_invalid(self):\n"
            "        ok = subprocess.run([sys.executable, 'cli.py', '--values', '10,20,30'], capture_output=True, text=True)\n"
            "        self.assertEqual(ok.returncode, 0)\n"
            "        self.assertEqual(ok.stdout.strip(), '{\"count\": 3, \"max\": 30.0, \"mean\": 20.0, \"min\": 10.0}')\n"
            "        bad = subprocess.run([sys.executable, 'cli.py', '--values', ''], capture_output=True, text=True)\n"
            "        self.assertEqual(bad.returncode, 2)\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n"
        )

        # Decomposer returns 3 overlapping-scope children; AGISS partitioner must make them disjoint & ordered!
        decompose_payload = {
            "children": [
                {
                    "goal": "Implement `summarize_latencies` in `metrics.py`.",
                    "done_when": ["`metrics.py` defines `summarize_latencies(values)`."],
                    "scope_hint": ["metrics.py", "cli.py", "test_metrics.py"],
                },
                {
                    "goal": "Implement `--values` CLI in `cli.py` calling `metrics.py`.",
                    "done_when": ["`cli.py` prints canonical JSON for valid `--values`."],
                    "scope_hint": ["metrics.py", "cli.py", "test_metrics.py"],
                },
                {
                    "goal": "Create unit test suite in `test_metrics.py` testing `metrics.py` and `cli.py`.",
                    "done_when": ["`test_metrics.py` passes via unittest."],
                    "scope_hint": ["metrics.py", "cli.py", "test_metrics.py"],
                },
            ]
        }

        child1_steps = iter([
            self._tool_msg("context_sufficiency_check", {"context_status": "sufficient", "reason": "Spec complete."}),
            # Child 1 tries to prematurely create cli.py -> must be blocked by disjoint ownership!
            self._tool_msg("write_file", {"path": "cli.py", "content": "x = 1\n"}),
            self._tool_msg("write_file", {"path": "metrics.py", "content": metrics_src}),
            self._tool_msg(
                "run_file",
                {
                    "path": "metrics.py",
                    "function": "summarize_latencies",
                    "arguments": [[10, 20, 30]],
                    "expected": {"count": 3, "min": 10.0, "max": 30.0, "mean": 20.0},
                },
            ),
            self._done_msg("Implemented and verified metrics.py."),
        ])
        child2_steps = iter([
            self._tool_msg("context_sufficiency_check", {"context_status": "sufficient", "reason": "Sibling contract clear."}),
            # First write has hallucinated symbol `compute_average` -> live Assume-Guarantee ACI check catches it!
            self._tool_msg("write_file", {"path": "cli.py", "content": cli_bad_import_src}),
            self._tool_msg("write_file", {"path": "cli.py", "content": cli_good_src}),
            self._tool_msg(
                "run_command",
                {
                    "command": "python cli.py --values 10,20,30",
                    "expected_stdout": '{"count": 3, "max": 30.0, "mean": 20.0, "min": 10.0}\n',
                },
            ),
            self._done_msg("Implemented and verified cli.py."),
        ])
        child3_steps = iter([
            self._tool_msg("context_sufficiency_check", {"context_status": "sufficient", "reason": "Both siblings verified."}),
            self._tool_msg("write_file", {"path": "test_metrics.py", "content": test_src}),
            self._tool_msg("run_command", {"command": "python -m unittest test_metrics.py"}),
            self._done_msg("Created and verified test_metrics.py."),
        ])
        root_integration_steps = iter([
            self._tool_msg("context_sufficiency_check", {"context_status": "sufficient", "reason": "All 3 children verified."}),
            self._tool_msg("run_command", {"command": "python -m unittest test_metrics.py"}),
            self._done_msg("Parent integration verified full multi-file suite."),
        ])

        aci_warnings_seen: list[str] = []

        def fake_http_post_json(_url, timeout=None, payload=None):
            opts = dict((payload or {}).get("options") or {})
            msgs = list((payload or {}).get("messages") or [])
            fmt = (payload or {}).get("format")
            user_blob = "\n".join(str(m.get("content", "")) for m in msgs if isinstance(m, dict))
            recorded_options.append(("structured" if fmt else "chat", opts))

            class _Resp:
                status_code = 200
                text = "{}"

                def __init__(self, msg_dict: dict):
                    self._body = {
                        "done": True,
                        "done_reason": "stop",
                        "eval_count": 32,
                        "prompt_eval_count": 128,
                        "message": msg_dict,
                    }

                def json(self):
                    return self._body

            if fmt is not None:
                fmt_str = json.dumps(fmt)
                if '"children"' in fmt_str:
                    return _Resp({"role": "assistant", "content": json.dumps(decompose_payload)})
                if '"goal_anchor"' in fmt_str:
                    target_file = (
                        "metrics.py" if '"id": "1"' in user_blob and '"id": "ROOT"' not in user_blob
                        else "cli.py" if '"id": "2"' in user_blob and '"id": "ROOT"' not in user_blob
                        else "test_metrics.py"
                    )
                    return _Resp({
                        "role": "assistant",
                        "content": json.dumps({
                            "goal_anchor": prompt[:200],
                            "task": f"Implement {target_file}",
                            "targets": [target_file],
                            "existing_facts": [],
                            "implementation_plan": [f"Write {target_file}"],
                            "interfaces_to_reuse": [],
                            "invariants": ["Python 3 stdlib only"],
                            "project_specific_quality_rules": [],
                            "do_not": [],
                            "verification_plan": [f"Verify {target_file}"],
                            "done_when": [f"{target_file} verified"],
                            "expected_outcome": f"{target_file} ready",
                        }),
                    })
                return _Resp({"role": "assistant", "content": json.dumps({"decision": "split"})})

            for m in msgs:
                if isinstance(m, dict) and "ASSUME-GUARANTEE INTERFACE CHECK:" in str(m.get("content", "")):
                    aci_warnings_seen.append(str(m["content"]))

            if "ROLE CONSTRAINT: You are strictly READ-ONLY" in user_blob:
                if (mini.WORKSPACE / "test_metrics.py").is_file():
                    if any(m.get("role") == "tool" for m in msgs):
                        return _Resp(self._done_msg("Falsifier verified unittest suite."))
                    return _Resp(self._tool_msg("run_command", {"command": "python -m unittest test_metrics.py"}))
                return _Resp(self._done_msg("Read-only review complete."))

            first_user = next((str(m.get("content", "")) for m in msgs if isinstance(m, dict) and m.get("role") == "user"), "")
            if "CURRENT TASK:\nImplement `summarize_latencies`" in first_user:
                child_prompts.setdefault("1", user_blob)
                return _Resp(next(child1_steps))
            if "CURRENT TASK:\nImplement `--values` CLI" in first_user:
                child_prompts.setdefault("2", user_blob)
                return _Resp(next(child2_steps))
            if "CURRENT TASK:\nCreate unit test suite" in first_user:
                child_prompts.setdefault("3", user_blob)
                return _Resp(next(child3_steps))
            if "HIERARCHICAL INTEGRATION CONTRACT:" in first_user:
                return _Resp(next(root_integration_steps, self._done_msg("Integrated.")))
            return _Resp(self._done_msg("Ready."))

        with patch.object(mini, "http_post_json", side_effect=fake_http_post_json):
            result, _mem = mini.run_recursive_request(
                prompt,
                mini.load_memory(),
                interactive=False,
                contract_override=contract,
                worker_progress_policy="progress_constrained",
                verification_environment_policy="resolved",
                decoding_policy="adaptive",
            )

        self.assertEqual(result["status"], "done", result)
        self.assertEqual(mini.RUN.get("splits"), 1)
        self.assertGreaterEqual(mini.RUN.get("assume_guarantee_partitions", 0), 1)

        # Verify Adaptive Decoding (`min_p`, `top_p`) was actually sent in Ollama options!
        chat_opts = [opts for kind, opts in recorded_options if kind == "chat"]
        self.assertTrue(any("min_p" in opts and opts["min_p"] >= 0.05 for opts in chat_opts), chat_opts)

        # Verify Child 2 received Child 1's verified AST signature (`summarize_latencies(values)`)!
        self.assertIn("ASSUME-GUARANTEE SIBLING CONTRACT:", child_prompts["2"])
        self.assertIn("summarize_latencies", child_prompts["2"])
        self.assertIn("OWNED WRITABLE FILES (edit/create ONLY these): cli.py", child_prompts["2"])

        # Verify live write-time Assume-Guarantee ACI caught `from metrics import compute_average`!
        self.assertTrue(
            any("compute_average" in w for w in aci_warnings_seen),
            f"Expected live ACI warning for hallucinated symbol compute_average, got: {aci_warnings_seen}",
        )

        # Verify all 3 committed deliverables exist and pass real subprocess unittest independently!
        for fname in ("metrics.py", "cli.py", "test_metrics.py"):
            self.assertTrue((mini.WORKSPACE / fname).is_file(), f"Missing committed file {fname}")
        ext_run = subprocess.run(
            [sys.executable, "-m", "unittest", "test_metrics.py"],
            cwd=str(mini.WORKSPACE),
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(ext_run.returncode, 0, ext_run.stderr)

    def test_multifile_threejs_webgl_agiss_visual_anti_overlap_and_initial_frame_e2e(self) -> None:
        ok, _ = mini.ensure_browser(False)
        if not ok:
            self.skipTest("Playwright Chromium unavailable")

        # 1. Verify Three.js scene that does NOT render before start() triggers `blank_initial_canvas`,
        #    and overlapping HUD triggers `hud_layout_overlap`!
        blank_and_overlapping_html = """<!doctype html>
<html><head><title>Broken Three Draft</title>
<script type="importmap">{"imports": {"three": "./fake-three.js"}}</script>
<style>
  html, body { margin: 0; height: 100%; background: #050816; overflow: hidden; }
  canvas { width: 100vw; height: 100vh; display: block; }
  #hud-a { position: absolute; top: 20px; right: 20px; width: 180px; height: 60px; color: #fff; }
  #hud-b { position: absolute; top: 24px; right: 24px; width: 180px; height: 60px; color: #0ff; }
</style></head>
<body>
  <div id="hud-a">Score: 0</div>
  <div id="hud-b">Controls: WASD</div>
  <canvas id="c" width="1440" height="900"></canvas>
  <script>
    const c = document.getElementById('c');
    const gl = c.getContext('webgl2') || c.getContext('webgl');
    if (gl) { gl.clearColor(0.02, 0.03, 0.09, 1.0); gl.clear(gl.COLOR_BUFFER_BIT); }
    // Intentionally references THREE without rendering any geometry before start()
    window.THREE_MARKER = 'THREE';
    let s = { status: 'paused', score: 0, player: { x: 0, z: 0 }, position: { x: 0, y: 0.5, z: 0 }, tick: 0 };
    window.AGENT_GAME = {
      getState: () => ({ ...s }),
      start: () => { s.status = 'playing'; },
      restart: () => { s.score = 0; s.status = 'playing'; },
      move: () => { s.player = { x: 1, z: 0 }; s.position = { x: 1, y: 0.5, z: 0 }; }
    };
  </script>
</body></html>"""
        (mini.WORKSPACE / "fake-three.js").write_text("export const REVISION = '160';\n", encoding="utf-8")
        (mini.WORKSPACE / "index.html").write_text(blank_and_overlapping_html, encoding="utf-8")
        mini.ACTIVE_TOOL_CONTRACT = {"goal": "Build a 3D Three.js browser game in index.html"}
        profile = mini.infer_web_profile("Build a 3D Three.js browser game with keyboard movement and restart", {})

        # Deterministic pure-Python check of `evaluate_web_snapshot` + `run_integration_preflight`
        # (always runs even if OS commit limits prevent spawning a Chromium subprocess)
        det_bad = mini.evaluate_web_snapshot(
            {
                "title": "Broken Three Draft",
                "text": "Score: 0 Controls: WASD",
                "console_errors": [],
                "page_errors": [],
                "network_errors": [],
                "runtime_state": {
                    "canvasCount": 1,
                    "gameBridge": {"name": "AGENT_GAME", "state": {"status": "paused", "score": 0}},
                    "canvasMetrics": {
                        "count": 1,
                        "maxWidth": 1440,
                        "maxHeight": 900,
                        "visibleCount": 1,
                        "hasImportMap": True,
                        "hasWebGL": True,
                        "requiresThreeWebGL": True,
                        "hudOverlapCount": 1,
                        "hudOverlaps": ["#hud-a vs #hud-b"],
                        "initialFrameBlank": True,
                    },
                },
                "interaction_checks": [{"name": n, "passed": True} for n in profile.required_interactions],
            },
            profile,
        )
        self.assertFalse(det_bad["passed"])
        det_codes = {f["code"] for f in det_bad.get("failures", [])}
        self.assertIn("hud_layout_overlap", det_codes)
        self.assertIn("blank_initial_canvas", det_codes)

        bad_snap = mini.browser_workspace_snapshot("index.html", profile=profile)
        if bad_snap.get("environment_error"):
            # Still verify Assume-Guarantee multi-file HTML+JS preflight deterministically before skipping Chromium
            (mini.WORKSPACE / "fake-three.js").unlink(missing_ok=True)
            (mini.WORKSPACE / "three-lite.js").write_text("export const THREE = {}; export function renderWebGLScene(){}\n", encoding="utf-8")
            (mini.WORKSPACE / "index.html").write_text(
                '<!doctype html><html><head><title>App</title><script type="importmap">{"imports":{"three":"./three-lite.js"}}</script></head>'
                '<body><canvas id="scene-canvas"></canvas><span id="score-val"></span><script type="module" src="./game.js"></script></body></html>',
                encoding="utf-8",
            )
            (mini.WORKSPACE / "game.js").write_text(
                "import { THREE } from 'three';\nconst el = document.getElementById('missing-dom-id');\nexport { el };\n",
                encoding="utf-8",
            )
            mismatch_pf = mini.run_integration_preflight()
            self.assertFalse(mismatch_pf["passed"], mismatch_pf)
            self.assertGreaterEqual(mini.RUN.get("interface_hallucinations_detected", 0), 1)
            self.skipTest(f"Host commit limit prevented Chromium launch: {bad_snap.get('evidence')}")
        self.assertFalse(bad_snap["passed"])
        failure_codes = {f["code"] for f in bad_snap.get("failures", [])}
        self.assertIn("hud_layout_overlap", failure_codes, bad_snap)
        self.assertIn("blank_initial_canvas", failure_codes, bad_snap)
        self.assertTrue(any("overlap" in h.lower() for h in bad_snap.get("repair_hints", [])))
        self.assertTrue(any("init()" in h for h in bad_snap.get("repair_hints", [])))

        # 2. Verify modular `index.html` + `game.js` with immediate pre-start WebGL rendering,
        #    non-overlapping 4-corner HUD, and clean Assume-Guarantee preflight passes 100%!
        clean_html = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Cyber Prism Arena 3D</title>
<script type="importmap">{"imports": {"three": "./three-lite.js"}}</script>
<style>
  html, body { margin: 0; height: 100%; background: #040714; overflow: hidden; font-family: system-ui, sans-serif; }
  #scene-canvas { width: 100vw; height: 100vh; display: block; }
  #brand-hud { position: fixed; top: 18px; left: 20px; color: #22d3ee; font-size: 22px; font-weight: 700; }
  #stats-hud { position: fixed; top: 18px; right: 20px; color: #f8fafc; background: rgba(15,23,42,0.78); padding: 10px 16px; border-radius: 10px; }
  #action-bar { position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%); display: flex; gap: 12px; }
  #action-bar button { padding: 10px 18px; border-radius: 8px; border: 1px solid #22d3ee; background: #0e7490; color: #fff; cursor: pointer; }
  #legend-hud { position: fixed; bottom: 22px; right: 20px; color: #cbd5e1; font-size: 13px; background: rgba(15,23,42,0.72); padding: 8px 12px; border-radius: 8px; }
</style></head>
<body>
  <canvas id="scene-canvas" width="1440" height="900"></canvas>
  <div id="brand-hud">Cyber Prism Arena 3D <span id="status-badge">PAUSED</span></div>
  <div id="stats-hud">Score: <span id="score-val">0</span> | Prisms: <span id="collected-val">0</span></div>
  <div id="action-bar"><button id="start-btn">Start Mission</button><button id="reset-btn">Reset</button></div>
  <div id="legend-hud">WASD / Arrows: Pilot Hovercraft</div>
  <script type="module" src="./game.js"></script>
</body></html>"""
        three_lite_js = """export function renderWebGLScene(canvas, shipX, shipZ, tick) {
  const gl = canvas.getContext('webgl2', { preserveDrawingBuffer: true }) || canvas.getContext('webgl', { preserveDrawingBuffer: true });
  if (!gl) return false;
  gl.viewport(0, 0, canvas.width, canvas.height);
  gl.enable(gl.SCISSOR_TEST);
  gl.scissor(0, 0, canvas.width, canvas.height);
  gl.clearColor(0.02, 0.04, 0.11, 1.0);
  gl.clear(gl.COLOR_BUFFER_BIT);
  // Render cyber gridhorizon bands + glowing prisms + hovercraft in center playfield immediately on init()!
  for (let i = 0; i < 9; i++) {
    gl.scissor(160 + i * 130, 180, 4, 520);
    gl.clearColor(0.05, 0.45, 0.65, 1.0);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }
  const prisms = [[340, 320], [520, 480], [920, 340], [1060, 500], [720, 260], [600, 610]];
  for (const [px, py] of prisms) {
    gl.scissor(px, py + ((tick * 2) % 12), 34, 34);
    gl.clearColor(1.0, 0.82, 0.12, 1.0);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }
  const cx = Math.max(120, Math.min(1300, Math.round(700 + shipX * 45)));
  const cz = Math.max(150, Math.min(750, Math.round(430 + shipZ * 45)));
  gl.scissor(cx - 28, cz - 14, 56, 28);
  gl.clearColor(0.0, 0.96, 1.0, 1.0);
  gl.clear(gl.COLOR_BUFFER_BIT);
  gl.disable(gl.SCISSOR_TEST);
  return true;
}
export const THREE = { REVISION: '160' };
"""
        game_js = """import { THREE, renderWebGLScene } from 'three';

const canvas = document.getElementById('scene-canvas');
const scoreEl = document.getElementById('score-val');
const collectedEl = document.getElementById('collected-val');
const statusEl = document.getElementById('status-badge');
const startBtn = document.getElementById('start-btn');
const resetBtn = document.getElementById('reset-btn');

const state = { status: 'paused', score: 0, collected: 0, player: { x: 0, z: 0 }, position: { x: 0, y: 0.5, z: 0 }, tick: 0 };

function syncHud() {
  scoreEl.textContent = String(state.score);
  collectedEl.textContent = String(state.collected);
  statusEl.textContent = state.status.toUpperCase();
}

function animate() {
  state.tick += 1;
  renderWebGLScene(canvas, state.position.x, state.position.z, state.tick);
  requestAnimationFrame(animate);
}

window.AGENT_GAME = {
  getState: () => JSON.parse(JSON.stringify(state)),
  start: () => { state.status = 'playing'; syncHud(); },
  restart: () => { state.score = 0; state.collected = 0; state.position = { x: 0, y: 0.5, z: 0 }; state.player = { x: 0, z: 0 }; state.status = 'playing'; syncHud(); },
  move: (dir) => {
    const step = 1.0;
    if (dir === 'up' || dir === 'forward') state.position.z -= step;
    if (dir === 'down' || dir === 'backward') state.position.z += step;
    if (dir === 'left') state.position.x -= step;
    if (dir === 'right') state.position.x += step;
    state.player = { x: state.position.x, z: state.position.z };
    renderWebGLScene(canvas, state.position.x, state.position.z, state.tick);
  },
  forceCollect: () => { state.score += 10; state.collected += 1; syncHud(); },
  forceCollision: () => { state.status = 'gameover'; syncHud(); },
  forceWin: () => { state.status = 'won'; syncHud(); }
};

startBtn.addEventListener('click', () => window.AGENT_GAME.start());
resetBtn.addEventListener('click', () => window.AGENT_GAME.restart());
syncHud();
// Render immediately on init() so initialFrameBlank is False BEFORE Start is clicked!
renderWebGLScene(canvas, 0, 0, 1);
requestAnimationFrame(animate);
"""
        (mini.WORKSPACE / "fake-three.js").unlink(missing_ok=True)
        (mini.WORKSPACE / "three-lite.js").write_text(three_lite_js, encoding="utf-8")
        (mini.WORKSPACE / "index.html").write_text(clean_html, encoding="utf-8")
        (mini.WORKSPACE / "game.js").write_text(game_js, encoding="utf-8")

        preflight = mini.run_integration_preflight()
        self.assertTrue(preflight["passed"], preflight)

        good_snap = mini.browser_workspace_snapshot("index.html", profile=profile)
        self.assertTrue(good_snap["passed"], good_snap)
        metrics = good_snap["runtime_state"]["canvasMetrics"]
        self.assertEqual(metrics.get("hudOverlapCount"), 0)
        self.assertFalse(metrics.get("initialFrameBlank"))
        self.assertGreater(metrics.get("initialCenterLuminanceStd", 0), 1.0)


if __name__ == "__main__":
    unittest.main()
