"""
The FastAPI server implementing the 5 endpoints from challenge-testing-brief.md §2:
  POST /v1/context   - receive context pushes
  POST /v1/tick      - periodic wake-up, bot may initiate
  POST /v1/reply     - receive a merchant/customer reply
  GET  /v1/healthz   - liveness probe
  GET  /v1/metadata  - bot identity

Run: uvicorn bot:app --host 0.0.0.0 --port 8080
"""
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel

from state_store import store
from composer import compose
from conversation_handlers import respond

app = FastAPI(title="Vera-Beta magicpin Challenge Bot")
START_TIME = time.time()

MAX_ACTIONS_PER_TICK = 20


# ---------------------------------------------------------------------------
# GET /v1/healthz
# ---------------------------------------------------------------------------
@app.get("/v1/healthz")
async def healthz():
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": store.counts_by_scope(),
    }


# ---------------------------------------------------------------------------
# GET /v1/metadata
# ---------------------------------------------------------------------------
@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Solo Team",          # <-- edit with your name/team
        "team_members": ["Ayush Kumar"],   # <-- edit
        "model": "openai/gpt-oss-120b (via Groq)",
        "approach": "single-prompt composer with digest/offer resolution + rule-based "
                    "auto-reply/intent-transition detection ahead of the LLM",
        "contact_email": "ayushkumar_23cs104@dtu.ac.in",  # <-- edit
        "version": "1.0.0",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# POST /v1/context
# ---------------------------------------------------------------------------
class CtxBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str


@app.post("/v1/context")
async def push_context(body: CtxBody):
    if body.scope not in ("category", "merchant", "customer", "trigger"):
        return {"accepted": False, "reason": "invalid_scope", "details": f"unknown scope '{body.scope}'"}

    accepted, reason, current_version = store.push_context(
        body.scope, body.context_id, body.version, body.payload
    )
    if not accepted:
        return {"accepted": False, "reason": reason, "current_version": current_version}

    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Helpers shared by /v1/tick and /v1/reply
# ---------------------------------------------------------------------------
def _resolve_trigger_extras(trigger_payload: dict, category_slug: str) -> dict:
    """Attach real content for anything the trigger only references by id."""
    enriched = dict(trigger_payload)
    inner = trigger_payload.get("payload", {})
    category = store.get_context("category", category_slug)
    if category:
        top_item_id = inner.get("top_item_id")
        if top_item_id:
            for item in category.get("digest", []):
                if item["id"] == top_item_id:
                    enriched["resolved_digest_item"] = item
                    break
        offer_id = inner.get("offer_id")
        if offer_id:
            for offer in category.get("offer_catalog", []):
                if offer["id"] == offer_id:
                    enriched["resolved_offer"] = offer
                    break
    return enriched


# ---------------------------------------------------------------------------
# POST /v1/tick
# ---------------------------------------------------------------------------
class TickBody(BaseModel):
    now: str
    available_triggers: list[str] = []


@app.post("/v1/tick")
async def tick(body: TickBody):
    actions = []

    for trigger_id in body.available_triggers:
        if len(actions) >= MAX_ACTIONS_PER_TICK:
            break

        trigger = store.get_context("trigger", trigger_id)
        if not trigger:
            continue

        suppression_key = trigger.get("suppression_key", "")
        if store.is_suppressed(suppression_key):
            continue

        merchant_id = trigger.get("merchant_id")
        merchant = store.get_context("merchant", merchant_id) if merchant_id else None
        if not merchant:
            continue

        category_slug = merchant.get("category_slug")
        category = store.get_context("category", category_slug) if category_slug else None
        if not category:
            continue

        customer = None
        customer_id = trigger.get("customer_id")
        if customer_id:
            customer = store.get_context("customer", customer_id)

        enriched_trigger = _resolve_trigger_extras(trigger, category_slug)

        try:
            composed = compose(category, merchant, enriched_trigger, customer=customer)
        except Exception as e:
            print(f"[/v1/tick] compose() failed for trigger {trigger_id}: {e}")
            continue

        if not composed["body"]:
            continue  # composer gave up gracefully; skip this action, don't crash the tick

        conversation_id = f"conv_{merchant_id}_{trigger_id}_{uuid.uuid4().hex[:8]}"
        store.get_or_create_conversation(
            conversation_id, merchant_id, customer_id,
            category=category, merchant=merchant, customer=customer, trigger=enriched_trigger,
        )
        send_as = composed["send_as"]
        store.add_turn(conversation_id, send_as, composed["body"])
        store.mark_suppressed(suppression_key)

        actions.append({
            "conversation_id": conversation_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": send_as,
            "trigger_id": trigger_id,
            "template_name": f"vera_{trigger.get('kind', 'generic')}_v1",
            "template_params": [merchant["identity"]["name"]],
            "body": composed["body"],
            "cta": composed["cta"],
            "suppression_key": suppression_key,
            "rationale": composed["rationale"],
        })

    return {"actions": actions}


# ---------------------------------------------------------------------------
# POST /v1/reply
# ---------------------------------------------------------------------------
class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    category = merchant = customer = None

    # Only needed the first time this conversation_id is seen by respond();
    # afterwards the ConversationState remembers them.
    if body.conversation_id not in store.conversations:
        merchant = store.get_context("merchant", body.merchant_id) if body.merchant_id else None
        category_slug = merchant.get("category_slug") if merchant else None
        category = store.get_context("category", category_slug) if category_slug else None
        customer = store.get_context("customer", body.customer_id) if body.customer_id else None

    result = respond(
        store,
        conversation_id=body.conversation_id,
        merchant_id=body.merchant_id,
        customer_id=body.customer_id,
        from_role=body.from_role,
        message=body.message,
        category=category,
        merchant=merchant,
        customer=customer,
    )
    return result


# ---------------------------------------------------------------------------
# POST /v1/teardown (optional, per testing-brief.md §11)
# ---------------------------------------------------------------------------
@app.post("/v1/teardown")
async def teardown():
    store.reset()
    return {"status": "wiped"}