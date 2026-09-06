"""CORE-4 ranking façade.

The canonical implementation lives in :mod:`hivo.fault_localization`; this
module keeps ranking-oriented imports discoverable without creating a second
ranking model.
"""

from .fault_localization import (
    FaultCandidate,
    FaultLocalizationResult,
    rerank_with_experimental_evidence,
    seed_hypotheses_from_localization,
)

__all__ = [
    "FaultCandidate", "FaultLocalizationResult",
    "rerank_with_experimental_evidence", "seed_hypotheses_from_localization",
]
