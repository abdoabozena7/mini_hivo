"""Role-conditioned and stagnation-adaptive decoding hyperparameters for Mini Hivo.

Grounded in:
- Nguyen et al. (ICLR 2025 Oral, Min-p Sampling, arXiv:2407.01082)
- Zhu et al. (AAAI 2024, Hot or Cold? Adaptive Temperature Sampling for Code Generation, arXiv:2309.02772)
- Zhang et al. (2024, EDT: Entropy-based Dynamic Temperature Sampling, arXiv:2403.14541)
- Renze & Guven (EMNLP 2024 Findings, arXiv:2402.05201)
"""

from __future__ import annotations

import math


DECODING_POLICIES = ("fixed", "adaptive")

PRIME_SEED_STRIDE = 7919
_MAX_SEED = 2147483647
_SEED_MODULUS = _MAX_SEED + 1

ANALYTICAL_ROLES = frozenset({
    "specifier",
    "clarifier",
    "planner",
    "impactplanner",
    "impact planner",
    "decomposer",
    "challenger",
    "impactchallenger",
    "impact challenger",
    "reviser",
    "impactplanreviser",
    "impact plan reviser",
    "falsifier",
    "quality review",
    "quality",
    "reviewer",
    "classifier",
    "integrator",
    "coordinator",
    "predictor",
    "missioncompiler",
    "mission compiler",
    "requirementextractor",
    "requirement extractor",
    "reconagent",
    "recon agent",
    "taskbraincompiler",
    "task brain compiler",
})

RECOVERY_ROLES = frozenset({"repairer"})


def validate_decoding_policy(policy: str) -> str:
    """Validate and normalize a decoding policy identifier."""
    if not isinstance(policy, str):
        raise ValueError(
            f"decoding policy must be one of {DECODING_POLICIES}, got {policy!r}"
        )
    normalized = policy.strip().lower()
    if normalized not in DECODING_POLICIES:
        raise ValueError(
            f"unknown decoding policy {policy!r}; expected one of {DECODING_POLICIES}"
        )
    return normalized


def normalize_decoding_role(role: str) -> str:
    """Normalize a controller role name for decoding tier classification."""
    if not isinstance(role, str):
        raise ValueError(f"role must be a string, got {role!r}")
    cleaned = role.replace("_", " ").replace("-", " ").strip().lower()
    return " ".join(cleaned.split())


def _coerce_temperature(value: int | float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite int or float, got {value!r}")
    return min(2.0, max(0.0, float(value)))


def _coerce_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int (not bool), got {value!r}")
    return int(value)


def _bounded_seed(raw_seed: int) -> int:
    seed = int(raw_seed)
    if -1 <= seed <= _MAX_SEED:
        return seed
    return seed % _SEED_MODULUS


def resolve_decoding_options(
    role: str,
    *,
    policy: str = "fixed",
    base_temperature: float = 0.1,
    temperature_override: float | None = None,
    structured: bool = False,
    epoch: int = 0,
    stagnant_count: int = 0,
    seed_base: int = 0,
) -> dict[str, int | float]:
    """Resolve Ollama decoding options for a role, retry epoch, and stagnation state."""
    validated_policy = validate_decoding_policy(policy)
    normalized_role = normalize_decoding_role(role)
    validated_base_temp = _coerce_temperature(base_temperature, "base_temperature")
    validated_override = (
        None
        if temperature_override is None
        else _coerce_temperature(temperature_override, "temperature_override")
    )
    is_structured = bool(structured)
    norm_epoch = max(0, _coerce_int(epoch, "epoch"))
    norm_stagnant = max(0, _coerce_int(stagnant_count, "stagnant_count"))
    norm_seed_base = _coerce_int(seed_base, "seed_base")

    if validated_policy == "fixed":
        return {
            "temperature": validated_base_temp if validated_override is None else validated_override,
            "seed": _bounded_seed(norm_seed_base),
        }

    steps = norm_epoch + norm_stagnant
    if is_structured or normalized_role in ANALYTICAL_ROLES:
        if norm_epoch >= 1 or norm_stagnant >= 1:
            temp = round(min(0.20, 0.05 + 0.05 * steps), 3)
            seed = _bounded_seed(norm_seed_base + PRIME_SEED_STRIDE * steps)
        else:
            temp = 0.05
            seed = _bounded_seed(norm_seed_base)
        options: dict[str, int | float] = {
            "temperature": temp,
            "min_p": 0.05,
            "top_p": 0.85,
            "repeat_penalty": 1.0,
            "repeat_last_n": 64,
            "seed": seed,
        }
    elif normalized_role in RECOVERY_ROLES or norm_epoch >= 1 or norm_stagnant >= 1:
        temp = round(min(0.48, 0.20 + 0.08 * norm_epoch + 0.08 * norm_stagnant), 3)
        min_p = round(min(0.16, 0.07 + 0.025 * steps), 3)
        if norm_stagnant >= 1:
            repeat_penalty = round(min(1.15, 1.06 + 0.03 * (norm_stagnant - 1)), 3)
            repeat_last_n = 192
        else:
            repeat_penalty = 1.0
            repeat_last_n = 64
        seed = _bounded_seed(norm_seed_base + PRIME_SEED_STRIDE * max(1, steps))
        options = {
            "temperature": temp,
            "min_p": min_p,
            "top_p": 0.94,
            "repeat_penalty": repeat_penalty,
            "repeat_last_n": repeat_last_n,
            "seed": seed,
        }
    else:
        options = {
            "temperature": 0.08,
            "min_p": 0.08,
            "top_p": 0.90,
            "repeat_penalty": 1.0,
            "repeat_last_n": 64,
            "seed": _bounded_seed(norm_seed_base),
        }

    if validated_override is not None:
        options["temperature"] = validated_override

    return options
