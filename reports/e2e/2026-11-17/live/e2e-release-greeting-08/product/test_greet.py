import unittest
from greet import greet

class TestGreeting(unittest.TestCase):

    def test_default_greeting_function(self):
        # Test the exposed function with default name
        expected = "Hello, World!"
        self.assertEqual(greet(), expected)

    def test_named_greeting_function(self):
        # Test the exposed function with a specific name
        expected = "Hello, Ada!"
        self.assertEqual(greet("Ada"), expected)

class TestCommandLine(unittest.TestCase):
    
    def test_default_cli_greeting(self):
        # Test running python greet.py with no arguments
        # Expected output: Hello, World!\n
        import subprocess
        result = subprocess.run(
            ["python", "greet.py"], 
            capture_output=True, 
            text=True, 
            check=True
        )
        self.assertEqual(result.stdout, "Hello, World!\n")

    def test_named_cli_greeting(self):
        # Test running python greet.py with an argument
        # Expected output: Hello, Ada!\n
        import subprocess
        result = subprocess.run(
            ["python", "greet.py", "Ada"], 
            capture_output=True, 
            text=True, 
            check=True
        )
        self.assertEqual(result.stdout, "Hello, Ada!\n")

if __name__ == '__main__':
    unittest.main()