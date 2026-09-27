"""
The core compose() function: turns (category, merchant, trigger, customer?)
into a ComposedMessage dict, per challenge-brief.md §5.
Also compose_reply() for multi-turn conversation continuation.
"""
import json
import re
from groq_client import call_llm
from dataset_loader import Dataset

_VALID_CTAS = {"binary_yes_stop", "open_ended", "none"}

_SHARED_RULES = """
FORMATTING RULES (WhatsApp-native only):
- Bold: single asterisks like *this*, NEVER double asterisks like **this**.
- No hashtags (#like #this). No markdown headers. No emoji spam — at most one
  emoji, and only if the category voice allows it (clinical categories: zero emoji).
- No hype phrases: "Limited slots", "act fast", "AMAZING", "hurry", "don't miss out",
  excessive exclamation marks. A peer/clinical voice never uses retail-promo language.
- Exactly ONE call-to-action. Never present multiple options as "Reply YES for X, NO
  for Y" — pick the single most useful ask.
"""

SYSTEM_PROMPT = """You are Vera-Beta, an AI assistant that writes WhatsApp messages on \
behalf of "magicpin" to Indian local-business merchants (and sometimes to their \
customers, on the merchant's behalf).

You will be given four JSON context blocks: CATEGORY, MERCHANT, TRIGGER, and \
optionally CUSTOMER. Write ONE WhatsApp message using ONLY facts present in these \
blocks. Follow these rules exactly:

1. SPECIFICITY: anchor the message on a concrete, verifiable fact from the contexts \
   (a real number, date, headline, or peer stat). Never write generic filler like \
   "grow your business" or "10% off" if a specific offer/number is available instead.
2. CATEGORY FIT: match the category's voice (tone, allowed vocabulary, taboo words) \
   EXACTLY as given in CATEGORY.voice. A clinical/peer category (dentists, doctors) \
   must sound like a knowledgeable peer, never retail-promo hype.
3. MERCHANT FIT: personalize to this merchant's actual numbers, offers, signals, and \
   conversation history. Honor their language preference (identity.languages) — \
   Hindi-English code-mix is encouraged when "hi" is present, using natural Hinglish.
4. TRIGGER RELEVANCE: explicitly convey WHY this message is happening now — reference \
   the specific trigger. Do not send a generic nudge with no stated reason.
5. ENGAGEMENT COMPULSION: use at least one lever — specificity, loss aversion, social \
   proof, effort externalization, curiosity, reciprocity, asking the merchant a \
   question, or a single binary CTA (reply YES/STOP).
6. NEVER FABRICATE: if a fact isn't literally present in the provided context blocks, \
   do not invent it. No fake research citations, no fake competitor names, no fake offers.
7. NO PREAMBLE: no "I hope you're doing well" openers. Don't reintroduce yourself if \
   conversation_history shows prior turns. Keep it concise — the CTA should land in the \
   final sentence, not be buried.
8. CUSTOMER-FACING messages (when CUSTOMER is provided) must sound like the merchant \
   speaking, follow the category's customer-facing voice rules (no medical claims, no \
   "guaranteed"), and use the customer's name + language_pref + preferences.
""" + _SHARED_RULES + """
Output ONLY a single JSON object (no markdown fences, no commentary, no text before or \
after the JSON, no nested/duplicate keys) with EXACTLY these four keys and nothing else:
{
  "body": "<the WhatsApp message text — plain text only, must not contain the literal characters '\\"cta\\"' or '\\"rationale\\"' anywhere>",
  "cta": "binary_yes_stop" | "open_ended" | "none",
  "send_as": "vera" | "merchant_on_behalf",
  "rationale": "<one sentence: why this message, what it should achieve>"
}
"""

