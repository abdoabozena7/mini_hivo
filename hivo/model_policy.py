"""Single-model policy.

The experiment intentionally measures one installed model.  Model selection,
role routing, and silent fallbacks would make the result impossible to
attribute, so every model-backed role is pinned here.
"""

from dataclasses import dataclass


GEMMA_MODEL = "gemma4:e4b"


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
        }

    def context_window(self, role: str) -> int:
        """Return conservative local context limits to avoid KV-cache OOMs."""
        role_key = role.strip().lower()
        if role_key in {"visual", "coordinator", "quality", "predictor", "challenger"}:
            return 4096
        if role_key in {"falsifier", "repairer"}:
            return 8192
        return 16384
