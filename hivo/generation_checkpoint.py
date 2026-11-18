"""Deterministic resume checkpoints for verified CORE-6 generation work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .project_brain_refs import canonical_hash


CHECKPOINT_READY = "CHECKPOINT_READY"
CHECKPOINT_STALE = "CHECKPOINT_STALE"
CHECKPOINT_INVALID = "CHECKPOINT_INVALID"


@dataclass(frozen=True)
class GenerationCheckpoint:
    checkpoint_id: str
    blueprint_identity: str
    plan_identity: str
    completed_units: tuple[str, ...] = ()
    verified_contracts: tuple[str, ...] = ()
    subject_hash: str = ""
    repository_map_hash: str = ""
    lexical_index_identity: str = ""
    brain_working_identity: str = ""
    receipt_hashes: tuple[tuple[str, str], ...] = ()
    generation_lineage: tuple[str, ...] = ()
    status: str = CHECKPOINT_READY
    schema_version: str = "CORE-6-GENERATION-CHECKPOINT-V1"

    def __post_init__(self) -> None:
        if not str(self.checkpoint_id or "").strip():
            raise ValueError("checkpoint_id is required")
        if not str(self.blueprint_identity or "").strip() or not str(self.plan_identity or "").strip():
            raise ValueError("checkpoint must bind blueprint and plan")
        object.__setattr__(self, "checkpoint_id", str(self.checkpoint_id).strip())
        object.__setattr__(self, "completed_units", tuple(sorted(set(str(item) for item in self.completed_units))))
        object.__setattr__(self, "verified_contracts", tuple(sorted(set(str(item) for item in self.verified_contracts))))
        object.__setattr__(self, "receipt_hashes", tuple(sorted((str(k), str(v)) for k, v in self.receipt_hashes)))
        object.__setattr__(self, "generation_lineage", tuple(str(item) for item in self.generation_lineage))
        object.__setattr__(self, "status", str(self.status or CHECKPOINT_READY).upper())

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "checkpoint_id": self.checkpoint_id,
            "blueprint_identity": self.blueprint_identity,
            "plan_identity": self.plan_identity,
            "completed_units": list(self.completed_units),
            "verified_contracts": list(self.verified_contracts),
            "subject_hash": self.subject_hash,
            "repository_map_hash": self.repository_map_hash,
            "lexical_index_identity": self.lexical_index_identity,
            "brain_working_identity": self.brain_working_identity,
            "receipt_hashes": {key: value for key, value in self.receipt_hashes},
            "generation_lineage": list(self.generation_lineage),
            "status": self.status,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value

    @classmethod
    def from_value(cls, value: Any) -> "GenerationCheckpoint":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("checkpoint must be an object")
        receipts = value.get("receipt_hashes", {}) or {}
        if isinstance(receipts, Mapping):
            receipts = tuple(receipts.items())
        return cls(
            checkpoint_id=str(value.get("checkpoint_id", "")),
            blueprint_identity=str(value.get("blueprint_identity", "")),
            plan_identity=str(value.get("plan_identity", "")),
            completed_units=tuple(value.get("completed_units", ()) or ()),
            verified_contracts=tuple(value.get("verified_contracts", ()) or ()),
            subject_hash=str(value.get("subject_hash", "")),
            repository_map_hash=str(value.get("repository_map_hash", "")),
            lexical_index_identity=str(value.get("lexical_index_identity", "")),
            brain_working_identity=str(value.get("brain_working_identity", "")),
            receipt_hashes=tuple(receipts),
            generation_lineage=tuple(value.get("generation_lineage", ()) or ()),
            status=str(value.get("status", CHECKPOINT_READY)),
            schema_version=str(value.get("schema_version", "CORE-6-GENERATION-CHECKPOINT-V1")),
        )


def create_generation_checkpoint(
    *,
    checkpoint_id: str,
    blueprint_identity: str,
    plan_identity: str,
    completed_units: Iterable[str] = (),
    verified_contracts: Iterable[str] = (),
    subject_hash: str = "",
    repository_map_hash: str = "",
    lexical_index_identity: str = "",
    brain_working_identity: str = "",
    receipt_hashes: Mapping[str, str] | Iterable[tuple[str, str]] = (),
    generation_lineage: Iterable[str] = (),
) -> GenerationCheckpoint:
    receipts = tuple(receipt_hashes.items()) if isinstance(receipt_hashes, Mapping) else tuple(receipt_hashes)
    return GenerationCheckpoint(
        checkpoint_id=checkpoint_id,
        blueprint_identity=blueprint_identity,
        plan_identity=plan_identity,
        completed_units=tuple(completed_units),
        verified_contracts=tuple(verified_contracts),
        subject_hash=subject_hash,
        repository_map_hash=repository_map_hash,
        lexical_index_identity=lexical_index_identity,
        brain_working_identity=brain_working_identity,
        receipt_hashes=receipts,
        generation_lineage=tuple(generation_lineage),
    )


def validate_generation_checkpoint(
    checkpoint: GenerationCheckpoint | Mapping[str, Any],
    *,
    blueprint_identity: str,
    plan_identity: str,
    subject_hash: str | None = None,
    repository_map_hash: str | None = None,
    lexical_index_identity: str | None = None,
    receipt_hashes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    current = GenerationCheckpoint.from_value(checkpoint)
    reasons: list[str] = []
    if current.blueprint_identity != str(blueprint_identity):
        reasons.append("blueprint_identity_changed")
    if current.plan_identity != str(plan_identity):
        reasons.append("plan_identity_changed")
    if subject_hash is not None and current.subject_hash != str(subject_hash):
        reasons.append("subject_hash_changed")
    if repository_map_hash is not None and current.repository_map_hash != str(repository_map_hash):
        reasons.append("repository_map_changed")
    if lexical_index_identity is not None and current.lexical_index_identity != str(lexical_index_identity):
        reasons.append("lexical_index_changed")
    if receipt_hashes is not None:
        expected = dict(receipt_hashes)
        actual = dict(current.receipt_hashes)
        for unit_id in current.completed_units:
            if expected.get(unit_id) != actual.get(unit_id):
                reasons.append(f"receipt_changed:{unit_id}")
    valid = not reasons and current.status == CHECKPOINT_READY
    return {
        "valid": valid,
        "status": CHECKPOINT_READY if valid else CHECKPOINT_STALE,
        "reasons": tuple(reasons),
        "checkpoint": current.to_dict(),
        "checkpoint_hash": current.canonical_hash,
    }


def resume_completed_units(
    checkpoint: GenerationCheckpoint | Mapping[str, Any] | None,
    *,
    blueprint_identity: str,
    plan_identity: str,
    subject_hash: str | None = None,
    repository_map_hash: str | None = None,
    lexical_index_identity: str | None = None,
    receipt_hashes: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    if checkpoint is None:
        return ()
    result = validate_generation_checkpoint(
        checkpoint,
        blueprint_identity=blueprint_identity,
        plan_identity=plan_identity,
        subject_hash=subject_hash,
        repository_map_hash=repository_map_hash,
        lexical_index_identity=lexical_index_identity,
        receipt_hashes=receipt_hashes,
    )
    if not result["valid"]:
        raise ValueError(CHECKPOINT_STALE)
    return tuple(result["checkpoint"]["completed_units"])


__all__ = [
    "CHECKPOINT_READY", "CHECKPOINT_STALE", "CHECKPOINT_INVALID", "GenerationCheckpoint",
    "create_generation_checkpoint", "validate_generation_checkpoint", "resume_completed_units",
]
