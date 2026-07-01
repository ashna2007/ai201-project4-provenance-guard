"""
Provenance Guard - Flask backend
=================================

Classifies submitted text as "likely_ai", "likely_human", or "uncertain"
using two independent detection signals:

  Signal 1 (LLM):        Groq + llama-3.3-70b-versatile  -> AI-likeness score
  Signal 2 (Stylometry): pure-Python writing heuristics  -> AI-likeness score

The two scores are combined into a single confidence score, mapped to a
transparency label, logged to an append-only audit log (audit_log.json),
and returned to the caller. Creators may appeal a decision, which flips the
stored status to "under_review" and records their reasoning.

Run with:  python app.py
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone
from threading import Lock

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from groq import Groq

# ---------------------------------------------------------------------------
# Configuration & setup
# ---------------------------------------------------------------------------

# Load environment variables (GROQ_API_KEY) from a local .env file.
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "llama-3.3-70b-versatile"

# Path to the JSON audit log. Every decision and appeal is persisted here.
AUDIT_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit_log.json")

# A single Groq client, created once and reused across requests. If the API
# key is missing we keep the client as None so the app still boots and the LLM
# signal degrades gracefully instead of crashing at import time.
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Guards concurrent read/modify/write access to the audit log file so that two
# simultaneous requests cannot corrupt it.
_log_lock = Lock()

app = Flask(__name__)

# Rate limiting: in-memory storage, applied per-endpoint (see /submit below).
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri="memory://",
)

# ---------------------------------------------------------------------------
# Transparency labels
# ---------------------------------------------------------------------------

# Human-readable explanations returned alongside each classification. Keyed by
# the attribution value so the label always matches the decision.
TRANSPARENCY_LABELS = {
    "likely_ai": (
        "This work appears likely to be AI-generated. Our system found strong "
        "signals of automated writing, but this decision is not final and the "
        "creator may appeal."
    ),
    "likely_human": (
        "This work appears likely to be human-written. Our system found stronger "
        "signs of original human authorship than automated generation."
    ),
    "uncertain": (
        "We are not confident enough to label this work as AI-generated or "
        "human-written. The writing has mixed signals, so readers should treat "
        "the attribution as uncertain."
    ),
}

# ---------------------------------------------------------------------------
# Audit log helpers
# ---------------------------------------------------------------------------


def _load_log():
    """Read the audit log from disk, returning a list of entries.

    Missing or malformed files are treated as an empty log so the app is
    self-healing on first run.
    """
    if not os.path.exists(AUDIT_LOG_PATH):
        return []
    try:
        with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # Support both a bare list and a {"entries": [...]} wrapper.
        if isinstance(data, dict):
            return data.get("entries", [])
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _save_log(entries):
    """Write the full list of entries back to disk."""
    with open(AUDIT_LOG_PATH, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2)


def _now_iso():
    """Current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Detection Signal 1: LLM classification (Groq)
# ---------------------------------------------------------------------------


def llm_score(text):
    """Ask the LLM how AI-like the text is.

    Returns a float in [0.0, 1.0] where higher means more AI-like. If the Groq
    client is unavailable or the call fails, we return a neutral 0.5 so the
    pipeline can still produce an (appropriately uncertain) result.
    """
    if groq_client is None:
        return 0.5

    # A tightly scoped prompt: we want a single number, nothing else, so it is
    # trivial to parse and cannot drift into prose.
    system_prompt = (
        "You are an AI-text detection expert. You judge whether a piece of text "
        "was written by an AI language model or by a human. Consider tone, "
        "semantic flow, generic or template-like phrasing, over-polished "
        "structure, and signs of a natural personal voice. Respond with ONLY a "
        "single number between 0.0 and 1.0, where 1.0 means almost certainly "
        "AI-generated and 0.0 means almost certainly human-written. Output no "
        "words, no explanation, just the number."
    )

    try:
        completion = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            temperature=0.0,
            max_tokens=10,
        )
        raw = completion.choices[0].message.content.strip()

        # Extract the first floating-point number found in the response.
        match = re.search(r"[0-1](?:\.\d+)?|\.\d+", raw)
        if not match:
            return 0.5
        score = float(match.group())
        # Clamp defensively in case the model returns something out of range.
        return max(0.0, min(1.0, score))
    except Exception:
        # Any network / API / parsing error -> neutral score.
        return 0.5


