import unittest


class EvidencePolicyTests(unittest.TestCase):
    def test_mutation_failure_record_classifies_deterministic_categories(self):
        from hivo.evidence import mutation_failure_record

        cases = [
            ("error: malformed edit request", "INVALID_MUTATION"),
            ("error: JavaScript syntax validation failed: Unexpected token '}'", "SYNTAX_INVALID_MUTATION"),
            ("error: path is outside the workspace", "SAFETY_REJECTED_MUTATION"),
            ("error: expected 1 exact replacement(s), found 0; file was not changed", "STALE_TARGET"),
            ("error: file does not exist: app.js", "MISSING_TARGET"),
            ("error writing file: permission denied", "ENVIRONMENT_FAILURE"),
        ]
        for result, expected in cases:
            with self.subTest(expected=expected):
                record = mutation_failure_record("edit_file", "app.js", result, role="Builder")
                self.assertIsNotNone(record)
                self.assertEqual(record["kind"], "mutation_failure")
                self.assertEqual(record["category"], expected)
                self.assertTrue(record["deterministic"])
                self.assertEqual(record["count"], 1)

    def test_mutation_failure_record_only_accepts_failed_mutation_tools(self):
        from hivo.evidence import mutation_failure_record

        self.assertIsNone(mutation_failure_record("edit_file", "app.js", "edited app.js"))
        self.assertIsNone(mutation_failure_record("run_command", "pytest", "error: malformed command"))

    def test_not_applicable_runtime_probe_is_neither_success_nor_failure_evidence(self):
        from hivo.evidence import latest_verification_evidence, unresolved_tool_failures

        evidence = [{
            "tool": "run_file", "target": "script.js",
            "result": "[not_applicable] browser-target JavaScript must run in a browser",
        }]

        self.assertEqual(latest_verification_evidence(evidence), [])
        self.assertEqual(unresolved_tool_failures(evidence), [])

    def test_compact_json_false_result_is_a_failure(self):
        from hivo.evidence import result_failed

        self.assertTrue(result_failed('{"passed":false,"failures":[]}'))

    def test_concrete_nonzero_test_count_is_a_failure(self):
        from hivo.evidence import result_failed

        self.assertTrue(result_failed("pytest -> 1 failed"))
        self.assertFalse(result_failed("pytest -> 0 failed"))

    def test_refused_verifier_command_is_not_an_application_failure(self):
        from hivo.evidence import unresolved_tool_failures

        evidence = [{
            "tool": "run_command", "target": "touch app.py",
            "result": "error: command refused: executable 'touch' is not in the verification allowlist",
        }]
        self.assertEqual(unresolved_tool_failures(evidence), [])

    def test_a_later_success_resolves_an_earlier_verification_failure(self):
        from hivo.evidence import unresolved_tool_failures

        evidence = [
            {"tool": "verify_web_app", "target": "index.html", "result": '{"passed": false}'},
            {"tool": "edit_file", "target": "index.html", "result": "error: exact text not found"},
            {"tool": "verify_web_app", "target": "index.html", "result": '{"passed": true}'},
        ]
        self.assertEqual(unresolved_tool_failures(evidence), [])

    def test_latest_failed_verification_remains_unresolved(self):
        from hivo.evidence import unresolved_tool_failures

        evidence = [{"tool": "verify_web_app", "target": "index.html", "result": '{"passed": false}'}]
        self.assertEqual(len(unresolved_tool_failures(evidence)), 1)

    def test_review_projection_omits_resolved_and_non_mutating_edit_errors(self):
        from hivo.evidence import evidence_for_review

        evidence = [
            {"tool": "verify_web_app", "target": "index.html", "result": '{"passed": false}'},
            {"tool": "edit_file", "target": "index.html", "result": "error: exact text not found"},
            {"tool": "verify_web_app", "target": "index.html", "result": '{"passed": true}'},
        ]
        self.assertEqual(evidence_for_review(evidence), [evidence[-1]])


if __name__ == "__main__":
    unittest.main()
