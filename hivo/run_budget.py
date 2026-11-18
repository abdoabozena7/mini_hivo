"""Shared admission limits for one controller run."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from threading import Lock
from typing import Literal


class RunBudgetExceeded(RuntimeError):
    """A call was not admitted; resource is model, tool, or elapsed."""

    def __init__(self, resource: Literal["model", "tool", "elapsed"]) -> None:
        self.resource = resource
        super().__init__(f"Run budget exhausted: {resource}")


def _call_limit(name: str, value: int | None) -> int | None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise ValueError(f"{name} must be a non-negative integer or None")
    return value


def _finite_seconds(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        seconds = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(seconds):
        raise ValueError(f"{name} must be a finite number")
    return seconds


class RunBudget:
    """Charge each admitted call before dispatch, including retries.

    Limits of None are unlimited. Elapsed time starts at construction; its
    deadline limits admission, not execution already in flight.
    """

    def __init__(
        self,
        *,
        max_model_calls: int | None = None,
        max_tool_calls: int | None = None,
        max_elapsed_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = {
            "model": _call_limit("max_model_calls", max_model_calls),
            "tool": _call_limit("max_tool_calls", max_tool_calls),
        }
        self._elapsed_limit = (
            None if max_elapsed_seconds is None else _finite_seconds("max_elapsed_seconds", max_elapsed_seconds)
        )
        if self._elapsed_limit is not None and self._elapsed_limit < 0:
            raise ValueError("max_elapsed_seconds must be non-negative")
        self._clock = clock
        self._started_at = self._last_sample = _finite_seconds("clock()", clock())
        self._clock_failed = False
        self._calls = {"model": 0, "tool": 0}
        self._lock = Lock()

    def _observe_clock(self) -> None:
        if self._clock_failed:
            return
        try:
            now = _finite_seconds("clock()", self._clock())
        except Exception:
            self._clock_failed = True
            return
        if now < self._last_sample or not math.isfinite(now - self._started_at):
            self._clock_failed = True
        else:
            self._last_sample = now

    def _remaining(self) -> float | None:
        limit = self._elapsed_limit
        if limit is None:
            return None
        # A rounded-down elapsed difference must not admit a call at the deadline.
        if self._clock_failed or self._last_sample >= self._started_at + limit:
            return 0.0
        return max(0.0, limit - (self._last_sample - self._started_at))

    def claim(self, resource: Literal["model", "tool"]) -> None:
        """Admit one call or raise before dispatch, without charging a denial."""
        if resource not in ("model", "tool"):
            raise ValueError("resource must be 'model' or 'tool'")
        with self._lock:
            if self._elapsed_limit is not None:
                self._observe_clock()
                if self._remaining() == 0:
                    raise RunBudgetExceeded("elapsed")
            limit = self._limits[resource]
            if limit is not None and self._calls[resource] >= limit:
                raise RunBudgetExceeded(resource)
            self._calls[resource] += 1

    def remaining_seconds(self) -> float | None:
        """Return the usable time left, or None without a time limit."""
        with self._lock:
            if self._elapsed_limit is not None:
                self._observe_clock()
            return self._remaining()

    def snapshot(self) -> dict[str, int | float | None]:
        """Return admitted call counts and limits without admitting any work."""
        with self._lock:
            self._observe_clock()
            return {
                "max_model_calls": self._limits["model"],
                "max_tool_calls": self._limits["tool"],
                "max_elapsed_seconds": self._elapsed_limit,
                "model_calls": self._calls["model"],
                "tool_calls": self._calls["tool"],
                "elapsed_seconds": self._last_sample - self._started_at,
                "remaining_seconds": self._remaining(),
            }
