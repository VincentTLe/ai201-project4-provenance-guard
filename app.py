"""Provenance Guard — Flask API.

Milestone 3 scope:
  POST /submit  — accept {text, creator_id}, run Signal 1 (Groq LLM), persist a
                  content record + a structured audit-log entry, and return
                  content_id + a provisional attribution. Confidence and the
                  transparency label are placeholders until M4/M5.
  GET  /log     — return recent structured audit-log entries as JSON.

The full multi-signal confidence score (M4), transparency label (M5), appeals
endpoint (M5), and rate limiting (M5) build on this skeleton.
"""
import uuid

from flask import Flask, jsonify, request

import db
from config import AI_THRESHOLD, HUMAN_THRESHOLD, VERDICT_AI, VERDICT_HUMAN, VERDICT_UNCERTAIN
from detection import llm_signal

app = Flask(__name__)
db.init_db()

# M3 placeholders — real values arrive with the confidence combiner (M4) and
# transparency label (M5).
PLACEHOLDER_LABEL = "Full transparency label pending multi-signal scoring (Milestone 5)."


def _provisional_attribution(ai_probability: float) -> str:
    """Signal-1-only attribution for M3, using the spec's asymmetric thresholds.

    This is superseded in M4 once all three signals are combined; for now it lets
    /submit return a real, inspectable attribution from the one working signal.
    """
    if ai_probability >= AI_THRESHOLD:
        return VERDICT_AI
    if ai_probability < HUMAN_THRESHOLD:
        return VERDICT_HUMAN
    return VERDICT_UNCERTAIN


@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    creator_id = (data.get("creator_id") or "").strip()

    if not text or not creator_id:
        return jsonify({"error": "Both 'text' and 'creator_id' are required."}), 400

    content_id = str(uuid.uuid4())
    timestamp = db.utc_now()

    # --- Signal 1: Groq LLM judge ---
    signal = llm_signal(text)
    llm_score = signal["ai_probability"]

    attribution = _provisional_attribution(llm_score)
    confidence = None  # placeholder until M4 combines all signals
    status = "classified"

    # --- Persist content record ---
    db.create_content_record(
        content_id=content_id,
        creator_id=creator_id,
        text=text,
        attribution=attribution,
        confidence=confidence,
        ai_probability=llm_score,
        llm_score=llm_score,
        status=status,
        created_at=timestamp,
    )

    # --- Structured audit-log entry ---
    db.add_audit_entry(
        content_id,
        "classification",
        {
            "content_id": content_id,
            "creator_id": creator_id,
            "timestamp": timestamp,
            "attribution": attribution,
            "confidence": confidence,
            "llm_score": llm_score,
            "llm_rationale": signal["rationale"],
            "status": status,
        },
    )

    return jsonify(
        {
            "content_id": content_id,
            "attribution": attribution,
            "confidence": confidence,  # placeholder (M4)
            "signals": {"llm": llm_score},
            "label": PLACEHOLDER_LABEL,  # placeholder (M5)
        }
    )


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": db.get_recent_log()})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
