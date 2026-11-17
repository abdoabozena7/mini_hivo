import unittest
import sys
from greet import greet

class TestGreeting(unittest.TestCase):

    def test_default_greeting_cli(self):
        # Test case for running python greet.py without arguments
        # Expected output: "Hello, World!\n"
        # We capture stdout to check the printed output.
        # Since main() prints, we need to temporarily redirect stdout.
        # For simplicity in this test file, we will test the function call
        # that mimics the CLI behavior if possible, but the contract requires
        # testing the CLI execution.
        
        # To test the CLI behavior (print to stdout), we must run the script
        # via subprocess, which is better suited for unit testing the CLI entry point.
        # However, the contract also requires testing the exposed function `greet`.
        
        # Test the function call first (REQ-004/REQ-003 function test)
        self.assertEqual(greet(), "Hello, World!")

    def test_named_greeting_cli(self):
        # Test case for running python greet.py with an argument
        # Expected output: "Hello, Ada!\n"
        self.assertEqual(greet("Ada"), "Hello, Ada!")

    def test_cli_default_behavior(self):
        # Test the CLI behavior for no arguments (REQ-003)
        # We must execute the script itself to test the print behavior.
        # This test will run the script as if it were called from the shell.
        # We use subprocess to capture stdout.
        import subprocess
        
        # Capture stdout when running the script with no arguments
        result = subprocess.run([sys.executable, "greet.py"], capture_output=True, text=True)
        self.assertEqual(result.stdout, "Hello, World!\n")

    def test_cli_named_behavior(self):
        # Test the CLI behavior for one argument (REQ-002)
        # Capture stdout when running the script with "Ada"
        import subprocess
        result = subprocess.run([sys.executable, "greet.py", "Ada"], capture_output=True, text=True)
        self.assertEqual(result.stdout, "Hello, Ada!\n")

if __name__ == '__main__':
    unittest.main()