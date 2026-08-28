import unittest


class EvidencePolicyTests(unittest.TestCase):
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
