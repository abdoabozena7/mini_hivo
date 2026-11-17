import unittest
from greet import greet

class TestGreeting(unittest.TestCase):

    def test_default_greeting(self):
        # Test the function returning the default greeting without a newline
        self.assertEqual(greet(), "Hello, World")

    def test_named_greeting(self):
        # Test the function returning a specific named greeting without a newline
        self.assertEqual(greet("Ada"), "Hello, Ada")

    def test_cli_default(self):
        # Test CLI behavior when no arguments are provided (should print "Hello, World!\n")
        # We capture stdout to test the print output.
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            # Simulate running python greet.py
            # We need to mock sys.argv for this test to be self-contained, 
            # but since we are using unittest, we rely on the test runner setup.
            # For now, we will test the function and assume the CLI test will be run separately 
            # or we need to adjust the test structure.
            # Given the constraints, let's focus on testing the exposed function first, 
            # and then test the CLI execution separately if possible.
            
            # Since the requirement is to test the CLI execution, we must test the main() function's side effects.
            # We will test the CLI behavior by temporarily modifying sys.argv.
            
            # Test case: No arguments (sys.argv length == 1)
            import sys
            original_argv = sys.argv
            sys.argv = [original_argv[0]] # Only script name
            
            # We need to call main() which prints.
            try:
                from greet import main
                main()
            finally:
                sys.argv = original_argv # Restore original sys.argv

        output = f.getvalue()
        self.assertEqual(output, "Hello, World!\n")

    def test_cli_with_ada(self):
        # Test CLI behavior when argument is "Ada" (sys.argv length == 2 and arg == "Ada")
        import io
        from contextlib import redirect_stdout
        import sys
        
        original_argv = sys.argv
        try:
            # Simulate running python greet.py Ada
            sys.argv = [original_argv[0], "Ada"]
            
            f = io.StringIO()
            with redirect_stdout(f):
                from greet import main
                main()
            
            output = f.getvalue()
            self.assertEqual(output, "Hello, Ada!\n")
        finally:
            sys.argv = original_argv # Restore original sys.argv

    def test_cli_with_other_argument(self):
        # Test general argument passing (e.g., python greet.py Bob)
        import io
        from contextlib import redirect_stdout
        import sys
        
        original_argv = sys.argv
        try:
            # Simulate running python greet.py Bob
            sys.argv = [original_argv[0], "Bob"]
            
            f = io.StringIO()
            with redirect_stdout(f):
                from greet import main
                main()
            
            output = f.getvalue()
            self.assertEqual(output, "Hello, Bob!\n")
        finally:
            sys.argv = original_argv # Restore original sys.argv

if __name__ == '__main__':
    unittest.main()