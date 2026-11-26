"""Tool-layer profile configuration and schema-drift fingerprinting."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Sequence

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None

from .base import ToolSpec
from .edit_strategies import EDIT_STRATEGY_SPECS

ENGINE_VERSION = "0.5.0"

VALID_PROTOCOLS = ("native", "grammar_json", "xml_tags")
VALID_VERBOSITY = ("detailed", "compact")


@dataclass(frozen=True)
class ToolProfile:
    """Orthogonal per-model tool configuration loaded from YAML (zero model-name branches)."""

    # Tool-layer calibration knobs
    primary_edit_tool: str = "hashline"
    fallback_edit_tool: str | None = None
    tool_protocol: Literal["native", "grammar_json", "xml_tags"] = "native"
    max_active_tools: int = 6
    error_verbosity: Literal["detailed", "compact"] = "detailed"

    # Drift fingerprint fields
    model_id: str = "unknown"
    runtime_engine_version: str = ENGINE_VERSION
    tool_schema_hash: str = ""
    calibrated_at: str = ""

    def __post_init__(self) -> None:
        if self.primary_edit_tool not in EDIT_STRATEGY_SPECS:
            raise ValueError(
                f"Unknown primary_edit_tool {self.primary_edit_tool!r}; "
                f"expected one of {sorted(EDIT_STRATEGY_SPECS)}"
            )
        if self.fallback_edit_tool is not None and self.fallback_edit_tool not in EDIT_STRATEGY_SPECS:
            raise ValueError(
                f"Unknown fallback_edit_tool {self.fallback_edit_tool!r}; "
                f"expected one of {sorted(EDIT_STRATEGY_SPECS)} or None"
            )
        if self.tool_protocol not in VALID_PROTOCOLS:
            raise ValueError(f"tool_protocol must be one of {VALID_PROTOCOLS}, got {self.tool_protocol!r}")
        if self.max_active_tools < 1:
            raise ValueError("max_active_tools must be >= 1")
        if self.error_verbosity not in VALID_VERBOSITY:
            raise ValueError(f"error_verbosity must be one of {VALID_VERBOSITY}, got {self.error_verbosity!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_edit_tool": self.primary_edit_tool,
            "fallback_edit_tool": self.fallback_edit_tool,
            "tool_protocol": self.tool_protocol,
            "max_active_tools": self.max_active_tools,
            "error_verbosity": self.error_verbosity,
            "model_id": self.model_id,
            "runtime_engine_version": self.runtime_engine_version,
            "tool_schema_hash": self.tool_schema_hash,
            "calibrated_at": self.calibrated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolProfile:
        # Ignore unknown/legacy loop-level keys such as compaction_trigger_tokens or thinking_policy.
        return cls(
            primary_edit_tool=str(data.get("primary_edit_tool", "hashline")),
            fallback_edit_tool=(
                None if data.get("fallback_edit_tool") in (None, "", "null") else str(data.get("fallback_edit_tool"))
            ),
            tool_protocol=str(data.get("tool_protocol", "native")),  # type: ignore[arg-type]
            max_active_tools=int(data.get("max_active_tools", 6)),
            error_verbosity=str(data.get("error_verbosity", "detailed")),  # type: ignore[arg-type]
            model_id=str(data.get("model_id", "unknown")),
            runtime_engine_version=str(data.get("runtime_engine_version", ENGINE_VERSION)),
            tool_schema_hash=str(data.get("tool_schema_hash", "")),
            calibrated_at=str(data.get("calibrated_at", "")),
        )


ModelProfile = ToolProfile


def compute_tool_schema_hash(specs: Sequence[ToolSpec]) -> str:
    """Compute a deterministic SHA-256 hash over active tool definitions."""
    exported = [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in specs
    ]
    serialized = json.dumps(exported, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def stamp_profile_fingerprint(
    profile: ToolProfile,
    specs: Sequence[ToolSpec],
    *,
    model_id: str | None = None,
    runtime_engine_version: str | None = None,
    calibrated_at: str | None = None,
) -> ToolProfile:
    """Return a copy of ``profile`` stamped with current fingerprint metadata."""
    return replace(
        profile,
        model_id=model_id if model_id is not None else profile.model_id,
        runtime_engine_version=(
            runtime_engine_version
            if runtime_engine_version is not None
            else profile.runtime_engine_version
        ),
        tool_schema_hash=compute_tool_schema_hash(specs),
        calibrated_at=calibrated_at or datetime.now(timezone.utc).isoformat(),
    )


def check_profile_drift(
    profile: ToolProfile,
    *,
    active_specs: Sequence[ToolSpec],
    current_model_id: str | None = None,
    current_engine_version: str | None = None,
) -> list[str]:
    """Return deterministic warnings when runtime config drifts from saved profile fingerprint."""
    warnings: list[str] = []
    current_hash = compute_tool_schema_hash(active_specs)
    if profile.tool_schema_hash and profile.tool_schema_hash != current_hash:
        warnings.append(
            f"tool_schema_hash drifted: profile={profile.tool_schema_hash[:12]} != active={current_hash[:12]}"
        )
    if current_model_id is not None and profile.model_id and profile.model_id != current_model_id:
        warnings.append(f"model_id drifted: profile={profile.model_id!r} != current={current_model_id!r}")
    if (
        current_engine_version is not None
        and profile.runtime_engine_version
        and profile.runtime_engine_version != current_engine_version
    ):
        warnings.append(
            f"runtime_engine_version drifted: profile={profile.runtime_engine_version!r} != current={current_engine_version!r}"
        )
    return warnings


def save_tool_profile(profile: ToolProfile, path: str | Path) -> None:
    """Persist a ``ToolProfile`` to YAML."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = profile.to_dict()
    if yaml is not None:
        text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    else:  # pragma: no cover
        text = json.dumps(payload, indent=2, ensure_ascii=False)
    target.write_text(text, encoding="utf-8")


def load_tool_profile(path: str | Path) -> ToolProfile:
    """Load and validate a ``ToolProfile`` from YAML."""
    raw_text = Path(path).read_text(encoding="utf-8")
    if yaml is not None:
        loaded = yaml.safe_load(raw_text) or {}
    else:  # pragma: no cover
        loaded = json.loads(raw_text)
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in {path}, got {type(loaded).__name__}")
    return ToolProfile.from_dict(loaded)


save_model_profile = save_tool_profile
load_model_profile = load_tool_profile
