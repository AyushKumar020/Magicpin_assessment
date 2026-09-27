"""
In-memory state for the bot: pushed contexts (with version tracking) and
conversation histories. Everything resets if the process restarts — that's
allowed per the testing brief (§2.1 says in-memory storage is fine).
"""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ConversationTurn:
    from_role: str        # "vera" | "merchant" | "customer"
    body: str
    ts: str


@dataclass
class ConversationState:
    conversation_id: str
    merchant_id: str
    customer_id: str | None = None
    turns: list[ConversationTurn] = field(default_factory=list)
    ended: bool = False
    unanswered_nudges: int = 0
    auto_reply_probes_sent: int = 0
    category: dict | None = None
    merchant: dict | None = None
    customer: dict | None = None
    trigger: dict | None = None


class Store:
    def __init__(self):
        # (scope, context_id) -> {"version": int, "payload": dict}
        self.contexts: dict[tuple[str, str], dict] = {}
        self.conversations: dict[str, ConversationState] = {}
        self.used_suppression_keys: set[str] = set()

    # ---- context push handling ----
    def push_context(self, scope: str, context_id: str, version: int, payload: dict):
        """Returns (accepted: bool, reason: str|None, current_version: int|None)."""
        key = (scope, context_id)
        cur = self.contexts.get(key)
        if cur is not None and cur["version"] >= version:
            return False, "stale_version", cur["version"]
        self.contexts[key] = {"version": version, "payload": payload}
        return True, None, None

    def get_context(self, scope: str, context_id: str) -> dict | None:
        entry = self.contexts.get((scope, context_id))
        return entry["payload"] if entry else None

    def counts_by_scope(self) -> dict[str, int]:
        counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        for (scope, _cid), _entry in self.contexts.items():
            counts[scope] = counts.get(scope, 0) + 1
        return counts

    # ---- conversation handling ----
    def get_or_create_conversation(self, conversation_id: str, merchant_id: str, customer_id: str | None,
                                    category: dict | None = None, merchant: dict | None = None,
                                    customer: dict | None = None, trigger: dict | None = None) -> ConversationState:
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = ConversationState(
                conversation_id=conversation_id, merchant_id=merchant_id, customer_id=customer_id,
                category=category, merchant=merchant, customer=customer, trigger=trigger,
            )
        return self.conversations[conversation_id]

    def add_turn(self, conversation_id: str, from_role: str, body: str):
        conv = self.conversations[conversation_id]
        conv.turns.append(ConversationTurn(from_role=from_role, body=body, ts=datetime.utcnow().isoformat() + "Z"))

    def bot_bodies_sent(self, conversation_id: str) -> list[str]:
        """All message bodies the bot itself has sent in this conversation (anti-repetition check)."""
        conv = self.conversations.get(conversation_id)
        if not conv:
            return []
        return [t.body for t in conv.turns if t.from_role in ("vera", "merchant_on_behalf")]

    def is_auto_reply(self, conversation_id: str, incoming_body: str, threshold: int = 3) -> bool:
        """Same incoming message verbatim >= threshold times => treat as WhatsApp Business auto-reply."""
        conv = self.conversations.get(conversation_id)
        if not conv:
            return False
        matches = sum(
            1 for t in conv.turns
            if t.from_role in ("merchant", "customer") and t.body.strip() == incoming_body.strip()
        )
        return matches >= threshold

    def reset(self):
        """Called on /v1/teardown."""
        self.contexts.clear()
        self.conversations.clear()
        self.used_suppression_keys.clear()

    def is_suppressed(self, suppression_key: str) -> bool:
        return bool(suppression_key) and suppression_key in self.used_suppression_keys

    def mark_suppressed(self, suppression_key: str):
        if suppression_key:
            self.used_suppression_keys.add(suppression_key)


# module-level singleton — bot.py imports this one instance
store = Store()