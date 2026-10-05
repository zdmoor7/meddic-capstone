import os
from flask import Flask, request, render_template, jsonify
from dotenv import load_dotenv
from api_wrapper import AnthropicClient
from rag import load_docs_to_chroma, retrieve_relevant_chunks
import json
from datetime import datetime, timezone
from meddic import parse_meddic_response, MalformedOutputError
from prescription import parse_prescription_response, normalise_prescription
from refine import (READY_CHECK_SYSTEM_PROMPT, build_ready_check, clean_history,
                    parse_refine_response, plan_for_prompt, refine_system_prompt)
from storage import get_store

load_dotenv()

MEDDIC_MAX_TOKENS = 2048
PRESCRIPTION_MAX_TOKENS = 2048
REFINE_MAX_TOKENS = 1500
READY_CHECK_MAX_TOKENS = 1024

app = Flask(__name__)
# Keep MEDDIC elements in framework order (Metrics first) instead of alphabetical.
app.json.sort_keys = False
client = AnthropicClient(api_key=os.getenv("ANTHROPIC_API_KEY"))
store = get_store()
load_docs_to_chroma()

MEDDIC_SYSTEM_PROMPT = """You are a tool that organises messy discovery notes or call transcripts into a clean, organised plan that adheres to the MEDDIC sales qualification framework. Before outputting JSON, analyse each piece of information against all six MEDDIC categories and identify every category it could belong to. When you get the notes, separate the contents according to the extent to which they align with each category. If content aligns with two or more categories, flag this with ⚠️ and specify which categories with AND. If there is no relevant content for a category, leave content empty and set the flag to ❓ with a short note that nothing was captured.

Only use what was learned about the prospect. Exclude the rep's own pitching (descriptions of product features or of the selling company) from every MEDDIC field.

Then rate how well each element is covered with a status:
- GREEN: well covered and specific (named people, concrete numbers, dates, steps).
- YELLOW: present but thin, vague, second-hand or ambiguous.
- RED: missing, or nothing usable.

Metrics is the element reps miss most often, so judge it strictly:
- GREEN only if there is a quantified business outcome the prospect cares about, with a current baseline and a target or value (e.g. "onboarding takes 30 days today, they want 20").
- YELLOW if goals are stated without numbers, or numbers have no baseline or business impact.
- RED if no measurable outcome was discussed.

For every element that is not GREEN, give 1-3 short follow-up questions the rep should ask on the next discovery call to close the gap. Use an empty list for GREEN elements.

Separately, measure the balance of the call. Count one statement per speaker turn in a transcript, or one per line or bullet in notes; never split a turn into several statements. Classify each statement as:
- discovery: the rep asks a question, or the prospect says anything about their situation, problems, goals, tools, process or people, however brief.
- pitching: the rep describes product features, the selling company, customers, awards or pricing.
- other: greetings, logistics, scheduling or small talk.
If a rep turn mixes a question with pitching, classify it by what most of the turn is.
Count the discovery and pitching statements, and quote up to 2 short examples of pitching (under 15 words each). This balance is about the rep's behaviour and must not change the MEDDIC fields.

Output should follow this JSON structure exactly, no explanation:
{
  "meddic": {
    "Metrics": {"content": "...", "flag": "", "status": "GREEN|YELLOW|RED", "follow_up_questions": []},
    "Economic Buyer": {"content": "...", "flag": "", "status": "...", "follow_up_questions": []},
    "Decision Criteria": {"content": "...", "flag": "", "status": "...", "follow_up_questions": []},
    "Decision Process": {"content": "...", "flag": "", "status": "...", "follow_up_questions": []},
    "Identify Pain": {"content": "...", "flag": "", "status": "...", "follow_up_questions": []},
    "Champion": {"content": "...", "flag": "", "status": "...", "follow_up_questions": []}
  },
  "call_balance": {"discovery_count": 0, "pitching_count": 0, "other_count": 0, "pitching_examples": []}
}
Issue all output in JSON only, no explanation."""

