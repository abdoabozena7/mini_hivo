import sys

def greet(name="World"):
    """Returns a greeting string for the given name without a trailing newline."""
    return f"Hello, {name}!"

def main():
    """
    Main function to handle command-line arguments for greeting.
    Prints the greeting to stdout with a trailing newline.
    """
    if len(sys.argv) > 1:
        name = sys.argv[1]
    else:
        name = "World"
    
    # Print the greeting followed by a newline, as required by the contract.
    print(f"Hello, {name}!")

if __name__ == "__main__":
    main()