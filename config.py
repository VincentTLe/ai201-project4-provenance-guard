"""Central configuration for Provenance Guard.

Detection weights/thresholds live here so they are a single source of truth the
scoring logic (Milestone 4) reads from — see planning.md §1 and §2.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Groq (Signal 1) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LLM_MODEL = "llama-3.3-70b-versatile"

# --- Storage ---
DB_PATH = os.getenv("PROVENANCE_DB", "provenance.db")

# --- Detection combination (used from Milestone 4 onward) ---
# Weighted vote over the three signals; see planning.md §1.
SIGNAL_WEIGHTS = {"llm": 0.50, "stylometric": 0.30, "lexical": 0.20}

# Asymmetric verdict thresholds on the combined ai_probability; see planning.md §2.
AI_THRESHOLD = 0.70        # >= this -> likely_ai
HUMAN_THRESHOLD = 0.35     # <  this -> likely_human ; in between -> uncertain

# Verdict labels used across storage and responses.
VERDICT_AI = "likely_ai"
VERDICT_HUMAN = "likely_human"
VERDICT_UNCERTAIN = "uncertain"
