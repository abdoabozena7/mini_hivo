"""Small deterministic project playbooks for low-capacity model execution."""

from __future__ import annotations

import json
from typing import Any


PLAYBOOKS: dict[str, tuple[str, ...]] = {
    "web_game": (
        "Build one playable vertical slice before visual polish.",
        "Keep update/render/input/game-state boundaries explicit and testable.",
        "Expose deterministic state and interaction adapters for independent browser verification.",
        "Verify movement, failure/restart, requested scoring or collection, and mobile input when relevant.",
    ),
    "web_app": (
        "Establish the real data/state flow before styling secondary surfaces.",
        "For a new no-build browser app, keep markup, styles, and behavior in separate small local files unless the request explicitly requires one file.",
        "Implement loading, empty, error, and success behavior where relevant.",
        "Verify primary keyboard/pointer flows and responsive layout in a real browser.",
    ),
    "api": (
        "Define request, response, validation, and failure contracts before adding endpoints.",
        "Keep transport, business logic, and persistence boundaries testable.",
        "Run automated happy-path and invalid-input checks.",
    ),
    "cli": (
        "Separate argument parsing, domain behavior, and output formatting.",
        "Verify help, success, invalid input, and exit codes through real commands.",
    ),
    "library": (
        "Preserve the public API and isolate implementation details.",
        "Add focused tests for normal, boundary, and invalid inputs.",
    ),
    "data": (
        "Make schemas, transformations, and validation rules explicit.",
        "Use small deterministic fixtures and verify row counts and edge cases.",
    ),
    "documentation": (
        "Change only the requested documentation surface and verify references and examples.",
    ),
    "general": (
        "Inspect the existing project before changing it.",
        "Implement the smallest complete vertical slice and verify observable behavior.",
        "Preserve unrelated behavior and keep module boundaries cohesive.",
    ),
}


def _contract_text(contract: dict[str, Any]) -> str:
    return " ".join(
        [str(contract.get("goal", ""))]
        + [str(item) for item in contract.get("requirements", [])]
        + [str(item) for item in contract.get("constraints", [])]
    ).casefold()


def classify_project(contract: dict[str, Any]) -> str:
    text = _contract_text(contract)
    profiles = (
        ("web_game", ("browser game", "web game", "three.js", "webgl", "collision", "physics", "لعبة")),
        ("api", ("rest api", "http api", "endpoint", "fastapi", "flask api", "express api", "واجهة برمجة")),
        ("cli", ("command line", "cli", "terminal utility", "argparse", "أداة سطر")),
        ("data", ("data pipeline", "dataset", "etl", "csv", "pandas", "تحليل بيانات")),
        ("web_app", ("web app", "website", "dashboard", "landing page", "html", "react", "موقع")),
        ("library", ("library", "package", "sdk", "module", "مكتبة")),
        ("documentation", ("readme", "documentation", "docs", "typo", "توثيق")),
    )
    for profile, markers in profiles:
        if any(marker in text for marker in markers):
            return profile
    return "general"


def playbook_context(contract: dict[str, Any]) -> str:
    profile = classify_project(contract)
    checks = "\n".join(f"- {item}" for item in PLAYBOOKS[profile])
    return (
        f"PROJECT PROFILE: {profile}\n"
        "EXECUTION PLAYBOOK (architecture guidance, not proof of completion):\n"
        f"{checks}"
    )


def _is_complex(contract: dict[str, Any], profile: str) -> bool:
    requirements = contract.get("requirements", [])
    goal = str(contract.get("goal", ""))
    complex_profiles = {"web_game", "web_app", "api", "data"}
    return len(requirements) >= 2 or len(goal) > 450 or (
        profile in complex_profiles and len(requirements) >= 1 and len(goal) > 180
    )


def build_execution_stages(contract: dict[str, Any], max_stages: int = 6) -> list[dict[str, Any]]:
    """Create bounded, requirement-preserving stages without another model call."""
    maximum = max(1, min(6, int(max_stages)))
    profile = classify_project(contract)
    requirements = [str(item).strip() for item in contract.get("requirements", []) if str(item).strip()]
    if not requirements:
        requirements = [str(contract.get("goal", "Implement the requested change")).strip()]

    if not _is_complex(contract, profile) or maximum == 1:
        return [{
            "index": 1,
            "name": "complete vertical slice",
            "goal": "Implement and verify: " + "; ".join(requirements),
            "requirements": requirements,
        }]

    # The pinned model has low measured task capacity, so keep each explicit
    # requirement in its own pass while the contract fits the bounded maximum.
    # Larger contracts are still distributed without dropping or reordering.
    stage_count = min(maximum, max(2, len(requirements)))
    if len(requirements) == 1 and stage_count > 1:
        requirement = requirements[0]
        return [
            {
                "index": 1,
                "name": "working foundation",
                "goal": f"Establish a minimal executable foundation toward this exact requirement: {requirement}",
                "requirements": [requirement],
                "acceptance": PLAYBOOKS[profile][0],
            },
            {
                "index": 2,
                "name": "complete integration",
                "goal": f"Complete and independently verify this exact requirement: {requirement}",
                "requirements": [requirement],
                "acceptance": PLAYBOOKS[profile][min(1, len(PLAYBOOKS[profile]) - 1)],
            },
        ][:maximum]
    base_size, extras = divmod(len(requirements), stage_count)
    sizes = [base_size for _ in range(stage_count)]
    distribution = [0, *range(stage_count - 1, 0, -1)]
    for index in range(extras):
        sizes[distribution[index]] += 1
    buckets: list[list[str]] = []
    cursor = 0
    for size in sizes:
        buckets.append(requirements[cursor:cursor + size])
        cursor += size

    guidance = PLAYBOOKS[profile]
    stages: list[dict[str, Any]] = []
    for index, bucket in enumerate(buckets, start=1):
        if not bucket:
            continue
        prefix = "Establish the minimal working foundation and" if index == 1 else "Extend the existing verified workspace and"
        if index == stage_count:
            prefix = "Complete integration and"
        stages.append({
            "index": index,
            "name": f"vertical stage {index}",
            "goal": f"{prefix} implement these exact requirements: " + "; ".join(bucket),
            "requirements": bucket,
            "acceptance": guidance[min(index - 1, len(guidance) - 1)],
        })
    return stages


def compact_stage_plan(stages: list[dict[str, Any]], max_chars: int = 4000) -> str:
    projection = [
        {"index": stage["index"], "name": stage["name"], "goal": stage["goal"]}
        for stage in stages
    ]
    return json.dumps(projection, ensure_ascii=False)[:max_chars]
