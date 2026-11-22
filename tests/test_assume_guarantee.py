"""Unit tests for Assume-Guarantee Interface Certificates & Disjoint Child Ownership."""

from __future__ import annotations

import unittest

from hivo.assume_guarantee import (
    MISSING_DOM_ID,
    MISSING_HTML_SCRIPT,
    MISSING_HTML_STYLESHEET,
    MISSING_IMPORTMAP_SPECIFIER,
    MISSING_JS_EXPORT,
    MISSING_PYTHON_SYMBOL,
    MISSING_RELATIVE_MODULE,
    THREE_CORE_MISIMPORTED_FROM_ADDONS,
    _THREE_CORE_NOT_ADDONS,
    extract_file_certificate,
    format_sibling_guarantees_context,
    partition_disjoint_child_ownership,
    verify_compositional_certificates,
)


class PartitionDisjointChildOwnershipTests(unittest.TestCase):
    def test_python_producer_cli_consumer_and_test_suite_partition(self) -> None:
        raw_children = [
            {
                "id": "child_metrics",
                "goal": "Implement metrics.py with summarize_latencies(values)",
                "done_when": ["metrics.py computes min, max, mean, and p95"],
                "scope_hint": ["metrics.py"],
            },
            {
                "id": "child_cli",
                "goal": "Implement cli.py importing metrics.py to expose --values CLI flag",
                "done_when": ["cli.py prints formatted summary"],
                "scope_hint": ["cli.py", "metrics.py"],
            },
            {
                "id": "child_tests",
                "goal": "Write unit tests in test_metrics.py covering metrics.py and cli.py",
                "done_when": ["unittest suite passes"],
                "scope_hint": ["test_metrics.py"],
            },
        ]

        result = partition_disjoint_child_ownership(raw_children)

        # Ensure input dicts were deep-copied and never mutated in place
        self.assertEqual(raw_children[1]["scope_hint"], ["cli.py", "metrics.py"])
        self.assertNotIn("owned_mutation_paths", raw_children[0])

        children = {c["id"]: c for c in result["children"]}
        self.assertEqual(
            result["ownership_map"],
            {
                "metrics.py": "child_metrics",
                "cli.py": "child_cli",
                "test_metrics.py": "child_tests",
            },
        )

        # Disjoint owned_mutation_paths & narrowed scope_hint
        self.assertEqual(children["child_metrics"]["owned_mutation_paths"], ["metrics.py"])
        self.assertEqual(children["child_metrics"]["scope_hint"], ["metrics.py"])
        self.assertEqual(children["child_metrics"]["read_only_sibling_paths"], [])
        self.assertEqual(children["child_metrics"]["depends_on"], [])

        self.assertEqual(children["child_cli"]["owned_mutation_paths"], ["cli.py"])
        self.assertEqual(children["child_cli"]["scope_hint"], ["cli.py"])
        self.assertEqual(children["child_cli"]["read_only_sibling_paths"], ["metrics.py"])
        self.assertEqual(children["child_cli"]["depends_on"], ["child_metrics"])

        self.assertEqual(children["child_tests"]["owned_mutation_paths"], ["test_metrics.py"])
        self.assertEqual(children["child_tests"]["scope_hint"], ["test_metrics.py"])
        self.assertCountEqual(
            children["child_tests"]["read_only_sibling_paths"],
            ["metrics.py", "cli.py"],
        )
        self.assertEqual(
            children["child_tests"]["depends_on"],
            ["child_metrics", "child_cli"],
        )

        self.assertEqual(
            result["dependency_edges"],
            [
                ("child_metrics", "child_cli"),
                ("child_metrics", "child_tests"),
                ("child_cli", "child_tests"),
            ],
        )
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(result["conflicts"][0]["path"], "metrics.py")
        self.assertEqual(result["conflicts"][0]["owner_child_id"], "child_metrics")

    def test_html_shell_and_threejs_game_module_excludes_bare_library_names(self) -> None:
        raw_children = [
            {
                "id": "html_shell",
                "goal": "Create Three.js HTML shell in index.html with #gameCanvas and importmap",
                "done_when": ["index.html defines canvas and importmap"],
                "scope_hint": ["index.html"],
            },
            {
                "id": "game_logic",
                "goal": "Implement Three.js 3D scene and AGENT_GAME bridge in game.js",
                "done_when": ["game.js renders scene into #gameCanvas"],
                "scope_hint": ["game.js"],
            },
        ]

        result = partition_disjoint_child_ownership(raw_children)
        self.assertNotIn("Three.js", result["ownership_map"])
        self.assertNotIn("three.js", result["ownership_map"])
        self.assertEqual(
            result["ownership_map"],
            {"index.html": "html_shell", "game.js": "game_logic"},
        )

        by_id = {c["id"]: c for c in result["children"]}
        self.assertEqual(by_id["html_shell"]["owned_mutation_paths"], ["index.html"])
        self.assertEqual(by_id["html_shell"]["depends_on"], [])
        self.assertEqual(by_id["game_logic"]["owned_mutation_paths"], ["game.js"])
        self.assertEqual(by_id["game_logic"]["read_only_sibling_paths"], ["index.html"])
        self.assertEqual(by_id["game_logic"]["depends_on"], ["html_shell"])
        self.assertEqual(result["dependency_edges"], [("html_shell", "game_logic")])

    def test_mutual_html_and_js_mentions_remain_acyclic_producer_to_consumer(self) -> None:
        raw_children = [
            {
                "id": "c_html",
                "goal": "Create index.html loading ./game.js via module script",
                "scope_hint": ["index.html", "game.js"],
            },
            {
                "id": "c_js",
                "goal": "Create game.js mounting WebGLRenderer into index.html",
                "scope_hint": ["index.html", "game.js"],
            },
        ]

        result = partition_disjoint_child_ownership(raw_children)
        by_id = {c["id"]: c for c in result["children"]}
        self.assertEqual(by_id["c_html"]["owned_mutation_paths"], ["index.html"])
        self.assertEqual(by_id["c_js"]["owned_mutation_paths"], ["game.js"])
        # Acyclic: Tier 0 HTML shell produces DOM/importmap -> Tier 1 JS module consumes it
        self.assertEqual(by_id["c_html"]["depends_on"], [])
        self.assertEqual(by_id["c_js"]["depends_on"], ["c_html"])
        self.assertEqual(result["dependency_edges"], [("c_html", "c_js")])

    def test_declared_paths_canonical_basename_resolution_and_unclaimed_assignment(self) -> None:
        raw_children = [
            {
                "id": "core",
                "goal": "Implement models.py data structures",
                "scope_hint": [],
            },
            {
                "id": "app",
                "goal": "Build app.py entrypoint importing models.py",
                "scope_hint": [],
            },
            {
                "id": "suite",
                "goal": "Write unit tests for models and app",
                "scope_hint": [],
            },
        ]
        declared = ["src/models.py", "src/app.py", "tests/test_models.py"]
        result = partition_disjoint_child_ownership(raw_children, declared_paths=declared)
        self.assertEqual(
            result["ownership_map"],
            {
                "src/models.py": "core",
                "src/app.py": "app",
                "tests/test_models.py": "suite",
            },
        )
        by_id = {c["id"]: c for c in result["children"]}
        self.assertEqual(by_id["app"]["depends_on"], ["core"])
        self.assertEqual(by_id["suite"]["depends_on"], ["core", "app"])

    def test_blanket_inherited_scope_hint_is_narrowed_without_cycles(self) -> None:
        shared_scope = ["metrics.py", "cli.py", "test_metrics.py"]
        raw_children = [
            {"id": "1", "goal": "Create metrics.py core calculations", "scope_hint": list(shared_scope)},
            {"id": "2", "goal": "Create cli.py entrypoint", "scope_hint": list(shared_scope)},
            {"id": "3", "goal": "Create test_metrics.py unit tests", "scope_hint": list(shared_scope)},
        ]
        result = partition_disjoint_child_ownership(raw_children)
        by_id = {c["id"]: c for c in result["children"]}
        self.assertEqual(by_id["1"]["owned_mutation_paths"], ["metrics.py"])
        self.assertEqual(by_id["2"]["owned_mutation_paths"], ["cli.py"])
        self.assertEqual(by_id["3"]["owned_mutation_paths"], ["test_metrics.py"])
        self.assertEqual(by_id["1"]["depends_on"], [])
        self.assertEqual(by_id["2"]["depends_on"], ["1"])
        self.assertEqual(by_id["3"]["depends_on"], ["1", "2"])


