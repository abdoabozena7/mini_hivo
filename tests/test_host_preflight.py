import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import mini
from hivo import host_preflight as preflight
from hivo.http_client import JsonResponse


class HostPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.workspace = Path(self.temp.name)
        self.resources = {
            "total_system_ram_bytes": 16 * 1024 ** 3,
            "available_system_ram_bytes": 8 * 1024 ** 3,
            "gpu": {"status": "UNKNOWN", "reason": "test"},
        }
        self.sleep_calls = []

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def successful_response():
        return {"status_code": 200, "body": {"message": {"content": "HIVO_PREFLIGHT_OK"}}}

    def run_preflight(self, models=None, canary=None, resources=None, sleep=None, **kwargs):
        calls = []
        models = [{"name": "gemma4:e4b"}] if models is None else models

        def default_canary(model, prompt, timeout, base_url):
            calls.append((model, prompt, timeout, base_url))
            return self.successful_response()

        result = preflight.run_host_preflight(
            self.workspace, "gemma4:e4b", "http://127.0.0.1:11434",
            model_catalog_loader=kwargs.pop("model_catalog_loader", lambda _base_url: models),
            canary_call=canary or default_canary,
            resource_sampler=resources or (lambda: dict(self.resources)),
            sleep=self.sleep_calls.append if sleep is None else sleep,
            preflight_id=kwargs.pop("preflight_id", "test-preflight"),
            **kwargs,
        )
        result["test_calls"] = calls
        return result

    def test_three_successful_canaries_pass_sequentially_and_marker_completes(self):
        active = 0
        max_active = 0
        calls = []

        def canary(model, prompt, timeout, base_url):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            calls.append((model, prompt, timeout, base_url))
            active -= 1
            return self.successful_response()

        result = self.run_preflight(canary=canary)

        self.assertTrue(result["passed"])
        self.assertEqual(result["report"]["canary_calls_completed"], 3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(max_active, 1)
        self.assertEqual(self.sleep_calls, [2.0, 2.0, 2.0])
        marker = json.loads((self.workspace / preflight.HOST_PREFLIGHT_MARKER).read_text(encoding="utf-8"))
        self.assertEqual(marker["status"], "PASS")
        self.assertEqual(marker["canary_calls_completed"], 3)
        self.assertEqual(marker["preflight_id"], "test-preflight")
        self.assertFalse(list(self.workspace.glob(".*.tmp")))

    def test_running_marker_is_visible_before_first_canary(self):
        observed = []

        def canary(*_args):
            observed.append(json.loads((self.workspace / preflight.HOST_PREFLIGHT_MARKER).read_text(encoding="utf-8")))
            return self.successful_response()

        result = self.run_preflight(canary=canary)

        self.assertTrue(result["passed"])
        self.assertEqual(observed[0]["status"], "RUNNING")
        self.assertEqual(len(observed), 3)

    def test_exact_selected_model_and_tiny_zero_temperature_payload(self):
        captured = {}

        def fake_post(url, *, timeout, payload):
            captured.update({"url": url, "timeout": timeout, "payload": payload})
            return JsonResponse(200, json.dumps({"message": {"content": "HIVO_PREFLIGHT_OK"}}))

        with patch.object(preflight, "post_json", side_effect=fake_post):
            response = preflight._default_canary_call(
                "gemma4:e4b", preflight.CANARY_PROMPT, preflight.CANARY_TIMEOUT_SECONDS,
                "http://127.0.0.1:11434",
            )

        self.assertEqual(response["status_code"], 200)
        self.assertEqual(captured["payload"]["model"], "gemma4:e4b")
        self.assertEqual(captured["payload"]["messages"], [{"role": "user", "content": preflight.CANARY_PROMPT}])
        self.assertEqual(captured["payload"]["options"]["temperature"], 0)
        self.assertEqual(captured["payload"]["options"]["num_predict"], 32)

    def test_first_canary_failure_stops_with_zero_completed(self):
        calls = []

        def canary(*_args):
            calls.append(1)
            raise RuntimeError("provider worker failed")

        result = self.run_preflight(canary=canary)

        self.assertFalse(result["passed"])
        self.assertEqual(result["report"]["failure_reason"], "CANARY_PROVIDER_FAILURE")
        self.assertEqual(result["report"]["canary_calls_completed"], 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.sleep_calls, [])

    def test_second_canary_failure_reports_one_of_three(self):
        calls = []

        def canary(*_args):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("worker exited")
            return self.successful_response()

        result = self.run_preflight(canary=canary)

        self.assertFalse(result["passed"])
        self.assertEqual(result["report"]["failure_reason"], "CANARY_PROVIDER_FAILURE")
        self.assertEqual(result["report"]["canary_calls_completed"], 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.sleep_calls, [2.0])

    def test_third_canary_failure_reports_two_of_three(self):
        calls = []

        def canary(*_args):
            calls.append(1)
            if len(calls) == 3:
                raise TimeoutError("canary timeout")
            return self.successful_response()

        result = self.run_preflight(canary=canary)

        self.assertFalse(result["passed"])
        self.assertEqual(result["report"]["failure_reason"], "CANARY_TIMEOUT")
        self.assertEqual(result["report"]["canary_calls_completed"], 2)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.sleep_calls, [2.0, 2.0])

    def test_model_load_failure_is_a_preflight_failure(self):
        result = self.run_preflight(
            canary=lambda *_args: {
                "status_code": 500,
                "text": "model runner has unexpectedly stopped",
                "body": {"error": "model runner has unexpectedly stopped"},
            }
        )

        self.assertFalse(result["passed"])
        self.assertEqual(result["report"]["failure_reason"], "MODEL_LOAD_FAILED")
        self.assertEqual(result["report"]["provider_evidence"][0]["category"], "MODEL_LOAD_FAILED")

    def test_ollama_unavailable_fails_before_canary_or_task_creation(self):
        canary = Mock(return_value=self.successful_response())

        def unavailable(_base_url):
            raise preflight.HostPreflightProbeError("OLLAMA_UNAVAILABLE", "connection refused")

        result = self.run_preflight(model_catalog_loader=unavailable, canary=canary)

        self.assertFalse(result["passed"])
        self.assertEqual(result["report"]["failure_reason"], "OLLAMA_UNAVAILABLE")
        canary.assert_not_called()
        self.assertEqual(result["report"]["canary_calls_completed"], 0)
        self.assertFalse(any((self.workspace / name).exists() for name in ("index.html", "style.css", "game.js")))

    def test_model_unavailable_fails_before_canary(self):
        canary = Mock(return_value=self.successful_response())
        result = self.run_preflight(models=[], canary=canary)

        self.assertFalse(result["passed"])
        self.assertEqual(result["report"]["failure_reason"], "MODEL_UNAVAILABLE")
        canary.assert_not_called()

    def test_missing_gpu_telemetry_is_a_warning_not_a_failure(self):
        result = self.run_preflight()

        self.assertTrue(result["passed"])
        self.assertIn("gpu_telemetry_unavailable", result["report"]["warnings"])
        self.assertEqual(result["report"]["inventory"]["gpu"]["status"], "UNKNOWN")

    def test_warning_temperature_can_still_pass(self):
        resources = {
            "total_system_ram_bytes": 16 * 1024 ** 3,
            "available_system_ram_bytes": 8 * 1024 ** 3,
            "gpu": {"status": "MEASURED", "name": "test GPU", "temperature_c": 86.0,
                    "vram_free_mb": 4096, "utilization_percent": 5},
        }
        result = self.run_preflight(resources=lambda: dict(resources))

        self.assertTrue(result["passed"])
        self.assertIn("gpu_temperature_elevated", result["report"]["warnings"])

    def test_critical_memory_blocks_before_canary(self):
        canary = Mock(return_value=self.successful_response())
        resources = {
            "total_system_ram_bytes": 16 * 1024 ** 3,
            "available_system_ram_bytes": preflight.MIN_AVAILABLE_MEMORY_BYTES - 1,
            "gpu": {"status": "UNKNOWN"},
        }
        result = self.run_preflight(resources=lambda: dict(resources), canary=canary)

        self.assertFalse(result["passed"])
        self.assertEqual(result["report"]["failure_reason"], "CRITICAL_MEMORY_HEADROOM")
        canary.assert_not_called()

    def test_critical_free_disk_blocks_before_canary(self):
        canary = Mock(return_value=self.successful_response())
        usage = SimpleNamespace(total=10 * 1024 ** 3, used=10 * 1024 ** 3 - 1, free=1)
        with patch.object(preflight.shutil, "disk_usage", return_value=usage):
            result = self.run_preflight(canary=canary)

        self.assertFalse(result["passed"])
        self.assertEqual(result["report"]["failure_reason"], "CRITICAL_FREE_DISK")
        canary.assert_not_called()

    def test_critical_temperature_blocks(self):
        resources = {
            "total_system_ram_bytes": 16 * 1024 ** 3,
            "available_system_ram_bytes": 8 * 1024 ** 3,
            "gpu": {"status": "MEASURED", "temperature_c": 96.0},
        }
        result = self.run_preflight(resources=lambda: dict(resources))

        self.assertFalse(result["passed"])
        self.assertEqual(result["report"]["failure_reason"], "CRITICAL_TEMPERATURE")

    def test_stale_running_marker_is_reported_and_does_not_start_canary(self):
        stale = {
            "status": "RUNNING", "preflight_id": "old", "started_at": "2026-08-30T00:00:00Z",
            "model": "gemma4:e4b", "pid": 1234,
        }
        marker_path = self.workspace / preflight.HOST_PREFLIGHT_MARKER
        marker_path.write_text(json.dumps(stale), encoding="utf-8")
        canary = Mock(return_value=self.successful_response())

        result = self.run_preflight(canary=canary)

        self.assertFalse(result["passed"])
        self.assertEqual(result["report"]["failure_reason"], "PREVIOUS_HOST_PREFLIGHT_INTERRUPTED")
        self.assertEqual(result["report"]["previous_preflight"]["preflight_id"], "old")
        canary.assert_not_called()
        self.assertEqual(json.loads(marker_path.read_text(encoding="utf-8"))["status"], "FAIL")

    def test_missing_workspace_returns_structured_failure_without_creating_it(self):
        missing = self.workspace / "does-not-exist"
        result = preflight.failed_host_preflight_result(
            missing, "gemma4:e4b", reason="WORKSPACE_UNUSABLE", stage="workspace",
            summary="workspace is not a directory",
        )

        self.assertFalse(result["passed"])
        self.assertFalse(result["persisted"])
        self.assertEqual(result["report"]["failure_reason"], "WORKSPACE_UNUSABLE")
        self.assertFalse(missing.exists())

    def test_preflight_reference_is_attached_without_changing_task_model_metrics(self):
        result = self.run_preflight()
        old_result = mini.HOST_PREFLIGHT_RESULT
        old_run_id = mini.RUN_ID
        try:
            mini.HOST_PREFLIGHT_RESULT = result
            mini.RUN_ID = "metric-test"
            metrics = mini.new_metrics("recursive")
            self.assertEqual(metrics["host_preflight_status"], "PASS")
            self.assertEqual(metrics["host_preflight_id"], "test-preflight")
            self.assertEqual(metrics["model_calls"], 0)
            self.assertEqual(metrics["tasks_created"], 0)
        finally:
            mini.HOST_PREFLIGHT_RESULT = old_result
            mini.RUN_ID = old_run_id

    def test_preflight_does_not_mutate_hivo_task_or_model_call_metrics(self):
        saved_run, saved_tasks = mini.RUN, mini.TASKS
        mini.RUN = {"model_calls": 7, "tasks_created": 0}
        mini.TASKS = {}
        try:
            result = self.run_preflight()
            self.assertTrue(result["passed"])
            self.assertEqual(mini.RUN, {"model_calls": 7, "tasks_created": 0})
            self.assertEqual(mini.TASKS, {})
        finally:
            mini.RUN, mini.TASKS = saved_run, saved_tasks

    def test_main_pass_continues_into_existing_recursive_execution(self):
        prompt_path = self.workspace / "prompt.txt"
        prompt_path.write_text("deterministic test prompt", encoding="utf-8")
        preflight_result = {
            "passed": True, "status": "PASS", "preflight_id": "main-pass",
            "marker_path": str(self.workspace / preflight.HOST_PREFLIGHT_MARKER),
            "report": {"status": "PASS", "duration_seconds": 0.1},
        }
        args = SimpleNamespace(
            mode="recursive", model=None, prompt_file=str(prompt_path), workspace=str(self.workspace),
            self_test=False, install_browser=False, no_bootstrap=True,
        )
        old_result = mini.HOST_PREFLIGHT_RESULT
        try:
            with patch.object(mini, "parse_args", return_value=args), \
                    patch.object(mini, "ensure_dependencies", return_value=True), \
                    patch.object(mini, "get_workspace", return_value=self.workspace), \
                    patch.object(mini, "run_host_preflight", return_value=preflight_result), \
                    patch.object(mini, "select_local_ollama_model"), \
                    patch.object(mini, "load_memory", return_value={}), \
                    patch.object(mini, "run_recursive_request", return_value=({"status": "done", "summary": "ok"}, {})) as run:
                mini.main()
            run.assert_called_once_with("deterministic test prompt", {}, interactive=False)
        finally:
            mini.HOST_PREFLIGHT_RESULT = old_result

    def test_main_preflight_failure_stops_before_task_creation(self):
        preflight_result = {
            "passed": False, "status": "FAIL", "preflight_id": "main-fail",
            "marker_path": str(self.workspace / preflight.HOST_PREFLIGHT_MARKER),
            "report": {"status": "FAIL", "failure_reason": "OLLAMA_UNAVAILABLE", "failure_stage": "ollama",
                        "canary_calls_completed": 0, "canary_calls_requested": 3, "model": "gemma4:e4b",
                        "warnings": [], "inventory": {}, "resource_snapshots": []},
        }
        args = SimpleNamespace(
            mode="recursive", model=None, prompt_file=None, workspace=str(self.workspace),
            self_test=False, install_browser=False, no_bootstrap=True,
        )
        old_result = mini.HOST_PREFLIGHT_RESULT
        try:
            with patch.object(mini, "parse_args", return_value=args), \
                    patch.object(mini, "ensure_dependencies", return_value=True), \
                    patch.object(mini, "get_workspace", return_value=self.workspace), \
                    patch.object(mini, "run_host_preflight", return_value=preflight_result), \
                    patch.object(mini, "load_memory") as load_memory, \
                    patch.object(mini, "run_recursive_request") as run:
                with self.assertRaises(SystemExit) as exit_info:
                    mini.main()
            self.assertEqual(exit_info.exception.code, 2)
            load_memory.assert_not_called()
            run.assert_not_called()
        finally:
            mini.HOST_PREFLIGHT_RESULT = old_result


if __name__ == "__main__":
    unittest.main()
