"""Attempt-level accounting for counts reported by Ollama."""

_COUNT_FIELDS = ("prompt_eval_count", "eval_count")


def _empty_row():
    return {
        "attempts": 0,
        "prompt_eval_count": None,
        "eval_count": None,
        "missing_prompt_eval_count": 0,
        "missing_eval_count": 0,
    }


def record_provider_usage(totals: dict, role: str, payload: object) -> None:
    """Record one generation attempt, even if its response was not usable.

    Start with an empty dict. Both ``total`` and each entry in ``by_role``
    sum only reported counts. A sum is null until at least one valid count
    was reported; a nonzero missing counter means the sum is incomplete.
    Pass the raw decoded response body, or None when no body was available.
    """
    body = payload if isinstance(payload, dict) else {}
    total = totals.setdefault("total", _empty_row())
    by_role = totals.setdefault("by_role", {})
    role_usage = by_role.setdefault(role, _empty_row())
    total["attempts"] += 1
    role_usage["attempts"] += 1

    for field in _COUNT_FIELDS:
        count = body.get(field)
        if type(count) is int and count >= 0:  # JSON booleans are not counts.
            for row in (total, role_usage):
                previous = row[field]
                row[field] = count if previous is None else previous + count
        else:
            missing = f"missing_{field}"
            total[missing] += 1
            role_usage[missing] += 1