REPLY_SYSTEM_PROMPT = """You are Vera-Beta, continuing an in-progress WhatsApp conversation \
with an Indian merchant (or their customer) on behalf of magicpin. You will be given the \
CATEGORY, MERCHANT context, optional CUSTOMER context, the ORIGINAL TRIGGER that started \
this conversation, the conversation history so far, and the latest incoming message. You \
will also be told the MODE for this turn — follow it exactly:

- MODE=action_now: the other party just gave clear explicit agreement/intent (e.g. "yes",
  "let's do it", "go ahead"). Do NOT ask another qualifying question. Move straight into
  the concrete next step — and that next step MUST be built from real facts in CATEGORY,
  MERCHANT, or ORIGINAL TRIGGER (e.g. the actual digest item, the actual offer, the actual
  signal). If your own earlier message promised something ("a draft", "the abstract", "an
  SOP update"), fulfill that promise using ONLY the real content already available to you —
  NEVER invent unrelated generic business content (e.g. made-up compliance steps, customer
  service scripts, escalation procedures) that isn't grounded in the given data.
- MODE=normal: continue the conversation naturally, advancing toward the original goal.
  Answer any question asked, using only real data. If they raise an unrelated topic (e.g.
  asking for help with something magicpin/Vera doesn't do), politely decline that part in
  one sentence and return to the original topic — stay on-mission, do not be rude even if
  they were rude.
- MODE=probe_auto_reply: their reply looked like a generic WhatsApp Business auto-reply.
  Try ONE short, friendly nudge asking them personally to look for 2 minutes. Do not repeat
  your last message.

ANTI-HALLUCINATION (critical): every concrete claim, number, or "next step" you write must \
trace back to something literally present in CATEGORY, MERCHANT, ORIGINAL TRIGGER, CUSTOMER, \
or the conversation history below. If you don't have enough real material to fulfill a \
promise, say you're preparing it and will follow up shortly — do NOT fabricate content to \
fill the gap.

You MUST still match CATEGORY.voice exactly (a clinical category stays clinical even
mid-conversation — do not drift into retail-promo hype just because the merchant engaged).
Match their language (Hindi-English code-mix where appropriate). No preamble, no
re-introduction. Never repeat a message body you already sent in this conversation (it is
provided to you) — always say something meaningfully new.
""" + _SHARED_RULES + """
Output ONLY a single JSON object (no markdown fences, no commentary, no nested/duplicate
keys) with EXACTLY these three keys and nothing else:
{
  "body": "<message text, plain text only, must not contain the literal characters '\\"cta\\"' or '\\"rationale\\"' anywhere>",
  "cta": "binary_yes_stop" | "open_ended" | "none",
  "rationale": "<one short sentence>"
}
"""


def _extract_json(text: str) -> dict:
    """LLMs sometimes wrap JSON in markdown fences or add stray text. Extract robustly."""
    text = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
    return json.loads(text)


def _looks_malformed(body: str, cta: str) -> bool:
    """Catches syntactically-valid-but-corrupted JSON (leaked keys inside body, bad cta enum)."""
    if not body:
        return True
    if cta not in _VALID_CTAS:
        return True
    leak_markers = ['"cta"', '"rationale"', '"body"', '"send_as"']
    if any(marker in body for marker in leak_markers):
        return True
    if "**" in body:  # double-asterisk markdown leaked through despite instructions
        return True
    return False


def _get_structured_response(system_prompt: str, user_prompt: str, required_keys: set[str]) -> dict:
    """Calls the LLM, parses JSON, validates content, retries once on any failure."""
    try:
        raw = call_llm(system_prompt, user_prompt, temperature=0.0)
    except Exception as e:
        print(f"[composer] LLM call failed entirely: {e}")
        return {"body": "", "cta": "none", "send_as": "vera",
                "rationale": "composer unavailable (LLM call failed)"}

    def _try_parse(text: str) -> dict | None:
        try:
            parsed = _extract_json(text)
        except (json.JSONDecodeError, ValueError):
            return None
        if not required_keys.issubset(parsed.keys()):
            return None
        if _looks_malformed(parsed.get("body", ""), parsed.get("cta", "")):
            return None
        return parsed

    result = _try_parse(raw)
    if result is not None:
        return result

    # One repair attempt: explicit, strict re-ask.
    repair_prompt = (
        f"Your previous response was invalid or malformed:\n\n{raw}\n\n"
        f"Re-output ONLY a single clean JSON object with EXACTLY these keys: "
        f"{sorted(required_keys)}. Plain text values only. No markdown fences, "
        f"no double asterisks, no nested JSON-looking text inside 'body'."
    )
    raw2 = call_llm(system_prompt, repair_prompt, temperature=0.0)
    result = _try_parse(raw2)
    if result is not None:
        return result

    # Give up gracefully rather than crashing the whole request.
    return {"body": "", "cta": "none", "send_as": "vera", "rationale": "composer failed to produce valid output"}

def _trim_category_for_prompt(category: dict) -> dict:
    """Category JSON has large arrays (full digest, content library, trend_signals)
    that eat tokens without helping THIS message. Keep only what's broadly useful."""
    return {
        "slug": category.get("slug"),
        "display_name": category.get("display_name"),
        "voice": category.get("voice"),
        "offer_catalog": category.get("offer_catalog", []),
        "peer_stats": category.get("peer_stats"),
        "seasonal_beats": category.get("seasonal_beats", [])[:2],
    }


