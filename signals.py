"""
Lightweight, deterministic rule-based detectors for the three conversational
signals the challenge specifically grades:
  1. Auto-reply detection (WhatsApp Business canned replies)
  2. Intent-transition detection ("yes, let's do it" -> switch to action mode)
  3. Not-interested / STOP detection (graceful exit)

These run BEFORE we call the LLM for a reply, so obvious cases are handled
instantly and deterministically rather than hoping the LLM classifies them
right every time. Kept in English + common Hindi/Hinglish phrasing since the
brief explicitly expects Hindi-English code-mix merchants.
"""
import re

# --- Canned WhatsApp Business auto-reply phrasing (recognizable even on first message) ---
_AUTO_REPLY_PHRASES = [
    r"thank you for (contacting|reaching out|your message)",
    r"we (will|shall) get back to you",
    r"currently (unavailable|away|closed)",
    r"this is an automated (message|response|reply)",
    r"hamari team tak pahuncha",
    r"main aapki (yeh )?baatein.*team tak",
    r"main ek automated assistant",
    r"aapka (sandesh|message) mil gaya hai",
    r"business hours (are|hain)",
    r"we('| a)re currently closed",
]
_AUTO_REPLY_RE = re.compile("|".join(_AUTO_REPLY_PHRASES), re.IGNORECASE)

# --- Explicit "yes, do it" intent transition (English + Hinglish) ---
_INTENT_YES_PHRASES = [
    r"\byes\b", r"\by\b", r"let'?s do it", r"lets do it", r"go ahead",
    r"sounds good", r"sure,? (do it|proceed|go ahead)", r"please proceed",
    r"haan\s*(chalo|karo|kar do)?", r"theek hai\s*(chalo|karo)?", r"kar do",
    r"ok(ay)? (chalo|let'?s go|go ahead)?", r"i want to (join|do this)",
    r"mujhe (join|karna) (karna )?hai", r"chalo karte hai",
]
_INTENT_YES_RE = re.compile("|".join(_INTENT_YES_PHRASES), re.IGNORECASE)

# --- Not interested / hard stop ---
_NOT_INTERESTED_PHRASES = [
    r"\bstop\b", r"not interested", r"no thanks", r"nahi chahiye",
    r"band karo", r"unsubscribe", r"mujhe nahi karna", r"leave me alone",
    r"don'?t (message|contact|text) me",
]
_NOT_INTERESTED_RE = re.compile("|".join(_NOT_INTERESTED_PHRASES), re.IGNORECASE)

# --- Asked for time / not now (but not a hard no) ---
_WAIT_PHRASES = [
    r"call me later", r"not now", r"abhi nahi", r"baad me[i]?n?",
    r"give me (some|a) time", r"busy right now", r"thodi der baad",
    r"let me think", r"\bi'?ll get back to you\b",
]
_WAIT_RE = re.compile("|".join(_WAIT_PHRASES), re.IGNORECASE)


def looks_like_wait_request(text: str) -> bool:
    """Merchant wants time, but hasn't declined outright."""
    return bool(_WAIT_RE.search(text or ""))


def looks_like_auto_reply_text(text: str) -> bool:
    """Recognizable canned-reply phrasing, even on the FIRST occurrence."""
    return bool(_AUTO_REPLY_RE.search(text or ""))


def looks_like_intent_yes(text: str) -> bool:
    """Merchant explicitly agreeing / ready to proceed."""
    return bool(_INTENT_YES_RE.search(text or ""))


def looks_like_not_interested(text: str) -> bool:
    """Merchant explicitly declining or asking to stop."""
    return bool(_NOT_INTERESTED_RE.search(text or ""))


def classify_quick_signal(text: str) -> str:
    """
    One-shot classification used by /v1/reply before calling the LLM.
    Returns one of: "not_interested", "wait_requested", "auto_reply_phrase", "intent_yes", "other"
    """
    if looks_like_not_interested(text):
        return "not_interested"
    if looks_like_wait_request(text):
        return "wait_requested"
    if looks_like_auto_reply_text(text):
        return "auto_reply_phrase"
    if looks_like_intent_yes(text):
        return "intent_yes"
    return "other"


if __name__ == "__main__":
    tests = [
        ("Yes, send me the abstract", "intent_yes"),
        ("Mujhe magicpin judrna hai. Haan chalo karo", "intent_yes"),
        ("Thank you for contacting us, our team will get back to you", "auto_reply_phrase"),
        ("STOP", "not_interested"),
        ("Not interested right now", "not_interested"),
        ("Can you also help me file my GST?", "other"),
    ]
    for text, expected in tests:
        got = classify_quick_signal(text)
        status = "OK " if got == expected else "FAIL"
        print(f"[{status}] {text!r} -> {got} (expected {expected})")