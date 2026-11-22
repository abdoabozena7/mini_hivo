import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from hivo.deliverable_report import (
    build_deliverable_run_report,
    find_workspace_evidence_screenshots,
    inventory_workspace_deliverables,
    write_deliverable_run_report,
)
from hivo.model_policy import (
    GEMMA_MODEL,
    SingleModelPolicy,
    normalize_requested_model_name,
    validate_generative_model_capabilities,
)
from hivo.provider_usage import record_provider_usage
from hivo.run_budget import RunBudget


class ModelPolicyCapabilityTests(unittest.TestCase):
    def test_single_model_policy_backward_compatibility_preserved(self):
        policy = SingleModelPolicy()
        self.assertEqual(policy.model_name, GEMMA_MODEL)
        self.assertEqual(policy.validate(), GEMMA_MODEL)
        self.assertEqual(policy.validate(None), GEMMA_MODEL)
        self.assertEqual(policy.validate(GEMMA_MODEL), GEMMA_MODEL)
        self.assertEqual(set(policy.role_models().values()), {GEMMA_MODEL})
        with self.assertRaises(ValueError):
            policy.validate("qwen2.5-coder:7b")

    def test_normalize_requested_model_name_accepts_defaults_and_valid_names(self):
        self.assertEqual(normalize_requested_model_name(None), GEMMA_MODEL)
        self.assertEqual(normalize_requested_model_name(""), GEMMA_MODEL)
        self.assertEqual(normalize_requested_model_name("   \t\n "), GEMMA_MODEL)
        self.assertEqual(
            normalize_requested_model_name(None, default="qwen2.5-coder:1.5b"),
            "qwen2.5-coder:1.5b",
        )
        self.assertEqual(
            normalize_requested_model_name("  qwen2.5-coder:1.5b  "),
            "qwen2.5-coder:1.5b",
        )
        self.assertEqual(
            normalize_requested_model_name("gpt-oss:20b-cloud"),
            "gpt-oss:20b-cloud",
        )
        self.assertEqual(
            normalize_requested_model_name("library/gemma4:e4b"),
            "library/gemma4:e4b",
        )
        self.assertEqual(
            normalize_requested_model_name("huihui_ai/qwen2.5-coder:7b"),
            "huihui_ai/qwen2.5-coder:7b",
        )
        self.assertEqual(
            normalize_requested_model_name("namespace/model"),
            "namespace/model",
        )

    def test_normalize_requested_model_name_rejects_whitespace_urls_and_traversal(self):
        invalid_names = [
            "gemma4: e4b",
            "gemma4\ne4b",
            "gemma4\te4b",
            "../gemma4:e4b",
            "ns/../gemma4:e4b",
            "gemma4..e4b",
            "./gemma4:e4b",
            r"models\gemma4:e4b",
            r"C:\models\gemma4",
            "http://127.0.0.1:11434/gemma4:e4b",
            "https://ollama.com/library/gemma4:e4b",
            "/gemma4:e4b",
            "gemma4:e4b/",
            "org/sub/gemma4:e4b",
            "gemma4:",
            ":latest",
            "C:/models/gemma4",
        ]
        for bad in invalid_names:
            with self.subTest(model=bad):
                with self.assertRaises(ValueError):
                    normalize_requested_model_name(bad)

    def test_validate_generative_model_capabilities_rejects_non_generative_models(self):
        for model_name, caps in (
            ("laya:latest", ["decision"]),
            ("nomic-embed-text", ["embedding"]),
            ("nomic-embed-text:latest", ["embedding"]),
            ("bge-reranker:latest", {"rerank", "embedding"}),
        ):
            with self.subTest(model=model_name, capabilities=caps):
                with self.assertRaises(ValueError) as ctx:
                    validate_generative_model_capabilities(model_name, caps)
                message = str(ctx.exception)
                self.assertIn(model_name, message)
                self.assertIn("completion", message)
                self.assertIn(GEMMA_MODEL, message)

    def test_validate_generative_model_capabilities_accepts_generative_and_empty(self):
        validate_generative_model_capabilities("gemma4:e4b", ["completion", "tools"])
        validate_generative_model_capabilities("qwen2.5-coder:1.5b", ["completion"])
        validate_generative_model_capabilities("chat-only:latest", ("chat",))
        validate_generative_model_capabilities("COMPLETION-UPPER:1b", {"COMPLETION"})
        validate_generative_model_capabilities("legacy-ollama:latest", [])
        validate_generative_model_capabilities("legacy-ollama:latest", ())
        validate_generative_model_capabilities("legacy-ollama:latest", set())
        validate_generative_model_capabilities("mocked-test-model", None)


class DeliverableBackendReportTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.workspace = Path(self._tmpdir.name) / "demo_workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_inventory_excludes_runtime_dirs_sqlite_and_agent_files_with_posix_paths(self):
        index_bytes = b"<!doctype html><html><body>Hello Mini Hivo</body></html>\n"
        app_bytes = b"def add(a, b):\n    return a + b\n"
        (self.workspace / "index.html").write_bytes(index_bytes)
        (self.workspace / "src").mkdir()
        (self.workspace / "src" / "app.py").write_bytes(app_bytes)

        # Internal/runtime directories and files that MUST be excluded.
        for hidden_dir, filename in (
            (".hivo", "memory.sqlite3"),
            (".hivo", "memory.sqlite3-wal"),
            (".git", "HEAD"),
            ("__pycache__", "app.cpython-312.pyc"),
            ("node_modules", "pkg/index.js"),
            (".venv", "pyvenv.cfg"),
            (".agent_evidence", "task_ROOT.png"),
            (".agent_backups", "backup.json"),
            (".runtime-proof", "team-plan.json"),
        ):
            target = self.workspace / hidden_dir / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"internal-runtime-state")

        (self.workspace / ".agent_memory.json").write_text("{}", encoding="utf-8")
        (self.workspace / ".agent_experiment.jsonl").write_text("{}\n", encoding="utf-8")
        (self.workspace / "src" / ".agent_scratch.tmp").write_text("scratch", encoding="utf-8")

        deliverables = inventory_workspace_deliverables(self.workspace)
        self.assertEqual([item["path"] for item in deliverables], ["index.html", "src/app.py"])
        self.assertEqual(
            deliverables[0],
            {
                "path": "index.html",
                "size_bytes": len(index_bytes),
                "sha256": hashlib.sha256(index_bytes).hexdigest(),
            },
        )
        self.assertEqual(
            deliverables[1],
            {
                "path": "src/app.py",
                "size_bytes": len(app_bytes),
                "sha256": hashlib.sha256(app_bytes).hexdigest(),
            },
        )
        for entry in deliverables:
            self.assertNotIn("\\", entry["path"])
            self.assertFalse(entry["path"].startswith("/"))
            self.assertNotIn(str(self.workspace), entry["path"])

    def test_find_workspace_evidence_screenshots_discovers_only_supported_images(self):
        self.assertEqual(find_workspace_evidence_screenshots(self.workspace), [])

        evidence = self.workspace / ".agent_evidence"
        (evidence / "screens" / "01-flow").mkdir(parents=True)
        (evidence / "verified_child_receipts").mkdir(parents=True)

        (evidence / "task_ROOT.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (evidence / "screens" / "01-flow" / "001-open.webp").write_bytes(b"RIFFwebp")
        (evidence / "screens" / "01-flow" / "002-final.JPG").write_bytes(b"\xff\xd8\xff")
        (evidence / "verified_child_receipts" / "child_1.json").write_text("{}", encoding="utf-8")
        (evidence / "trace.zip").write_bytes(b"PK\x03\x04")

        screenshots = find_workspace_evidence_screenshots(self.workspace)
        self.assertEqual(
            screenshots,
            [
                ".agent_evidence/screens/01-flow/001-open.webp",
                ".agent_evidence/screens/01-flow/002-final.JPG",
                ".agent_evidence/task_ROOT.png",
            ],
        )
        for path in screenshots:
            self.assertNotIn("\\", path)
            self.assertNotIn(":", path)

    def test_build_and_write_deliverable_run_report_schema_tokens_and_privacy(self):
        (self.workspace / "cli").mkdir()
        (self.workspace / "cli" / "main.py").write_text("print('ok')\n", encoding="utf-8")
        (self.workspace / ".hivo").mkdir()
        (self.workspace / ".hivo" / "memory.sqlite3").write_bytes(b"SQLite format 3\x00")
        (self.workspace / ".agent_evidence").mkdir()
        (self.workspace / ".agent_evidence" / "verify.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        usage: dict = {}
        record_provider_usage(usage, "Builder", {"prompt_eval_count": 320, "eval_count": 140})
        record_provider_usage(usage, "Repairer", {"prompt_eval_count": 180, "eval_count": 60})

        clock_values = iter([10.0, 22.5])
        budget = RunBudget(max_model_calls=10, max_tool_calls=20, clock=lambda: next(clock_values))
        budget.claim("model")
        budget.claim("model")
        budget.claim("tool")
        budget_snap = budget.snapshot()

        run_metrics = {
            "run_budget": budget_snap,
            "splits": 1,
            "max_depth": 2,
            "leaf_tasks": 2,
            "repairer_calls": 1,
            "browser_checks": 1,
            "evidence_licensed_corrections": 2,
            "provider_usage": usage,
        }
        task_ledger = {
            "ROOT": {"id": "ROOT", "status": "done"},
            "1": {"id": "1", "status": "done"},
            "2": {"id": "2", "status": "failed"},
            "3": {"id": "3", "status": "pending"},
        }

        report = build_deliverable_run_report(
            run_id="20261121T201030-deadbeef",
            model="qwen2.5-coder:1.5b",
            mode="build",
            status="done",
            exit_code=0,
            summary=f"Verified cli/main.py inside {self.workspace} without C:\\Users\\Alice\\secret.txt",
            workspace=self.workspace,
            run_metrics=run_metrics,
            task_ledger=task_ledger,
        )

        self.assertEqual(report["schema_version"], "1.0")
        self.assertEqual(report["run_id"], "20261121T201030-deadbeef")
        self.assertEqual(report["model"], "qwen2.5-coder:1.5b")
        self.assertEqual(report["mode"], "build")
        self.assertEqual(report["status"], "done")
        self.assertEqual(report["exit_code"], 0)
        self.assertTrue(report["verified"])
        self.assertEqual(
            report["telemetry"],
            {
                "model_calls": 2,
                "tool_calls": 1,
                "splits": 1,
                "max_depth": 2,
                "leaf_tasks": 2,
                "repairer_calls": 1,
                "browser_checks": 1,
                "evidence_licensed_corrections": 2,
                "input_tokens": 500,
                "output_tokens": 200,
                "elapsed_seconds": 12.5,
            },
        )
        self.assertEqual([d["path"] for d in report["deliverables"]], ["cli/main.py"])
        self.assertEqual(report["screenshots"], [".agent_evidence/verify.png"])
        self.assertEqual(
            report["task_summary"],
            {"total_nodes": 4, "done_nodes": 2, "failed_nodes": 1},
        )

        output_path = Path(self._tmpdir.name) / "nested" / "reports" / "deliverable_report.json"
        written_path = write_deliverable_run_report(report, output_path)
        self.assertEqual(written_path, output_path)
        raw_json = output_path.read_text(encoding="utf-8")
        loaded = json.loads(raw_json)
        self.assertEqual(loaded, report)

        # Guarantee zero personal host absolute paths leak into serialized report.
        self.assertNotIn(str(self.workspace), raw_json)
        self.assertNotIn(self.workspace.as_posix(), raw_json)
        self.assertNotIn("C:\\Users", raw_json)
        self.assertNotIn("D:\\projects", raw_json)
        self.assertNotIn("memory.sqlite3", raw_json)

    def test_verified_flag_and_list_task_ledger_handling(self):
        failed_report = build_deliverable_run_report(
            run_id="run-fail-1",
            model=GEMMA_MODEL,
            mode="build",
            status="done",
            exit_code=1,
            summary="Process exited non-zero",
            workspace=self.workspace,
            task_ledger=[
                {"task_id": "ROOT", "status": "failed"},
                {"task_id": "1", "status": "done"},
            ],
        )
        self.assertFalse(failed_report["verified"])
        self.assertEqual(
            failed_report["task_summary"],
            {"total_nodes": 2, "done_nodes": 1, "failed_nodes": 1},
        )

        incomplete_status_report = build_deliverable_run_report(
            run_id="run-fail-2",
            model=GEMMA_MODEL,
            mode="build",
            status="failed",
            exit_code=0,
            summary="Controller reported failed status",
            workspace=self.workspace,
        )
        self.assertFalse(incomplete_status_report["verified"])
        self.assertEqual(
            incomplete_status_report["task_summary"],
            {"total_nodes": 0, "done_nodes": 0, "failed_nodes": 0},
        )

    def test_type_guards_missing_workspace_and_write_path_rejection(self):
        with self.assertRaises(ValueError):
            normalize_requested_model_name(123)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            validate_generative_model_capabilities("gemma4:e4b", "chat")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            build_deliverable_run_report(
                run_id="bool-exit",
                model=GEMMA_MODEL,
                mode="build",
                status="done",
                exit_code=False,  # type: ignore[arg-type]
                summary="bool exit code must not pass as 0",
                workspace=self.workspace,
            )

        missing_ws = Path(self._tmpdir.name) / "does_not_exist"
        self.assertEqual(inventory_workspace_deliverables(missing_ws), [])
        self.assertEqual(find_workspace_evidence_screenshots(missing_ws), [])

        wrapper_ledger = {
            "run_id": "run-snapshot",
            "status": "running",
            "tasks": [
                {"task_id": "ROOT", "status": "parent_verified"},
                {"task_id": "1", "status": "done"},
                {"task_id": "2", "status": "too_broad"},
                {"task_id": "3", "status": "provider_failure"},
            ],
        }
        snapshot_report = build_deliverable_run_report(
            run_id="run-snapshot",
            model=GEMMA_MODEL,
            mode="build",
            status="done",
            exit_code=0,
            summary="Snapshot ledger summary",
            workspace=missing_ws,
            run_metrics={"input_tokens": 90, "output_tokens": 45},
            task_ledger=wrapper_ledger,
        )
        self.assertEqual(snapshot_report["telemetry"]["input_tokens"], 90)
        self.assertEqual(snapshot_report["telemetry"]["output_tokens"], 45)
        self.assertEqual(
            snapshot_report["task_summary"],
            {"total_nodes": 4, "done_nodes": 2, "failed_nodes": 2},
        )

        tampered = dict(snapshot_report)
        tampered["deliverables"] = [{"path": r"C:\Users\Alice\app.py", "size_bytes": 1, "sha256": "0" * 64}]
        with self.assertRaises(ValueError):
            write_deliverable_run_report(tampered, Path(self._tmpdir.name) / "bad.json")


if __name__ == "__main__":
    unittest.main()
