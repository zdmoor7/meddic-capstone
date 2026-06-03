import os
import re
from flask import Flask, request, render_template, jsonify
from dotenv import load_dotenv
from api_wrapper import AnthropicClient
from rag import load_docs_to_chroma, retrieve_relevant_chunks
import json
from database import save_insight, create_table

load_dotenv()

app = Flask(__name__)
client = AnthropicClient(api_key=os.getenv("ANTHROPIC_API_KEY"))
create_table()
load_docs_to_chroma()

MEDDIC_SYSTEM_PROMPT = """You are a tool that organises messy discovery notes into a clean, organised plan that adheres to the MEDDIC sales qualification framework. Before outputting JSON, analyse each piece of information against all six MEDDIC categories and identify every category it could belong to. When you get the notes, separate the contents according to the extent to which they align with each category. If content aligns with two or more categories, flag this with ⚠️ and specify which categories with AND. If there is no relevant content for a category, output ❓ and flag that this is the case. Output should follow this JSON structure exactly, no explanation:
{
  "Metrics": {"content": "...", "flag": ""},
  "Economic Buyer": {"content": "...", "flag": ""},
  "Decision Criteria": {"content": "...", "flag": ""},
  "Decision Process": {"content": "...", "flag": ""},
  "Identify Pain": {"content": "...", "flag": ""},
  "Champion": {"content": "...", "flag": ""}
}
Issue all output in JSON only, no explanation."""

PRESCRIPTION_SYSTEM_PROMPT = """You are a senior sales engineering advisor. You receive a structured MEDDIC analysis of a discovery call and produce a concise deal prescription for the SE.

Your output must contain exactly three sections:

1. DEAL OVERVIEW: A 3-4 sentence summary of the opportunity, the key stakeholders, and the stage of the deal based on the MEDDIC data.

2. DEMO PRESCRIPTION: The story the SE should tell in the demo. Which features to focus on, in which order, and why. Frame it as a narrative arc that maps directly to the identified pain and decision criteria.

3. MARKET CONTEXT: 3-5 bullet points on relevant competitors, industry dynamics, and why this product is well-positioned for this specific prospect.

Output in JSON with this structure:
{
  "deal_overview": "...",
  "demo_prescription": "...",
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
        result = client.send_message(message=notes, system=MEDDIC_SYSTEM_PROMPT)
        clean = re.sub(r'```json\n|```', '', result).strip()
        return jsonify({"result": clean})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/get-prescription", methods=["POST"])
def get_prescription():
    meddic_output = request.json.get("meddic_output", "")
    buyer = request.json.get("buyer", "")
    try:
        chunks = retrieve_relevant_chunks(meddic_output)
        augmented_prompt = PRESCRIPTION_SYSTEM_PROMPT + "\n\nRelevant product documentation:\n" + "\n".join(chunks)
        result = client.send_message(message=meddic_output, system=augmented_prompt)
        clean = re.sub(r'```json\n|```', '', result).strip()
        prescription = json.loads(clean)
        meddic_parsed = json.loads(meddic_output)
        problem = meddic_parsed["Identify Pain"]["content"]
        relevant_features = prescription["demo_prescription"]
        save_insight(buyer, problem, relevant_features, None)
        return jsonify({"result": clean})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
        



if __name__ == "__main__":
    app.run(debug=True)
    
