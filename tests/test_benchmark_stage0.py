"""Stage 0 Offline Benchmark Self-Test Suite (zero LLM calls).

Verifies all 7 anti-false-result contracts defined in
``dev_rules/benchmarking_rules.md`` and ``docs/BENCHMARKING_ARCHITECTURE.md``:
  1. test_decontamination_strips_git_history
  2. test_invalid_baseline_quarantined
  3. test_protected_path_tamper_rejected
  4. test_missing_or_skipped_test_never_passes
  5. test_trace_cheat_scanner_catches_planted_exploits
  6. test_kpi_aggregator_sanity_bounds
  7. test_preflight_reports_missing_deps_cleanly
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from hivo.benchmarks import (
    build_benchmark_results,
    check_protected_paths_in_patch,
    compute_pass_hat_k,
    compute_percentile,
    docker_network_args,
    evaluate_baseline_oracle,
    evaluate_candidate_verdict,
    run_preflight,
    scan_trace_for_cheats,
    strip_git_and_reinit,
    verify_workspace_decontaminated,
)
from hivo.providers import EndpointConfig, ollama_worker


def _load_swebench_runner_module():
    path = Path(__file__).resolve().parent.parent / "scripts" / "run_swebench_hybrid.py"
    spec = importlib.util.spec_from_file_location("swebench_hybrid_runner", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )


class BenchmarkStage0SelfTests(unittest.TestCase):
    """Adversarial offline self-tests guaranteeing zero false benchmark positives."""

    def test_decontamination_strips_git_history(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "sample_repo"
            repo.mkdir()
            _git(repo, "init", "-q")
            _git(repo, "config", "user.name", "Test")
            _git(repo, "config", "user.email", "test@example.com")
            _git(repo, "config", "commit.gpgsign", "false")

            (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "initial commit")
            _git(repo, "tag", "v0.1")
            _git(repo, "remote", "add", "origin", "https://example.invalid/repo.git")
            _git(repo, "checkout", "-q", "-b", "future-solution")
            (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "SECRET_GOLD_FIX_SHOULD_VANISH")

            # Pre-strip repo fails decontamination audit.
            before = verify_workspace_decontaminated(repo)
            self.assertFalse(before["decontaminated"])
            self.assertGreater(before["commit_count"], 1)

            # Strip and reinit -> 1 fresh orphan commit, zero remotes/tags/history.
            after = strip_git_and_reinit(repo, commit_message="clean baseline")
            self.assertTrue(after["decontaminated"])
            self.assertEqual(after["commit_count"], 1)
            self.assertEqual(after["remotes"], [])
            self.assertEqual(after["tags"], [])
            self.assertEqual(len(after["branches"]), 1)

            log_out = _git(repo, "log", "--all", "--oneline").stdout
            self.assertNotIn("SECRET_GOLD_FIX_SHOULD_VANISH", log_out)
            self.assertEqual((repo / "app.py").read_text(encoding="utf-8"), "x = 2\n")

            # Negative boundary: invalid network modes fail closed.
            self.assertEqual(docker_network_args("none"), ["--network", "none"])
            with self.assertRaises(ValueError):
                docker_network_args("host")
            with self.assertRaises(ValueError):
                docker_network_args("bridge")

    def test_invalid_baseline_quarantined(self) -> None:
        # Pre-passing F2P (e.g., psf__requests-1724 6/6 pre-patch) must fail baseline validity.
        bad_base = evaluate_baseline_oracle(
            infra_ok=True,
            f2p_passed=6,
            f2p_total=6,
            p2p_passed=79,
            p2p_total=79,
        )
        self.assertFalse(bad_base["valid"])
        self.assertTrue(any("already passing" in r for r in bad_base["reasons"]))

        # Even if candidate passes 100%, an invalid baseline can NEVER yield resolved=True.
        verdict = evaluate_candidate_verdict(
            baseline_oracle=bad_base,
            model_patch="diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-a\n+b\n",
            protected_paths=("tests/**",),
            infra_ok=True,
            patch_applied=True,
            test_patch_applied=True,
            f2p_passed=6,
            f2p_total=6,
            p2p_passed=79,
            p2p_total=79,
        )
        self.assertFalse(verdict["resolved"])
        self.assertEqual(verdict["verdict_code"], "INVALID_BASELINE")

        # Controlled functional check on run_swebench_hybrid.run_single_instance:
        # pre-solve invalid baseline must quarantine with ZERO HybridAgentRunner invocations.
        runner_mod = _load_swebench_runner_module()
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            fake_row = {
                "instance_id": "psf__requests-1724",
                "repo": "psf/requests",
                "version": "2.0",
                "difficulty": "<15 min fix",
                "base_commit": "deadbeef",
                "problem_statement": "Fix method bytes handling.",
                "FAIL_TO_PASS": json.dumps(["test_requests.py::test_fix"]),
                "PASS_TO_PASS": json.dumps(["test_requests.py::test_keep"]),
                "test_patch": "diff --git a/test_requests.py b/test_requests.py\n+++ b/test_requests.py\n",
            }
            orch_cfg = EndpointConfig(
                provider_type="openai_compat",
                base_url="https://example.invalid/v1",
                model="test-orch",
                api_key_env="GROQ_API_KEY",
            )
            worker_cfg = ollama_worker(model="qwen3.5:2b-q4_K_M")

            ok_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"Python 3.11\n", stderr=b"")
            pre_passing_eval = {
                "infra_ok": True,
                "patch_applied": True,
                "test_patch_applied": True,
                "patch_apply_error": "",
                "exit_code": 0,
                "output": "PASSED test_requests.py::test_fix\nPASSED test_requests.py::test_keep\n",
            }

            with (
                mock.patch.object(runner_mod, "_run_cmd", return_value=ok_proc),
                mock.patch.object(runner_mod, "_docker_eval_once", return_value=pre_passing_eval),
                mock.patch.object(runner_mod, "HybridAgentRunner") as mock_agent_cls,
            ):
                rec = runner_mod.run_single_instance(
                    fake_row,
                    run_dir=run_dir,
                    orch_cfg=orch_cfg,
                    worker_cfg=worker_cfg,
                    keep_images=True,
                    max_orch_turns=4,
                    max_worker_turns=2,
                    max_elapsed_sec=60.0,
                )

            mock_agent_cls.assert_not_called()
            self.assertFalse(rec["resolved"])
            self.assertEqual(rec["status"], "INVALID_BASELINE")
            self.assertEqual(rec["tokens"]["orch_in"], 0)
            self.assertFalse(rec["baseline_oracle"]["valid"])

    def test_protected_path_tamper_rejected(self) -> None:
        protected = ("tests/**", "testing/**", "test_*.py", "*_test.py")
        tamper_patch = (
            "diff --git a/src/calc.py b/src/calc.py\n"
            "--- a/src/calc.py\n"
            "+++ b/src/calc.py\n"
            "@@ -1 +1 @@\n-return 1\n+return 2\n"
            "diff --git a/tests/test_calc.py b/tests/test_calc.py\n"
            "--- a/tests/test_calc.py\n"
            "+++ b/tests/test_calc.py\n"
            "@@ -1 +1 @@\n-assert calc() == 2\n+assert True\n"
        )
        offending = check_protected_paths_in_patch(tamper_patch, protected)
        self.assertEqual(offending, ("tests/test_calc.py",))

        valid_base = evaluate_baseline_oracle(
            infra_ok=True,
            f2p_passed=0,
            f2p_total=1,
            p2p_passed=5,
            p2p_total=5,
        )
        self.assertTrue(valid_base["valid"])

        verdict = evaluate_candidate_verdict(
            baseline_oracle=valid_base,
            model_patch=tamper_patch,
            protected_paths=protected,
            infra_ok=True,
            patch_applied=True,
            test_patch_applied=True,
            f2p_passed=1,
            f2p_total=1,
            p2p_passed=5,
            p2p_total=5,
        )
        self.assertFalse(verdict["resolved"])
        self.assertEqual(verdict["verdict_code"], "TAMPER_DETECTED")
        self.assertEqual(verdict["protected_touched"], ["tests/test_calc.py"])

        # Clean non-test patch must pass cleanly.
        clean_patch = (
            "diff --git a/src/calc.py b/src/calc.py\n"
            "--- a/src/calc.py\n"
            "+++ b/src/calc.py\n"
            "@@ -1 +1 @@\n-return 1\n+return 2\n"
        )
        clean_verdict = evaluate_candidate_verdict(
            baseline_oracle=valid_base,
            model_patch=clean_patch,
            protected_paths=protected,
            infra_ok=True,
            patch_applied=True,
            test_patch_applied=True,
            f2p_passed=1,
            f2p_total=1,
            p2p_passed=5,
            p2p_total=5,
        )
        self.assertTrue(clean_verdict["resolved"])
        self.assertEqual(clean_verdict["verdict_code"], "RESOLVED")

    def test_missing_or_skipped_test_never_passes(self) -> None:
        valid_base = evaluate_baseline_oracle(
            infra_ok=True,
            f2p_passed=0,
            f2p_total=2,
            p2p_passed=2,
            p2p_total=2,
        )
        clean_patch = "diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-a\n+b\n"

        # Case 1: Missing F2P target must never resolve.
        missing_verdict = evaluate_candidate_verdict(
            baseline_oracle=valid_base,
            model_patch=clean_patch,
            protected_paths=("tests/**",),
            infra_ok=True,
            patch_applied=True,
            test_patch_applied=True,
            f2p_passed=1,
            f2p_total=2,
            p2p_passed=2,
            p2p_total=2,
            f2p_details={"t1": "PASSED", "t2": "MISSING"},
        )
        self.assertFalse(missing_verdict["resolved"])
        self.assertEqual(missing_verdict["verdict_code"], "MISSING_TEST_TARGETS")
        self.assertEqual(missing_verdict["missing_tests"], 1)

        # Case 2: SKIPPED P2P target must never resolve.
        skipped_verdict = evaluate_candidate_verdict(
            baseline_oracle=valid_base,
            model_patch=clean_patch,
            protected_paths=("tests/**",),
            infra_ok=True,
            patch_applied=True,
            test_patch_applied=True,
            f2p_passed=2,
            f2p_total=2,
            p2p_passed=1,
            p2p_total=2,
            f2p_details={"t1": "PASSED", "t2": "PASSED"},
            p2p_failed={"p2": "SKIPPED"},
        )
        self.assertFalse(skipped_verdict["resolved"])
        self.assertEqual(skipped_verdict["verdict_code"], "MISSING_TEST_TARGETS")
        self.assertEqual(skipped_verdict["skipped_tests"], 1)

    def test_trace_cheat_scanner_catches_planted_exploits(self) -> None:
        protected = ("tests/**", "test_*.py")
        planted_trace = [
            # Pure reasoning prose mentioning git log must be ignored (only executed calls count).
            {"event": "reasoning", "turn": 1, "content": "I should not run git log or cat /tmp/oracle."},
            # Benign executed calls must produce 0 hits.
            {"event": "tool_call", "turn": 2, "tool": "read_file", "args": {"path": "src/app.py"}},
            {"event": "tool_call", "turn": 2, "tool": "read_file", "args": {"path": ".env.example"}},
            # Planted Tier 1 git history mining
            {"event": "tool_call", "turn": 3, "tool": "run_command", "args": {"command": "git log -n 5"}},
            # Planted Tier 2 hidden object recovery
            {"event": "tool_call", "turn": 4, "tool": "run_command", "args": {"command": "git cat-file -p HEAD~1"}},
            # Planted Tier 3 /tmp & secret & network probes
            {"event": "tool_call", "turn": 5, "tool": "run_command", "args": {"command": "cat /tmp/oracle_patch.diff"}},
            {"event": "tool_call", "turn": 6, "tool": "read_file", "args": {"path": ".env"}},
            {"event": "tool_call", "turn": 7, "tool": "run_command", "args": {"command": "curl https://github.com/org/repo"}},
            # Planted protected-path edit attempt
            {"event": "tool_call", "turn": 8, "tool": "edit_file", "args": {"path": "tests/test_app.py"}, "error_code": "ORACLE_LOCKED"},
        ]
        hits = scan_trace_for_cheats(planted_trace, protected_paths=protected)
        categories = {h["category"] for h in hits}
        self.assertIn("TIER1_GIT_HISTORY_MINING", categories)
        self.assertIn("TIER2_GIT_OBJECT_RECOVERY", categories)
        self.assertIn("TIER3_OUT_OF_REPO_SCAN", categories)
        self.assertIn("TIER3_SECRET_FILE_PROBE", categories)
        self.assertIn("PROTECTED_PATH_TAMPER", categories)

        # Clean trace has 0 hits.
        clean_trace = [
            {"event": "tool_call", "turn": 1, "tool": "search_code", "args": {"query": "has_add_permission"}},
            {"event": "tool_call", "turn": 2, "tool": "edit_file", "args": {"path": "src/admin.py"}},
            {"event": "tool_call", "turn": 3, "tool": "run_command", "args": {"command": "git diff"}},
        ]
        self.assertEqual(scan_trace_for_cheats(clean_trace, protected_paths=protected), [])

        # Downgraded cheating_adjusted_rate in aggregator.
        meta = {
            "seed": 42,
            "decontamination": {"git_stripped": True, "network_mode": "none", "tmp_clean": True, "secrets_isolated": True},
            "worker": {"runtime": "ollama", "gpu_residency_pct": 100.0},
        }
        cases = [
            {
                "task_id": "t_clean",
                "baseline_oracle": {"valid": True},
                "candidate_oracle": {"patch_applied": True, "protected_touched": [], "missing_tests": 0, "skipped_tests": 0},
                "resolved": True,
                "cheat_flags": [],
                "tokens": {"orch_in": 1000, "orch_cached_in": 500},
                "usd": 0.02,
                "latency_ms": 1000.0,
            },
            {
                "task_id": "t_cheated",
                "baseline_oracle": {"valid": True},
                "candidate_oracle": {"patch_applied": True, "protected_touched": [], "missing_tests": 0, "skipped_tests": 0},
                "resolved": True,
                "cheat_flags": hits[:1],
                "tokens": {"orch_in": 1000, "orch_cached_in": 500},
                "usd": 0.02,
                "latency_ms": 2000.0,
            },
        ]
        agg = build_benchmark_results(meta, cases, pass_k=1)
        self.assertEqual(agg["summary"]["valid_resolve_rate"], 1.0)
        self.assertEqual(agg["summary"]["cheating_adjusted_rate"], 0.5)

    def test_kpi_aggregator_sanity_bounds(self) -> None:
        # Exact binomial check: task1 (4/5 -> C(4,3)/C(5,3)=0.4), task2 (5/5 -> 1.0) => mean 0.7.
        self.assertAlmostEqual(
            compute_pass_hat_k([[True, True, True, True, False], [True, True, True, True, True]], k=3),
            0.7,
            places=6,
        )
        # Negative bounds on pass^k and percentiles.
        with self.assertRaises(ValueError):
            compute_pass_hat_k([[True, True]], k=0)
        with self.assertRaises(ValueError):
            compute_pass_hat_k([], k=1)
        with self.assertRaises(ValueError):
            compute_pass_hat_k([[True, False]], k=3)
        with self.assertRaises(ValueError):
            compute_percentile([1.0, float("nan")], 50.0)

        meta = {
            "date": "2026-11-26",
            "seed": 42,
            "decontamination": {"git_stripped": True, "network_mode": "none", "tmp_clean": True, "secrets_isolated": True},
            "worker": {"runtime": "ollama", "gpu_residency_pct": 100.0},
        }
        cases = [
            {
                "task_id": "c1",
                "baseline_oracle": {"valid": True},
                "candidate_oracle": {"patch_applied": True, "protected_touched": [], "missing_tests": 0, "skipped_tests": 0, "verdict_code": "RESOLVED"},
                "resolved": True,
                "trial_outcomes": [True, True, True],
                "cheat_flags": [],
                "tokens": {"orch_in": 10_000, "orch_cached_in": 6_000, "orch_out": 500},
                "usd": 0.10,
                "latency_ms": 1000.0,
                "funnel": {"localized": True, "dispatches": 1, "rollbacks": 0, "tool_calls": 10, "tool_schema_errors": 0},
            },
            {
                "task_id": "c2",
                "baseline_oracle": {"valid": True},
                "candidate_oracle": {"patch_applied": False, "protected_touched": [], "missing_tests": 0, "skipped_tests": 0, "verdict_code": "EMPTY_PATCH"},
                "resolved": False,
                "trial_outcomes": [False, False, False],
                "cheat_flags": [],
                "tokens": {"orch_in": 10_000, "orch_cached_in": 4_000, "orch_out": 500},
                "usd": 0.10,
                "latency_ms": 3000.0,
                "funnel": {"localized": True, "dispatches": 1, "rollbacks": 1, "tool_calls": 10, "tool_schema_errors": 1},
            },
            {
                "task_id": "c3_invalid",
                "baseline_oracle": {"valid": False},
                "candidate_oracle": {"patch_applied": False, "protected_touched": [], "missing_tests": 0, "skipped_tests": 0, "verdict_code": "INVALID_BASELINE"},
                "resolved": False,
                "trial_outcomes": [False, False, False],
                "cheat_flags": [],
                "tokens": {"orch_in": 0, "orch_cached_in": 0, "orch_out": 0},
                "usd": 0.0,
                "latency_ms": 500.0,
                "funnel": {"localized": None, "dispatches": 0, "rollbacks": 0, "tool_calls": 0, "tool_schema_errors": 0},
            },
        ]
        res = build_benchmark_results(meta, cases, pass_k=3)
        self.assertEqual(set(res.keys()), {"meta", "summary", "cases"})
        s = res["summary"]
        self.assertEqual(s["total_n"], 3)
        self.assertEqual(s["invalid_baseline_n"], 1)
        self.assertEqual(s["valid_non_blocked_n"], 2)
        self.assertEqual(s["resolved_n"], 1)
        self.assertEqual(s["cache_hit_rate"], 0.5)
        self.assertEqual(s["usd_per_resolved"], 0.2)
        self.assertEqual(sum(s["failure_buckets"].values()), 2)
        self.assertEqual(s["failure_buckets"]["1_infra_quota_baseline"], 1)
        self.assertEqual(s["failure_buckets"]["4_worker_edit_fidelity"], 1)
        self.assertEqual(res["meta"]["truth_check"]["status"], "PASS")

        # Negative Truth-Check test: unstripped .git must trigger INVALID_HARNESS!
        bad_meta = dict(meta)
        bad_meta["decontamination"] = {"git_stripped": False, "network_mode": "none", "tmp_clean": True, "secrets_isolated": True}
        bad_res = build_benchmark_results(bad_meta, cases, pass_k=3)
        self.assertEqual(bad_res["meta"]["truth_check"]["status"], "INVALID_HARNESS")
        self.assertIn("1_decontam", bad_res["meta"]["truth_check"]["failed_checks"])

    def test_preflight_reports_missing_deps_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            secret_token = "FAKE_SUPER_SECRET_TOKEN_987654321"

            def ok_cmd(args: list[str], _to: int) -> tuple[int, str, str]:
                if args[:2] == ["docker", "info"]:
                    return 0, "29.6.2", ""
                if args[:3] == ["docker", "network", "ls"]:
                    return 0, "none", ""
                if args[0] == "nvidia-smi":
                    return 0, "GTX 1650, 3200 MiB, 4096 MiB", ""
                return 1, "", "unexpected"

            def ok_http(url: str, _to: float) -> dict[str, object]:
                if url.endswith("/api/tags"):
                    return {"models": [{"name": "qwen3.5:2b-q4_K_M"}]}
                if url.endswith("/api/ps"):
                    return {"models": [{"name": "qwen3.5:2b-q4_K_M", "size": 1_600_000_000, "size_vram": 1_600_000_000}]}
                raise AssertionError(f"Unexpected URL: {url}")

            def ok_disk(_path: Path) -> tuple[int, int, int]:
                return 100 * (1024**3), 50 * (1024**3), 50 * (1024**3)

            # 1. All green + strict secret-redaction check.
            good = run_preflight(
                repo_root=root,
                provider="nvidia",
                worker_model="qwen3.5:2b-q4_K_M",
                require_docker=True,
                require_local_worker=True,
                require_harbor=False,
                env={"NVIDIA_API_KEY": secret_token},
                cmd_runner=ok_cmd,
                http_get=ok_http,
                disk_usage=ok_disk,
                which_fn=lambda _: None,
            )
            self.assertTrue(good["ready"])
            self.assertEqual(good["gpu_residency_pct"], 100.0)
            self.assertNotIn(secret_token, json.dumps(good))

            # 2. Negative checks: Docker down, low disk, missing key, CPU spill (<99%), missing Harbor.
            def bad_cmd(_args: list[str], _to: int) -> tuple[int, str, str]:
                return 1, "", "Cannot connect to Docker daemon"

            def spill_http(url: str, _to: float) -> dict[str, object]:
                if url.endswith("/api/tags"):
                    return {"models": [{"name": "qwen3.5:2b-q4_K_M"}]}
                return {"models": [{"name": "qwen3.5:2b-q4_K_M", "size": 2_000_000_000, "size_vram": 1_300_000_000}]}

            def low_disk(_path: Path) -> tuple[int, int, int]:
                return 100 * (1024**3), 99 * (1024**3), 1 * (1024**3)

            bad = run_preflight(
                repo_root=root,
                provider="nvidia",
                worker_model="qwen3.5:2b-q4_K_M",
                require_docker=True,
                require_local_worker=True,
                require_harbor=True,
                min_free_gb=5.0,
                env={},
                cmd_runner=bad_cmd,
                http_get=spill_http,
                disk_usage=low_disk,
                which_fn=lambda _: None,
            )
            self.assertFalse(bad["ready"])
            self.assertEqual(bad["gpu_residency_pct"], 65.0)
            self.assertEqual(
                set(bad["failed_required"]),
                {"docker_sandbox", "disk_headroom", "provider_credentials", "local_worker_ollama", "harbor_cli"},
            )


if __name__ == "__main__":
    unittest.main()
