#!/usr/bin/env python
import sys

def main():
    """
    Accepts exactly two integer command-line arguments and prints their product.
    Exits with a non-zero status if arguments are invalid or missing.
    """
    args = sys.argv[1:]

    # Requirement: Accept exactly two integer command-line arguments
    if len(args) != 2:
        print("Error: This utility requires exactly two integer arguments.", file=sys.stderr)
        sys.exit(1)

    try:
        # Attempt to convert arguments to integers
        num1 = int(args[0])
        num2 = int(args[1])
    except ValueError:
        # Requirement: Invalid arguments must cause a nonzero exit status.
        print("Error: Both arguments must be valid integers.", file=sys.stderr)
        sys.exit(1)

    # Requirement: Print their product followed by a newline.
    product = num1 * num2
    print(product)

if __name__ == "__main__":
    main()