"""Terminal observations for already-bounded tool failure episodes."""

from collections.abc import Iterable


MUTATION_ARGUMENT_RETRIES_EXHAUSTED = "MUTATION_ARGUMENT_RETRIES_EXHAUSTED"
WORKER_NO_MUTATION_PROGRESS = "WORKER_NO_MUTATION_PROGRESS"
BROWSER_VERIFICATION_STAGNATION = "BROWSER_VERIFICATION_STAGNATION"


def classify_mutation_exhaustion(categories: Iterable[str | None]) -> str:
    """Report what was observed at a same-target mutation retry limit.

    The controller supplies one category per failed attempt after applying
    its guards. Only a nonempty series of argument-validator refusals supports
    the narrower schema-exhaustion code. Mixed or unqualified failures only
    show lack of progress applying the mutation, not why the task failed.
    """
    saw_argument_refusal = False
    for category in categories:
        if category != "TOOL_ARGUMENT_REJECTED":
            return WORKER_NO_MUTATION_PROGRESS
        saw_argument_refusal = True
    return MUTATION_ARGUMENT_RETRIES_EXHAUSTED if saw_argument_refusal else WORKER_NO_MUTATION_PROGRESS
