"""Controlled functional end-to-end tests for HybridAgentRunner (zero live API calls).

Tests the full Cloud Thinking Orchestrator -> dispatch_worker -> fenced Local Worker
(think=False, Hashline edit_file, syntax self-correction, checkpoint rollback) ->
independent unittest verification lifecycle using scripted HTTP transports.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from hivo.hybrid import HybridAgentRunner, HybridRunConfig
from hivo.providers import (
    RawHttpResponse,
    create_client,
    groq_orchestrator,
    nvidia_nim_orchestrator,
    ollama_worker,
    openrouter_orchestrator,
)
from hivo.tools import ERR_PATH_SECURITY


def _openai_ok(
    *,
    content: str = "",
    reasoning_content: str = "",
    tool_calls: list[dict] | None = None,
    prompt_tokens: int = 100,
    completion_tokens: int = 30,
) -> RawHttpResponse:
    msg: dict = {"role": "assistant", "content": content}
    if reasoning_content:
        msg["reasoning_content"] = reasoning_content
    if tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.get("id", f"call_{i + 1}"),
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": json.dumps(tc["arguments"]),
                },
            }
            for i, tc in enumerate(tool_calls)
        ]
    body = {
        "model": "qwen/qwen3.8-27b",
        "choices": [{"finish_reason": "tool_calls" if tool_calls else "stop", "message": msg}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
    return RawHttpResponse(200, json.dumps(body), {})


def _ollama_ok(
    *,
    content: str = "",
    tool_calls: list[dict] | None = None,
    prompt_eval_count: int = 60,
    eval_count: int = 20,
) -> RawHttpResponse:
    msg: dict = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.get("id", f"wcall_{i + 1}"),
                "function": {"name": tc["name"], "arguments": tc["arguments"]},
            }
            for i, tc in enumerate(tool_calls)
        ]
    body = {
        "model": "qwen3.5:2b",
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": prompt_eval_count,
        "eval_count": eval_count,
        "message": msg,
    }
    return RawHttpResponse(200, json.dumps(body), {})


class TestHybridAgentRunnerControlledE2E(unittest.TestCase):
    def _create_buggy_workspace(self, ws: Path) -> None:
        (ws / "src").mkdir()
        (ws / "tests").mkdir()
        (ws / "src" / "calc.py").write_text(
            "def add(a: int, b: int) -> int:\n    return a - b\n",
            encoding="utf-8",
        )
        (ws / "src" / "secret_neighbor.py").write_text("DO_NOT_TOUCH = 1\n", encoding="utf-8")
        (ws / ".env").write_text("GROQ_API_KEY=do_not_expose\n", encoding="utf-8")
        (ws / "tests" / "test_calc.py").write_text(
            "import unittest\n"
            "from src.calc import add\n\n"
            "class CalcTest(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n",
            encoding="utf-8",
        )

    def test_full_cloud_orchestrator_to_local_worker_fix_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            self._create_buggy_workspace(ws)

            orch_payloads: list[dict] = []
            worker_payloads: list[dict] = []

            def orch_transport(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
                orch_payloads.append(payload)
                turn = len(orch_payloads)
                if turn == 1:
                    return _openai_ok(
                        reasoning_content="SECRET_ORCH_THOUGHT_MUST_NOT_LEAK_TO_WORKER",
                        tool_calls=[
                            {"id": "o1", "name": "code_intel", "arguments": {"action": "find_symbol", "symbol": "add"}},
                            {
                                "id": "o2",
                                "name": "update_plan",
                                "arguments": {
                                    "steps": [
                                        {"id": "s1", "title": "Fix add()", "status": "in_progress", "files": ["src/calc.py"]}
                                    ]
                                },
                            },
                        ],
                    )
                if turn == 2:
                    return _openai_ok(
                        content="<think>Hidden inline chain</think>",
                        tool_calls=[{
                            "id": "o3",
                            "name": "dispatch_worker",
                            "arguments": {
                                "task": "Change add(a, b) in src/calc.py to return a + b.",
                                "target_files": ["src/calc.py"],
                                "context": "Line 2 currently returns a - b.",
                            },
                        }],
                    )
                if turn == 3:
                    return _openai_ok(
                        tool_calls=[{
                            "id": "o4",
                            "name": "run_command",
                            "arguments": {"command": f'"{sys.executable}" -m unittest discover -s tests -v'},
                        }],
                    )
                return _openai_ok(content="Fixed add(a, b) in src/calc.py and verified tests pass.")

            def worker_transport(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
                worker_payloads.append(payload)
                # Enforce PDF quick wins on every local worker call
                self.assertFalse(payload["think"])
                self.assertEqual(payload["options"]["num_ctx"], 4096)
                # Verify cloud orchestrator private thinking NEVER leaked to worker prompt
                all_worker_text = json.dumps(payload["messages"])
                self.assertNotIn("SECRET_ORCH_THOUGHT_MUST_NOT_LEAK_TO_WORKER", all_worker_text)
                self.assertNotIn("Hidden inline chain", all_worker_text)

                turn = len(worker_payloads)
                if turn == 1:
                    # Also probe fence: try reading disallowed neighbor + real target
                    return _ollama_ok(tool_calls=[
                        {"id": "w1", "name": "read_file", "arguments": {"path": "src/secret_neighbor.py"}},
                        {"id": "w2", "name": "read_file", "arguments": {"path": "src/calc.py"}},
                    ])
                if turn == 2:
                    # Extract line 2 anchor from previous read_file observation
                    last_obs = payload["messages"][-1]["content"]
                    start = last_obs.find("{")
                    end = last_obs.rfind("}") + 1
                    env = json.loads(last_obs[start:end])
                    line2 = env["data"]["content"].splitlines()[1]
                    # First attempt writes syntax error to test inline feedback + self-correction
                    return _ollama_ok(tool_calls=[{
                        "id": "w3",
                        "name": "edit_file",
                        "arguments": {
                            "path": "src/calc.py",
                            "operation": "replace",
                            "start_anchor": line2,
                            "content": "    return a + (",
                        },
                    }])
                if turn == 3:
                    last_obs = payload["messages"][-1]["content"]
                    env = json.loads(last_obs[last_obs.find("{") : last_obs.rfind("}") + 1])
                    self.assertFalse(env["data"]["syntax_ok"])
                    refreshed = next(
                        ln for ln in env["data"]["updated_window"].splitlines() if ln.startswith("2:")
                    )
                    return _ollama_ok(tool_calls=[{
                        "id": "w4",
                        "name": "edit_file",
                        "arguments": {
                            "path": "src/calc.py",
                            "operation": "replace",
                            "start_anchor": refreshed,
                            "content": "    return a + b",
                        },
                    }])
                return _ollama_ok(content="Updated src/calc.py line 2 to return a + b.")

            orch_cfg = groq_orchestrator()
            worker_cfg = ollama_worker(model="qwen3.5:2b", num_ctx=4096)
            runner = HybridAgentRunner(
                ws,
                HybridRunConfig(
                    orchestrator=orch_cfg,
                    worker=worker_cfg,
                    protected_paths=("tests/**",),
                ),
                orchestrator_client=create_client(orch_cfg, api_key="test-key", transport=orch_transport),
                worker_client=create_client(worker_cfg, transport=worker_transport),
            )

            result = runner.run("Fix add() in src/calc.py and run unit tests.")
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.modified_files, ("src/calc.py",))
            self.assertEqual(result.orchestrator_turns, 4)
            self.assertGreater(result.orchestrator_reasoning_chars, 0)
            self.assertEqual(len(result.worker_runs), 1)
            self.assertEqual(result.worker_runs[0].status, "done")
            self.assertFalse(result.worker_runs[0].rolled_back)
            self.assertIn("-    return a - b", result.worker_runs[0].unified_diff)
            self.assertIn("+    return a + b", result.worker_runs[0].unified_diff)
            # Verify orchestrator received the real unified_diff in its turn-3 tool observation
            turn3_tool_obs = orch_payloads[2]["messages"][-1]["content"]
            self.assertIn("unified_diff", turn3_tool_obs)
            self.assertIn("+    return a + b", turn3_tool_obs)

            # Verify non-interactive orchestrator omits ask_user and worker stays lean (3 tools)
            run_started = next(e for e in result.trace if e.get("event") == "run_started")
            self.assertNotIn("ask_user", run_started["orchestrator_tools"])
            worker_started = next(e for e in result.trace if e.get("event") == "worker_started")
            self.assertEqual(worker_started["worker_tools"], ["edit_file", "read_file", "write_file"])

            # Verify fence blocked disallowed file in worker trace
            blocked_events = [
                e for e in result.trace
                if e.get("event") == "worker_tool" and e.get("error_code") == ERR_PATH_SECURITY
            ]
            self.assertEqual(len(blocked_events), 1)

            # Independent disk + unittest oracle
            self.assertEqual(
                (ws / "src" / "calc.py").read_text(encoding="utf-8"),
                "def add(a: int, b: int) -> int:\n    return a + b\n",
            )
            proc = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                cwd=ws,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)

    def test_broken_worker_edit_rolls_back_cleanly_via_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            self._create_buggy_workspace(ws)
            original_bytes = (ws / "src" / "calc.py").read_text(encoding="utf-8")

            orch_turn = {"n": 0}

            def orch_transport(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
                orch_turn["n"] += 1
                if orch_turn["n"] == 1:
                    return _openai_ok(tool_calls=[{
                        "id": "o1",
                        "name": "dispatch_worker",
                        "arguments": {"task": "Edit calc.py", "target_files": ["src/calc.py"]},
                    }])
                # Inspect worker failure envelope returned to orchestrator
                tool_msg = payload["messages"][-1]["content"]
                self.assertIn('"status": "failed"', tool_msg)
                return _openai_ok(content="Worker failed syntax check and was rolled back.")

            worker_turn = {"n": 0}

            def worker_transport(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
                worker_turn["n"] += 1
                if worker_turn["n"] == 1:
                    return _ollama_ok(tool_calls=[{"id": "w1", "name": "read_file", "arguments": {"path": "src/calc.py"}}])
                if worker_turn["n"] == 2:
                    obs = payload["messages"][-1]["content"]
                    env = json.loads(obs[obs.find("{") : obs.rfind("}") + 1])
                    line2 = env["data"]["content"].splitlines()[1]
                    return _ollama_ok(tool_calls=[{
                        "id": "w2",
                        "name": "edit_file",
                        "arguments": {
                            "path": "src/calc.py",
                            "operation": "replace",
                            "start_anchor": line2,
                            "content": "    return a + (",
                        },
                    }])
                # Worker stops without fixing broken syntax
                return _ollama_ok(content="Done.")

            orch_cfg = nvidia_nim_orchestrator()
            worker_cfg = ollama_worker()
            runner = HybridAgentRunner(
                ws,
                HybridRunConfig(orchestrator=orch_cfg, worker=worker_cfg, auto_checkpoint_worker=True),
                orchestrator_client=create_client(orch_cfg, api_key="fake-test-key", transport=orch_transport),
                worker_client=create_client(worker_cfg, transport=worker_transport),
            )
            result = runner.run("Edit calc.py")
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.worker_runs[0].status, "failed")
            self.assertTrue(result.worker_runs[0].rolled_back)
            self.assertEqual(result.worker_runs[0].unified_diff, "")
            self.assertEqual(result.modified_files, ())
            # Disk bytes restored identically
            self.assertEqual((ws / "src" / "calc.py").read_text(encoding="utf-8"), original_bytes)

    def test_worker_aborts_early_on_repeated_identical_tool_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            self._create_buggy_workspace(ws)
            original_bytes = (ws / "src" / "calc.py").read_text(encoding="utf-8")

            orch_turns = {"n": 0}

            def orch_transport(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
                orch_turns["n"] += 1
                if orch_turns["n"] == 1:
                    return _openai_ok(tool_calls=[{
                        "id": "o1",
                        "name": "dispatch_worker",
                        "arguments": {"task": "Edit calc.py", "target_files": ["src/calc.py"]},
                    }])
                return _openai_ok(content="Handled repeated error abort.")

            worker_turns = {"n": 0}

            def worker_transport(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
                worker_turns["n"] += 1
                # Always send stale/bad anchor -> EDIT_APPLY_ERROR every turn
                return _ollama_ok(tool_calls=[{
                    "id": f"w{worker_turns['n']}",
                    "name": "edit_file",
                    "arguments": {
                        "path": "src/calc.py",
                        "operation": "replace",
                        "start_anchor": "2:00",
                        "content": "    return a + b",
                    },
                }])

            orch_cfg = groq_orchestrator()
            worker_cfg = ollama_worker()
            runner = HybridAgentRunner(
                ws,
                HybridRunConfig(
                    orchestrator=orch_cfg,
                    worker=worker_cfg,
                    max_worker_turns=6,
                    max_consecutive_worker_errors=2,
                ),
                orchestrator_client=create_client(orch_cfg, api_key="k", transport=orch_transport),
                worker_client=create_client(worker_cfg, transport=worker_transport),
            )
            res = runner.run("Edit calc.py")
            self.assertEqual(res.status, "completed")
            # Stopped at turn 2 instead of burning all 6 turns!
            self.assertEqual(res.worker_runs[0].turns, 2)
            self.assertEqual(res.worker_runs[0].status, "failed")
            self.assertIn("2 consecutive EDIT_APPLY_ERROR", res.worker_runs[0].error or "")
            self.assertTrue(res.worker_runs[0].rolled_back)
            self.assertEqual((ws / "src" / "calc.py").read_text(encoding="utf-8"), original_bytes)

    def test_extra_orchestrator_tools_and_history_compaction(self) -> None:
        from hivo.tools import ToolSpec, ok_result

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            self._create_buggy_workspace(ws)
            custom_calls: list[str] = []

            def handle_custom(args: dict, ctx) -> dict:
                custom_calls.append(args["cmd"])
                return ok_result({"stdout": "X" * 3000, "exit_code": 0})

            custom_spec = ToolSpec(
                name="run_container_tests",
                description="Run repo tests inside isolated Docker container.",
                effect="exec",
                model_tier="orchestrator_only",
                parameters={
                    "type": "object",
                    "properties": {"cmd": {"type": "string"}},
                    "required": ["cmd"],
                    "additionalProperties": False,
                },
                handler=handle_custom,
            )

            seen_payloads: list[dict] = []

            def orch_transport(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
                seen_payloads.append(payload)
                t = len(seen_payloads)
                if t <= 4:
                    return _openai_ok(tool_calls=[{
                        "id": f"c{t}",
                        "name": "run_container_tests",
                        "arguments": {"cmd": f"pytest -k case_{t}"},
                    }])
                return _openai_ok(content="All checks done.")

            orch_cfg = groq_orchestrator()
            runner = HybridAgentRunner(
                ws,
                HybridRunConfig(
                    orchestrator=orch_cfg,
                    worker=ollama_worker(),
                    extra_orchestrator_tools=(custom_spec,),
                    max_history_chars=4000,
                ),
                orchestrator_client=create_client(orch_cfg, api_key="k", transport=orch_transport),
                worker_client=create_client(ollama_worker(), transport=lambda *_: _ollama_ok(content="unused")),
            )
            res = runner.run("Verify tests in container.")
            self.assertEqual(res.status, "completed")
            self.assertEqual(len(custom_calls), 4)
            # On turn 5, earliest bulky tool message must have been compacted
            turn5_msgs = seen_payloads[-1]["messages"]
            first_tool_msg = next(m for m in turn5_msgs if m.get("role") == "tool")
            self.assertIn("compacted from", first_tool_msg["content"])

    def test_provider_failure_is_explicit_and_config_swap_works_across_presets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            self._create_buggy_workspace(ws)

            # 1. Explicit failure on HTTP 500 (never fabricated)
            fail_cfg = openrouter_orchestrator()
            runner_fail = HybridAgentRunner(
                ws,
                HybridRunConfig(orchestrator=fail_cfg, worker=ollama_worker()),
                orchestrator_client=create_client(
                    fail_cfg,
                    api_key="or-test",
                    transport=lambda *_: RawHttpResponse(500, "upstream down", {}),
                    sleep_fn=lambda _: None,
                ),
                worker_client=create_client(ollama_worker(), transport=lambda *_: _ollama_ok(content="unused")),
            )
            res_fail = runner_fail.run("Check calc.py")
            self.assertEqual(res_fail.status, "provider_error")
            self.assertIn("HTTP 500", res_fail.error or "")

            # 2. Same runner code works identically across Groq / NVIDIA NIM / OpenRouter presets
            for preset in (groq_orchestrator(), nvidia_nim_orchestrator(), openrouter_orchestrator()):
                seen_urls: list[str] = []

                def ok_transport(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
                    seen_urls.append(url)
                    return _openai_ok(content=f"Answered by {preset.model}")

                runner = HybridAgentRunner(
                    ws,
                    HybridRunConfig(orchestrator=preset, worker=ollama_worker()),
                    orchestrator_client=create_client(preset, api_key="k", transport=ok_transport),
                    worker_client=create_client(ollama_worker(), transport=lambda *_: _ollama_ok(content="unused")),
                )
                res = runner.run("Summarize calc.py")
                self.assertEqual(res.status, "completed")
                self.assertEqual(seen_urls, [f"{preset.base_url}/chat/completions"])
                self.assertEqual(res.orchestrator_model, preset.model)

    def test_worker_unified_diff_truncates_cleanly_and_prompt_enforces_one_by_one(self) -> None:
        from hivo.hybrid.prompts import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(include_run_command=True)
        self.assertIn("ONE small problem at a time", prompt)
        self.assertIn("unified_diff", prompt)

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "big.txt").write_text("line_0\n", encoding="utf-8")

            orch_turn = {"n": 0}

            def orch_transport(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
                orch_turn["n"] += 1
                if orch_turn["n"] == 1:
                    return _openai_ok(tool_calls=[{
                        "id": "o1",
                        "name": "dispatch_worker",
                        "arguments": {"task": "Expand big.txt", "target_files": ["big.txt"]},
                    }])
                return _openai_ok(content="Checked truncated diff.")

            worker_turn = {"n": 0}

            def worker_transport(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
                worker_turn["n"] += 1
                if worker_turn["n"] == 1:
                    big_body = "".join(f"row_{i}_" + ("x" * 40) + "\n" for i in range(40))
                    return _ollama_ok(tool_calls=[{
                        "id": "w1",
                        "name": "write_file",
                        "arguments": {"path": "big.txt", "content": big_body, "overwrite": True},
                    }])
                return _ollama_ok(content="Updated big.txt.")

            orch_cfg = groq_orchestrator()
            worker_cfg = ollama_worker()
            runner = HybridAgentRunner(
                ws,
                HybridRunConfig(
                    orchestrator=orch_cfg,
                    worker=worker_cfg,
                    max_worker_diff_chars=300,
                ),
                orchestrator_client=create_client(orch_cfg, api_key="k", transport=orch_transport),
                worker_client=create_client(worker_cfg, transport=worker_transport),
            )
            res = runner.run("Expand big.txt")
            self.assertEqual(res.status, "completed")
            diff = res.worker_runs[0].unified_diff
            self.assertIn("truncated from", diff)
            self.assertLessEqual(len(diff), 400)


if __name__ == "__main__":
    unittest.main()
