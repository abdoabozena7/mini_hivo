"""Core policies for the Mini Hivo coding orchestrator.

The executable remains ``mini.py`` for backwards compatibility.  This package
contains policy and state-free components that can be tested without Ollama or
a browser.
"""

from .model_policy import GEMMA_MODEL, SingleModelPolicy
from .memory import MemoryStore
from .playbooks import build_execution_stages, classify_project
from .projects import ProjectStore
from .project_brain_refs import (
    ProjectBrainEntity, TypedReference, create_project_brain_entity,
    mark_reference_stale, normalize_legacy_brain_record,
)
from .repository_map import RepositoryMap, build_repository_map, incremental_reindex
from .reference_resolution import (
    EvidenceResolutionRequest, ProjectReferenceResolver, ResolvedEvidence,
)

__all__ = [
    "GEMMA_MODEL", "MemoryStore", "ProjectStore", "SingleModelPolicy",
    "build_execution_stages", "classify_project",
    "ProjectBrainEntity", "TypedReference", "RepositoryMap", "build_repository_map",
    "incremental_reindex", "EvidenceResolutionRequest", "ProjectReferenceResolver",
    "ResolvedEvidence", "create_project_brain_entity", "mark_reference_stale",
    "normalize_legacy_brain_record",
]