# ---------------------------------------------------------------------------
# Detection Signal 2: Stylometric heuristics (pure Python)
# ---------------------------------------------------------------------------


def stylometric_score(text):
    """Estimate AI-likeness from measurable writing statistics.

    Combines four sub-metrics, each normalized to [0, 1] where higher = more
    AI-like, then averages them. Returns a float in [0.0, 1.0].

    Sub-metrics:
      1. Sentence length variation  - AI text tends to be uniform (low variation).
      2. Vocabulary diversity (TTR) - AI text can be moderately repetitive.
      3. Punctuation density        - very low density reads as mechanical.
      4. Casual markers             - human writing uses more informal cues.
    """
    text = (text or "").strip()
    if not text:
        return 0.5

    # --- Tokenize into sentences and words -------------------------------
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    words = re.findall(r"\b\w+\b", text.lower())

    if not words:
        return 0.5

    # --- 1. Sentence length variation ------------------------------------
    # Uniform sentence lengths -> more AI-like (score near 1).
    sentence_lengths = [len(re.findall(r"\b\w+\b", s)) for s in sentences] or [len(words)]
    mean_len = sum(sentence_lengths) / len(sentence_lengths)
    if len(sentence_lengths) > 1 and mean_len > 0:
        variance = sum((l - mean_len) ** 2 for l in sentence_lengths) / len(sentence_lengths)
        std_dev = variance ** 0.5
        # Coefficient of variation: 0 = perfectly uniform. Humans typically
        # sit around 0.5+. Map low variation -> high AI score.
        cv = std_dev / mean_len
        uniformity_score = 1.0 - (cv / 0.6)
    else:
        # A single sentence gives us no variation signal -> neutral.
        uniformity_score = 0.5
    uniformity_score = max(0.0, min(1.0, uniformity_score))

    # --- 2. Vocabulary diversity (type-token ratio) ----------------------
    # TTR = unique words / total words. Lower TTR (repetitive) -> more AI-like.
    ttr = len(set(words)) / len(words)
    # Human writing commonly lands around 0.6+ TTR for short samples. Map a
    # high TTR to a low AI score and vice-versa.
    repetition_score = max(0.0, min(1.0, 1.0 - (ttr - 0.4) / 0.4))

    # --- 3. Punctuation density ------------------------------------------
    # Punctuation marks per word. Very sparse punctuation reads mechanical.
    punctuation_count = len(re.findall(r"[,;:\-\(\)\"'!?]", text))
    punctuation_density = punctuation_count / len(words)
    # Humans use varied punctuation (~0.15+ per word). Low density -> AI-like.
    punctuation_score = max(0.0, min(1.0, 1.0 - (punctuation_density / 0.15)))

    # --- 4. Casual markers ------------------------------------------------
    # Contractions, informal words, and interjections signal human authorship.
    casual_markers = {
        "i'm", "don't", "can't", "won't", "it's", "that's", "i've", "you're",
        "gonna", "wanna", "kinda", "yeah", "ok", "okay", "lol", "haha",
        "honestly", "basically", "actually", "like", "stuff", "thing", "really",
        "pretty", "super", "tbh", "imo",
    }
    marker_hits = sum(1 for w in words if w in casual_markers)
    marker_hits += len(re.findall(r"\b\w+'\w+\b", text.lower()))  # any contraction
    casual_ratio = marker_hits / len(words)
    # Many casual markers -> human. Map presence of casual language to a low
    # AI score.
    casual_score = max(0.0, min(1.0, 1.0 - (casual_ratio / 0.05)))

    # --- Combine sub-metrics (equal weight) ------------------------------
    combined = (
        uniformity_score
        + repetition_score
        + punctuation_score
        + casual_score
    ) / 4.0
    return max(0.0, min(1.0, combined))


# ---------------------------------------------------------------------------
# Confidence scoring & label selection
# ---------------------------------------------------------------------------


