"""Offline safety tests for the optional local coding probe; no provider calls."""
import unittest
from scripts.local_worker_diagnostic import validate_source
from hivo.providers import ProviderFailure


class LocalWorkerDiagnosticTests(unittest.TestCase):
    def test_exact_pure_function_passes_real_execution_oracle(self):
        source = 'def increment(value):\n    return value + 1\n'
        self.assertEqual(validate_source(source), source)

    def test_incorrect_and_executable_extra_code_are_rejected(self):
        for source in ['def increment(value):\n    return value\n',
                       'import os\ndef increment(value):\n    return value + 1\n',
                       '@print\ndef increment(value):\n    return value + 1\n',
                       'def increment(value):\n    return value + 1\nprint(1)',
                       'def increment(value):\n    return value + 1\n\x00']:
            with self.subTest(source=source):
                with self.assertRaises(ProviderFailure):
                    validate_source(source)


if __name__ == '__main__':
    unittest.main()
