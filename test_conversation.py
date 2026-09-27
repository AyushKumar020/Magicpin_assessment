"""
Simulates the three Phase-4 replay scenarios from challenge-testing-brief.md §4,
locally, without needing bot.py or HTTP at all.
"""
import json
from dataset_loader import Dataset
from state_store import Store
from conversation_handlers import respond

ds = Dataset()


def fresh_store_and_context(merchant_id: str):
    store = Store()
    merchant = ds.get_merchant(merchant_id)
    category = ds.get_category(merchant["category_slug"])
    return store, category, merchant


def scenario_1_auto_reply_hell():
    print("\n=== Scenario 1: Auto-reply hell ===")
    store, category, merchant = fresh_store_and_context("m_003_studio11_salon_hyderabad")
    conv_id = "conv_test_1"
    canned = "Thank you for contacting us. Our team will get back to you shortly."

    for i in range(4):
        r = respond(store, conv_id, merchant["merchant_id"], None, "merchant", canned,
                    category=category, merchant=merchant, customer=None)
        print(f"Turn {i+1}: incoming={canned!r}\n  -> {json.dumps(r, ensure_ascii=False)}")
        if r["action"] == "end":
            print("  (bot ended conversation)")
            break


def scenario_2_intent_transition():
    print("\n=== Scenario 2: Intent transition ===")
    store, category, merchant = fresh_store_and_context("m_001_drmeera_dentist_delhi")
    conv_id = "conv_test_2"

    turns = [
        "Hi, tell me more about this",
        "How many patients would this actually affect?",
        "ok let's do it",
    ]
    for msg in turns:
        r = respond(store, conv_id, merchant["merchant_id"], None, "merchant", msg,
                    category=category, merchant=merchant, customer=None)
        print(f"Incoming: {msg!r}\n  -> {json.dumps(r, ensure_ascii=False)}")


def scenario_3_hostile_offtopic():
    print("\n=== Scenario 3: Hostile / off-topic ===")
    store, category, merchant = fresh_store_and_context("m_005_pizzajunction_restaurant_delhi")
    conv_id = "conv_test_3"

    turns = [
        "Why do you keep spamming me, this is useless",
        "Can you also help me file my GST return?",
    ]
    for msg in turns:
        r = respond(store, conv_id, merchant["merchant_id"], None, "merchant", msg,
                    category=category, merchant=merchant, customer=None)
        print(f"Incoming: {msg!r}\n  -> {json.dumps(r, ensure_ascii=False)}")


if __name__ == "__main__":
    scenario_1_auto_reply_hell()
    scenario_2_intent_transition()
    scenario_3_hostile_offtopic()