"""Model pinning and role-routing policies.

Experiments intentionally pin explicit installed models with zero silent
fallbacks so outcomes remain strictly attributable:
- ``SingleModelPolicy`` pins one model across all 17 roles.
- ``AsymmetricModelPolicy`` pins an analytical ``orchestrator_model`` across all
  15 planning/verification roles and a dedicated ``worker_model`` exclusively to
  ``builder`` and ``repairer`` (preserving the Zero Orchestrator Code-Writing
  Invariant).
"""

from collections.abc import Collection
from dataclasses import dataclass
import re


GEMMA_MODEL = "gemma4:e4b"
GENERATIVE_CAPABILITIES = frozenset({"completion", "chat"})
WORKER_ROLES = frozenset({"builder", "repairer"})
ORCHESTRATOR_ROLES = frozenset({
    "coordinator",
    "predictor",
    "challenger",
    "falsifier",
    "quality",
    "visual",
    "specifier",
    "mission_compiler",
    "clarifier",
    "requirement_extractor",
    "recon_agent",
    "task_brain_compiler",
    "impact_planner",
    "impact_challenger",
    "impact_plan_reviser",
})
_ROLE_ORDER: tuple[str, ...] = (
    "coordinator",
    "predictor",
    "builder",
    "challenger",
    "falsifier",
    "quality",
    "repairer",
    "visual",
    "specifier",
    "mission_compiler",
    "clarifier",
    "requirement_extractor",
    "recon_agent",
    "task_brain_compiler",
    "impact_planner",
    "impact_challenger",
    "impact_plan_reviser",
)

_MODEL_SEGMENT_RE = r"[A-Za-z0-9][A-Za-z0-9._-]*"
_VALID_OLLAMA_MODEL_RE = re.compile(
    rf"^(?:{_MODEL_SEGMENT_RE}/)?{_MODEL_SEGMENT_RE}(?::{_MODEL_SEGMENT_RE})?$"
)
_ULTRA_COMPACT_PARAM_RE = re.compile(
    r"(?:^|[:/_-]|(?<=:)e)(?P<billions>\d+(?:\.\d+)?)b(?:$|[^A-Za-z0-9])",
    re.IGNORECASE,
)


def is_worker_role(role: str) -> bool:
    """Return True iff normalized role is an execution worker ('builder' or 'repairer')."""
    if not isinstance(role, str):
        return False
    return role.strip().lower() in WORKER_ROLES


def is_ultra_compact_model(model_name: str) -> bool:
    """Return True when model_name encodes an explicit <=3.5B parameter size."""
    return _is_ultra_compact_model(model_name)


def _is_ultra_compact_model(model_name: str) -> bool:
    """Return True when model_name encodes an explicit <=3.5B parameter size."""
    if not isinstance(model_name, str) or not model_name:
        return False
    matches = [
        float(match.group("billions"))
        for match in _ULTRA_COMPACT_PARAM_RE.finditer(model_name)
    ]
    if not matches:
        return False
    return 0.0 < matches[-1] <= 3.5


def _base_context_window(role: str) -> int:
    role_key = role.strip().lower()
    if role_key in {
        "visual", "coordinator", "quality", "predictor", "challenger",
        "specifier", "missioncompiler", "mission_compiler", "clarifier",
        "requirementextractor", "requirement_extractor", "reconagent",
        "recon_agent", "taskbraincompiler", "task_brain_compiler",
        "impactplanner", "impact_planner", "impactchallenger", "impact_challenger",
        "impactplanreviser", "impact_plan_reviser",
    }:
        return 4096
    if role_key in {"falsifier", "repairer"}:
        return 8192
    if role_key == "builder":
        # Bounded stages keep real prompts well below this value. Reserving
        # 16K caused repeated CUDA worker initialization failures locally.
        return 12288
    return 8192


def _role_temperature(role: str) -> float:
    role_key = role.strip().lower()
    if role_key in {"builder", "repairer"}:
        return 0.1
    if role_key == "visual":
        return 0.2
    return 0.0


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

    @property
    def orchestrator_model(self) -> str:
        return self.model_name

    @property
    def worker_model(self) -> str:
        return self.model_name

    @property
    def is_asymmetric(self) -> bool:
        return False

    def distinct_models(self) -> tuple[str, ...]:
        return (self.model_name,)

    def model_for_role(self, role: str) -> str:
        return self.model_name

    def validate(self, requested: str | None = None) -> str:
        if requested and requested != self.model_name:
            raise ValueError(
                f"this experiment is pinned to {self.model_name}; "
                f"requested model {requested!r} is not allowed"
            )
        return self.model_name

    def role_models(self) -> dict[str, str]:
        return {role: self.model_name for role in _ROLE_ORDER}

    def context_window(self, role: str) -> int:
        """Return conservative local context limits to avoid KV-cache OOMs."""
        return _base_context_window(role)

    def temperature(self, role: str) -> float:
        """Use reproducible low-variance sampling for weak-model coding loops."""
        return _role_temperature(role)


@dataclass(frozen=True)
class AsymmetricModelPolicy:
    orchestrator_model: str = GEMMA_MODEL
    worker_model: str = GEMMA_MODEL

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "orchestrator_model",
            normalize_requested_model_name(self.orchestrator_model),
        )
        object.__setattr__(
            self,
            "worker_model",
            normalize_requested_model_name(self.worker_model),
        )

    @property
    def model_name(self) -> str:
        return self.worker_model

    @property
    def is_asymmetric(self) -> bool:
        return self.orchestrator_model != self.worker_model

    def distinct_models(self) -> tuple[str, ...]:
        if self.orchestrator_model == self.worker_model:
            return (self.orchestrator_model,)
        return (self.orchestrator_model, self.worker_model)

    def model_for_role(self, role: str) -> str:
        if is_worker_role(role):
            return self.worker_model
        return self.orchestrator_model

    def validate(self, requested: str | None = None) -> str:
        if not requested:
            return self.worker_model
        if requested in {self.orchestrator_model, self.worker_model}:
            return requested
        raise ValueError(
            f"this experiment pins orchestrator={self.orchestrator_model} and "
            f"worker={self.worker_model}; requested model {requested!r} is not allowed"
        )

    def role_models(self) -> dict[str, str]:
        return {role: self.model_for_role(role) for role in _ROLE_ORDER}

    def context_window(self, role: str) -> int:
        """Return conservative local context limits, capping <=3.5B builders to 8192."""
        role_key = role.strip().lower()
        if role_key == "builder" and _is_ultra_compact_model(self.model_for_role(role)):
            return 8192
        return _base_context_window(role)

    def temperature(self, role: str) -> float:
        """Use reproducible low-variance sampling for weak-model coding loops."""
        return _role_temperature(role)
