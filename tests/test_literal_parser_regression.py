"""Experiment 21: independent payload oracles and real file/authority checks."""
import hashlib
import json
import unittest
from unittest.mock import patch

import mini
import test_greenfield_impact_lifecycle as lifecycle


class LiteralParserTests(unittest.TestCase):
    def test_explicit_colon_payload_is_never_consumed_as_a_generic_token(self):
        cases = [
            ("exactly:Hello", "Hello"), ("exactly: Hello", "Hello"),
            ("exactly :Hello", "Hello"), ("exactly : Hello", "Hello"),
            ("exactly:Hello.", "Hello."), ("exactly:Hello!", "Hello!"),
            ("exactly:https://example.com/a:b", "https://example.com/a:b"),
            ("exactly:Hello Mini Hivo", "Hello Mini Hivo"),
            ('exactly:"Hello"', "Hello"), ("exactly:'Hello'", "Hello"),
            ("exactly:`Hello`", "Hello"), ('exactly:"  Hello  "', "  Hello  "),
            ('exactly:""', ""), ("exactly:مرحبا", "مرحبا"),
            ('exactly "exactly:Hello"', "exactly:Hello"),
            ("exactly welcome.", "welcome"), ('exactly the text "Hello Mini Hivo".', "Hello Mini Hivo"),
        ]
        for suffix, expected in cases:
            with self.subTest(suffix=suffix):
                self.assertEqual(mini.literal_file_request(
                    "Create a text file named note.txt containing " + suffix),
                    {"name": "note.txt", "content": expected, "kind": "text"})

    def test_malformed_explicit_payload_cannot_fall_back_to_generic_text(self):
        for suffix in ("exactly:", "exactly:   ", 'exactly:"Hello',
                       "exactly:Hello\nAlso change another file.",
                       "exactly:\nHello", "exactly:Hello\rWorld",
                       "exactly:Hello. Also change another file.",
                       "exactly:Hello and write another file."):
            with self.subTest(suffix=suffix):
                self.assertIsNone(mini.literal_file_request(
                    "Create a text file named note.txt containing " + suffix))


class LiteralParserFunctionalTests(unittest.TestCase):
    setUp = lifecycle.GreenfieldImpactLifecycleTests.setUp
    call = staticmethod(lifecycle.GreenfieldImpactLifecycleTests.call)
    execute = lifecycle.GreenfieldImpactLifecycleTests.execute

    def prepare(self, suffix, name="note.txt"):
        self.goal = f"Create a text file named {name} containing " + suffix
        self.contract = mini.get_goal_contract(self.goal, interactive=False)
        mini.RUN["source_contract"] = self.contract
        mini.ACTIVE_CONTRACT = mini.ACTIVE_TOOL_CONTRACT = self.contract
        self.task = mini.root_task_from_contract(self.contract)

    def replies(self, content):
        return [self.call("context_sufficiency_check", context_status="sufficient",
                          reason="The source explicitly names the single file and its exact bytes."),
                self.call("write_file", path="note.txt", content=content),
                self.call("run_file", path="note.txt"),
                {"role": "assistant", "content": "Readback completed.", "tool_calls": []}]

    def check_root(self, suffix, expected):
        self.prepare(suffix)
        candidate = mini._prepare_task_impact_contract(self.task, self.contract)
        digest = hashlib.sha256(expected.encode("utf-8")).hexdigest()
        self.assertEqual(candidate["authorized_mutation_paths"], ["note.txt"])
        self.assertEqual(candidate["expected_targets"][0]["post_state_sha256"], digest)
        replies = self.replies(expected) + [self.call("run_file", path="note.txt"),
            {"role": "assistant", "content": "Independent readback completed.", "tool_calls": []}]
        with patch.object(mini, "ask_ollama", side_effect=replies), \
                patch.object(mini.subprocess, "run", side_effect=AssertionError("No shell expected")):
            result, _ = mini.run_baseline_request(self.goal, {}, contract_override=self.contract,
                                                  repo_snapshot={"files": []}, finish=False)
        self.assertEqual(result["status"], "done", result)
        self.assertTrue(mini.RUN["root_verified"])
        self.assertEqual((self.root / "note.txt").read_bytes(), expected.encode("utf-8"))
        readbacks = [json.loads(e["result"]) for e in result["falsifier"]["tool_evidence"]
                     if e["tool"] == "run_file"]
        self.assertTrue(readbacks)
        self.assertEqual(readbacks[-1]["actual_sha256"], digest)
        self.assertTrue(readbacks[-1]["passed"])

    def test_compact_single_word_reaches_verified_root_with_exact_bytes(self):
        self.check_root("exactly:Hello", "Hello")

    def test_colon_payload_preserves_final_period_through_verification(self):
        self.check_root("exactly:Hello.", "Hello.")

    def test_explicit_empty_quoted_file_reaches_verified_root(self):
        self.check_root('exactly:""', "")

    def test_old_bug_payload_is_rejected_by_native_proof_and_post_state(self):
        self.prepare("exactly:Hello")
        result = self.execute(self.replies("exactly:Hello"))
        proof = next(json.loads(e["result"]) for e in result["tool_evidence"] if e["tool"] == "run_file")
        self.assertFalse(proof["passed"])
        self.assertEqual(proof["expected_sha256"], hashlib.sha256(b"Hello").hexdigest())
        self.assertFalse(mini._impact_post_mutation_check(result["impact_contract"],
                                                        verification_result={"passed": True})["passed"])

    def test_compact_syntax_does_not_authorize_workspace_escape(self):
        self.prepare("exactly:Hello", "../escape.txt")
        candidate = mini._prepare_task_impact_contract(self.task, self.contract)
        self.assertNotIn("../escape.txt", candidate.get("authorized_mutation_paths", []))


if __name__ == "__main__":
    unittest.main()
