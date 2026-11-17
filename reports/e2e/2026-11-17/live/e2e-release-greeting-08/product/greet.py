import sys

def greet(name="World"):
    """Returns the greeting string without a trailing newline."""
    return f"Hello, {name}!"

def main():
    """Handles command-line execution for greeting."""
    name = sys.argv[1] if len(sys.argv) > 1 else "World"
    
    if name == "World" and len(sys.argv) == 1:
        # Case: python greet.py (no arguments) -> Hello, World!\n
        print("Hello, World!")
    else:
        # Case: python greet.py Ada -> Hello, Ada!\n
        print(f"Hello, {name}!")

if __name__ == "__main__":
    main()