class ExtractFileCertificateTests(unittest.TestCase):
    def test_extract_python_certificate_functions_classes_constants_cli_and_imports(self) -> None:
        py_src = (
            "import argparse\n"
            "from metrics import summarize_latencies\n"
            "\n"
            "DEFAULT_PRECISION = 2\n"
            "__all__ = ['run_cli', 'SummaryFormatter']\n"
            "\n"
            "def _internal_helper(x):\n"
            "    return x\n"
            "\n"
            "def run_cli(values, precision=2, *, as_json=False):\n"
            "    parser = argparse.ArgumentParser()\n"
            "    parser.add_argument('--values', nargs='+')\n"
            "    parser.add_argument('--json', action='store_true')\n"
            "    return summarize_latencies(values)\n"
            "\n"
            "class SummaryFormatter:\n"
            "    def _secret(self):\n"
            "        pass\n"
            "    def render(self, payload):\n"
            "        return str(payload)\n"
        )
        cert = extract_file_certificate(".\\src\\cli.py", py_src)
        self.assertEqual(cert["path"], "src/cli.py")
        self.assertTrue(cert["parse_valid"])
        self.assertEqual(len(cert["content_sha256"]), 64)
        self.assertEqual(len(cert["certificate_sha256"]), 64)

        guar = cert["guarantees"]
        self.assertEqual(
            guar["functions"],
            [{"name": "run_cli", "args": ["values", "precision", "as_json"], "defaults_count": 2}],
        )
        self.assertEqual(
            guar["classes"],
            [{"name": "SummaryFormatter", "methods": ["render"]}],
        )
        self.assertCountEqual(
            guar["constants"],
            ["DEFAULT_PRECISION", "run_cli", "SummaryFormatter"],
        )
        self.assertEqual(guar["cli_flags"], ["--values", "--json"])
        self.assertEqual(
            cert["assumes"]["python_imports"],
            [
                {"module": "argparse", "names": []},
                {"module": "metrics", "names": ["summarize_latencies"]},
            ],
        )

    def test_certificate_sha256_is_invariant_to_internal_body_changes(self) -> None:
        v1 = "def summarize_latencies(values):\n    return {'count': len(values)}\n"
        v2 = "def summarize_latencies(values):\n    # refactored implementation\n    total = len(values)\n    return {'count': total}\n"
        c1 = extract_file_certificate("metrics.py", v1)
        c2 = extract_file_certificate("metrics.py", v2)
        self.assertNotEqual(c1["content_sha256"], c2["content_sha256"])
        self.assertEqual(c1["certificate_sha256"], c2["certificate_sha256"])

    def test_extract_html_certificate_detects_ids_importmap_and_malformed_close_tag(self) -> None:
        valid_html = """<!DOCTYPE html>
<html>
<head>
  <link rel="stylesheet" href="./styles.css">
  <script type="importmap">
  {
    "imports": {
      "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
      "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
    }
  }
  </script>
</head>
<body>
  <canvas id="gameCanvas" data-mode="arcade"></canvas>
  <button id="start-btn" data-action="start">Start</button>
  <button id="reset-btn">Reset</button>
  <script type="module" src="./game.js"></script>
</body>
</html>"""
        cert = extract_file_certificate("index.html", valid_html)
        guar = cert["guarantees"]
        self.assertEqual(guar["dom_ids"], ["gameCanvas", "reset-btn", "start-btn"])
        self.assertEqual(guar["canvas_ids"], ["gameCanvas"])
        self.assertEqual(guar["button_ids"], ["reset-btn", "start-btn"])
        self.assertEqual(guar["data_attributes"], ["data-action", "data-mode"])
        self.assertEqual(guar["importmap_keys"], ["three", "three/addons/"])
        self.assertTrue(guar["has_body_tag"])
        self.assertEqual(cert["assumes"]["module_scripts"], ["./game.js"])
        self.assertEqual(cert["assumes"]["stylesheets"], ["./styles.css"])

        malformed_html = valid_html.replace("</html>", "</html\\>")
        bad_cert = extract_file_certificate("index.html", malformed_html)
        self.assertFalse(bad_cert["guarantees"]["has_body_tag"])

    def test_extract_js_certificate_exports_globals_dynamic_dom_and_comment_stripping(self) -> None:
        js_src = """
// import { FakeCommented } from './DoesNotExist.js';
/* document.getElementById('commented-out-id'); */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import Starfield, { createNebula as makeNebula } from './Starfield.js';

export const MAX_SCORE = 100;
export function initGame() {
  const toast = document.createElement('div');
  toast.id = 'dynamic-toast';
  const hud = document.getElementById('score');
  const canvas = document.querySelector('#gameCanvas');
  return { toast, hud, canvas };
}
export default class GameApp {}

window.AGENT_GAME = {
  getState() {
    return { score: 0, nestedIgnored: true };
  },
  move: (dir) => dir,
  forceWin() {},
};
"""
        cert = extract_file_certificate("game.js", js_src)
        guar = cert["guarantees"]
        assumes = cert["assumes"]
        self.assertCountEqual(guar["exports"], ["default", "MAX_SCORE", "initGame"])
        self.assertEqual(guar["globals"], ["getState", "move", "forceWin"])
        self.assertEqual(guar["created_dom_ids"], ["dynamic-toast"])
        self.assertEqual(
            assumes["relative_imports"],
            [{"source": "./Starfield.js", "names": ["default", "createNebula"]}],
        )
        self.assertEqual(
            assumes["package_imports"],
            [
                {"source": "three", "names": ["*"]},
                {"source": "three/addons/controls/OrbitControls.js", "names": ["OrbitControls"]},
            ],
        )
        self.assertEqual(assumes["queried_dom_ids"], ["gameCanvas", "score"])

    def test_nested_js_template_literals_do_not_corrupt_comment_stripping(self) -> None:
        js_src = (
            "const status = `State: ${active ? `LIVE` : 'IDLE'}`;\n"
            "// document.getElementById('commented-after-nested-template');\n"
            "export function updateHud() {\n"
            "  return document.getElementById('live-hud');\n"
            "}\n"
        )
        cert = extract_file_certificate("hud.js", js_src)
        self.assertEqual(cert["guarantees"]["exports"], ["updateHud"])
        self.assertEqual(cert["assumes"]["queried_dom_ids"], ["live-hud"])

    def test_extract_css_certificate_ignores_hex_colors_and_numeric_decimals(self) -> None:
        css_src = """
/* #commented-id .commented-class */
#game-container, .hud-panel {
  color: #fff;
  background-color: #0a1b2c;
  transition: opacity 0.25s ease-in-out;
}
@media (max-width: 800px) {
  #score.active-badge {
    border: 1.5px solid #abcdef;
  }
}
@keyframes pulse {
  from { opacity: 0.5; }
  to { opacity: 1.0; }
}
"""
        cert = extract_file_certificate("styles.css", css_src)
        self.assertEqual(cert["guarantees"]["css_ids"], ["game-container", "score"])
        self.assertEqual(cert["guarantees"]["css_classes"], ["active-badge", "hud-panel"])


