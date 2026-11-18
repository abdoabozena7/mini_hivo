"""Bounded conversation projection for local model calls."""

from copy import deepcopy
import hashlib
import json


def _content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:12]


def _compact_marker(content: str) -> str:
    digest = _content_digest(content)
    return (
        f"[HIVO HISTORY OMITTED: non-source metadata only; chars={len(content)}; sha256={digest}; "
        "re-read the current file; never copy this marker into code]"
    )


def projected_size(messages: list[dict]) -> int:
    """Approximate provider payload characters, including tool arguments."""
    total = 0
    for item in messages:
        total += len(str(item.get("content", "")))
        total += len(json.dumps(item.get("tool_calls", []), ensure_ascii=False, default=str))
    return total


def _compact_argument_payload(value, threshold: int = 700):
    if isinstance(value, str):
        # Keep the historical tool schema valid without placing a copyable
        # pseudo-source marker where a weak model expects real file content.
        # Current bytes live in the workspace and must be recovered by read_file.
        return "" if len(value) > threshold else value
    if isinstance(value, dict):
        return {key: _compact_argument_payload(item, threshold) for key, item in value.items()}
    if isinstance(value, list):
        return [_compact_argument_payload(item, threshold) for item in value]
    return value


def _compact_tool_arguments(message: dict) -> None:
    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        return
    for call in calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (ValueError, TypeError):
                if len(arguments) > 700:
                    function["arguments"] = {}
                continue
        function["arguments"] = _compact_argument_payload(arguments)


def compact_messages(messages: list[dict], max_chars: int, keep_recent: int = 8) -> list[dict]:
    """Return a provider-safe copy without mutating the agent's source history."""
    projected = deepcopy(messages)

    def size() -> int:
        return projected_size(projected)

    # Do not rewrite a healthy prompt merely because it contains a recent file
    # mutation. Gemma needs its own immediately preceding payload to avoid
    # inventing or copying compaction placeholders. Only compact on real overflow,
    # starting outside the protected recent window.
    cutoff = max(1, len(projected) - keep_recent)
    if size() > max_chars:
        for index in range(1, cutoff):
            _compact_tool_arguments(projected[index])
            if size() <= max_chars:
                break

    for index in range(1, cutoff):
        if size() <= max_chars:
            break
        content = projected[index].get("content")
        if isinstance(content, str) and len(content) > 300:
            projected[index]["content"] = _compact_marker(content)

    if size() > max_chars:
        for index in range(1, max(1, len(projected) - 1)):
            if size() <= max_chars:
                break
            content = projected[index].get("content")
            if isinstance(content, str) and len(content) > 120:
                projected[index]["content"] = _compact_marker(content)

    # If old history was not enough, remove large argument bodies from oldest
    # to newest. Empty string fields are valid historical arguments and cannot
    # masquerade as source code. Paths and tool outcomes remain available.
    if size() > max_chars:
        for item in projected[1:]:
            _compact_tool_arguments(item)
            if size() <= max_chars:
                break

    # A very large latest tool result is still bounded so output tokens remain
    # available to the model. Keep both ends because code declarations and
    # closing syntax commonly live at opposite ends of a file.
    if size() > max_chars and projected:
        last = projected[-1]
        content = last.get("content")
        if isinstance(content, str) and len(content) > 300:
            overflow = size() - max_chars
            target = max(200, len(content) - overflow - 80)
            head = max(100, target * 2 // 3)
            tail = max(80, target - head)
            last["content"] = content[:head] + "\n...\n" + content[-tail:]

    # Tool schemas and message metadata add provider overhead, so never return a
    # projection whose measured payload is above the explicit message budget.
    if size() > max_chars:
        for item in projected[1:]:
            content = item.get("content")
            if size() <= max_chars:
                break
            if isinstance(content, str) and len(content) > 120:
                item["content"] = _compact_marker(content)
    return projected
