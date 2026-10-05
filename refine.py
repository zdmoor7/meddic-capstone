"""Interactive refinement of the demo plan, and the final "ready to demo?" check.

Edits come back as a diff (only the steps that changed) to keep each chat
turn short; apply_changes() merges them into the current prescription and
re-validates so the agenda and steps stay keyed to the same labels.
"""
import json
import logging

from meddic import MEDDIC_ELEMENTS, MalformedOutputError, _text, extract_json
from prescription import _label_key, _string_list, bullets, check_agenda_shape

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 10
MAX_MESSAGE_CHARS = 2000
MAX_MODEL_GAPS = 5
SEVERITIES = ("blocker", "risk")

REFINE_SYSTEM_PROMPT = """You are a senior sales engineering advisor helping an SE refine their demo plan before the demo. You have the MEDDIC analysis of the discovery call, the call balance, and the current demo plan below.

The SE will ask questions or ask for edits. Reply in at most 3 short sentences. Only change the plan when the SE asks for a change. Never invent facts about the prospect that are not in the MEDDIC analysis.

When you change the plan, return ONLY what changed:
- "changed_steps": the complete new bullets for each agenda step you changed, using the step's exact label.
- "demo_agenda": the complete new agenda, only if you add, remove, rename or reorder steps. Every new or renamed step must also appear in changed_steps. Keep 4-6 steps of 2-5 words.
- "deal_overview": the complete new list, only if you changed it.
Each bullet is one idea in at most 25 words. Leave out any key you did not change.

Output JSON only, no explanation:
{"reply": "...", "changes": null}
or
{"reply": "...", "changes": {"changed_steps": [{"step": "Step label", "points": ["...", "..."]}], "demo_agenda": ["..."], "deal_overview": ["..."]}}

MEDDIC analysis:
%(meddic)s

Call balance:
%(call_balance)s

Current demo plan:
%(plan)s"""

READY_CHECK_SYSTEM_PROMPT = """You are a senior sales engineering leader doing a final review before an SE runs a demo. You get the MEDDIC analysis of discovery and the SE's final demo plan.

Find the gaps that would hurt this demo, for example: a step that maps to no stated pain or decision criterion, a key pain or decision criterion the plan never addresses, no plan to quantify value against the Metrics, the Economic Buyer's priorities ignored, or no clear next step at the end.

Return at most 5 gaps, most important first. Mark a gap "blocker" only if the SE should not run the demo until it is fixed; otherwise "risk". Each issue and fix is one sentence of at most 20 words. Return an empty list if the plan is ready.

Output JSON only, no explanation:
{"gaps": [{"severity": "blocker|risk", "area": "...", "issue": "...", "fix": "..."}]}
"area" is a MEDDIC element name, the exact label of an agenda step, or "Overall plan"."""


def plan_for_prompt(prescription):
    return {k: prescription.get(k) for k in ("deal_overview", "demo_agenda", "demo_prescription", "market_context")}


def refine_system_prompt(meddic, call_balance, prescription):
    return REFINE_SYSTEM_PROMPT % {
        "meddic": json.dumps(meddic, indent=1),
        "call_balance": json.dumps(call_balance or {}, indent=1),
        "plan": json.dumps(plan_for_prompt(prescription), indent=1),
    }


def clean_history(messages):
    """Last few chat turns, starting with a user turn and ending with one, as the API requires."""
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")
    turns = [
        {"role": m["role"], "content": _text(m.get("content"))[:MAX_MESSAGE_CHARS]}
        for m in messages
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and _text(m.get("content"))
    ][-MAX_HISTORY_MESSAGES:]
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    if not turns or turns[-1]["role"] != "user":
        raise ValueError("The last message must be from the user.")
    return turns