class CompositionalVerificationTests(unittest.TestCase):
    def test_threejs_swarm_bug_1_missing_relative_starfield_module(self) -> None:
        html_cert = extract_file_certificate(
            "index.html",
            """<!DOCTYPE html><html><head><script type="importmap">
            {"imports": {"three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js"}}
            </script></head><body><canvas id="gameCanvas"></canvas>
            <script type="module" src="./game.js"></script></body></html>""",
        )
        js_cert = extract_file_certificate(
            "game.js",
            """import * as THREE from 'three';
            import { Starfield } from './Starfield.js';
            const c = document.getElementById('gameCanvas');
            """,
        )
        verdict = verify_compositional_certificates(
            {"index.html": html_cert, "game.js": js_cert},
            workspace_files={"index.html", "game.js"},
        )
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["interface_hallucination_count"], 1)
        self.assertEqual(verdict["violations"][0]["code"], MISSING_RELATIVE_MODULE)
        self.assertIn("./Starfield.js", verdict["repair_counterexamples"][0])
        self.assertIn("Starfield.js", verdict["repair_counterexamples"][0])

    def test_threejs_swarm_bug_2_grid_helper_misimported_from_addons(self) -> None:
        self.assertIn("GridHelper", _THREE_CORE_NOT_ADDONS)
        html_cert = extract_file_certificate(
            "index.html",
            """<!DOCTYPE html><html><head><script type="importmap">
            {"imports": {
              "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
              "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
            }}
            </script></head><body><canvas id="gameCanvas"></canvas>
            <script type="module" src="./game.js"></script></body></html>""",
        )
        js_cert = extract_file_certificate(
            "game.js",
            """import * as THREE from 'three';
            import { GridHelper } from 'three/addons/helpers/GridHelper.js';
            const c = document.getElementById('gameCanvas');
            """,
        )
        verdict = verify_compositional_certificates({"index.html": html_cert, "game.js": js_cert})
        self.assertFalse(verdict["passed"])
        codes = [v["code"] for v in verdict["violations"]]
        self.assertEqual(codes, [THREE_CORE_MISIMPORTED_FROM_ADDONS])
        self.assertIn("GridHelper", verdict["repair_counterexamples"][0])
        self.assertIn("core 'three'", verdict["repair_counterexamples"][0])

    def test_threejs_swarm_bug_3_missing_dom_ids_game_container_and_score(self) -> None:
        html_cert = extract_file_certificate(
            "index.html",
            """<!DOCTYPE html><html><head><script type="importmap">
            {"imports": {"three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js"}}
            </script></head><body>
            <canvas id="gameCanvas"></canvas>
            <button id="start-btn">Start</button>
            <button id="reset-btn">Reset</button>
            <script type="module" src="./game.js"></script>
            </body></html>""",
        )
        js_cert = extract_file_certificate(
            "game.js",
            """import * as THREE from 'three';
            const container = document.getElementById('game-container');
            const scoreEl = document.querySelector('#score');
            """,
        )
        verdict = verify_compositional_certificates({"index.html": html_cert, "game.js": js_cert})
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["interface_hallucination_count"], 2)
        self.assertEqual(
            [v["code"] for v in verdict["violations"]],
            [MISSING_DOM_ID, MISSING_DOM_ID],
        )
        self.assertIn(
            "game.js assumes DOM '#score', but index.html only defines IDs: ['gameCanvas', 'reset-btn', 'start-btn']",
            verdict["repair_counterexamples"],
        )
        self.assertIn(
            "game.js assumes DOM '#game-container', but index.html only defines IDs: ['gameCanvas', 'reset-btn', 'start-btn']",
            verdict["repair_counterexamples"],
        )

    def test_threejs_swarm_bug_4_missing_importmap_keys_for_bare_specifiers(self) -> None:
        html_cert = extract_file_certificate(
            "index.html",
            """<!DOCTYPE html><html><head>
            <script type="importmap">
            {"imports": {"three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js"}}
            </script>
            </head><body><canvas id="gameCanvas"></canvas>
            <script type="module" src="./game.js"></script></body></html>""",
        )
        js_cert = extract_file_certificate(
            "game.js",
            """import * as THREE from 'three';
            import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
            const c = document.getElementById('gameCanvas');
            """,
        )
        verdict = verify_compositional_certificates({"index.html": html_cert, "game.js": js_cert})
        self.assertFalse(verdict["passed"])
        self.assertEqual(len(verdict["violations"]), 1)
        self.assertEqual(verdict["violations"][0]["code"], MISSING_IMPORTMAP_SPECIFIER)
        self.assertIn("three/addons/controls/OrbitControls.js", verdict["repair_counterexamples"][0])

    def test_all_four_threejs_swarm_bugs_caught_simultaneously_and_pass_once_fixed(self) -> None:
        broken_html = extract_file_certificate(
            "index.html",
            """<!DOCTYPE html><html><head></head><body>
            <canvas id="gameCanvas"></canvas>
            <script type="module" src="./game.js"></script>
            </body></html>""",
        )
        broken_js = extract_file_certificate(
            "game.js",
            """import * as THREE from 'three';
            import { GridHelper } from 'three/addons/helpers/GridHelper.js';
            import { Starfield } from './Starfield.js';
            const root = document.getElementById('game-container');
            const score = document.querySelector('#score');
            """,
        )
        broken_verdict = verify_compositional_certificates(
            {"index.html": broken_html, "game.js": broken_js}
        )
        self.assertFalse(broken_verdict["passed"])
        observed_codes = {v["code"] for v in broken_verdict["violations"]}
        self.assertEqual(
            observed_codes,
            {
                MISSING_RELATIVE_MODULE,
                THREE_CORE_MISIMPORTED_FROM_ADDONS,
                MISSING_IMPORTMAP_SPECIFIER,
                MISSING_DOM_ID,
            },
        )
        for line in broken_verdict["repair_counterexamples"]:
            self.assertNotIn("\n", line)

        # Now provide repaired certificates
        fixed_html = extract_file_certificate(
            "index.html",
            """<!DOCTYPE html><html><head>
            <script type="importmap">
            {"imports": {
              "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
              "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
            }}
            </script>
            </head><body>
            <div id="game-container"><canvas id="gameCanvas"></canvas><span id="score">0</span></div>
            <script type="module" src="./game.js"></script>
            </body></html>""",
        )
        fixed_starfield = extract_file_certificate(
            "Starfield.js",
            "export class Starfield { constructor(scene) { this.scene = scene; } }\n",
        )
        fixed_js = extract_file_certificate(
            "game.js",
            """import * as THREE from 'three';
            import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
            import { Starfield } from './Starfield.js';
            const grid = new THREE.GridHelper(20, 20);
            const root = document.getElementById('game-container');
            const score = document.querySelector('#score');
            """,
        )
        fixed_verdict = verify_compositional_certificates(
            {
                "index.html": fixed_html,
                "Starfield.js": fixed_starfield,
                "game.js": fixed_js,
            }
        )
        self.assertTrue(fixed_verdict["passed"])
        self.assertEqual(fixed_verdict["interface_hallucination_count"], 0)
        self.assertEqual(fixed_verdict["violations"], [])
        self.assertEqual(fixed_verdict["repair_counterexamples"], [])

    def test_js_named_vs_default_export_mismatch_is_caught(self) -> None:
        starfield_cert = extract_file_certificate(
            "Starfield.js",
            "export default class Starfield {}\n",
        )
        game_cert = extract_file_certificate(
            "game.js",
            "import { Starfield } from './Starfield.js';\n",
        )
        verdict = verify_compositional_certificates(
            {"Starfield.js": starfield_cert, "game.js": game_cert}
        )
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["violations"][0]["code"], MISSING_JS_EXPORT)
        self.assertIn("Starfield", verdict["repair_counterexamples"][0])
        self.assertIn("['default']", verdict["repair_counterexamples"][0])

    def test_python_cross_file_symbol_mismatch_and_valid_import(self) -> None:
        metrics_cert = extract_file_certificate(
            "metrics.py",
            "MAX_SAMPLES = 1000\n\ndef summarize_latencies(values):\n    return {'mean': sum(values) / len(values)}\n",
        )
        bad_cli_cert = extract_file_certificate(
            "cli.py",
            "from metrics import compute_mean\n\nprint(compute_mean([1, 2, 3]))\n",
        )
        bad_verdict = verify_compositional_certificates(
            {"metrics.py": metrics_cert, "cli.py": bad_cli_cert}
        )
        self.assertFalse(bad_verdict["passed"])
        self.assertEqual(bad_verdict["interface_hallucination_count"], 1)
        self.assertEqual(bad_verdict["violations"][0]["code"], MISSING_PYTHON_SYMBOL)
        self.assertIn("compute_mean", bad_verdict["repair_counterexamples"][0])
        self.assertIn("summarize_latencies", bad_verdict["repair_counterexamples"][0])

        good_cli_cert = extract_file_certificate(
            "cli.py",
            "from metrics import summarize_latencies, MAX_SAMPLES\n",
        )
        good_verdict = verify_compositional_certificates(
            {"metrics.py": metrics_cert, "cli.py": good_cli_cert}
        )
        self.assertTrue(good_verdict["passed"])

    def test_dynamic_js_dom_ids_are_not_falsely_flagged(self) -> None:
        html_cert = extract_file_certificate(
            "index.html",
            """<!DOCTYPE html><html><body>
            <canvas id="gameCanvas"></canvas>
            <script type="module" src="./game.js"></script>
            </body></html>""",
        )
        js_cert = extract_file_certificate(
            "game.js",
            """
            const el = document.createElement('div');
            el.id = 'dynamic-toast';
            document.body.appendChild(el);
            const banner = document.createElement('div');
            banner.setAttribute('id', 'dynamic-banner');
            document.body.insertAdjacentHTML('beforeend', `<div id="template-modal"></div>`);

            const q1 = document.getElementById('dynamic-toast');
            const q2 = document.querySelector('#dynamic-banner');
            const q3 = document.getElementById('template-modal');
            const q4 = document.getElementById('gameCanvas');
            """,
        )
        verdict = verify_compositional_certificates({"index.html": html_cert, "game.js": js_cert})
        self.assertTrue(verdict["passed"])
        self.assertEqual(verdict["violations"], [])

    def test_check_html_assets_toggle_controls_missing_script_and_stylesheet_checks(self) -> None:
        html_cert = extract_file_certificate(
            "index.html",
            """<!DOCTYPE html><html><head><link rel="stylesheet" href="./styles.css"></head>
            <body><script type="module" src="./game.js"></script></body></html>""",
        )
        # Before consumer files exist, Producer HTML shell alone passes with check_html_assets=False
        early_verdict = verify_compositional_certificates(
            {"index.html": html_cert},
            check_html_assets=False,
        )
        self.assertTrue(early_verdict["passed"])

        # Final compositional check with check_html_assets=True flags missing local assets
        final_verdict = verify_compositional_certificates(
            {"index.html": html_cert},
            check_html_assets=True,
        )
        self.assertFalse(final_verdict["passed"])
        self.assertEqual(
            {v["code"] for v in final_verdict["violations"]},
            {MISSING_HTML_SCRIPT, MISSING_HTML_STYLESHEET},
        )


