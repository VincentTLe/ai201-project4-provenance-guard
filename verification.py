"""Provenance-certificate verification (stretch feature).

A creator earns a "verified human" credential by completing a challenge/response
step: `/verify/start` issues a random pledge sentence, and the creator must type it
back exactly to `/verify/complete`. Typing a specific phrase back is a deliberate
human action — a lightweight, self-contained stand-in for a real identity/liveness
check (which a production system would replace with proper KYC). See planning.md.
"""
import secrets

# Pledge sentences the creator must type back verbatim. Kept short and human-readable.
PLEDGE_PHRASES = [
    "I am a human creator and this is my own original work.",
    "I write my own words and I stand behind this creation.",
    "This work comes from my own hand, my own voice, my own effort.",
    "I am a real person and I authored this piece myself.",
    "My creativity is my own and I verify that I am human.",
]


def new_challenge_phrase() -> str:
    """Return a random pledge sentence for a verification challenge."""
    return secrets.choice(PLEDGE_PHRASES)


def _normalize(s: str) -> str:
    """Case-insensitive, whitespace-collapsed comparison — forgiving of spacing/case."""
    return " ".join(s.lower().split())


def responses_match(expected: str, got: str) -> bool:
    """True if the typed-back response matches the issued phrase."""
    return _normalize(expected) == _normalize(got)
