"""Source-ID accountability for ordinary greenfield plans; never write authority.

An allocation is a planning prerequisite, not behavioral proof. Oracle and
current-artifact evidence are separate acceptance obligations.
"""
import copy
import os
from pathlib import PurePosixPath

from hivo.integration_gate import canonical_hash, _PATH_SUFFIXES
from hivo.requirements import freeze

INCOMPLETE = 'REQUIREMENT_OWNERSHIP_INCOMPLETE'


def validate(records, children, parent_ids, *, outer_paths=None):
    errors = []
    source = {r['requirement_id']: r for r in records}
    owners = {key: [] for key in source}
    if not isinstance(parent_ids, list) or not all(isinstance(i, str) for i in parent_ids):
        errors.append('parent_requirement_ids must be explicit source IDs')
        parent_ids = []
    for key in parent_ids:
        if key not in source:
            errors.append('unknown parent requirement: ' + key)
        else:
            owners[key].append('PARENT')
    for child in children:
        ids = child.get('requirement_ids')
        paths = child.get('implementation_paths', [])
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            errors.append('child requirement_ids missing or malformed')
            continue
        if not paths:
            errors.append('child has no concrete implementation scope')
        if outer_paths is not None and any(os.path.normcase(p) not in {
                os.path.normcase(x) for x in outer_paths} for p in paths):
            errors.append('child scope exceeds explicit outer mutation boundary')
        for key in ids:
            if key not in source:
                errors.append('unknown child requirement: ' + key)
            else:
                owners[key].append(str(child['id']))
    for key, assigned in owners.items():
        if not assigned:
            errors.append('unowned requirement: ' + key)
        # Explicit source file names need an implementation owner; parent
        # read-only verification is not permission to create an omitted file.
        for item in source[key].get('explicit_items', []):
            if not isinstance(item, str) or PurePosixPath(item).suffix.casefold() not in (
                    _PATH_SUFFIXES | {'.txt', '.csv', '.svg', '.png', '.md'}):
                continue
            item = item.replace('\\', '/')
            if not any(str(c['id']) in assigned and os.path.normcase(item) in {
                    os.path.normcase(p) for p in c.get('implementation_paths', [])} for c in children):
                errors.append('unowned required artifact: ' + item)
    payload = {'version': 1, 'valid': not errors, 'errors': errors,
               'source_hash': canonical_hash(records), 'requirements': copy.deepcopy(records),
               'owners': owners, 'children': copy.deepcopy(children),
               'parent_requirement_ids': list(parent_ids)}
    payload['allocation_hash'] = canonical_hash(payload)
    return freeze(payload)
