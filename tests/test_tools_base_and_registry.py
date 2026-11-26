"""Unit tests for base contracts, schemas, path safety, secret guards, and role profiles."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from hivo.tools import (
    ALL_TOOLS,
    CORE_TOOLS,
    ERR_PATH_SECURITY,
    ROLE_PROFILES,
    ToolContext,
    ToolProfile,
    build_profile_tools,
    create_tool_binding,
    err_result,
    execute_tool,
    line_hash,
    ok_result,
    serialize_envelope,
    serialize_openai_tools,
)
from hivo.tools.base import parse_anchor

ENVELOPE_KEYS = {"ok", "data", "error", "error_code", "hint", "truncated"}


def _assert_flat_schema(testcase: unittest.TestCase, schema: dict, tool_name: str) -> None:
    props = schema.get("properties", {})
    for key, prop in props.items():
        ptype = prop.get("type")
        testcase.assertIn(
            ptype,
            {"string", "integer", "boolean", "array"},
            msg=f"slm_safe tool '{tool_name}' param '{key}' must be flat primitive/array, got {ptype!r}",
        )
        if ptype == "array":
            items = prop.get("items", {})
            testcase.assertNotEqual(
                items.get("type"),
                "object",
                msg=f"slm_safe tool '{tool_name}' param '{key}' cannot have object items",
            )


class TestBaseAndRegistry(unittest.TestCase):
    def test_core_tool_count_and_envelope_shape(self) -> None:
        self.assertEqual(len(ALL_TOOLS), 15)
        self.assertEqual(len(CORE_TOOLS), 15)
        ok_env = ok_result({"a": 1})
        err_env = err_result("boom", hint="fix it")
        self.assertEqual(set(ok_env.keys()), ENVELOPE_KEYS)
        self.assertEqual(set(err_env.keys()), ENVELOPE_KEYS)
        self.assertTrue(ok_env["ok"])
        self.assertIsNone(ok_env["error"])
        self.assertIsNone(ok_env["error_code"])
        self.assertFalse(err_env["ok"])
        self.assertTrue(err_env["error_code"])
        self.assertIsInstance(err_env["hint"], str)
        self.assertTrue(err_env["hint"])
        self.assertEqual(serialize_envelope(ok_env), serialize_envelope(ok_env))

    def test_slm_safe_tools_have_flat_schemas_and_deterministic_serialization(self) -> None:
        for name, spec in CORE_TOOLS.items():
            if spec.model_tier == "slm_safe":
                _assert_flat_schema(self, spec.parameters, name)

        coder = build_profile_tools("coder_worker")
        first = serialize_openai_tools(coder)
        second = serialize_openai_tools(coder)
        self.assertEqual(first, second)

    def test_role_profiles_enforce_allowlists_and_least_privilege(self) -> None:
        self.assertEqual(set(ROLE_PROFILES), {"orchestrator", "coder_worker", "research_worker", "verifier"})

        coder = build_profile_tools("coder_worker")
        self.assertEqual([s.name for s in coder], ["read_file", "edit_file", "write_file", "code_intel"])
        self.assertTrue(all(s.model_tier == "slm_safe" for s in coder))

        coder_del = build_profile_tools("coder_worker", allow_delete=True)
        self.assertEqual(
            [s.name for s in coder_del],
            ["read_file", "edit_file", "write_file", "code_intel", "delete_file"],
        )

        research = build_profile_tools("research_worker")
        self.assertEqual([s.name for s in research], ["read_file", "list_files", "search_code", "code_intel"])
        self.assertTrue(all(s.effect == "read" for s in research))

        verifier = build_profile_tools("verifier")
        self.assertEqual([s.name for s in verifier], ["read_file", "code_intel", "run_command"])
        self.assertTrue(all(s.effect != "write" for s in verifier))

        orch = build_profile_tools("orchestrator")
        self.assertEqual(len(orch), 8)
        orch_cmd = build_profile_tools("orchestrator", include_run_command=True)
        self.assertEqual(len(orch_cmd), 9)

        with tempfile.TemporaryDirectory() as tmp:
            ctx = ToolContext(workspace_root=Path(tmp))
            res = execute_tool("run_command", {"command": "python --version"}, ctx, allowed_specs=coder)
            self.assertEqual(set(res.keys()), ENVELOPE_KEYS)
            self.assertFalse(res["ok"])
            self.assertIn("not enabled", res["error"])
            self.assertIn("read_file", res["hint"])

    def test_strict_argument_validation_across_all_tool_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ToolContext(workspace_root=Path(tmp))

            res_nondict = execute_tool("read_file", "not-a-dict", ctx)
            self.assertFalse(res_nondict["ok"])
            self.assertIn("JSON object", res_nondict["error"])

            res_missing = execute_tool("read_file", {}, ctx)
            self.assertFalse(res_missing["ok"])
            self.assertIn("path", res_missing["error"])

            res_extra = execute_tool("list_files", {"bogus": 123}, ctx)
            self.assertFalse(res_extra["ok"])
            self.assertIn("unexpected", res_extra["error"])

            res_bool = execute_tool("read_file", {"path": "a.py", "start_line": True}, ctx)
            self.assertFalse(res_bool["ok"])
            self.assertIn("integer", res_bool["error"])

            res_min = execute_tool("list_files", {"max_depth": 0}, ctx)
            self.assertFalse(res_min["ok"])
            self.assertIn(">=", res_min["error"])

            res_cmd = execute_tool("run_command", {"command": 42}, ctx)
            self.assertFalse(res_cmd["ok"])
            self.assertIn("string", res_cmd["error"])

            res_enum = execute_tool(
                "edit_file",
                {"path": "a.py", "operation": "append", "start_anchor": "1:aa", "content": "x"},
                ctx,
            )
            self.assertFalse(res_enum["ok"])
            self.assertIn("one of", res_enum["error"])

    def test_secret_file_blocking_and_example_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / ".env").write_text("SECRET_TOKEN=abc123\n", encoding="utf-8")
            (ws / ".env.prod").write_text("DB_PASS=xyz\n", encoding="utf-8")
            (ws / "key.pem").write_text("PRIVATE KEY\n", encoding="utf-8")
            (ws / ".env.example").write_text("SECRET_TOKEN=changeme\n", encoding="utf-8")
            (ws / "main.py").write_text("x = 1\n", encoding="utf-8")
            ctx = ToolContext(workspace_root=ws)

            for secret_name in (".env", ".env.prod", "key.pem"):
                r = execute_tool("read_file", {"path": secret_name}, ctx)
                self.assertFalse(r["ok"], msg=f"{secret_name} should be blocked")
                self.assertEqual(r["error_code"], ERR_PATH_SECURITY)

            r_ex = execute_tool("read_file", {"path": ".env.example"}, ctx)
            self.assertTrue(r_ex["ok"])
            self.assertIn("changeme", r_ex["data"]["content"])

            r_list = execute_tool("list_files", {}, ctx)
            self.assertNotIn(".env", [e for e in r_list["data"]["entries"] if e != ".env.example"])
            self.assertIn(".env.example", r_list["data"]["entries"])

            r_search = execute_tool("search_code", {"query": "SECRET_TOKEN"}, ctx)
            self.assertEqual(r_search["data"]["match_count"], 1)
            self.assertEqual(r_search["data"]["matches"][0]["path"], ".env.example")

    def test_workspace_confinement_and_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as outer:
            outer_path = Path(outer)
            ws = outer_path / "ws"
            ws.mkdir()
            secret = outer_path / "secret.txt"
            secret.write_text("TOP_SECRET", encoding="utf-8")

            ctx = ToolContext(workspace_root=ws)

            r1 = execute_tool("read_file", {"path": "../secret.txt"}, ctx)
            self.assertFalse(r1["ok"])
            self.assertEqual(r1["error_code"], ERR_PATH_SECURITY)
            self.assertNotIn("TOP_SECRET", str(r1))

            r2 = execute_tool("read_file", {"path": str(secret)}, ctx)
            self.assertFalse(r2["ok"])
            self.assertEqual(r2["error_code"], ERR_PATH_SECURITY)

            link_path = ws / "link_to_secret.txt"
            try:
                os.symlink(secret, link_path)
            except OSError as exc:
                self.skipTest(f"OS symlink creation unavailable without privileges: {exc}")

            r3 = execute_tool("read_file", {"path": "link_to_secret.txt"}, ctx)
            self.assertFalse(r3["ok"])
            self.assertEqual(r3["error_code"], ERR_PATH_SECURITY)

    def test_parse_anchor_forgiving_variants_and_strict_rejections(self) -> None:
        self.assertEqual(parse_anchor("42:a3"), (42, "a3"))
        self.assertEqual(parse_anchor("L42:A3"), (42, "a3"))
        self.assertEqual(parse_anchor(" l7:0f | def foo(): "), (7, "0f"))
        self.assertEqual(parse_anchor("12:cd|"), (12, "cd"))
        for bad in ("42:zz", "42:a", "42:abc", "abc:a3", "42:a3:extra", "-1:a3", "L 42:a3", ""):
            self.assertIsNone(parse_anchor(bad), msg=f"Should reject malformed anchor {bad!r}")

    def test_tool_binding_and_spawn_worker_fencing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "target.py").write_text("x = 1\n", encoding="utf-8")
            (ws / "other.py").write_text("y = 2\n", encoding="utf-8")

            dispatched_packets: list[dict] = []
            orch_ctx = ToolContext(
                workspace_root=ws,
                max_read_lines=400,
                plan_store=[],
                worker_dispatcher=lambda pkt: dispatched_packets.append(pkt) or {"status": "ok", "modified_files": []},
            )
            orch_binding = create_tool_binding("orchestrator", context=orch_ctx)
            self.assertEqual(len(orch_binding.schema_hash()), 64)

            env_disp, obs_disp = orch_binding.execute_call(
                "dispatch_worker",
                {"task": "Update x", "target_files": ["target.py"], "allow_delete": False},
            )
            self.assertTrue(env_disp["ok"])
            self.assertIn("<tool_observation", obs_disp)

            worker_profile = ToolProfile(
                primary_edit_tool="hashline",
                tool_protocol="grammar_json",
                max_active_tools=4,
            )
            worker_binding = orch_binding.spawn_worker_binding(
                dispatched_packets[0],
                worker_profile=worker_profile,
                max_read_lines=150,
            )
            self.assertEqual(worker_binding.role, "coder_worker")
            self.assertEqual(worker_binding.context.allowed_paths, ("target.py",))
            self.assertEqual(worker_binding.context.max_read_lines, 150)
            self.assertIsNone(worker_binding.context.plan_store)
            self.assertIsNone(worker_binding.context.worker_dispatcher)
            self.assertEqual(worker_binding.render_tools()["protocol"], "grammar_json")

            # Worker succeeds on allowed target via protocol response and fails outside fence
            res_ok = worker_binding.execute_response(
                f'{{"tool": "edit_file", "arguments": {{"path": "target.py", "operation": "replace", "start_anchor": "L1:{line_hash("x = 1")}| x = 1", "content": "x = 42"}}}}'
            )
            self.assertTrue(res_ok[0][1]["ok"])
            self.assertEqual((ws / "target.py").read_text(encoding="utf-8"), "x = 42\n")

            env_esc, _ = worker_binding.execute_call("read_file", {"path": "other.py"})
            self.assertFalse(env_esc["ok"])
            self.assertEqual(env_esc["error_code"], ERR_PATH_SECURITY)


if __name__ == "__main__":
    unittest.main()
