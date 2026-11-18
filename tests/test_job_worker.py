"""Controlled functional tests: scripted Ollama I/O, native Mini Hivo gates."""

import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

import mini
from hivo import job_worker as worker
from hivo.http_client import HttpTransportError, JsonResponse
from hivo.job_result import snapshot_digest


ROOT = Path(__file__).resolve().parents[1]
PROMPT = (
    "Update the CLI greeting in greeting.py to WELCOME.\n"
    "Requirements:\n"
    "- The accepted input prints WELCOME.\n"
    "- Invalid input must still exit nonzero.\n"
)
BASE = {
    "greeting.py": b"def get_greeting():\n    # Accepted input greeting behavior.\n    return 'HELLO'\n",
    "cli.py": (
        b"def main(value, message=None):\n"
        b"    if value != 'valid':\n"
        b"        return 2\n"
        b"    if message is None:\n"
        b"        from greeting import get_greeting\n"
        b"        message = get_greeting()\n"
        b"    print(message)\n"
        b"    return 0\n"
    ),
    "test_cli.py": (
        b"import ast\n"
        b"import contextlib\n"
        b"import io\n"
        b"import sys\n"
        b"sys.dont_write_bytecode = True\n"
        b"from cli import main\n"
        b"from pathlib import Path\n"
        b"function, = ast.parse(Path('greeting.py').read_text()).body\n"
        b"assert isinstance(function, ast.FunctionDef) and function.name == 'get_greeting'\n"
        b"statement, = function.body\n"
        b"assert isinstance(statement, ast.Return)\n"
        b"message = ast.literal_eval(statement.value)\n"
        b"output = io.StringIO()\n"
        b"with contextlib.redirect_stdout(output):\n"
        b"    assert main('valid', message) == 0\n"
        b"    assert main('invalid', message) == 2\n"
        b"assert output.getvalue() == 'WELCOME\\n', output.getvalue()\n"
        b"print('syntax check passed: greeting.py')\n"
    ),
}


def _reply(data=None, *, tool=None, **args):
    message = {"role": "assistant", "content": json.dumps(data) if isinstance(data, dict) else (data or "")}
    if tool:
        message["tool_calls"] = [{"function": {"name": tool, "arguments": args}}]
    return JsonResponse(200, json.dumps({"message": message, "done": True, "done_reason": "stop"}))


class FixtureProvider:
    """Only model responses are scripted, not Mini Hivo decisions or tool results."""

    def __init__(self, *, execute=False, content="WELCOME"):
        self.execute = execute
        self.content = content
        self.calls = []
        self.builder_steps = 0
        self.falsifier_steps = 0

    def __call__(self, op, path, *, timeout, payload):
        assert (op, path, payload["model"]) == ("post", "/api/chat", "gemma4:e4b")
        assert 0 < timeout <= 120 and payload["stream"] is False
        properties = set((payload.get("format") or {}).get("properties", {}))
        self.calls.append(properties)
        if self.execute:
            assert not properties.intersection({
                "requirements", "questions", "root_goal", "paths", "decisions", "challenges", "impacts",
            }), f"planning re-entered after approval: {properties}"
        if "questions" in properties:
            return _reply({"questions": []})
        if properties == {"paths"}:
            return _reply({"paths": ["greeting.py", "cli.py", "test_cli.py"]})
        if "root_goal" in properties:
            spec = {key: [] for key in properties}
            spec.update(root_goal=PROMPT.splitlines()[0])
            return _reply(spec)
        if "decisions" in properties:
            frame = mini.RUN["impact_decision_frame"]
            return _reply(mini.stage3.deterministic_impact_decision_choices(frame))
        if "impacts" in properties:
            return _reply(self._impact_map())
        if "challenges" in properties:
            return _reply({"challenges": []})
        if "objective" in properties:
            return _reply({"objective": "Update only greeting.py."})
        if properties == {"decision"}:
            return _reply({"decision": "execute"})
        if properties:
            raise AssertionError(f"unplanned structured role: {properties}")
        assert self.execute, "an execution role ran before operator approval"
        system = payload["messages"][0]["content"]
        if system.startswith(mini.ROLE_SYSTEM_PROMPTS["Repairer"]):
            return _reply("Unable to repair within the current verified scope.")
        if system.startswith(mini.ROLE_SYSTEM_PROMPTS["Builder"]):
            self.builder_steps += 1
            return {
                1: _reply(tool="context_sufficiency_check", context_status="sufficient",
                          reason="The current source and exact authorized target are established."),
                2: _reply(tool="edit_file", path="greeting.py", old="HELLO", new=self.content),
                3: _reply(tool="run_command", command="python test_cli.py"),
            }.get(self.builder_steps, _reply("The greeting has been updated and checked."))
        if system.startswith(mini.ROLE_SYSTEM_PROMPTS["Falsifier"]):
            self.falsifier_steps += 1
            if self.falsifier_steps == 1:
                return _reply(tool="run_command", command="python test_cli.py")
            return _reply("The CLI test checks the greeting and the invalid exit status.")
        raise AssertionError(f"unplanned execution role: {system[:180]}")

    @staticmethod
    def _impact_map():
        seed = next(item for item in mini.RUN["impact_seeds"] if item["canonical_path"] == "greeting.py")
        ids = [item["requirement_id"] for item in
               mini._active_stage3_requirements(mini.RUN["source_contract"])]
        return {
            "impacts": [{
                "impact_id": seed["impact_id"], "surface_id": seed["surface_id"],
                "disposition": "MUST_CHANGE", "requirement_ids": ids,
                "action": "Set the fixture greeting to WELCOME and preserve invalid input behavior.",
                "verification": ["python test_cli.py"],
            }],
            "integration_verification": ["python test_cli.py"], "insufficient_evidence": [],
        }