PRESCRIPTION_SYSTEM_PROMPT = """You are a senior sales engineering advisor. You receive a structured MEDDIC analysis of a discovery call and produce a concise deal prescription for the SE.

Write every section as short bullet points, never paragraphs. Each bullet is one idea in at most 25 words.

Your output must contain exactly four sections:

1. DEAL OVERVIEW: 3-5 bullets summarising the opportunity, the key stakeholders, and the stage of the deal based on the MEDDIC data.

2. DEMO AGENDA: The recommended demo agenda as 4-6 steps, each a short label of 2-5 words, in the order they should be shown. The agenda follows the narrative arc of the demo prescription.

3. DEMO PRESCRIPTION: The story the SE should tell in the demo, broken down by agenda step. Include one entry per agenda step, in the same order, using exactly the same label as the agenda. For each step, give 2-4 bullets on which features to show and why, mapped directly to the identified pain and decision criteria.

4. MARKET CONTEXT: 3-5 bullet points on relevant competitors, industry dynamics, and why this product is well-positioned for this specific prospect.

Output in JSON with this structure:
{
  "deal_overview": ["...", "...", "..."],
  "demo_agenda": ["Step label", "Step label", "..."],
  "demo_prescription": [
    {"step": "Step label", "points": ["...", "..."]}
  ],
  "market_context": ["...", "...", "..."]
}

JSON only, no explanation."""

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/notes-cleanup", methods=["POST"])
def notes_cleanup():
    notes = request.json.get("notes", "")
    try:
        result = client.send_message(message=notes, system=MEDDIC_SYSTEM_PROMPT, max_tokens=MEDDIC_MAX_TOKENS)
        return jsonify({"result": parse_meddic_response(result)})
    except MalformedOutputError as e:
        app.logger.error("Malformed MEDDIC output: %s\n%s", e, result)
        return jsonify({"error": "The model returned output we couldn't read. Please try again."}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/get-prescription", methods=["POST"])
def get_prescription():
    meddic_output = request.json.get("meddic_output", "")
    buyer = request.json.get("buyer", "")
    call_balance = request.json.get("call_balance")
    gate_overridden = bool(request.json.get("gate_overridden"))
    try:
        chunks = retrieve_relevant_chunks(meddic_output)
        augmented_prompt = PRESCRIPTION_SYSTEM_PROMPT + "\n\nRelevant product documentation:\n" + "\n".join(chunks)
        result = client.send_message(message=meddic_output, system=augmented_prompt, max_tokens=PRESCRIPTION_MAX_TOKENS)
        prescription = parse_prescription_response(result)
        deal_id = store.save_deal({
            "buyer": buyer,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "meddic": json.loads(meddic_output),
            "call_balance": call_balance,
            "prescription": prescription,
            "gate_overridden": gate_overridden,
        })
        return jsonify({"result": prescription, "deal_id": deal_id})
    except MalformedOutputError as e:
        app.logger.error("Malformed prescription output: %s\n%s", e, result)
        return jsonify({"error": "The model returned a prescription we couldn't read. Please try again."}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/refine", methods=["POST"])
def refine():
    """One chat turn on the demo plan. History lives in the browser; edits come back as a diff."""
    body = request.json or {}
    result = None
    try:
        prescription = normalise_prescription(body.get("prescription"))
        messages = clean_history(body.get("messages"))
    except (MalformedOutputError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    try:
        system = refine_system_prompt(body.get("meddic") or {}, body.get("call_balance"), prescription)
        result = client.send_message(messages=messages, system=system, max_tokens=REFINE_MAX_TOKENS)
        return jsonify({"result": parse_refine_response(result, prescription)})
    except MalformedOutputError as e:
        app.logger.error("Malformed refine output: %s\n%s", e, result)
        return jsonify({"error": "The model returned a reply we couldn't read. Please try again."}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ready-check", methods=["POST"])
def ready_check():
    """Save the SE's final plan over the deal, then flag any remaining gaps."""
    body = request.json or {}
    meddic = body.get("meddic") or {}
    try:
        prescription = normalise_prescription(body.get("prescription"))
    except MalformedOutputError as e:
        return jsonify({"error": str(e)}), 400
    try:
        saved = bool(body.get("deal_id")) and store.update_prescription(int(body["deal_id"]), prescription)
        try:
            review = client.send_message(
                message=json.dumps({"meddic": meddic, "demo_plan": plan_for_prompt(prescription)}),
                system=READY_CHECK_SYSTEM_PROMPT, max_tokens=READY_CHECK_MAX_TOKENS)
        except Exception as e:
            # The rule checks still run; build_ready_check notes the review was unavailable.
            app.logger.error("Readiness review call failed: %s", e)
            review = ""
        return jsonify({"result": build_ready_check(meddic, prescription, review), "saved": saved})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
    
