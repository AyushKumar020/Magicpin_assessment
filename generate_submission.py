"""
Generates submission.jsonl — the 30 required test-case outputs per
challenge-brief.md §7.2. Uses the LOCAL compose() function directly
(not HTTP) for speed and to avoid Render's free-tier cold-start delays,
since this only needs to run once before packaging the final submission.
"""
import json
import time
from dataset_loader import Dataset
from composer import compose

ds = Dataset()


def resolve_trigger(trigger: dict) -> dict:
    """Same enrichment logic bot.py uses: attach real digest/offer content
    the trigger only references by id."""
    enriched = dict(trigger)
    inner = trigger.get("payload", {})
    category_slug = inner.get("category")
    if not category_slug:
        merchant = ds.get_merchant(trigger.get("merchant_id"))
        category_slug = merchant["category_slug"] if merchant else None

    if category_slug:
        top_item_id = inner.get("top_item_id")
        if top_item_id:
            item = ds.resolve_digest_item(category_slug, top_item_id)
            if item:
                enriched["resolved_digest_item"] = item
        offer_id = inner.get("offer_id")
        if offer_id:
            offer = ds.resolve_offer(category_slug, offer_id)
            if offer:
                enriched["resolved_offer"] = offer
    return enriched


def main():
    results = []
    total = len(ds.test_pairs)

    for i, pair in enumerate(ds.test_pairs, 1):
        test_id = pair["test_id"]
        trigger = ds.get_trigger(pair["trigger_id"])
        merchant = ds.get_merchant(pair["merchant_id"])
        customer = ds.get_customer(pair["customer_id"]) if pair.get("customer_id") else None

        if not trigger or not merchant:
            print(f"[{i}/{total}] {test_id}: SKIPPED (missing trigger or merchant)")
            continue

        category = ds.get_category(merchant["category_slug"])
        enriched_trigger = resolve_trigger(trigger)

        print(f"[{i}/{total}] {test_id}: composing...")
        composed = None
        for outer_attempt in range(3):
            try:
                composed = compose(category, merchant, enriched_trigger, customer=customer)
            except Exception as e:
                composed = {"body": "", "cta": "none", "send_as": "vera",
                            "suppression_key": trigger.get("suppression_key", ""),
                            "rationale": f"generation failed: {e}"}
            if composed["body"]:
                break  # success
            print(f"  empty body (likely rate-limited), waiting 20s before outer retry "
                  f"{outer_attempt + 1}/3...")
            time.sleep(20)

        results.append({
            "test_id": test_id,
            "body": composed["body"],
            "cta": composed["cta"],
            "send_as": composed["send_as"],
            "suppression_key": composed["suppression_key"],
            "rationale": composed["rationale"],
        })

        # Small pause to stay well under Groq's free-tier 30 RPM / 8K TPM caps
        time.sleep(4)

    with open("submission.jsonl", "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nDone. Wrote {len(results)} lines to submission.jsonl")
    empty_count = sum(1 for r in results if not r["body"])
    if empty_count:
        print(f"WARNING: {empty_count} lines have an empty body (generation failed) — review before submitting.")


if __name__ == "__main__":
    main()