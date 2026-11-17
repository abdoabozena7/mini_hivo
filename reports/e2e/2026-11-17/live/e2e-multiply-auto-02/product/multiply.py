import sys

def main():
    """
    A command-line utility that accepts exactly two integer arguments
    and prints their product. Exits with a non-zero status if arguments are invalid or missing.
    """
    # Check if exactly two arguments are provided (sys.argv[0] is the script name)
    if len(sys.argv) != 3:
        print("Usage: python multiply.py <integer1> <integer2>", file=sys.stderr)
        sys.exit(1)

    args = sys.argv[1:]
    
    try:
        # Attempt to convert both arguments to integers
        num1 = int(args[0])
        num2 = int(args[1])
    except ValueError:
        print("Error: Both arguments must be valid integers.", file=sys.stderr)
        sys.exit(1)

    # Calculate and print the product
    product = num1 * num2
    print(product)

if __name__ == "__main__":
    main()