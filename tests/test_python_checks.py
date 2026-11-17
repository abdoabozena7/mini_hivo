import tempfile
import unittest
from pathlib import Path

from hivo.python_checks import check_source_assertion, source_assertions


class SourceAcceptanceTests(unittest.TestCase):
    def test_literal_cli_and_equal_return_contract_detect_a_punctuation_mismatch(self):
        requirements = [
            {"requirement_id": "REQ-A", "provenance": "USER_STATED",
             "text": "Running python caption.py Guest prints exactly Welcome, Guest! followed by a newline."},
            {"requirement_id": "REQ-B", "provenance": "USER_STATED",
             "text": "Running python caption.py without arguments prints exactly Welcome, All! followed by a newline."},
            {"requirement_id": "REQ-C", "provenance": "USER_STATED",
             "text": 'Expose a caption(name="All") function that returns the same greeting without a newline.'},
        ]
        cases = source_assertions(requirements)
        self.assertEqual(len(cases), 4)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "caption.py"
            path.write_text(
                'import sys\n'
                'def caption(name="All"):\n    return f"Welcome, {name}"\n'
                'if __name__ == "__main__":\n'
                '    print(f"Welcome, {sys.argv[1] if len(sys.argv)>1 else \'All\'}!")\n',
                encoding="utf-8",
            )
            observed = [check_source_assertion(directory, case)["passed"] for case in cases]
            self.assertEqual(observed, [True, True, False, False])
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    'return f"Welcome, {name}"', 'return f"Welcome, {name}!"',
                ), encoding="utf-8",
            )
            self.assertTrue(all(check_source_assertion(directory, case)["passed"] for case in cases))
        self.assertEqual(cases[2]["requirement_ids"], ["REQ-A", "REQ-C"])

    def test_unknown_or_ambiguous_expectations_are_never_invented(self):
        self.assertEqual(source_assertions([{
            "requirement_id": "REQ-1", "provenance": "DERIVED",
            "text": "Running python unknown.py prints exactly invented followed by a newline.",
        }]), [])
        with self.assertRaises(ValueError):
            source_assertions([{
                "requirement_id": "REQ-2", "provenance": "USER_STATED",
                "text": 'Expose a caption(name="All") function that returns the same output without a newline.',
            }])


if __name__ == "__main__":
    unittest.main()
