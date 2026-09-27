"""
Multi-turn conversation logic — the optional deliverable from
challenge-brief.md §7.4, and the logic behind bot.py's /v1/reply endpoint.

respond() decides, for each incoming merchant/customer message:
  - "send"  -> compose and send a reply
  - "wait"  -> back off for N seconds, no message
  - "end"   -> gracefully exit the conversation

Handles the three Phase-4 replay scenarios from challenge-testing-brief.md §4:
  1. Auto-reply hell      -> detect, probe once, then exit
  2. Intent transition    -> switch straight to action mode, no re-qualifying
  3. Hostile / off-topic  -> stay polite, stay on-mission (handled in the LLM prompt)
"""
from signals import classify_quick_signal
from composer import compose_reply
from state_store import Store


def respond(store: Store, conversation_id: str, merchant_id: str, customer_id: str | None,
            from_role: str, message: str,
            category: dict | None = None, merchant: dict | None = None, customer: dict | None = None) -> dict:
    """
    Main entry point called by bot.py's /v1/reply.
    category/merchant/customer are only needed the FIRST time this conversation_id
    is seen (bot.py should pass them from its context store); after that the
    conversation remembers them.
    """
    conv = store.get_or_create_conversation(
        conversation_id, merchant_id, customer_id,
        category=category, merchant=merchant, customer=customer,
    )

    # Conversation already over — don't re-engage.
    if conv.ended:
        return {"action": "end", "rationale": "conversation already ended previously"}

    store.add_turn(conversation_id, from_role, message)

    signal = classify_quick_signal(message)

    # --- Hard stop: merchant/customer explicitly not interested ---
    if signal == "not_interested":
        conv.ended = True
        return {"action": "end", "rationale": "explicit not-interested/STOP signal detected; exiting gracefully"}

    # --- Asked for time: back off, don't burn a turn on an LLM call ---
    if signal == "wait_requested":
        conv.unanswered_nudges += 1
        return {"action": "wait", "wait_seconds": 1800, "rationale": "party asked for time; backing off 30 min"}

    # --- Auto-reply detection ---
    if signal == "auto_reply_phrase" or store.is_auto_reply(conversation_id, message, threshold=3):
        if store.is_auto_reply(conversation_id, message, threshold=3) or conv.auto_reply_probes_sent >= 1:
            # Same canned text has now repeated 3+ times, OR we've already used our one probe — stop wasting turns.
            conv.ended = True
            return {"action": "end", "rationale": "repeated auto-reply detected; already probed once, exiting to avoid wasting turns"}
        mode = "probe_auto_reply"
        conv.auto_reply_probes_sent += 1

    elif signal == "intent_yes":
        mode = "action_now"

    else:
        mode = "normal"

    # --- Compose the next message via LLM, with anti-repetition context ---
    history = [{"from_role": t.from_role, "body": t.body} for t in conv.turns]
    previously_sent = store.bot_bodies_sent(conversation_id)

    result = compose_reply(
        category=conv.category,
        merchant=conv.merchant,
        customer=conv.customer,
        trigger=conv.trigger,
        history=history,
        latest_message=message,
        mode=mode,
        previously_sent_bodies=previously_sent,
    )

    body = result["body"]

    # Safety net: if the LLM repeated itself anyway, don't send a flagged duplicate — end gracefully instead.
    if body and body.strip() in previously_sent:
        conv.ended = True
        return {"action": "end", "rationale": "composed reply duplicated a prior message; exiting rather than repeating"}

    if not body:
        if result["rationale"] == "composer unavailable (LLM call failed)":
            # Temporary failure, not a real conversational end — ask the harness to retry later.
            return {"action": "wait", "wait_seconds": 60, "rationale": "temporary composer issue, retry shortly"}
        conv.ended = True
        return {"action": "end", "rationale": "no further message warranted"}

    send_as = "merchant_on_behalf" if conv.customer_id else "vera"
    store.add_turn(conversation_id, send_as, body)
    conv.unanswered_nudges = 0

    return {"action": "send", "body": body, "cta": result["cta"], "rationale": result["rationale"]}