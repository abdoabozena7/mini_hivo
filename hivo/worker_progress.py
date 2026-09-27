"""Deterministic progress accounting for one approved initial Worker attempt."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


READ_TOOLS = frozenset({"read_file", "read_file_range", "read_candidate_span", "list_files"})
MUTATION_TOOLS = frozenset({"write_file", "edit_file", "edit_file_range"})
NO_PROGRESS_LIMIT = 3


def _fingerprint(value):
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()


@dataclass
class WorkerProgress:
    task_id: str
    approved_targets: tuple[str, ...]
    approved_inspection_paths: tuple[str, ...] = ()
    policy: str = "current"
    gate_ready: bool = False
    tool_steps: int = 0
    pre_mutation_read_steps: int = 0
    unique_evidence: int = 0
    repeated_inspections: int = 0
    repeated_gate_checks: int = 0
    same_file_revisits_without_new_info: int = 0
    invalid_rejected_tool_calls: int = 0
    no_progress_streak: int = 0
    first_legal_mutation: dict | None = None
    inspected: set[tuple[str, str]] = field(default_factory=set)
    full_file_reads: set[str] = field(default_factory=set)
    events: list[dict] = field(default_factory=list)

    def _relevant_target(self, target):
        paths = self.approved_targets + self.approved_inspection_paths
        return any(target == path or target.endswith("/" + path) for path in paths)

    def observe(self, *, name, target, result, successful, gate_ready,
                changed_file=False, model_round=0, remaining_budget=0):
        """Record an actual tool outcome; only new contract-relevant facts advance progress."""
        self.tool_steps += 1
        target = str(target or "-").replace("\\", "/").casefold()
        was_ready = self.gate_ready
        self.gate_ready = bool(gate_ready)
        before_mutation = self.first_legal_mutation is None
        novelty = None
        progress = False
        if name == "context_sufficiency_check" and was_ready:
            self.repeated_gate_checks += 1
        if not successful:
            self.invalid_rejected_tool_calls += 1
            novelty = "rejected"
        elif name in MUTATION_TOOLS and changed_file:
            if before_mutation:
                self.first_legal_mutation = {
                    "tool_step": self.tool_steps,
                    "model_round": model_round,
                    "remaining_budget": remaining_budget,
                    "tool": name,
                    "target": target,
                }
            novelty = "legal_mutation"
            progress = True
        elif name == "context_sufficiency_check":
            progress = self.gate_ready and not was_ready
            novelty = "gate_ready" if progress else "repeated_gate"
        elif name in READ_TOOLS and before_mutation:
            self.pre_mutation_read_steps += 1
            if name == "list_files":
                novelty = "known_contract_targets" if self.approved_targets else "repository_listing"
                progress = not self.approved_targets and (name, _fingerprint(result)) not in self.inspected
                self.inspected.add((name, _fingerprint(result)))
            else:
                signature = (target, _fingerprint(result))
                progress = (
                    self._relevant_target(target)
                    and target not in self.full_file_reads
                    and signature not in self.inspected
                )
                self.inspected.add(signature)
                if name == "read_file":
                    self.full_file_reads.add(target)
                if progress:
                    self.unique_evidence += 1
                    novelty = "new_file_evidence"
                else:
                    self.repeated_inspections += 1
                    self.same_file_revisits_without_new_info += 1
                    novelty = "repeated_file_evidence"
        else:
            novelty = "no_new_target_evidence"
        if before_mutation and self.gate_ready:
            self.no_progress_streak = 0 if progress else self.no_progress_streak + 1
        event = {
            "tool_step": self.tool_steps,
            "model_round": model_round,
            "tool": name,
            "target": target,
            "novelty": novelty,
            "gate_ready": self.gate_ready,
            "no_progress_streak": self.no_progress_streak,
            "remaining_budget": remaining_budget,
        }
        self.events.append(event)
        return event

    def should_stop(self):
        return (
            self.policy == "progress_constrained"
            and self.gate_ready
            and self.first_legal_mutation is None
            and self.no_progress_streak >= NO_PROGRESS_LIMIT
        )

    def summary(self):
        return {
            "task_id": self.task_id,
            "policy": self.policy,
            "approved_targets": list(self.approved_targets),
            "approved_inspection_paths": list(self.approved_inspection_paths),
            "tool_steps": self.tool_steps,
            "pre_mutation_read_steps": self.pre_mutation_read_steps,
            "unique_evidence": self.unique_evidence,
            "repeated_inspections": self.repeated_inspections,
            "repeated_gate_checks": self.repeated_gate_checks,
            "same_file_revisits_without_new_info": self.same_file_revisits_without_new_info,
            "invalid_rejected_tool_calls": self.invalid_rejected_tool_calls,
            "no_progress_streak": self.no_progress_streak,
            "first_legal_mutation": self.first_legal_mutation,
            "events": list(self.events),
        }
