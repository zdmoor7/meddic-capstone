"""Parse and validate the demo prescription returned by the model.

The agenda is the spine of the prescription: every prescription step must
carry the same label, in the same order, as an agenda item. When the model
drifts we repair what we safely can and record a warning.
"""
import logging
import re

from meddic import MalformedOutputError, extract_json, _text

logger = logging.getLogger(__name__)

AGENDA_MIN_STEPS = 4
AGENDA_MAX_STEPS = 6
AGENDA_MIN_WORDS = 2
AGENDA_MAX_WORDS = 5
# A bullet longer than this runs past ~4 lines in the output panel and PDF.
MAX_BULLET_WORDS = 30


def _label_key(label):
    return " ".join(label.lower().split())


def _string_list(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [t for t in (_text(v) for v in value) if t]


def split_sentences(text):
    return [t.strip() for t in re.split(r"(?<=[.!?])\s+", text) if t.strip()]


def bullets(value, field, warnings):
    """Coerce a field to a list of bullets; prose is split into one bullet per sentence."""
    if isinstance(value, str) and value.strip():
        warnings.append(f"{field} came back as prose; split into sentence bullets.")
        items = split_sentences(value)
    else:
        items = _string_list(value)
    for item in items:
        words = len(item.split())
        if words > MAX_BULLET_WORDS:
            warnings.append(f"{field} has a {words}-word bullet (max {MAX_BULLET_WORDS}).")
    return items


def _steps(value, warnings):
    if not isinstance(value, list) or not value:
        raise MalformedOutputError("demo_prescription must be a non-empty list of agenda steps.")
    steps = []
    for item in value:
        if not isinstance(item, dict) or not _text(item.get("step")):
            raise MalformedOutputError("Each demo_prescription item needs a 'step' label.")
        label = _text(item.get("step"))
        points = item.get("points", item.get("detail"))
        steps.append({"step": label, "points": bullets(points, f"Step {label!r}", warnings)})
    return steps


def align_agenda(agenda, steps, warnings):
    """Make agenda labels and prescription steps match one-to-one, in order."""
    if not agenda:
        warnings.append("demo_agenda missing; built from prescription steps.")
        return [s["step"] for s in steps], steps

    if len(agenda) != len(steps):
        warnings.append(
            f"demo_agenda has {len(agenda)} steps but demo_prescription has {len(steps)}; "
            "agenda rebuilt from prescription steps."
        )
        return [s["step"] for s in steps], steps

    for label, step in zip(agenda, steps):
        if _label_key(label) != _label_key(step["step"]):
            warnings.append(f"Prescription step {step['step']!r} relabelled to agenda item {label!r}.")
        step["step"] = label
    return agenda, steps


def check_agenda_shape(agenda, warnings):
    if not AGENDA_MIN_STEPS <= len(agenda) <= AGENDA_MAX_STEPS:
        warnings.append(f"demo_agenda has {len(agenda)} steps (expected {AGENDA_MIN_STEPS}-{AGENDA_MAX_STEPS}).")
    for label in agenda:
        words = len(label.split())
        if not AGENDA_MIN_WORDS <= words <= AGENDA_MAX_WORDS:
            warnings.append(f"Agenda item {label!r} is {words} words (expected {AGENDA_MIN_WORDS}-{AGENDA_MAX_WORDS}).")


def parse_prescription_response(raw):
    data = extract_json(raw)
    warnings = []

    steps = _steps(data.get("demo_prescription"), warnings)
    agenda, steps = align_agenda(_string_list(data.get("demo_agenda")), steps, warnings)
    check_agenda_shape(agenda, warnings)

    result = {
        "deal_overview": bullets(data.get("deal_overview"), "deal_overview", warnings),
        "demo_agenda": agenda,
        "demo_prescription": steps,
        "market_context": bullets(data.get("market_context"), "market_context", warnings),
        "warnings": warnings,
    }
    for w in warnings:
        logger.warning("Prescription output: %s", w)
    return result
