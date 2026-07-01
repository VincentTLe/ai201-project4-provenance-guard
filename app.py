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
from detection import combine, lexical_signal, llm_signal, stylometry_signal

app = Flask(__name__)
db.init_db()

# M5 placeholder — the reader-facing transparency label is generated in Milestone 5.
PLACEHOLDER_LABEL = "Transparency label pending (Milestone 5)."


@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    creator_id = (data.get("creator_id") or "").strip()

    if not text or not creator_id:
        return jsonify({"error": "Both 'text' and 'creator_id' are required."}), 400

    content_id = str(uuid.uuid4())
    timestamp = db.utc_now()
    word_count = len(text.split())

    # --- Multi-signal detection pipeline ---
    llm = llm_signal(text)
    stylo = stylometry_signal(text)
    lexical = lexical_signal(text)

    result = combine(
        llm["ai_probability"],
        stylo["ai_probability"],
        lexical["ai_probability"],
        word_count,
    )
    attribution = result["verdict"]
    confidence = result["confidence"]
    status = "classified"

    # --- Persist content record ---
    db.create_content_record(
        content_id=content_id,
        creator_id=creator_id,
        text=text,
        attribution=attribution,
        confidence=confidence,
        ai_probability=result["ai_probability"],
        llm_score=llm["ai_probability"],
        stylometric_score=stylo["ai_probability"],
        lexical_score=lexical["ai_probability"],
        status=status,
        created_at=timestamp,
    )

    # --- Structured audit-log entry (all three signals + combined result) ---
    db.add_audit_entry(
        content_id,
        "classification",
        {
            "content_id": content_id,
            "creator_id": creator_id,
            "timestamp": timestamp,
            "attribution": attribution,
            "confidence": confidence,
            "ai_probability": result["ai_probability"],
            "llm_score": llm["ai_probability"],
            "stylometric_score": stylo["ai_probability"],
            "lexical_score": lexical["ai_probability"],
            "signal_spread": result["signal_spread"],
            "llm_rationale": llm["rationale"],
            "scoring_notes": result["notes"],
            "status": status,
        },
    )

    return jsonify(
        {
            "content_id": content_id,
            "attribution": attribution,
            "confidence": confidence,
            "ai_probability": result["ai_probability"],
            "signals": {
                "llm": llm["ai_probability"],
                "stylometric": stylo["ai_probability"],
                "lexical": lexical["ai_probability"],
            },
            "label": PLACEHOLDER_LABEL,  # real label at M5
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
