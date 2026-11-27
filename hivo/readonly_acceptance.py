"""Enforced read-only parent scope and bounded project integrity snapshots.

Receipt data is evidence, never a mutation authority. Runtime provenance and
browser evidence live separately from project-source files.
"""
import hashlib
import os
from pathlib import Path

from hivo.integration_gate import canonical_hash

READ_ONLY = 'PARENT_VERIFICATION_READ_ONLY'
SOURCE_CHANGED = 'READ_ONLY_PARENT_SOURCE_CHANGED'


def inspection_paths(workspace, values):
    root = Path(workspace).resolve()
    result = set()
    for raw in values:
        try:
            path = Path(raw)
            path = path.resolve() if path.is_absolute() else (root / path).resolve()
            relative = path.relative_to(root)
            if any(p.casefold() in {'.git', '.hivo'} or p.startswith('.agent') for p in relative.parts):
                continue
            result.add(os.path.normcase(relative.as_posix()))
        except (TypeError, OSError, ValueError):
            continue
    return result


def tool_guard(workspace, active, name, args):
    if not active.get('parent_verification_read_only'):
        return None
    if name not in {'read_file', 'read_file_range', 'verify_web_app'}:
        return 'error: ' + READ_ONLY + ': only bounded inspection/browser tools are allowed'
    target = (args or {}).get('path') if isinstance(args, dict) else None
    requested = inspection_paths(workspace, [target])
    allowed = inspection_paths(workspace, active.get('allowed_inspection_paths', []))
    if not requested or not requested <= allowed:
        return 'error: ' + READ_ONLY + ': inspection target is outside parent scope'
    return None


def snapshot(workspace):
    root = Path(workspace).resolve()
    result = {}
    total = 0
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {'.git', '.hivo', '__pycache__'} and not d.startswith('.agent'))
        for name in sorted(files):
            if name.startswith('.agent'):
                continue
            path = Path(current) / name
            path.resolve().relative_to(root)  # Refuse an escaping source symlink.
            if len(result) >= 512 or path.stat().st_size + total > 16 * 1024 * 1024:
                raise ValueError('bounded read-only source snapshot limit exceeded')
            data = path.read_bytes()
            total += len(data)
            result[path.relative_to(root).as_posix()] = hashlib.sha256(data).hexdigest()
    return result


def child_proof_valid(task, result, records):
    gate = result.get('gate') or {}
    proof = gate.get('obligation_verification') or {}
    if gate.get('passed') is not True or proof.get('passed') is not True:
        return False
    content = {k: v for k, v in proof.items() if k != 'receipt_hash'}
    if proof.get('receipt_hash') != canonical_hash(content):
        return False
    if proof.get('source_hash') != canonical_hash(records):
        return False
    if proof.get('obligation_hash') != canonical_hash(task.get('verification_obligations', [])):
        return False
    if proof.get('subject_before') != proof.get('subject_after') or not proof.get('subject_before'):
        return False
    expected = {(o['requirement_id'], o['target']) for o in task.get('verification_obligations', [])}
    actual = {(c.get('requirement_id'), c.get('target')) for c in proof.get('checks', []) if c.get('passed') is True}
    return bool(expected) and expected <= actual