class FormatSiblingGuaranteesContextTests(unittest.TestCase):
    def test_renders_headers_and_interfaces_within_max_chars(self) -> None:
        py_cert = extract_file_certificate(
            "metrics.py",
            "DEFAULT_WINDOW = 60\ndef summarize_latencies(values, precision=2):\n    return {}\n",
        )
        html_cert = extract_file_certificate(
            "index.html",
            """<!DOCTYPE html><html><head><script type="importmap">
            {"imports": {"three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js"}}
            </script></head><body><canvas id="gameCanvas"></canvas><button id="start-btn">Go</button></body></html>""",
        )
        rendered = format_sibling_guarantees_context(
            [py_cert, html_cert],
            owned_paths=["cli.py", "game.js"],
            read_only_paths=["metrics.py", "index.html"],
            max_chars=1200,
        )
        self.assertLessEqual(len(rendered), 1200)
        self.assertIn("OWNED WRITABLE FILES (edit/create ONLY these): cli.py, game.js", rendered)
        self.assertIn(
            "READ-ONLY VERIFIED SIBLING FILES (DO NOT write_file/edit_file these; import/reference their exact interfaces below):",
            rendered,
        )
        self.assertIn("summarize_latencies(values, precision=...)", rendered)
        self.assertIn("#gameCanvas", rendered)
        self.assertIn("'three'", rendered)

    def test_strictly_respects_tight_max_chars_budgets(self) -> None:
        certs = [
            extract_file_certificate(
                f"module_{i}.py",
                "\n".join(
                    f"def helper_function_{i}_{j}(alpha, beta, gamma=1):\n    return alpha\n"
                    for j in range(10)
                ),
            )
            for i in range(12)
        ]
        for budget in (1200, 600, 300, 160, 80, 20, 0):
            with self.subTest(max_chars=budget):
                output = format_sibling_guarantees_context(
                    certs,
                    owned_paths=["consumer_main.py"],
                    max_chars=budget,
                )
                self.assertLessEqual(len(output), budget)


if __name__ == "__main__":
    unittest.main()
