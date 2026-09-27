"""
Loads the expanded dataset (categories, merchants, customers, triggers)
into memory once, and provides lookup + resolution helpers.
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "dataset" / "expanded"


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Dataset:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.categories: dict[str, dict] = {}
        self.merchants: dict[str, dict] = {}
        self.customers: dict[str, dict] = {}
        self.triggers: dict[str, dict] = {}

        for f in (data_dir / "categories").glob("*.json"):
            c = _load_json(f)
            self.categories[c["slug"]] = c

        for f in (data_dir / "merchants").glob("*.json"):
            m = _load_json(f)
            self.merchants[m["merchant_id"]] = m

        for f in (data_dir / "customers").glob("*.json"):
            c = _load_json(f)
            self.customers[c["customer_id"]] = c

        for f in (data_dir / "triggers").glob("*.json"):
            t = _load_json(f)
            self.triggers[t["id"]] = t

        pairs_path = data_dir / "test_pairs.json"
        self.test_pairs = _load_json(pairs_path)["pairs"] if pairs_path.exists() else []

    # ---- lookups ----
    def get_category(self, slug: str) -> dict | None:
        return self.categories.get(slug)

    def get_merchant(self, merchant_id: str) -> dict | None:
        return self.merchants.get(merchant_id)

    def get_customer(self, customer_id: str) -> dict | None:
        return self.customers.get(customer_id)

    def get_trigger(self, trigger_id: str) -> dict | None:
        return self.triggers.get(trigger_id)

    # ---- resolution: fill in cross-references the trigger only points to ----
    def resolve_digest_item(self, category_slug: str, digest_id: str) -> dict | None:
        """Triggers reference digest items by id (e.g. top_item_id). Look up the real content."""
        cat = self.get_category(category_slug)
        if not cat:
            return None
        for item in cat.get("digest", []):
            if item["id"] == digest_id:
                return item
        return None

    def resolve_offer(self, category_slug: str, offer_id: str) -> dict | None:
        cat = self.get_category(category_slug)
        if not cat:
            return None
        for offer in cat.get("offer_catalog", []):
            if offer["id"] == offer_id:
                return offer
        return None


if __name__ == "__main__":
    # quick self-test
    ds = Dataset()
    print(f"Loaded {len(ds.categories)} categories, {len(ds.merchants)} merchants, "
          f"{len(ds.customers)} customers, {len(ds.triggers)} triggers, "
          f"{len(ds.test_pairs)} test pairs")

    trg = ds.get_trigger("trg_001_research_digest_dentists")
    merchant = ds.get_merchant(trg["merchant_id"])
    digest_item = ds.resolve_digest_item(trg["payload"]["category"], trg["payload"]["top_item_id"])
    print("\nTrigger:", trg["kind"])
    print("Merchant:", merchant["identity"]["name"])
    print("Resolved digest item title:", digest_item["title"] if digest_item else None)