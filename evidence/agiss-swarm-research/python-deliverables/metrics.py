import statistics
from typing import List, Dict

def summarize_latencies(values: List[float]) -> Dict[str, float]:
    """
    Calculates summary statistics for a list of latency values.

    Args:
        values: A list of floating-point latency values.

    Returns:
        A dictionary containing count, min, max, and mean of the values.

    Raises:
        ValueError: If the input list of values is empty.
    """
    if not values:
        raise ValueError("values must not be empty")

    count = len(values)
    min_val = min(values)
    max_val = max(values)
    mean_val = sum(values) / count

    return {
        "count": float(count),
        "min": min_val,
        "max": max_val,
        "mean": round(mean_val, 2)
    }
