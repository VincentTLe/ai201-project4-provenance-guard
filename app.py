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
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import db
from detection import combine, lexical_signal, llm_signal, stylometry_signal
from labels import make_label

app = Flask(__name__)
db.init_db()

# Rate limiting (see README for chosen limits + reasoning). In-memory storage is
# fine for local/dev; a real deployment would use Redis so limits survive restarts
# and span multiple workers.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    data = request.get_json(silent=True) or {}
    raw_text = data.get("text")
    raw_creator = data.get("creator_id")

    # Both fields must be non-empty strings. Guard against non-string JSON values
    # (e.g. numbers, lists) so they return a clean 400 rather than crashing on .strip().
    if not isinstance(raw_text, str) or not isinstance(raw_creator, str):
        return jsonify({"error": "'text' and 'creator_id' must be strings."}), 400
    text = raw_text.strip()
    creator_id = raw_creator.strip()
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
    label = make_label(attribution, confidence)
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
            "label": label,
        }
    )


@app.route("/appeal", methods=["POST"])
def appeal():
    """A creator contests a classification. Flips status to 'under_review' and logs
    the appeal alongside the original decision. No automated re-classification —
    a human reviewer owns the outcome. See planning.md §4.
    """
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id")
    reasoning = data.get("creator_reasoning")

    if not isinstance(content_id, str) or not isinstance(reasoning, str):
        return jsonify({"error": "'content_id' and 'creator_reasoning' must be strings."}), 400
    content_id = content_id.strip()
    reasoning = reasoning.strip()
    if not content_id or not reasoning:
        return jsonify({"error": "Both 'content_id' and 'creator_reasoning' are required."}), 400

    record = db.get_content_record(content_id)
    if record is None:
        return jsonify({"error": f"No content found with id '{content_id}'."}), 404

    db.update_content_status(content_id, "under_review")
    timestamp = db.utc_now()

    # Log the appeal beside the original decision it contests.
    db.add_audit_entry(
        content_id,
        "appeal",
        {
            "content_id": content_id,
            "creator_id": record["creator_id"],
            "timestamp": timestamp,
            "event": "appeal_filed",
            "creator_reasoning": reasoning,
            "original_attribution": record["attribution"],
            "original_confidence": record["confidence"],
            "original_ai_probability": record["ai_probability"],
            "llm_score": record["llm_score"],
            "stylometric_score": record["stylometric_score"],
            "lexical_score": record["lexical_score"],
            "status": "under_review",
        },
    )

    return jsonify(
        {
            "content_id": content_id,
            "status": "under_review",
            "message": "Your appeal has been received and this content is now under "
                       "review by a human moderator. The original automated "
                       "classification has been logged alongside your appeal.",
        }
    )


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": db.get_recent_log()})


@app.route("/analytics", methods=["GET"])
def analytics():
    """Stretch: detection-pattern dashboard — verdict distribution, appeal rate,
    and mean confidence, read straight from the audit store."""
    return jsonify(db.get_analytics())


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
