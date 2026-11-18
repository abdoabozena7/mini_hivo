"""Stable ordering of explicitly dependent children in the legacy scheduler."""

from collections.abc import Mapping
from heapq import heappop, heappush, heapify


def _child_positions(children):
    positions = {}
    ambiguous = set()
    for position, child in enumerate(children):
        if not isinstance(child, Mapping):
            continue
        child_id = str(child.get("id", ""))
        if not child_id:
            continue
        if child_id in positions:
            ambiguous.add(child_id)
        else:
            positions[child_id] = position
    return positions, ambiguous


def ambiguous_child_ids(children) -> set[str]:
    """IDs with no unique provider in this sibling list."""
    return _child_positions(children)[1]


def order_children(children, dependency_ids) -> list:
    """Return original children in stable prerequisite order, without mutation.

    The callback supplies each child's normalized, explicit dependency IDs.
    Pick the earliest declared child among those ready for ordering. IDs not
    present among siblings may refer to inherited results; leave those
    dependencies untouched for the runtime gate. Append unorderable children
    (cycles, ambiguous IDs and their dependents) in their original order so
    the caller can record a block for each rather than silently dropping any.
    A position in this list is never proof that a dependency completed.
    """
    nodes = list(children)
    positions, ambiguous = _child_positions(nodes)
    indegree = [0] * len(nodes)
    dependents = [[] for _ in nodes]
    ready = []
    for child_id, position in positions.items():
        if child_id in ambiguous:
            continue
        for dependency_id in set(dependency_ids(nodes[position])):
            if dependency_id in positions:
                # Ambiguous providers have a position but never enter ready.
                predecessor = positions[dependency_id]
                indegree[position] += 1
                dependents[predecessor].append(position)
        if indegree[position] == 0:
            ready.append(position)

    heapify(ready)
    ordered = []
    emitted = set()
    while ready:
        position = heappop(ready)
        ordered.append(nodes[position])
        emitted.add(position)
        for dependent in dependents[position]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heappush(ready, dependent)

    ordered.extend(child for position, child in enumerate(nodes) if position not in emitted)
    return ordered
