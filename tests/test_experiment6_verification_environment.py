import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo import verification_environment as env


class VerificationEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_npm_test_without_package_is_not_applicable(self):
        result = env.preflight_command(["npm", "test"], self.workspace,
                                       platform="nt", which=lambda _name: None)
        self.assertEqual(result["status"], env.VERIFICATION_NOT_APPLICABLE)

    def test_windows_npm_cmd_resolution_and_real_test_failure(self):
        (self.workspace / "package.json").write_text(
            json.dumps({"scripts": {"test": "node test.js"}}), encoding="utf-8")
        seen = []
        def resolve(name):
            seen.append(name)
            if name == "npm.cmd":
                return r"C:\node\npm.cmd"
            if name == "node.exe":
                return r"C:\node\node.exe"
            return None
        result = env.preflight_command(["npm", "test"], self.workspace,
                                       platform="nt", which=resolve)
        self.assertEqual(seen, ["npm.cmd", "node.exe"])
        self.assertEqual(result["command"], [r"C:\node\npm.cmd", "test"])
        self.assertEqual(env.command_result(subprocess.CompletedProcess([], 1))["status"],
                         env.TEST_FAILED)
        self.assertEqual(env.command_result(None, launch_error=FileNotFoundError(2, "missing"))["status"],
                         env.VERIFIER_UNAVAILABLE)

    def test_npm_with_test_script_but_no_node_is_unavailable(self):
        (self.workspace / "package.json").write_text(
            json.dumps({"scripts": {"test": "node test.js"}}), encoding="utf-8")
        result = env.preflight_command(["npm", "test"], self.workspace,
                                       platform="nt", which=lambda name: "npm.cmd" if name == "npm.cmd" else None)
        self.assertEqual(result["status"], env.VERIFIER_UNAVAILABLE)
        self.assertIn("Node.js", result["reason"])

    def test_missing_test_script_is_not_applicable_even_if_npm_exists(self):
        (self.workspace / "package.json").write_text(
            json.dumps({"scripts": {"build": "node build.js"}}), encoding="utf-8")
        result = env.preflight_command(["npm", "test"], self.workspace,
                                       platform="nt", which=lambda _name: r"C:\node\npm.cmd")
        self.assertEqual(result["status"], env.VERIFICATION_NOT_APPLICABLE)

    def test_refused_tool_call_is_not_an_executed_test_failure(self):
        self.assertIsNone(env.classify_observation({
            "tool": "run_command", "target": "echo unsupported",
            "result": "error: command refused: executable 'echo' is not in the verification allowlist",
        }))

    def test_preexisting_missing_browser_bridge_is_unavailable_but_regression_is_defect(self):
        target = self.workspace / "index.html"
        browser = {"passed": False, "environment_error": False,
                   "resolved_entrypoint": "index.html", "interaction_checks": [],
                   "failures": [{"code": "missing_game_bridge"},
                                {"code": "missing_interaction"}]}
        before = {"files": {str(target.resolve()):
                            {"existed": True, "content": b"<html>game</html>"}}}
        self.assertEqual(env.classify_browser_result(browser, transaction=before,
                                                     workspace=self.workspace),
                         env.VERIFIER_UNAVAILABLE)
        with_bridge = {"files": {str(target.resolve()):
                                 {"existed": True, "content": b"window.AGENT_GAME = game"}}}
        self.assertEqual(env.classify_browser_result(browser, transaction=with_bridge,
                                                     workspace=self.workspace),
                         env.TEST_FAILED)
        browser["interaction_checks"] = [{"name": "restart", "passed": False}]
        self.assertEqual(env.classify_browser_result(browser, transaction=before,
                                                     workspace=self.workspace),
                         env.TEST_FAILED)


class VerificationResolutionControllerTests(unittest.TestCase):
    def setUp(self):
        self.saved = (mini.WORKSPACE, mini.RUN, mini.RUN_ID, mini.ACTIVE_TRANSACTION)
        self.temp = tempfile.TemporaryDirectory()
        mini.WORKSPACE = Path(self.temp.name)
        mini.reset_run("experiment-6-test")
        mini.RUN["verification_environment_policy"] = "resolved"
        self.target = mini.WORKSPACE / "index.html"
        self.target.write_text("<html>before</html>\n", encoding="utf-8")

    def tearDown(self):
        if mini.ACTIVE_TRANSACTION is not None:
            mini.rollback_transaction()
        (mini.WORKSPACE, mini.RUN, mini.RUN_ID, mini.ACTIVE_TRANSACTION) = self.saved
        self.temp.cleanup()

    def test_unavailable_verifier_is_not_sent_to_repair_and_candidate_survives_rollback(self):
        mini.begin_transaction("EXEC-001")
        mini._transaction_capture(self.target)
        self.target.write_text("<html>candidate</html>\n", encoding="utf-8")
        browser = {"passed": False, "environment_error": False,
                   "resolved_entrypoint": "index.html", "interaction_checks": [],
                   "failures": [{"code": "missing_game_bridge"},
                                {"code": "missing_interaction"}]}
        builder = {"status": "done", "tool_evidence": [
            {"tool": "run_command", "target": "npm test",
             "result": "[not_applicable] VERIFICATION_NOT_APPLICABLE: package.json is absent"}]}
        gate = {"passed": False, "deterministic_failures": [
            {"name": "browser_contract"}, {"name": "executable_verification"}]}
        self.assertEqual(mini.classify_failure(builder, gate, browser),
                         env.VERIFIER_UNAVAILABLE)
        self.assertNotEqual(mini.classify_failure(builder, gate, browser),
                            "IMPLEMENTATION_ERROR")
        mini.rollback_transaction()
        self.assertEqual(self.target.read_text(encoding="utf-8"), "<html>before</html>\n")
        manifest = Path(mini.RUN["candidate_patch_artifacts"][0])
        self.assertTrue(manifest.is_file())
        artifact = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(artifact["verification_status"], "UNVERIFIED")
        self.assertEqual(Path(artifact["files"][0]["candidate_path"]).read_text(encoding="utf-8"),
                         "<html>candidate</html>\n")

    def test_executed_failing_test_still_reaches_implementation_repair(self):
        builder = {"status": "done", "tool_evidence": [
            {"tool": "run_command", "target": "npm test",
             "result": "[exit_code=1]\nAssertionError: expected restart"}]}
        gate = {"passed": False, "deterministic_failures": [
            {"name": "executable_failures"}]}
        self.assertEqual(mini.classify_failure(builder, gate), "IMPLEMENTATION_ERROR")

    def test_run_command_skips_unavailable_npm_without_spawning(self):
        with patch.object(mini.subprocess, "run") as spawned:
            result = mini.run_command("npm test")
        self.assertIn("VERIFICATION_NOT_APPLICABLE", result)
        spawned.assert_not_called()


if __name__ == "__main__":
    unittest.main()
