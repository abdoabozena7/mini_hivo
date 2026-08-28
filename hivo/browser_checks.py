"""Deterministic, profile-driven interactions for browser verification."""

from __future__ import annotations

import re
from typing import Any


_TIMER_CHECKS = frozenset({
    "timer_start_changes_visible_time",
    "timer_pause_freezes_visible_time",
    "timer_reset_restores_visible_time",
    "timer_phase_switches_and_counts_session",
})

_CLOCK_JS = r"""() => {
    const visible = (element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const candidates = Array.from(document.querySelectorAll('body *')).flatMap((element) => {
        if (!visible(element)) return [];
        // A legitimate clock is often composed from nested minute/colon/second
        // spans. Judge the combined visible value, not an implementation-specific
        // requirement that the clock live in one leaf text node.
        const text = (element.textContent || '').replace(/\s+/g, '').trim();
        const match = text.match(/^(\d{1,3}):([0-5]\d)(?::([0-5]\d))?$/);
        if (!match) return [];
        const parts = match.slice(1).filter((value) => value !== undefined).map(Number);
        const seconds = parts.length === 3
            ? parts[0] * 3600 + parts[1] * 60 + parts[2]
            : parts[0] * 60 + parts[1];
        return [{text, seconds, fontSize: parseFloat(getComputedStyle(element).fontSize) || 0}];
    });
    candidates.sort((left, right) => right.fontSize - left.fontSize);
    return candidates[0] || null;
}"""


def _check(name: str, passed: bool, **evidence: Any) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), **evidence}


def _button(page, pattern: str):
    locator = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE))
    return locator.first if locator.count() else None


def _clock(page) -> dict[str, Any] | None:
    return page.evaluate(_CLOCK_JS)


def _phase_text(page) -> str:
    return str(page.evaluate(r"""() => {
        const visible = (element) => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden'
                && rect.width > 0 && rect.height > 0;
        };
        const textOf = (element) => (element.textContent || '').replace(/\s+/g, ' ').trim();
        const phaseWords = /\b(?:focus|break|work|rest)(?:\s+(?:time|session))?\b|(?:وقت\s*)?(?:التركيز|الاستراحة|العمل|الراحة)/i;
        const semantic = Array.from(document.querySelectorAll(
            '[id*="phase" i], [class*="phase" i], [id*="status" i], [class*="status" i], [aria-live]'
        )).filter((element) => visible(element) && phaseWords.test(textOf(element)));
        if (semantic.length) {
            return semantic.map(textOf).filter(Boolean).join(' | ');
        }

        // Visual wording is the contract. Do not require a particular id/class
        // merely to make an independently implemented timer verifiable.
        const visibleLabels = Array.from(document.querySelectorAll('body *'))
            .filter((element) => element.children.length === 0 && visible(element))
            .map((element) => ({
                text: textOf(element),
                fontSize: parseFloat(getComputedStyle(element).fontSize) || 0,
            }))
            .filter((candidate) => candidate.text.length <= 80 && phaseWords.test(candidate.text));
        visibleLabels.sort((left, right) => right.fontSize - left.fontSize);
        return visibleLabels.slice(0, 3).map((candidate) => candidate.text).join(' | ');
    }"""))