class JobWorkerTests(unittest.TestCase):
    def setUp(self):
        self.scratch = ROOT / ".runtime-proof" / ("worker-fixtures-" + uuid4().hex)
        self.scratch.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.scratch)
        self.origin = self.scratch / "original"
        self.origin.mkdir()
        for path, content in BASE.items():
            (self.origin / path).write_bytes(content)
        self.job = {
            "status": "running", "job_id": "job-01", "project_id": "fixture",
            "base_revision": "a" * 40, "attempt_id": "plan-initial", "prompt": PROMPT,
            "checkpoint": None, "decision_request": None, "decision": None,
            "limits": {"max_model_calls": 18, "max_tool_calls": 25, "max_elapsed_seconds": 120,
                       "max_attempts": 3},
        }
        self.fail_root_check = False
        self.root_checks = 0
        # Permit only the exact, pre-authored verifier and application from
        # this disposable fixture. Never run model-generated code on the host.
        original_run = subprocess.run

        def guarded_run(args, **kwargs):
            root = Path(kwargs["cwd"])
            self.assertTrue(root.is_relative_to(self.scratch) and root != self.origin, args)
            self.assertEqual(args[1:], ["test_cli.py"], args)
            self.assertIn(Path(args[0]).stem, {"python", "python3"})
            for name in ("test_cli.py", "cli.py"):
                self.assertEqual((root / name).read_bytes(), BASE[name], "an authored executable changed")
            if mini.RUN.get("integration_executor_calls"):
                self.root_checks += 1
                if self.fail_root_check:
                    raise FileNotFoundError("scripted unavailability of the fresh parent check")
            return original_run([sys.executable, "-B", "test_cli.py"], **kwargs)

        runner = patch.object(mini.subprocess, "run", side_effect=guarded_run)
        self.command = runner.start()
        self.addCleanup(runner.stop)

    def stage(self):
        return shutil.copytree(self.origin, self.scratch / uuid4().hex)

    def pause_for_approval(self):
        workspace, provider = self.stage(), FixtureProvider()
        base_digest = snapshot_digest(self.origin)
        outcome = worker.run_attempt(self.job, workspace, transport=provider)
        self.assertEqual(outcome["status"], "waiting_approval", outcome)
        self.assertEqual(outcome["usage"]["model_calls"], len(provider.calls))
        self.assertEqual(outcome["usage"]["tool_calls"], 0)
        self.assertEqual(outcome["checkpoint"]["allowed_paths"], ["greeting.py"])
        self.assertEqual(outcome["checkpoint"]["base_sha256"], base_digest)
        self.assertIsInstance(outcome["decision_request"]["plan_summary"], str)
        self.assertIn("greeting.py", outcome["decision_request"]["plan_summary"])
        self.assertEqual(snapshot_digest(workspace), base_digest)
        self.command.assert_not_called()
        return outcome

    def resume(self, pause, *, answer="Set the greeting text to WELCOME."):
        # Force the same JSON/independent-process representation as the store.
        request = pause["decision_request"]
        decision = {"decision_id": request["decision_id"], "actor_id": "operator"}
        if request["kind"] == "clarification":
            decision.update(kind="answer", answers={item["question_id"]: answer for item in request["questions"]})
        else:
            decision.update(kind="approve", plan_hash=request["plan_hash"])
        limits = {
            key: self.job["limits"][key] - pause["usage"][resource]
            for key, resource in zip(worker._BUDGET_KEYS, ("model_calls", "tool_calls", "elapsed_seconds"))
        }
        limits["max_attempts"] = self.job["limits"]["max_attempts"] - 1
        return json.loads(json.dumps({
            **self.job, "attempt_id": "reclaimed-attempt", "decision": decision,
            "checkpoint": pause["checkpoint"], "decision_request": request, "limits": limits,
        }))

    def test_exact_plan_waits_then_executes_without_planning_and_returns_candidate_only(self):
        pause = self.pause_for_approval()
        job, work, provider = self.resume(pause), self.stage(), FixtureProvider(execute=True)
        outcome = worker.run_attempt(job, work, transport=provider)
        self.assertEqual(outcome["status"], "candidate", outcome)
        self.assertEqual(outcome["usage"]["model_calls"], len(provider.calls))
        self.assertGreaterEqual(outcome["usage"]["tool_calls"], 3)
        self.assertGreater(self.root_checks, 0)
        self.assertGreater(self.command.call_count, self.root_checks, "child check must precede root")
        self.assertEqual((work / "greeting.py").read_text(),
                         BASE["greeting.py"].decode().replace("HELLO", "WELCOME"))
        self.assertEqual((self.origin / "greeting.py").read_bytes(), BASE["greeting.py"])
        self.assertIsNone(outcome["checkpoint"])
        self.assertNotIn("patch", outcome)
        self.assertEqual(outcome["evidence"], {
            "job_id": job["job_id"], "attempt_id": job["attempt_id"], "root_verified": True,
            "base_revision": job["base_revision"], "plan_hash": job["decision"]["plan_hash"],
            "allowed_paths": ["greeting.py"], "workspace_sha256": snapshot_digest(work),
        })

    def test_passing_child_cannot_replace_a_fresh_root_check(self):
        job, work = self.resume(self.pause_for_approval()), self.stage()
        self.fail_root_check = True
        graph = mini.execute_approved_plan_graph
        observed = []

        def capture(*args, **kwargs):
            root, memory = graph(*args, **kwargs)
            observed.append(root)
            return root, memory

        with patch.object(mini, "execute_approved_plan_graph", side_effect=capture):
            outcome = worker.run_attempt(job, work, transport=FixtureProvider(execute=True))
        self.assertGreater(self.root_checks, 0, "root verification should actually be attempted")
        self.assertTrue(observed[0]["children"][0]["receipt_verified"])
        self.assertEqual(observed[0]["integration_result"], mini.INTEGRATION_EVIDENCE_UNAVAILABLE)
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["failure_code"], "ROOT_VERIFICATION_FAILED")
        self.assertIsNone(outcome["evidence"])
        self.assertEqual((self.origin / "greeting.py").read_bytes(), BASE["greeting.py"])

    def test_stale_approval_plan_scope_prompt_attempt_or_base_never_dispatch(self):
        pause = self.pause_for_approval()
        for variant in ("decision", "plan", "scope", "prompt", "attempt", "base"):
            with self.subTest(variant=variant):
                job, work = self.resume(pause), self.stage()
                if variant == "decision":
                    job["decision"]["plan_hash"] = "0" * 64
                elif variant == "plan":
                    job["checkpoint"]["authority"]["plan"]["task_goal"] = "Tampered"
                    # The native plan gate must fail even with a recomputed envelope hash.
                    job["checkpoint"].pop("checkpoint_sha256")
                    job["checkpoint"]["checkpoint_sha256"] = worker._hash(job["checkpoint"])
                elif variant == "scope":
                    job["checkpoint"]["allowed_paths"].append("cli.py")
                elif variant == "prompt":
                    job["prompt"] += "\n"
                elif variant == "attempt":
                    job["attempt_id"] = pause["checkpoint"]["paused_attempt_id"]
                else:
                    (work / "cli.py").write_bytes(BASE["cli.py"] + b"\n# stale\n")
                initial = snapshot_digest(work)
                outcome = worker.run_attempt(job, work, transport=self.unexpected_provider)
                self.assertEqual(outcome["status"], "blocked", outcome)
                self.assertEqual(outcome["usage"]["model_calls"], 0)
                self.assertIsNone(outcome["evidence"])
                self.assertEqual(snapshot_digest(work), initial)
        self.command.assert_not_called()

    def test_source_clarification_uses_original_question_and_exact_answer(self):
        prompt = (
            "Requirements:\n"
            "- Remove keyboard controls.\n"
            "- Keyboard controls must remain unchanged.\n"
        )
        self.job["prompt"] = prompt
        pause = worker.run_attempt(self.job, self.stage(), transport=self.unexpected_provider)
        self.assertEqual(pause["status"], "waiting_clarification", pause)
        self.assertEqual(len(pause["decision_request"]["questions"]), 1)
        self.assertEqual(pause["usage"]["model_calls"], 0)
        rejected = self.resume(pause)
        rejected["decision"]["answers"]["OTHER-Q"] = "forged"
        outcome = worker.run_attempt(rejected, self.stage(), transport=self.unexpected_provider)
        self.assertEqual(outcome["failure_code"], "INVALID_CLARIFICATION_ANSWERS")

        answer = "Keep the existing  keyboard controls."
        seen = []

        def observe_contract(goal, contract, **kwargs):
            self.assertEqual(goal, prompt)
            seen.extend(contract["clarification_answers"])
            return stage2(goal, contract, **kwargs)

        def fail_provider(op, path, *, timeout, payload):
            # Stop after the actual source continuation has been observed; this
            # deliberately conflicting fixture is not the successful edit case.
            raise mini.RunBudgetExceeded("model")

        stage2 = mini.prepare_stage2_context
        with patch.object(mini, "get_goal_contract", side_effect=AssertionError("reasked source clarification")), \
                patch.object(mini, "prepare_stage2_context", side_effect=observe_contract):
            outcome = worker.run_attempt(self.resume(pause, answer=answer), self.stage(), transport=fail_provider)
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["question_id"], pause["decision_request"]["questions"][0]["question_id"])
        self.assertEqual(seen[0]["authority_decision_id"], pause["decision_request"]["decision_id"])
        self.assertEqual(seen[0]["answer"], answer)
        self.command.assert_not_called()

    def test_provider_error_and_budget_cannot_return_candidate(self):
        requests = []

        def failing_provider(*args, **kwargs):
            requests.append(args)
            raise HttpTransportError("scripted failure")

        work = self.stage()
        outcome = worker.run_attempt(self.job, work, transport=failing_provider)
        self.assertEqual(outcome["failure_code"], "PROVIDER_FAILURE")
        self.assertGreater(len(requests), 0)
        self.assertEqual(outcome["usage"]["model_calls"], len(requests))
        self.assertIsNone(outcome["evidence"])
        self.assertEqual(snapshot_digest(work), snapshot_digest(self.origin))
        limited = {**self.job, "limits": {**self.job["limits"], "max_model_calls": 0}}
        outcome = worker.run_attempt(limited, self.stage(), transport=self.unexpected_provider)
        self.assertEqual(outcome["failure_code"], "RUN_BUDGET_MODEL_EXHAUSTED")
        self.assertEqual(outcome["usage"]["model_calls"], 0)
        elapsed = {**self.job, "limits": {**self.job["limits"], "max_elapsed_seconds": 0}}
        outcome = worker.run_attempt(elapsed, self.stage(), transport=self.unexpected_provider)
        self.assertEqual(outcome["status"], "timed_out")
        self.assertEqual(outcome["usage"]["model_calls"], 0)

    def test_stdio_uses_prefixed_provider_frames_and_returns_one_outcome(self):
        work = self.stage()
        request = json.dumps({
            "kind": "start", "job": {**self.job, "limits": {**self.job["limits"], "max_model_calls": 1}},
            "workspace": str(work),
        })
        stdin = io.BytesIO((request + '\n{"kind":"provider_result","error":"unavailable"}\n').encode())
        stdout, stderr = io.BytesIO(), io.StringIO()
        from contextlib import redirect_stderr
        with redirect_stderr(stderr):
            worker._serve(stdin, stdout)
        provider, outcome = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual((provider["kind"], provider["op"], provider["path"]), ("provider", "post", "/api/chat"))
        self.assertEqual(provider["payload"]["model"], "gemma4:e4b")
        self.assertEqual(outcome["kind"], "outcome")
        self.assertEqual(outcome["outcome"]["usage"]["model_calls"], 1)
        self.assertIsNone(outcome["outcome"]["evidence"])

    @staticmethod
    def unexpected_provider(*args, **kwargs):
        raise AssertionError(f"unexpected provider request: {args}")


if __name__ == "__main__":
    unittest.main()
