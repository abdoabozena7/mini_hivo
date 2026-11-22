"""Single-model policy.

The experiment intentionally measures one installed model.  Model selection,
role routing, and silent fallbacks would make the result impossible to
attribute, so every model-backed role is pinned here.
"""

from collections.abc import Collection
from dataclasses import dataclass
import re


GEMMA_MODEL = "gemma4:e4b"
GENERATIVE_CAPABILITIES = frozenset({"completion", "chat"})

_MODEL_SEGMENT_RE = r"[A-Za-z0-9][A-Za-z0-9._-]*"
_VALID_OLLAMA_MODEL_RE = re.compile(
    rf"^(?:{_MODEL_SEGMENT_RE}/)?{_MODEL_SEGMENT_RE}(?::{_MODEL_SEGMENT_RE})?$"
)


def normalize_requested_model_name(
    requested: str | None,
    default: str = GEMMA_MODEL,
) -> str:
    """Normalize an Ollama model identifier and reject unsafe or malformed names."""
    if requested is not None and not isinstance(requested, str):
        raise ValueError("requested model name must be a string or None")
    if not isinstance(default, str):
        raise ValueError("default model name must be a string")

    candidate = default.strip() if requested is None or not requested.strip() else requested.strip()
    if not candidate:
        raise ValueError("model name must not be empty")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in candidate):
        raise ValueError(
            f"invalid model name {requested!r}: whitespace and control characters are not allowed"
        )
    if "://" in candidate:
        raise ValueError(
            f"invalid model name {requested!r}: URL schemes are not allowed"
        )
    if "\\" in candidate or ".." in candidate:
        raise ValueError(
            f"invalid model name {requested!r}: path separators and traversal segments are not allowed"
        )
    if not _VALID_OLLAMA_MODEL_RE.fullmatch(candidate):
        raise ValueError(
            f"invalid model name {requested!r}: expected 'model[:tag]' or 'namespace/model[:tag]'"
        )
    return candidate


def validate_generative_model_capabilities(
    model_name: str,
    capabilities: list[str] | tuple[str, ...] | set[str] | None,
) -> None:
    """Verify that non-empty Ollama capabilities include generative text/chat completion."""
    if capabilities is None:
        return
    if isinstance(capabilities, (str, bytes)) or not isinstance(capabilities, Collection):
        raise ValueError("capabilities must be a collection of strings or None")

    normalized = sorted({
        str(item).strip().lower()
        for item in capabilities
        if item is not None and str(item).strip()
    })
    if not normalized:
        return
    if GENERATIVE_CAPABILITIES.intersection(normalized):
        return

    raise ValueError(
        f"model {model_name!r} reports capabilities {normalized} without text/chat "
        f"'completion' support (e.g., encoder/classifier/embedding-only model) and "
        f"cannot run generative coding roles; choose a generative Ollama model such as "
        f"{GEMMA_MODEL!r}"
    )


@dataclass(frozen=True)
class SingleModelPolicy:
    model_name: str = GEMMA_MODEL

    def validate(self, requested: str | None = None) -> str:
        if requested and requested != self.model_name:
            raise ValueError(
                f"this experiment is pinned to {self.model_name}; "
                f"requested model {requested!r} is not allowed"
            )
        return self.model_name

    def role_models(self) -> dict[str, str]:
        return {
            "coordinator": self.model_name,
            "predictor": self.model_name,
            "builder": self.model_name,
            "challenger": self.model_name,
            "falsifier": self.model_name,
            "quality": self.model_name,
            "repairer": self.model_name,
            "visual": self.model_name,
            "specifier": self.model_name,
            "mission_compiler": self.model_name,
            "clarifier": self.model_name,
            "requirement_extractor": self.model_name,
            "recon_agent": self.model_name,
            "task_brain_compiler": self.model_name,
            "impact_planner": self.model_name,
            "impact_challenger": self.model_name,
            "impact_plan_reviser": self.model_name,
        }

    def context_window(self, role: str) -> int:
        """Return conservative local context limits to avoid KV-cache OOMs."""
        role_key = role.strip().lower()
        if role_key in {"visual", "coordinator", "quality", "predictor", "challenger",
                        "specifier", "missioncompiler", "mission_compiler", "clarifier",
                        "requirementextractor", "requirement_extractor", "reconagent",
                        "recon_agent", "taskbraincompiler", "task_brain_compiler",
                        "impactplanner", "impact_planner", "impactchallenger", "impact_challenger",
                        "impactplanreviser", "impact_plan_reviser"}:
            return 4096
        if role_key in {"falsifier", "repairer"}:
            return 8192
        if role_key == "builder":
            # Bounded stages keep real prompts well below this value. Reserving
            # 16K caused repeated CUDA worker initialization failures locally.
            return 12288
        return 8192

    def temperature(self, role: str) -> float:
        """Use reproducible low-variance sampling for weak-model coding loops."""
        role_key = role.strip().lower()
        if role_key in {"builder", "repairer"}:
            return 0.1
        if role_key == "visual":
            return 0.2
        return 0.0