def _completed_count(text: str) -> int | None:
    match = re.search(
        r"(?:completed\s*(?:sessions?|cycles?)|sessions?\s*completed|جلسات?\s*مكتملة)[^0-9]{0,30}(\d+)",
        text,
        re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


def _run_timer_checks(page, required: set[str]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    start = _button(page, r"^(?:start|begin|resume|ابدأ|تشغيل|استئناف)$")
    pause = _button(page, r"^(?:pause|إيقاف مؤقت|توقف مؤقت)$")
    reset = _button(page, r"^(?:reset|restart|إعادة ضبط|إعادة)$")
    before = _clock(page)

    if start is None or pause is None or reset is None or before is None:
        evidence = {
            "before": before,
            "missing": [
                name for name, value in (("start", start), ("pause", pause), ("reset", reset), ("clock", before))
                if value is None
            ],
        }
        return [_check(name, False, **evidence) for name in required & _TIMER_CHECKS]

    start.click()
    page.clock.run_for(1200)
    after_start = _clock(page)
    if "timer_start_changes_visible_time" in required:
        checks.append(_check(
            "timer_start_changes_visible_time",
            bool(before["seconds"] > 0 and after_start and after_start["seconds"] < before["seconds"]),
            before=before,
            after=after_start,
        ))

    pause.click()
    paused_before = _clock(page)
    page.clock.run_for(2200)
    paused_after = _clock(page)
    if "timer_pause_freezes_visible_time" in required:
        checks.append(_check(
            "timer_pause_freezes_visible_time",
            bool(
                before["seconds"] > 0
                and after_start
                and after_start["seconds"] < before["seconds"]
                and paused_before
                and paused_after
                and paused_before["seconds"] > 0
                and paused_before["seconds"] == paused_after["seconds"]
            ),
            before=paused_before,
            after=paused_after,
        ))

    reset.click()
    page.clock.run_for(100)
    after_reset = _clock(page)
    if "timer_reset_restores_visible_time" in required:
        checks.append(_check(
            "timer_reset_restores_visible_time",
            bool(before["seconds"] > 0 and after_reset and after_reset["seconds"] == before["seconds"]),
            before=before,
            after=after_reset,
        ))

    if "timer_phase_switches_and_counts_session" in required:
        before_text = page.locator("body").inner_text()
        before_phase = _phase_text(page)
        before_count = _completed_count(before_text)
        if before["seconds"] <= 0:
            checks.append(_check(
                "timer_phase_switches_and_counts_session", False,
                before_clock=before, before_phase=before_phase, before_count=before_count,
            ))
        else:
            start.click()
            page.clock.run_for((int(before["seconds"]) + 1) * 1000)
            after_text = page.locator("body").inner_text()
            after_phase = _phase_text(page)
            after_count = _completed_count(after_text)
            checks.append(_check(
                "timer_phase_switches_and_counts_session",
                bool(before_phase and after_phase and before_phase != after_phase)
                and before_count is not None and after_count is not None and after_count > before_count,
                before_phase=before_phase,
                after_phase=after_phase,
                before_count=before_count,
                after_count=after_count,
            ))
            current_pause = _button(page, r"^(?:pause|إيقاف مؤقت|توقف مؤقت)$")
            if current_pause is not None and current_pause.is_enabled():
                current_pause.click()
    return checks


def _run_settings_persistence(page) -> dict[str, Any]:
    numbers = page.locator('input[type="number"]:visible')
    if not numbers.count():
        return _check("settings_persistence", False, evidence="no visible numeric setting")
    field = numbers.first
    original = field.input_value()
    try:
        current = float(original)
        minimum = float(field.get_attribute("min") or 0)
        maximum_text = field.get_attribute("max")
        maximum = float(maximum_text) if maximum_text else current + 10
        candidate = current + 1 if current + 1 <= maximum else current - 1
        candidate = max(minimum, candidate)
        desired = str(int(candidate)) if candidate.is_integer() else str(candidate)
    except ValueError:
        return _check("settings_persistence", False, before=original, evidence="numeric setting is invalid")
    field.fill(desired)
    field.dispatch_event("change")
    field.blur()
    save = _button(page, r"^(?:save(?: settings)?|apply(?: settings)?|حفظ|تطبيق)$")
    if save is not None and save.is_enabled():
        save.click()
    page.clock.run_for(100)
    page.reload(wait_until="domcontentloaded", timeout=15000)
    page.clock.run_for(100)
    reloaded = page.locator('input[type="number"]:visible')
    after = reloaded.first.input_value() if reloaded.count() else None
    return _check("settings_persistence", after == desired, before=original, requested=desired, after=after)


def _run_duration_configuration(page) -> dict[str, Any]:
    numbers = page.locator('input[type="number"]:visible')
    if numbers.count() < 2:
        return _check(
            "timer_duration_configuration", False,
            evidence="fewer than two visible numeric duration settings",
        )
    field = numbers.first
    original = field.input_value()
    label = str(field.evaluate(r"""(element) => {
        const explicit = Array.from(element.labels || []).map((item) => item.textContent || '').join(' ');
        return `${explicit} ${element.getAttribute('aria-label') || ''}`.replace(/\s+/g, ' ').trim();
    }"""))
    try:
        minimum = float(field.get_attribute("min") or "nan")
        maximum_text = field.get_attribute("max")
        maximum = float(maximum_text) if maximum_text else max(minimum + 60, 60)
        if minimum < 1 or maximum < minimum:
            raise ValueError("duration bounds are not sensible")
        current = float(original)
        candidate = minimum if current != minimum else min(maximum, minimum + 1)
        desired = str(int(candidate)) if candidate.is_integer() else str(candidate)
    except ValueError as exc:
        return _check(
            "timer_duration_configuration", False,
            before=original, label=label, evidence=str(exc),
        )

    field.fill(desired)
    field.dispatch_event("input")
    field.dispatch_event("change")
    field.blur()
    save = _button(page, r"^(?:save(?: settings)?|apply(?: settings)?|حفظ|تطبيق)$")
    if save is not None and save.is_enabled():
        save.click()
    page.clock.run_for(100)
    after_clock = _clock(page)
    unit_seconds = 1 if re.search(r"\bsec(?:ond)?s?\b|ثوان", label, re.IGNORECASE) else 60
    expected_seconds = int(candidate * unit_seconds)

    invalid_value = minimum - 1
    invalid_text = str(int(invalid_value)) if invalid_value.is_integer() else str(invalid_value)
    field.fill(invalid_text)
    below_minimum_is_invalid = not bool(field.evaluate("(element) => element.checkValidity()"))
    field.fill(desired)
    field.dispatch_event("change")
    return _check(
        "timer_duration_configuration",
        bool(after_clock and after_clock["seconds"] == expected_seconds and below_minimum_is_invalid),
        before=original,
        requested=desired,
        expected_seconds=expected_seconds,
        after_clock=after_clock,
        minimum=minimum,
        maximum=maximum,
        below_minimum_is_invalid=below_minimum_is_invalid,
        label=label,
    )


def _run_keyboard_activation(page) -> dict[str, Any]:
    start = _button(page, r"^(?:start|begin|resume|ابدأ|تشغيل|استئناف)$")
    if start is None:
        return _check("keyboard_activation", False, evidence="no Start button")
    if start.is_disabled():
        pause = _button(page, r"^(?:pause|إيقاف مؤقت|توقف مؤقت)$")
        if pause is not None and pause.is_enabled():
            pause.click()
    before = start.is_disabled()
    start.focus()
    page.keyboard.press("Enter")
    page.clock.run_for(100)
    after = start.is_disabled()
    return _check("keyboard_activation", before != after, before_disabled=before, after_disabled=after)


def _run_responsive_check(page) -> dict[str, Any]:
    page.set_viewport_size({"width": 390, "height": 844})
    page.clock.run_for(100)
    state = page.evaluate(r"""() => ({
        viewportWidth: innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
        bodyScrollWidth: document.body.scrollWidth,
        visibleButtons: Array.from(document.querySelectorAll('button')).filter((button) => {
            const rect = button.getBoundingClientRect();
            const style = getComputedStyle(button);
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
        }).length
    })""")
    passed = (
        state["scrollWidth"] <= state["viewportWidth"] + 1
        and state["bodyScrollWidth"] <= state["viewportWidth"] + 1
        and state["visibleButtons"] > 0
    )
    return _check("responsive_no_overflow", passed, **state)


def _run_reduced_motion_check(page) -> dict[str, Any]:
    page.emulate_media(reduced_motion="reduce")
    durations = page.evaluate(r"""() => {
        const seconds = (value) => value.split(',').reduce((maximum, item) => {
            const text = item.trim();
            const amount = parseFloat(text) || 0;
            return Math.max(maximum, text.endsWith('ms') ? amount / 1000 : amount);
        }, 0);
        return Array.from(document.querySelectorAll('body *')).reduce((result, element) => {
            const style = getComputedStyle(element);
            result.transition = Math.max(result.transition, seconds(style.transitionDuration));
            result.animation = Math.max(result.animation, seconds(style.animationDuration));
            return result;
        }, {transition: 0, animation: 0});
    }""")
    return _check(
        "reduced_motion",
        durations["transition"] <= 0.01 and durations["animation"] <= 0.01,
        **durations,
    )


def run_profile_interactions(page, profile) -> list[dict[str, Any]]:
    """Run only deterministic checks explicitly required by the inferred profile."""
    required = set(profile.required_interactions)
    checks: list[dict[str, Any]] = []
    if required & _TIMER_CHECKS:
        try:
            checks.extend(_run_timer_checks(page, required))
        except Exception as exc:
            checks.extend(_check(name, False, evidence=f"timer check error: {exc}") for name in required & _TIMER_CHECKS)
    for name, runner in (
        ("timer_duration_configuration", _run_duration_configuration),
        ("settings_persistence", _run_settings_persistence),
        ("keyboard_activation", _run_keyboard_activation),
        ("responsive_no_overflow", _run_responsive_check),
        ("reduced_motion", _run_reduced_motion_check),
    ):
        if name not in required:
            continue
        try:
            checks.append(runner(page))
        except Exception as exc:
            checks.append(_check(name, False, evidence=f"check error: {exc}"))
    return checks
