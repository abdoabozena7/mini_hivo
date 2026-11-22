import argparse
import json
import sys
import metrics

def parse_values(value_str: str) -> list[float]:
    """Parses a comma-separated string of values into a list of floats."""
    if not value_str:
        return []

    values = []
    parts = value_str.split(',')
    for part in parts:
        part = part.strip()
        if part:
            try:
                values.append(float(part))
            except ValueError:
                # Re-raise as a specific error type or handle it to fail gracefully later
                raise ValueError(f"Invalid numeric value found: '{part}'")
    return values

def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Swarm Telemetry Analyzer. Summarizes latency metrics from comma-separated values.",
        epilog="Example: python cli.py --values 10.5,20.1,30.0"
    )
    parser.add_argument(
        '--values',
        type=str,
        required=True,
        help='Comma-separated list of floating-point latency values.'
    )

    args = parser.parse_args()

    try:
        # 1. Parse the input string
        values = parse_values(args.values)

        if not values:
            # This handles cases where --values is provided but is empty or only commas
            raise ValueError("Input values list cannot be empty.")

        # 2. Call the core logic
        result = metrics.summarize_latencies(values)

        # 3. Print canonical JSON to stdout
        print(json.dumps(result, sort_keys=True))
        sys.exit(0)

    except ValueError as e:
        # Catches both parsing errors and the specific ValueError from metrics.summarize_latencies
        error_message = f"Error processing input values: {e}"
        print(error_message, file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        # Catch any other unexpected errors
        error_message = f"An unexpected error occurred: {type(e).__name__}: {e}"
        print(error_message, file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
