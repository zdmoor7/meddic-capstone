"""Parse and validate the MEDDIC analysis returned by the model.

The model is asked for strict JSON, but it can still return fences, prose,
missing fields or unknown status values. Everything here normalises that
into one predictable shape for the frontend, or raises MalformedOutputError
when the output can't be used at all.
"""
import json
import logging

logger = logging.getLogger(__name__)

MEDDIC_ELEMENTS = [
    "Metrics",
    "Economic Buyer",
    "Decision Criteria",
    "Decision Process",
    "Identify Pain",
    "Champion",
]

STATUSES = ("RED", "YELLOW", "GREEN")
MAX_FOLLOW_UPS = 3


class MalformedOutputError(Exception):
    pass


def extract_json(raw):
    """Pull the JSON object out of a model reply, tolerating code fences or stray prose."""
    if not isinstance(raw, str):
        raise MalformedOutputError("Model reply was not text.")
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        raise MalformedOutputError("Model reply did not contain a JSON object.")
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError as e:
        raise MalformedOutputError(f"Model reply was not valid JSON: {e}")
    if not isinstance(data, dict):
        raise MalformedOutputError("Model reply JSON was not an object.")
    return data


def _text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(_text(v) for v in value if _text(v))
    return str(value).strip()


def _questions(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [q for q in (_text(v) for v in value) if q][:MAX_FOLLOW_UPS]


def normalise_element(name, value, warnings):
    if not isinstance(value, dict):
        warnings.append(f"{name}: missing from model output, marked RED.")
        value = {}

    content = _text(value.get("content"))
    flag = _text(value.get("flag"))
    questions = _questions(value.get("follow_up_questions"))
    status = _text(value.get("status")).upper()

    if status not in STATUSES:
        fallback = "YELLOW" if content else "RED"
        if value:
            warnings.append(f"{name}: invalid status {status or '(none)'!r}, defaulted to {fallback}.")
        status = fallback

    # Nothing captured can't be covered, whatever the model said.
    if not content and status != "RED":
        warnings.append(f"{name}: no content but status {status}, changed to RED.")
        status = "RED"

    return {
        "content": content,
        "flag": flag,
        "status": status,
        "follow_up_questions": [] if status == "GREEN" else questions,
    }


def build_gate(meddic):
    """Readiness gate: any RED element means 'not ready to demo'."""
    missing = [
        {"element": name, "follow_up_questions": meddic[name]["follow_up_questions"]}
        for name in MEDDIC_ELEMENTS
        if meddic[name]["status"] == "RED"
    ]
    return {
        "ready": not missing,
        "missing": missing,
        "metrics_status": meddic["Metrics"]["status"],
    }


def parse_meddic_response(raw):
    """Turn a raw model reply into {"meddic", "gate", "warnings"}."""
    data = extract_json(raw)
    # Accept the six elements either wrapped in "meddic" or at the top level.
    source = data.get("meddic") if isinstance(data.get("meddic"), dict) else data
    if not any(name in source for name in MEDDIC_ELEMENTS):
        raise MalformedOutputError("Model reply contained none of the MEDDIC elements.")

    warnings = []
    meddic = {name: normalise_element(name, source.get(name), warnings) for name in MEDDIC_ELEMENTS}
    for w in warnings:
        logger.warning("MEDDIC output: %s", w)

    return {"meddic": meddic, "gate": build_gate(meddic), "warnings": warnings}