def classify(llm, stylo):
    """Combine the two signals and map to an attribution + label.

    combined = 0.65 * llm_score + 0.35 * stylometric_score

      >= 0.75         -> likely_ai
      0.40 - 0.74     -> uncertain
      <  0.40         -> likely_human
    """
    combined = 0.65 * llm + 0.35 * stylo

    if combined >= 0.75:
        attribution = "likely_ai"
    elif combined >= 0.40:
        attribution = "uncertain"
    else:
        attribution = "likely_human"

    return attribution, round(combined, 4), TRANSPARENCY_LABELS[attribution]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute")
@limiter.limit("100 per day")
def submit():
    """Classify a submitted text and log the decision.

    Expects JSON: {"text": "...", "creator_id": "..."}
    """
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    creator_id = data.get("creator_id")

    # --- Input validation ------------------------------------------------
    if not text or not isinstance(text, str) or not text.strip():
        return jsonify({"error": "Field 'text' is required and must be a non-empty string."}), 400
    if not creator_id or not isinstance(creator_id, str):
        return jsonify({"error": "Field 'creator_id' is required and must be a string."}), 400

    # --- Run both detection signals --------------------------------------
    signal_llm = llm_score(text)
    signal_stylo = stylometric_score(text)

    # --- Combine and label ------------------------------------------------
    attribution, confidence, label = classify(signal_llm, signal_stylo)

    # --- Build the audit log entry ---------------------------------------
    content_id = str(uuid.uuid4())
    entry = {
        "timestamp": _now_iso(),
        "content_id": content_id,
        "creator_id": creator_id,
        "attribution": attribution,
        "confidence": confidence,
        "llm_score": round(signal_llm, 4),
        "stylometric_score": round(signal_stylo, 4),
        "label": label,
        "status": "classified",
    }

    # --- Persist under a lock to avoid concurrent-write corruption -------
    with _log_lock:
        entries = _load_log()
        entries.append(entry)
        _save_log(entries)

    # --- Response ---------------------------------------------------------
    return jsonify({
        "content_id": content_id,
        "attribution": attribution,
        "confidence": confidence,
        "llm_score": round(signal_llm, 4),
        "stylometric_score": round(signal_stylo, 4),
        "label": label,
        "status": entry["status"],
    }), 200


@app.route("/appeal", methods=["POST"])
def appeal():
    """Record a creator's appeal against a prior decision.

    Expects JSON: {"content_id": "...", "creator_reasoning": "..."}
    Updates the matching audit entry: status -> "under_review" and stores the
    creator's reasoning.
    """
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id")
    creator_reasoning = data.get("creator_reasoning")

    # --- Input validation ------------------------------------------------
    if not content_id or not isinstance(content_id, str):
        return jsonify({"error": "Field 'content_id' is required and must be a string."}), 400
    if not creator_reasoning or not isinstance(creator_reasoning, str) or not creator_reasoning.strip():
        return jsonify({"error": "Field 'creator_reasoning' is required and must be a non-empty string."}), 400

    # --- Find and update the matching entry ------------------------------
    with _log_lock:
        entries = _load_log()
        target = None
        for entry in entries:
            if entry.get("content_id") == content_id:
                entry["status"] = "under_review"
                entry["creator_reasoning"] = creator_reasoning
                entry["appeal_timestamp"] = _now_iso()
                target = entry
                break

        if target is None:
            return jsonify({"error": f"No submission found with content_id '{content_id}'."}), 404

        _save_log(entries)

    return jsonify({
        "content_id": content_id,
        "status": "under_review",
        "creator_reasoning": creator_reasoning,
        "message": "Appeal received. This content is now under review.",
    }), 200


@app.route("/log", methods=["GET"])
def get_log():
    """Return every audit log entry."""
    with _log_lock:
        entries = _load_log()
    return jsonify(entries), 200


# ---------------------------------------------------------------------------
# Error handlers (always return JSON, never HTML)
# ---------------------------------------------------------------------------


@app.errorhandler(429)
def rate_limit_exceeded(error):
    """Return JSON when a rate limit is hit."""
    return jsonify({
        "error": "Rate limit exceeded.",
        "detail": str(error.description),
    }), 429


@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found."}), 404


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Debug server is fine for a class project; use a WSGI server in production.
     app.run(debug=True, port=5001)