def _trim_merchant_for_prompt(merchant: dict) -> dict:
    """Keep full identity/performance/offers/signals, but cap conversation_history
    and review_themes so we don't resend the whole history every call."""
    trimmed = dict(merchant)
    if "conversation_history" in trimmed:
        trimmed["conversation_history"] = trimmed["conversation_history"][-3:]
    if "review_themes" in trimmed:
        trimmed["review_themes"] = trimmed["review_themes"][:3]
    return trimmed

def _build_user_prompt(category: dict, merchant: dict, trigger: dict, customer: dict | None) -> str:
    parts = [
        "CATEGORY:\n" + json.dumps(_trim_category_for_prompt(category), ensure_ascii=False),
        "MERCHANT:\n" + json.dumps(_trim_merchant_for_prompt(merchant), ensure_ascii=False),
        "TRIGGER:\n" + json.dumps(trigger, ensure_ascii=False),
    ]
    if customer:
        parts.append("CUSTOMER:\n" + json.dumps(customer, ensure_ascii=False))
    else:
        parts.append("CUSTOMER: none — this message is merchant-facing.")
    parts.append(
        "\nWrite the message now. Respond with ONLY the JSON object described in "
        "your instructions."
    )
    return "\n\n".join(parts)


def compose(category: dict, merchant: dict, trigger: dict, customer: dict | None = None) -> dict:
    """Returns dict with: body, cta, send_as, suppression_key, rationale."""
    user_prompt = _build_user_prompt(category, merchant, trigger, customer)
    parsed = _get_structured_response(
        SYSTEM_PROMPT, user_prompt, required_keys={"body", "cta", "send_as", "rationale"}
    )
    return {
        "body": parsed.get("body", "").strip(),
        "cta": parsed.get("cta", "none"),
        "send_as": parsed.get("send_as", "merchant_on_behalf" if customer else "vera"),
        "suppression_key": trigger.get("suppression_key", ""),
        "rationale": parsed.get("rationale", ""),
    }


def compose_reply(
    category: dict,
    merchant: dict,
    customer: dict | None,
    trigger: dict | None,
    history: list[dict],
    latest_message: str,
    mode: str,
    previously_sent_bodies: list[str],
) -> dict:
    """Returns dict with: body, cta, rationale."""
    history_text = "\n".join(f"{t['from_role']}: {t['body']}" for t in history) or "(no prior turns)"
    prev_bodies_text = "\n".join(f"- {b}" for b in previously_sent_bodies) or "(none yet)"

    user_prompt = (
        f"MODE={mode}\n\n"
        f"CATEGORY:\n{json.dumps(_trim_category_for_prompt(category), ensure_ascii=False)}\n\n"
        f"MERCHANT:\n{json.dumps(_trim_merchant_for_prompt(merchant), ensure_ascii=False)}\n\n"
        f"CUSTOMER:\n{json.dumps(customer, ensure_ascii=False) if customer else 'none'}\n\n"
        f"ORIGINAL TRIGGER (the real facts this conversation is grounded in):\n"
        f"{json.dumps(trigger, ensure_ascii=False) if trigger else 'none'}\n\n"
        f"CONVERSATION SO FAR:\n{history_text}\n\n"
        f"MESSAGES YOU ALREADY SENT (never repeat these verbatim):\n{prev_bodies_text}\n\n"
        f"LATEST INCOMING MESSAGE:\n{latest_message}\n\n"
        "Respond with ONLY the JSON object described in your instructions."
    )

    parsed = _get_structured_response(
        REPLY_SYSTEM_PROMPT, user_prompt, required_keys={"body", "cta", "rationale"}
    )
    return {
        "body": parsed.get("body", "").strip(),
        "cta": parsed.get("cta", "none"),
        "rationale": parsed.get("rationale", ""),
    }


if __name__ == "__main__":
    ds = Dataset()

    trg = ds.get_trigger("trg_001_research_digest_dentists")
    merchant = ds.get_merchant(trg["merchant_id"])
    category = ds.get_category(merchant["category_slug"])
    digest_item = ds.resolve_digest_item(trg["payload"]["category"], trg["payload"]["top_item_id"])
    enriched_trigger = dict(trg)
    enriched_trigger["resolved_digest_item"] = digest_item

    result = compose(category, merchant, enriched_trigger, customer=None)
    print("--- Merchant-facing ---")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    trg2 = ds.get_trigger("trg_003_recall_due_priya")
    merchant2 = ds.get_merchant(trg2["merchant_id"])
    category2 = ds.get_category(merchant2["category_slug"])
    customer2 = ds.get_customer(trg2["customer_id"]) if trg2.get("customer_id") else None

    result2 = compose(category2, merchant2, trg2, customer=customer2)
    print("\n--- Customer-facing ---")
    print(json.dumps(result2, indent=2, ensure_ascii=False))