def apply_changes(prescription, changes, warnings):
    """Merge a diff of changed steps into the prescription. Returns (prescription, changed_labels)."""
    current = {_label_key(s["step"]): s["points"] for s in prescription["demo_prescription"]}

    changed = {}
    for item in changes.get("changed_steps") or []:
        if not isinstance(item, dict) or not _text(item.get("step")):
            raise MalformedOutputError("Each changed step needs a 'step' label.")
        label = _text(item["step"])
        changed[_label_key(label)] = bullets(item.get("points"), f"Step {label!r}", warnings)

    agenda = _string_list(changes.get("demo_agenda")) or list(prescription["demo_agenda"])
    agenda_keys = {_label_key(label) for label in agenda}
    for key in changed:
        if key not in agenda_keys:
            warnings.append(f"Changed step {key!r} is not on the agenda; ignored.")

    steps, changed_labels = [], []
    for label in agenda:
        key = _label_key(label)
        if key in changed:
            points = changed[key]
            if points != current.get(key):
                changed_labels.append(label)
        elif key in current:
            points = current[key]
        else:
            warnings.append(f"New step {label!r} came back without any detail.")
            points = []
            changed_labels.append(label)
        steps.append({"step": label, "points": points})

    updated = dict(prescription, demo_agenda=agenda, demo_prescription=steps)
    if changes.get("deal_overview"):
        updated["deal_overview"] = bullets(changes["deal_overview"], "deal_overview", warnings)
    check_agenda_shape(agenda, warnings)
    return updated, changed_labels


def parse_refine_response(raw, prescription):
    data = extract_json(raw)
    warnings = []
    reply = _text(data.get("reply"))
    changes = data.get("changes")
    if changes is not None and not isinstance(changes, dict):
        raise MalformedOutputError("'changes' must be an object or null.")
    if not reply and not changes:
        raise MalformedOutputError("Reply had neither a message nor changes.")

    updated, changed_labels = prescription, []
    if changes:
        updated, changed_labels = apply_changes(prescription, changes, warnings)
    for w in warnings:
        logger.warning("Refine output: %s", w)
    return {
        "reply": reply or "Updated the plan.",
        "prescription": dict(updated, warnings=warnings),
        "changed_steps": changed_labels,
        "warnings": warnings,
    }


def rule_gaps(meddic, prescription):
    """Gaps we can find without the model."""
    gaps = []
    for name in MEDDIC_ELEMENTS:
        element = meddic.get(name) or {}
        if element.get("status", "RED") == "RED":
            questions = element.get("follow_up_questions") or []
            gaps.append({
                "severity": "blocker",
                "area": name,
                "issue": f"{name} is still missing from discovery.",
                "fix": f"Ask before the demo: {questions[0]}" if questions else f"Cover {name} before the demo.",
            })
    for step in prescription["demo_prescription"]:
        if not step["points"]:
            gaps.append({"severity": "risk", "area": step["step"], "issue": "This step has no detail.",
                         "fix": "Say what to show in this step and why it matters to them."})
    shape = []
    check_agenda_shape(prescription["demo_agenda"], shape)
    for w in shape:
        gaps.append({"severity": "risk", "area": "Demo agenda", "issue": w, "fix": "Keep 4-6 short agenda steps."})
    return gaps


def model_gaps(raw, warnings):
    try:
        data = extract_json(raw)
    except MalformedOutputError as e:
        warnings.append(f"Readiness review unreadable, showing rule checks only: {e}")
        return []
    gaps = []
    for gap in data.get("gaps") or []:
        if not isinstance(gap, dict) or not _text(gap.get("issue")):
            continue
        severity = _text(gap.get("severity")).lower()
        gaps.append({
            "severity": severity if severity in SEVERITIES else "risk",
            "area": _text(gap.get("area")) or "Demo plan",
            "issue": _text(gap.get("issue")),
            "fix": _text(gap.get("fix")),
        })
    return gaps[:MAX_MODEL_GAPS]


def build_ready_check(meddic, prescription, model_raw):
    warnings = []
    rules = rule_gaps(meddic, prescription)
    covered = {_label_key(g["area"]) for g in rules}
    review = [g for g in model_gaps(model_raw, warnings) if _label_key(g["area"]) not in covered]
    gaps = rules + review
    gaps.sort(key=lambda g: SEVERITIES.index(g["severity"]))
    return {"ready": not any(g["severity"] == "blocker" for g in gaps), "gaps": gaps, "warnings": warnings}
